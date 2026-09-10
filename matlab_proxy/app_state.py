# Copyright 2020-2026 The MathWorks, Inc.

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Final

from matlab_proxy import util
from matlab_proxy.constants import (
    CHECK_MATLAB_STATUS_INTERVAL_SECONDS,
    CONNECTOR_SECUREPORT_FILENAME,
    IS_CONCURRENCY_CHECK_ENABLED,
    MATLAB_LOGS_FILE_NAME,
    USER_CODE_OUTPUT_FILE_NAME,
    ExitReason,
)
from matlab_proxy.settings import get_process_startup_timeout
from matlab_proxy.util import mw, mwi, system, windows
from matlab_proxy.util.dpop import DPoPKey
from matlab_proxy.util.mwi import environment_variables as mwi_env
from matlab_proxy.util.mwi import token_auth
from matlab_proxy.util.mwi.exceptions import (
    EmbeddedConnectorError,
    EntitlementError,
    FatalError,
    LicensingError,
    MatlabError,
    MatlabInstallError,
    OnlineLicensingError,
    UIVisibleFatalError,
    WindowManagerError,
    XvfbError,
    log_error,
)

logger = mwi.logger.get()


def _parse_expiry(expiry: str) -> datetime:
    """Parse an OAuth/MHLM expiry timestamp into a timezone-aware datetime.

    The OAuth server is not guaranteed to include fractional seconds or to use a
    colon in the UTC offset, so we try a few ISO-8601 variants rather than a
    single rigid format. Python 3.11+ ``fromisoformat`` handles most of these,
    with explicit ``strptime`` fallbacks for older interpreters.
    """
    # datetime.fromisoformat is the most forgiving on 3.11+ (accepts optional
    # fractional seconds and both +HH:MM / +HHMM offsets, plus a trailing 'Z').
    try:
        return datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(expiry, fmt)
        except ValueError:
            continue

    raise ValueError(f"Unrecognized expiry timestamp format: {expiry!r}")


def _get_server_urls(server_url: str, mwi_auth_token_str: str) -> list[str]:
    """Returns list of server URLs including user supplied hostname, if any."""
    # By default mwi_server_url usually points to 0.0.0.0 as the hostname, but this does not work well
    # on some browsers. Specifically on Safari (MacOS), hence the replace op with localhost.
    server_urls_with_auth_token = [
        f'{server_url.replace("0.0.0.0", "localhost")}{mwi_auth_token_str}'
    ]
    if user_supplied_hostname := os.getenv(mwi_env.get_env_name_app_host(), "").strip():
        server_urls_with_auth_token.append(
            f'{server_urls_with_auth_token[0].replace("localhost", user_supplied_hostname)}'
        )

    return server_urls_with_auth_token


class AppState:
    """A Class which represents the state of the App.
    This class handles state of MATLAB, MATLAB Licensing and Xvfb.
    """

    # Constants that are applicable to AppState class
    MATLAB_PORT_CHECK_DELAY_IN_SECONDS: Final[int] = 1

    def __init__(self, settings):
        """Parameterized constructor for the AppState class.
        Initializes member variables and checks for an existing MATLAB installation.

        Args:
            settings (Dict): Represents the settings required for managing MATLAB, Licensing and Xvfb.
        """
        self.settings = settings
        self.processes = {"matlab": None, "xvfb": None}

        # Timeout for processes started by matlab-proxy
        self.PROCESS_TIMEOUT = get_process_startup_timeout()

        # The port on which MATLAB(started by this matlab-proxy process) starts on.
        self.matlab_port = None

        # The directory in which the instance of MATLAB (started by this matlab-proxy process) will write logs to.
        self.mwi_logs_dir = None

        # Dictionary of all files used to manage the MATLAB session.
        self.matlab_session_files = {
            # The file created and written by MATLAB's Embedded connector to signal readiness.
            "matlab_ready_file": None,
        }

        # Dictionary of all files used to manage the server session.
        self.mwi_server_session_files = {
            # This file will contain the access URL to the server, this will include any tokens required by the server for access.
            "mwi_server_info_file": None,
        }

        self.licensing = None
        # MATLAB process related tasks which have the same lifetime as MATLAB
        self.matlab_tasks = {}
        self.logs = {
            "matlab": deque(maxlen=200),
        }

        # Initialize with the error state from the initialization of settings
        self.error = settings["error"]
        self.warnings = settings["warnings"]

        # Keep track of when the Embedded connector starts.
        # Would be initialized appropriately by get_embedded_connector_state() task.
        self.embedded_connector_start_time = None

        # Keep track of the state of the Embedded Connector.
        # If there is some problem with starting the Embedded Connector(say an issue with licensing),
        # the state of MATLAB process in app_state will continue to be in a 'starting' indefinitely.
        # This variable can be either "up" or "down"
        self.embedded_connector_state = "down"

        # Specific to concurrent session and is used to track the active client/s that are currently
        # connected to the backend
        self.active_client = None

        # Used to detect whether the active client is actively sending out request or is inactive
        self.active_client_request_detected = False

        # Initialize matlab with 'down' state.
        # Should only be updated/accessed  via setter/getter methods.
        self.__matlab_state = "down"

        # Initialize busy state as None as matlab state is initialized as 'down'.
        self.matlab_busy_state = None

        # Lock to be used before modifying MATLAB state
        self.matlab_state_updater_lock = util.TrackingLock(purpose="MATLAB state")

        loop = util.get_event_loop()

        # matlab-proxy server related tasks which have the same lifetime as the server
        self.server_tasks = {}

        self.is_idle_timeout_enabled = (
            True if self.settings["mwi_idle_timeout"] else False
        )

        if self.is_idle_timeout_enabled:
            self.__initial_idle_timeout = self.__remaining_idle_timeout = self.settings[
                "mwi_idle_timeout"
            ]
            # Lock to be used before updating IDLE timer.
            self.idle_timeout_lock = util.TrackingLock(purpose="MATLAB IDLE timer")
            self.server_tasks["decrement_idle_timer"] = loop.create_task(
                self.__decrement_idle_timer()
            )

        # Flag to track if matlab-proxy is in the process of shutting down
        self.is_shutting_down: bool = False
        self.exit_reason: ExitReason = ExitReason.NORMAL_SHUTDOWN

    def set_remaining_idle_timeout(self, new_timeout):
        """Sets the remaining IDLE timeout after the validating checks.

        Args:
            new_timeout (int): New timeout value
        """
        caller = util.get_caller_name()
        if self.idle_timeout_lock.validate_lock_for_caller(caller):
            self.__remaining_idle_timeout = new_timeout
            logger.debug(
                f"'{util.get_caller_name()}()' function acquired the lock to update IDLE timer"
            )

        else:
            # NOTE: This code branch should only ever be hit during development. We exit to enforce proper usage of this function during development time.
            sys.exit(1)

    def get_remaining_idle_timeout(self):
        """Returns the remaining IDLE timeout after which matlab-proxy will shutdown

        Returns:
            int: Remaining IDLE timeout
        """

        # Lock is not required when reading __idle_timeout_left as the value maybe atmost 1 second old.
        # Additionally, having a lock for the getter will increase the latency for the /get_status requests coming in.
        return self.__remaining_idle_timeout

    async def reset_timer(self):
        """Resets the IDLE timer to its original value after acquiring a lock."""
        await self.idle_timeout_lock.acquire()
        self.set_remaining_idle_timeout(self.__initial_idle_timeout)
        await self.idle_timeout_lock.release()

        logger.debug(
            f"IDLE timer has been reset to {self.get_remaining_idle_timeout()} seconds"
        )

    async def __decrement_idle_timer(self):
        """Decrements the IDLE timer by 1 after acquiring a lock."""
        this_task = "decrement_idle_timer"
        logger.debug(f"{this_task}: Starting task...")

        while self.get_remaining_idle_timeout() > 0:
            # If MATLAB is either starting, stopping or busy, reset the IDLE timer.
            if (
                self.get_matlab_state() in ["starting", "stopping"]
                or self.matlab_busy_state == "busy"
            ):
                await self.reset_timer()

            else:
                new_value = self.get_remaining_idle_timeout() - 1
                await self.idle_timeout_lock.acquire()
                self.set_remaining_idle_timeout(new_value)
                await self.idle_timeout_lock.release()

                logger.debug(
                    f"{this_task}: IDLE timer decremented to {new_value} seconds"
                )

            await asyncio.sleep(1)

        logger.info("The IDLE timer for shutdown has run out...")
        logger.info(f"Shutting down {self.settings['integration_name']}")
        self.exit_reason = ExitReason.IDLE_TIMEOUT
        await self.stop_matlab()
        loop = util.get_event_loop()
        loop.stop()

    def __get_cached_config_file(self):
        """Get the cached config file

        Returns:
            Path : Path object to cached config file
        """
        return self.settings["matlab_config_file"]

    def __delete_cached_config_file(self):
        """Deletes the cached config file"""
        try:
            logger.debug("Deleting any cached config files!")
            os.remove(self.__get_cached_config_file())
        except FileNotFoundError:
            # The file being absent is acceptable.
            pass

    def __write_cached_config_file(self, config):
        """Serialize ``config`` to the cached config file with owner-only perms.

        The cached config holds durable secrets (OAuth refresh_token + DPoP
        private key, or the MHLM identity token), so the file is written 0o600
        to keep it out of reach of other users on the host. We deliberately do
        NOT tighten the parent directory: it is shared with sibling subtrees
        (certs/, ports/, proxy_manager/) that jmp and other integrations own,
        so restricting it could lock a different-UID client out of its own
        state. Tightening the file perms is best-effort: on Windows os.chmod
        only toggles the read-only bit, and if the file already exists owned by
        a different user the chmod raises - in either case we log and continue
        rather than fail the licensing save. Note this only holds until another
        (possibly older) client rewrites the shared file at its own umask.
        """
        cached_config_file = self.__get_cached_config_file()
        cached_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cached_config_file, "w") as f:
            f.write(json.dumps(config))
        try:
            os.chmod(cached_config_file, 0o600)
        except OSError:
            logger.debug("Could not tighten permissions on %s.", cached_config_file)

    def __reset_and_delete_cached_config(self):
        """Reset licensing variable of the class and removes the cached config file."""
        logger.debug("Resetting cached config information...")
        self.licensing = None
        self.__delete_cached_config_file()

    async def __update_and_persist_licensing(self):
        """Update entitlements from mhlm servers and persist config data

        Returns:
            Boolean: True when entitlements were updated and persisted successfully. False otherwise.
        """
        successful_update = await self.update_entitlements()
        if successful_update:
            self.persist_config_data()
        else:
            self.__reset_and_delete_cached_config()
        return successful_update

    async def init_licensing(self):
        """Initialize licensing from environment variable or cached file.

        Greater precedence is given to value specified in environment variable MLM_LICENSE_FILE
            If specified, this function will delete previously cached licensing information.
            This enforces a clear understanding of what was used to initialize licensing.
            The contents of the environment variable are NEVER cached.
        """

        # Default value
        self.licensing = None

        # If MWI_USE_EXISTING_LICENSE is set in environment, try starting MATLAB directly
        if self.settings["mwi_use_existing_license"]:
            self.licensing = {"type": "existing_license"}
            logger.debug(
                f"{mwi_env.get_env_name_mwi_use_existing_license()} variable set in environment"
            )
            logger.info(
                "!!! Starting MATLAB without providing any additional licensing information. This requires MATLAB to have been activated on the machine from which its being started !!!"
            )

            # Delete old config info from cache to ensure its wiped out first before persisting new info.
            self.__delete_cached_config_file()

        # NLM Connection String set in environment
        elif self.settings.get("nlm_conn_str", None) is not None:
            nlm_licensing_str = self.settings.get("nlm_conn_str")
            logger.debug(f"Found NLM:[{nlm_licensing_str}] set in environment")
            logger.info(f"Using NLM:{nlm_licensing_str} to connect...")
            self.licensing = {
                "type": "nlm",
                "conn_str": nlm_licensing_str,
            }

            # Delete old config info from cache to ensure its wiped out first before persisting new info.
            self.__delete_cached_config_file()

        # If NLM connection string is not present or if an existing license is not being used,
        # then look for persistent LNU info
        elif self.__get_cached_config_file().exists():
            with open(self.__get_cached_config_file(), "r") as f:
                logger.debug("Found cached licensing information...")
                try:
                    # Load can throw if the file is empty or expected fields in the json object are missing.
                    cached_data = json.loads(f.read())
                    licensing = cached_data["licensing"]

                    # OAuth uses a multi-client structure (no top-level "matlab"
                    # key); MATLAB version lives inside each client entry. For all
                    # other licensing types, update matlab_version from the cache
                    # if it could not be determined on startup.
                    if (
                        licensing["type"] != "oauth"
                        and not self.settings["matlab_version"]
                    ):
                        self.settings["matlab_version"] = cached_data["matlab"][
                            "version"
                        ]

                    if licensing["type"] == "oauth":
                        await self._init_oauth_licensing_from_cache(licensing)

                    elif licensing["type"] == "nlm":
                        # Note: Only NLM settings entered in browser were cached.
                        self.licensing = {
                            "type": "nlm",
                            "conn_str": licensing["conn_str"],
                        }
                        logger.debug("Using cached NLM licensing to start MATLAB")

                    elif licensing["type"] == "mhlm":
                        # Cached MHLM licensing is always preferred, even when this
                        # integration also supports the OAuth device code flow
                        # (oauth_client_id present). MHLM tokens remain valid
                        # licensing; we do not discard them just because OAuth is
                        # available. The OAuth device code tab is only surfaced when
                        # there is no usable cached licensing.
                        self.licensing = {
                            "type": "mhlm",
                            "identity_token": licensing["identity_token"],
                            "source_id": licensing["source_id"],
                            "expiry": licensing["expiry"],
                            "email_addr": licensing["email_addr"],
                            "first_name": licensing["first_name"],
                            "last_name": licensing["last_name"],
                            "display_name": licensing["display_name"],
                            "user_id": licensing["user_id"],
                            "profile_id": licensing["profile_id"],
                            "entitlements": [],
                            "entitlement_id": licensing.get("entitlement_id"),
                        }

                        expiry_window = _parse_expiry(
                            self.licensing["expiry"]
                        ) - timedelta(hours=1)

                        if expiry_window > datetime.now(timezone.utc):
                            successful_update = (
                                await self.__update_and_persist_licensing()
                            )
                            if successful_update:
                                logger.debug(
                                    "Using cached Online Licensing to start MATLAB."
                                )
                        else:
                            self.__reset_and_delete_cached_config()
                    elif licensing["type"] == "existing_license":
                        logger.debug("Using cached existing license to start MATLAB")
                        self.licensing = licensing
                    else:
                        # Somethings wrong, licensing is neither NLM or MHLM
                        self.__reset_and_delete_cached_config()
                except Exception:
                    self.__reset_and_delete_cached_config()

    async def _init_oauth_licensing_from_cache(self, licensing):
        """Restore OAuth licensing for the current client_id from cached config.

        Searches the cached ``clients`` array for an entry matching this
        integration's ``oauth_client_id``. If found, loads the DPoP key and always
        refreshes to obtain a fresh access token (the access token is never
        persisted), unless the durable refresh token is missing or has already
        passed its computed ``refresh_token_expiry``, in which case the entry is
        dropped and a fresh sign-in is required. If not found (or if this config
        has no oauth_client_id), no cached token applies and the user must sign in.

        Args:
            licensing (dict): The cached "licensing" object (type == "oauth").
        """
        client_id = self.settings.get("oauth_client_id")

        # OAuth data was written by a config that had an oauth_client_id. If the
        # current config has none, ignore the cached data and fall back.
        if not client_id:
            logger.debug(
                "Cached OAuth licensing present but no oauth_client_id in config. "
                "Ignoring cached data."
            )
            self.licensing = None
            return

        clients = licensing.get("clients", [])
        entry = next((c for c in clients if c.get("client_id") == client_id), None)

        if entry is None:
            logger.debug(
                f"No cached OAuth token for client_id '{client_id}'. Sign-in required."
            )
            self.licensing = None
            return

        # Update MATLAB version from this client's cached entry if needed.
        if not self.settings["matlab_version"]:
            self.settings["matlab_version"] = entry.get("matlab", {}).get("version")

        dpop_key = (
            DPoPKey.from_dict(entry["dpop_key"]) if entry.get("dpop_key") else None
        )
        self.settings["dpop_key"] = dpop_key

        # Rebuild in-memory licensing from the cached entry. The access token was
        # NOT persisted (it is short-lived), so it is absent here and re-derived by
        # the refresh below - mirroring how MHLM re-fetches an access token from
        # the cached identity_token at startup.
        self.licensing = {
            "type": "oauth",
            "client_id": client_id,
            "source_id": client_id,
            "refresh_token_expiry": entry.get("refresh_token_expiry"),
            "email_addr": entry.get("email_addr"),
            "first_name": entry.get("first_name"),
            "last_name": entry.get("last_name"),
            "display_name": entry.get("display_name"),
            "user_id": entry.get("user_id"),
            "token": None,
            "refresh_token": entry.get("refresh_token"),
            "dpop_key": dpop_key,
            "entitlements": entry.get("entitlements", []),
            "entitlement_id": entry.get("entitlement_id"),
        }

        refresh_token = self.licensing.get("refresh_token")
        refresh_token_expiry = self.licensing.get("refresh_token_expiry")

        # No durable credential to work with: require a fresh sign-in.
        if not refresh_token:
            logger.debug("Cached OAuth entry has no refresh token; sign-in required.")
            self._remove_oauth_client_entry(client_id)
            self.licensing = None
            return

        # Predictive gate: if the refresh token has (per the server-configured
        # lifespan we mirrored at persist time) already expired, skip a doomed
        # refresh and require sign-in. This is only an optimization/UX shortcut -
        # the refresh call below remains the ground truth for token validity.
        if refresh_token_expiry is not None:
            try:
                if _parse_expiry(refresh_token_expiry) <= datetime.now(timezone.utc):
                    logger.debug(
                        "Cached OAuth refresh token expired; sign-in required."
                    )
                    self._remove_oauth_client_entry(client_id)
                    self.licensing = None
                    return
            except ValueError:
                # Unparseable stored value: fall through and let the refresh decide.
                logger.debug(
                    "Could not parse cached refresh_token_expiry; attempting refresh."
                )

        # Always refresh on restore: there is no cached access token to reuse, so
        # we exchange the (still-valid) refresh token for a fresh access/refresh
        # pair. A successful refresh also rotates the SAT and re-persists the new
        # refresh token and a fresh refresh_token_expiry.
        try:
            logger.debug("Refreshing cached OAuth token to start MATLAB...")
            await self._refresh_oauth_licensing()
        except Exception as e:
            # Catch broadly (network errors raise aiohttp.ClientError, not just
            # OnlineLicensingError). Remove ONLY this client's entry so other
            # integrations' cached tokens in the shared config are preserved -
            # letting this propagate would hit init_licensing's outer handler
            # and delete the entire cache file.
            logger.debug(f"OAuth token refresh failed ({e}); removing client entry.")
            self._remove_oauth_client_entry(client_id)
            self.licensing = None

    def _remove_oauth_client_entry(self, client_id):
        """Remove a single client's entry from the cached OAuth ``clients`` array.

        Deletes the whole cached config file if no client entries remain.
        """
        cached_config_file = self.__get_cached_config_file()
        if not cached_config_file.exists():
            return

        try:
            with open(cached_config_file, "r") as f:
                existing = json.loads(f.read())
        except Exception:
            self.__delete_cached_config_file()
            return

        if existing.get("licensing", {}).get("type") != "oauth":
            return

        clients = [
            c
            for c in existing["licensing"].get("clients", [])
            if c.get("client_id") != client_id
        ]

        if not clients:
            # No clients left, remove the entire cached config file.
            self.__delete_cached_config_file()
            return

        existing["licensing"]["clients"] = clients
        self.__write_cached_config_file(existing)

    async def __update_matlab_state_based_on_connector_state(self):
        """Updates MATLAB state based on the Embedded Connector state.
        This function is meant to be called after the required processes are ready.
        """
        if self.embedded_connector_state == "down":
            await self.matlab_state_updater_lock.acquire()
            # Even if the embedded connector's status is 'down', we return matlab status as
            # 'starting' because the MATLAB process itself has been created and matlab-proxy
            # is waiting for the embedded connector to start serving content.

            if (
                self.embedded_connector_state == "down"
            ):  # Double check EC state is down before invoking set_matlab_state().
                self.set_matlab_state("starting")

            # Update time stamp when MATLAB state is "starting".
            if not self.embedded_connector_start_time:
                self.embedded_connector_start_time = time.time()

        # Set matlab_status to "up" since embedded connector is up.
        else:
            await self.matlab_state_updater_lock.acquire()
            # Double check EC state is up before invoking set_matlab_state().
            if self.embedded_connector_state == "up":
                self.set_matlab_state("up")
        await self.matlab_state_updater_lock.release()

    async def __update_matlab_state_using_ping_endpoint(self) -> None:
        """Updates MATLAB and its busy state based on the response from PING endpoint"""
        # matlab-proxy sends a request to itself to the endpoint: /messageservice/json/state
        # which the server redirects to the matlab_view() function to handle (which then sends the request to EC)
        headers = self._get_token_auth_headers()
        self.embedded_connector_state = await mwi.embedded_connector.request.get_state(
            mwi_server_url=self.settings["mwi_server_url"],
            headers=headers,
        )

        await self.__update_matlab_state_based_on_connector_state()

        # When using the 'ping' endpoint its not possible to determine the busy status
        # of MATLAB, so default to busy until the switch is made to use the 'busy' status endpoint in __update_matlab_state task.
        # If EC is down, set MATLAB busy status to None
        self.matlab_busy_state = (
            "busy" if self.embedded_connector_state == "up" else None
        )

    async def __update_matlab_state_using_busy_status_endpoint(self) -> None:
        """Updates MATLAB and its busy state based on the response from 'ping' endpoint"""
        # matlab-proxy sends a request to itself to the endpoint: /messageservice/json/state
        # which the server redirects to the matlab_view() function to handle (which then sends the request to EC)
        headers = self._get_token_auth_headers()
        self.matlab_busy_state = await mwi.embedded_connector.request.get_busy_state(
            mwi_server_url=self.settings["mwi_server_url"],
            headers=headers,
        )

        self.embedded_connector_state = "down" if not self.matlab_busy_state else "up"
        await self.__update_matlab_state_based_on_connector_state()

    async def __update_matlab_state_based_on_endpoint_to_use(
        self, matlab_endpoint_to_use: Callable[[], None]
    ) -> None:
        """Updates MATLAB state based on:
         1) If the required processes are ready
         2) The response from Embedded connector.

        Args:
            matlab_endpoint_to_use (Callable): Function reference used to updated MATLAB and its busy status.
        """
        this_task = "update_matlab_state"
        # First check before acquiring the lock.
        if not self._are_required_processes_ready():
            await self.matlab_state_updater_lock.acquire()
            if (
                not self._are_required_processes_ready()
            ):  # Double check required processes are not ready before invoking set_matlab_state()
                self.set_matlab_state("down")
                logger.debug(f"{this_task}: Required processes are not ready yet")
                await self.matlab_state_updater_lock.release()
                # Double-checked locking: https://en.wikipedia.org/wiki/Double-checked_locking
                # If the lock is acquired inside the if condition (without a second check), it would lead to intermediate states
                # 'starting'(set by start_matlab) -> 'down' (set in the if condition above) -> 'up' (set by this function after matlab starts)

                # If lock is acquired before the if condition, it would lead to large sections of code being under lock which in this case would be
                # this entire function (and the functions calls within it).

            else:
                await self.matlab_state_updater_lock.release()
                await (
                    self._update_matlab_state_based_on_ready_file_and_connector_status(
                        matlab_endpoint_to_use
                    )
                )
                logger.debug(
                    f"{this_task}: Required processes are ready, Embedded Connector status is '{self.get_matlab_state()}'"
                )

        else:
            await self._update_matlab_state_based_on_ready_file_and_connector_status(
                matlab_endpoint_to_use
            )
            logger.debug(
                f"{this_task}: Required processes are ready, Embedded Connector status is '{self.get_matlab_state()}'"
            )

        await asyncio.sleep(CHECK_MATLAB_STATUS_INTERVAL_SECONDS)

    async def __update_matlab_state(self) -> None:
        """An indefinitely running asyncio task which determines the status of MATLAB to be down/starting/up."""
        this_task = "update_matlab_state"
        logger.debug(f"{this_task}: Starting task...")

        # Start with using the ping endpoint to update matlab and its 'busy' state.
        function_to_call = self.__update_matlab_state_using_ping_endpoint
        logger.debug("Using the 'ping' endpoint to determine MATLAB state")

        while True:
            await self.__update_matlab_state_based_on_endpoint_to_use(function_to_call)

            if self.get_matlab_state() == "up":
                logger.debug(
                    "MATLAB is up. Checking if 'busy' status endpoint is available"
                )

                # MATLAB is up, now switch to 'busy' status endpoint to check if 'busy' status updates
                # to a valid value.
                function_to_call = self.__update_matlab_state_using_busy_status_endpoint
                await self.__update_matlab_state_based_on_endpoint_to_use(
                    function_to_call
                )

                # If MATLAB 'busy' status is None even after MATLAB state is 'up', implies that the
                # endpoint is not available. So, fall back to using ping endpoint.
                if not self.matlab_busy_state:
                    function_to_call = self.__update_matlab_state_using_ping_endpoint
                    logger.debug(
                        "'busy' status endpoint returned an invalid response, falling back to using 'ping' endpoint to determine MATLAB state"
                    )
                    warning = f"{mwi_env.get_env_name_shutdown_on_idle_timeout()} environment variable is supported only for MATLAB versions R2021a or later"
                    logger.warning(warning)
                    self.warnings.append(warning)

                else:
                    logger.debug(
                        "'busy' status endpoint returned a valid response, will continue using it for determining MATLAB and its 'busy' state"
                    )

                break

        # Continue to use the same endpoint determined above.
        while True:
            await self.__update_matlab_state_based_on_endpoint_to_use(function_to_call)

    def set_matlab_state(self, new_state) -> None:
        """Updates MATLAB state. Will exit the matlab-proxy process if a lock is not acquired
        before calling this function.

        Args:
            new_state (str): The new state of MATLAB
        """
        caller = util.get_caller_name()
        if self.matlab_state_updater_lock.validate_lock_for_caller(caller):
            self.__matlab_state = new_state
            logger.debug(f"'{caller}()' function updated MATLAB state to '{new_state}'")

        else:
            # NOTE: This code branch should only ever be hit during development. We exit to enforce proper usage of this function during development time.
            sys.exit(1)

    def get_matlab_state(self) -> str:
        """Returns the state of MATLAB to be down/starting/up.

        Returns:
            String: Status of MATLAB. Returns either up, down or starting.
        """
        # Lock is not required when reading __matlab_state as the value maybe atmost 1 second old.
        # Additionally, having a lock for the getter will increase the latency for the /get_status requests coming in.
        return self.__matlab_state

    async def stop_server_tasks(self):
        """Stops all matlab-proxy server tasks"""
        await util.cancel_tasks(self.server_tasks)

    def _are_required_processes_ready(
        self, matlab_process=None, xvfb_process=None
    ) -> bool:
        """Checks if the required platform specific processes are ready.

        Args:
            matlab_process (asyncio.subprocess.Process | psutil.Process, optional): MATLAB process. Defaults to None.
            xvfb_process (asyncio.subprocess.Process, optional): Xvfb Process. Defaults to None.

        Returns:
            bool: Whether the required processes are ready or not.
        """

        # Update the processes to what is tracked in the instance's processes if a None is received
        if matlab_process is None:
            matlab_process = self.processes["matlab"]
        if xvfb_process is None:
            xvfb_process = self.processes["xvfb"]

        if system.is_linux():
            # If Xvfb is on system PATH, check if it up and running.
            if self.settings.get("is_xvfb_available", None) and (
                xvfb_process is None or xvfb_process.returncode is not None
            ):
                logger.debug(
                    "Xvfb has not started"
                    if xvfb_process is None
                    else f"Xvfb exited with returncode:{xvfb_process.returncode}"
                )
                return False

            if matlab_process is None or matlab_process.returncode is not None:
                logger.debug(
                    "MATLAB has not started"
                    if matlab_process is None
                    else f"MATLAB exited with returncode:{matlab_process.returncode}"
                )
                return False

        elif system.is_mac():
            if matlab_process is None or matlab_process.returncode is not None:
                logger.debug(
                    "MATLAB has not started"
                    if matlab_process is None
                    else f"MATLAB exited with returncode:{matlab_process.returncode}"
                )
                return False

        # For windows platform
        else:
            if matlab_process is None or not matlab_process.is_running():
                logger.debug(
                    "MATLAB has not started"
                    if matlab_process is None
                    else f"MATLAB exited with returncode:{matlab_process.wait()}"
                )
                return False

        return True

    def _get_token_auth_headers(self) -> dict | None:
        """Returns token info as headers if authentication is enabled.

        Returns:
            [Dict | None]: Returns token authentication headers if any.
        """
        return (
            {
                self.settings["mwi_auth_token_name_for_http"]: self.settings[
                    "mwi_auth_token_hash"
                ]
            }
            if self.settings["mwi_is_token_auth_enabled"]
            else None
        )

    async def _update_matlab_state_based_on_ready_file_and_connector_status(
        self, func_to_update_matlab_state: Callable[[], None]
    ) -> None:
        """Updates MATLAB and its 'busy' state based on Embedded Connector status.

        Args:
            func_to_update_matlab_state(callable): Function which updates MATLAB and its 'busy' state.
        """
        # NOTE: Double-checked locking should be applied where set_matlab_state() is called within this function,
        # as it is invoked frequently (from the __update_matlab_state or anywhere set_matlab_state() is invoked frequently)
        matlab_ready_file = self.matlab_session_files.get("matlab_ready_file")

        if not matlab_ready_file:
            await self.matlab_state_updater_lock.acquire()

            # Double check that matlab_ready_file is truthy before invoking set_matlab_state()
            if not matlab_ready_file:
                self.set_matlab_state("down")
                await self.matlab_state_updater_lock.release()
                return

            await self.matlab_state_updater_lock.release()
            return

        # If the matlab_ready_file path is constructed and is not yet created by the embedded connector.
        if matlab_ready_file and not matlab_ready_file.exists():
            await self.matlab_state_updater_lock.acquire()

            # Double check that matlab_ready_file is truthy and exists before invoking set_matlab_state()
            if matlab_ready_file and not matlab_ready_file.exists():
                self.set_matlab_state("starting")
                await self.matlab_state_updater_lock.release()
                return

            await self.matlab_state_updater_lock.release()
            return

        # Proceed to query the Embedded Connector about its state and update MATLAB and its 'busy' state.

        await func_to_update_matlab_state()

    async def set_licensing_nlm(self, conn_str):
        """Set the licensing type to NLM and the connection string."""

        # TODO Validate connection string
        self.licensing = {"type": "nlm", "conn_str": conn_str}
        self.persist_config_data()

    def set_licensing_existing_license(self):
        """Set the licensing type to NLM and the connection string."""
        self.licensing = {"type": "existing_license"}
        self.persist_config_data()

    async def set_licensing_mhlm(
        self,
        identity_token,
        email_addr,
        source_id,
        entitlements=[],
        entitlement_id=None,
    ):
        """Set the licensing type to MHLM and the details.

        Args:
            identity_token (String): Identity token of the user.
            email_addr (String): Email address of the user.
            source_id (String): Unique random string generated for the user.
            entitlements (list, optional): Eligible Entitlements of the user. Defaults to [].
            entitlement_id (String, optional): ID of an entitlement. Defaults to None.
        """
        try:
            token_data = await mw.fetch_expand_token(
                self.settings["mwa_api_endpoint"], identity_token, source_id
            )

            self.licensing = {
                "type": "mhlm",
                "identity_token": identity_token,
                "source_id": source_id,
                "expiry": token_data["expiry"],
                "email_addr": email_addr,
                "first_name": token_data["first_name"],
                "last_name": token_data["last_name"],
                "display_name": token_data["display_name"],
                "user_id": token_data["user_id"],
                "profile_id": token_data["profile_id"],
                "entitlements": entitlements,
                "entitlement_id": entitlement_id,
            }

            successful_update = await self.__update_and_persist_licensing()
            if successful_update:
                logger.debug("Login successful, persisting login information.")

        except OnlineLicensingError as e:
            self.error = e
            self.licensing = {
                "type": "mhlm",
                "email_addr": email_addr,
            }
            log_error(logger, e)

        except UIVisibleFatalError as e:
            self.error = e
            log_error(logger, e)

    async def set_licensing_from_token_response(self, token_response):
        """Set licensing from an OAuth token response.

        Used by both the device code sign-in flow and token refresh. The token
        response from the MathWorks OAuth server contains a nested ``mwa_token``
        object with the actual access token and user information. Fetches
        entitlements and auto-selects when only one is available.

        Args:
            token_response (dict): Token response from the OAuth server.
        """
        # The tokens are bound to the current client: an in-progress refresh
        # carries the client_id on self.licensing; a first-time device sign-in
        # has no licensing yet, so fall back to the configured client id.
        client_id = self.licensing.get("client_id") if self.licensing else None
        client_id = client_id or self.settings["oauth_client_id"]

        mwa_token = token_response.get("mwa_token", token_response)
        reference_detail = mwa_token.get("referenceDetail", {})
        access_token = mwa_token.get(
            "accessTokenString", token_response.get("access_token")
        )

        # Preserve the DPoP key already associated with this session (it must be
        # reused for refresh) so it survives a refresh that calls back into here.
        dpop_key = self.settings.get("dpop_key")

        # Preserve a previously chosen entitlement across a refresh. This method
        # rebuilds self.licensing from scratch, and a refresh on restore would
        # otherwise drop a multi-entitlement user's selection (auto-select below
        # only fires when there is exactly one entitlement).
        previous_entitlement_id = (
            self.licensing.get("entitlement_id") if self.licensing else None
        )

        # The refresh token is the durable credential. Some OAuth responses
        # include its lifetime in seconds; convert that to an absolute timestamp
        # when available so init_licensing() can avoid an unnecessary refresh
        # after expiry. The field is optional, however, and the refresh endpoint
        # remains the authority on token validity when it is absent.
        refresh_expires_in = token_response.get("refresh_expires_in")
        refresh_token_expiry = (
            (
                datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)
            ).isoformat()
            if refresh_expires_in is not None
            else None
        )

        self.licensing = {
            "type": "oauth",
            "client_id": client_id,
            # Access-token expiry (short-lived); kept in-memory for reference only.
            "expiry": mwa_token.get("expirationDate"),
            # Refresh-token expiry (durable); persisted and used as the startup gate.
            "refresh_token_expiry": refresh_token_expiry,
            "email_addr": reference_detail.get("email"),
            "first_name": reference_detail.get("firstName"),
            "last_name": reference_detail.get("lastName"),
            "display_name": reference_detail.get("displayName"),
            "user_id": reference_detail.get("userId"),
            "source_id": client_id,
            "token": access_token,
            "refresh_token": token_response.get("refresh_token"),
            "dpop_key": dpop_key,
            "entitlements": [],
            "entitlement_id": None,
        }

        # Fetch entitlements using the OAuth access token (same MHLM endpoint
        # used by the MHLM sign-in path).
        matlab_version = self.settings["matlab_version"]
        try:
            entitlements = await mw.fetch_entitlements(
                self.settings["mhlm_api_endpoint"],
                access_token,
                matlab_version,
            )
        except EntitlementError as e:
            # Do not retain the OAuth credentials from a token response that
            # cannot license this MATLAB release. Re-raise so each caller can
            # perform its context-specific cleanup and user-facing handling.
            self.licensing = None
            log_error(logger, e)
            raise

        self.licensing["entitlements"] = entitlements

        # Auto-select if only one entitlement is available; otherwise restore the
        # user's previous selection. This mirrors the MHLM cached path, which keeps
        # the entitlement_id restored from cache without re-validating that it is
        # still among the fetched entitlements.
        if len(entitlements) == 1:
            self.licensing["entitlement_id"] = entitlements[0]["id"]
        elif previous_entitlement_id is not None:
            self.licensing["entitlement_id"] = previous_entitlement_id

        self.persist_config_data()

    async def _refresh_oauth_licensing(self):
        """Refresh the OAuth access token using the stored refresh token.

        Uses the persisted DPoP key (the OAuth server requires the SAME key that
        was used during device authorization). SAT refresh tokens rotate, so the
        response contains a NEW refresh_token that replaces the old one - this is
        handled by set_licensing_from_token_response.
        """
        refresh_url = f"{self.settings['oauth_endpoint']}/oauth2/v1/oauth/refresh"
        client_id = self.licensing.get("client_id") or self.settings["oauth_client_id"]
        dpop_key = self.licensing.get("dpop_key")

        # Ensure the DPoP key is available to set_licensing_from_token_response.
        self.settings["dpop_key"] = dpop_key

        token_response = await mw.refresh_oauth_token(
            refresh_url,
            client_id,
            self.licensing["refresh_token"],
            dpop_key=dpop_key,
        )

        await self.set_licensing_from_token_response(token_response)

    def unset_licensing(self):
        """Unset the licensing."""

        self.licensing = None

        # If the error was due to licensing, clear it
        if isinstance(self.error, LicensingError):
            self.error = None

    def is_licensed(self):
        """Is MATLAB licensing configured?

        Returns:
            Boolean: True if MATLAB is Licensed. False otherwise.
        """
        if self.licensing is not None:
            logger.debug(f"Licensing type: {self.licensing.get('type')}")
            if self.licensing.get("type") == "nlm":
                if self.licensing.get("conn_str") is not None:
                    return True
            elif self.licensing.get("type") == "mhlm":
                if (
                    self.licensing.get("identity_token") is not None
                    and self.licensing.get("source_id") is not None
                    and self.licensing.get("expiry") is not None
                    and self.licensing.get("entitlement_id") is not None
                ):
                    return True
            elif self.licensing.get("type") == "oauth":
                # Gate on the durable credential (refresh_token), not the access
                # token or its expiry: the access token is ephemeral and re-derived
                # at startup, so it may legitimately be absent here. A usable
                # refresh token plus a chosen entitlement means we are licensed.
                if (
                    self.licensing.get("source_id") is not None
                    and self.licensing.get("refresh_token") is not None
                    and self.licensing.get("entitlement_id") is not None
                ):
                    return True
            elif self.licensing.get("type") == "existing_license":
                return True
        return False

    async def update_entitlements(self):
        """Speaks to MW and updates MHLM entitlements

        Raises:
            FatalError: When licensing is None or when licensing type is not MHLM.

        Returns:
            Boolean: True if update was successful
        """
        if self.licensing is None or self.licensing["type"] != "mhlm":
            raise FatalError(
                "MHLM licensing must be configured to update entitlements!"
            )

        try:
            # Fetch an access token
            access_token_data = await mw.fetch_access_token(
                self.settings["mwa_api_endpoint"],
                self.licensing["identity_token"],
                self.licensing["source_id"],
            )

            # Fetch entitlements
            entitlements = await mw.fetch_entitlements(
                self.settings["mhlm_api_endpoint"],
                access_token_data["token"],
                self.settings["matlab_version"],
            )

        except EntitlementError as e:
            self.error = e
            log_error(logger, e)
            self.licensing["identity_token"] = None
            self.licensing["source_id"] = None
            self.licensing["expiry"] = None
            self.licensing["first_name"] = None
            self.licensing["last_name"] = None
            self.licensing["display_name"] = None
            self.licensing["user_id"] = None
            self.licensing["profile_id"] = None
            self.licensing["entitlements"] = []
            self.licensing["entitlement_id"] = None
            # To ensure that any entitlement errors are displayed on the control panel,
            # the function returns true. The cached license file only contains the license type
            # and the user's email address. These two attributes are necessary for preventing
            # the LicenseGatherer step from becoming stuck on the front-end side.
            # Additionally, displaying the license type and user email address on the
            # information panel makes it worthwhile to maintain these attributes in the state.
            return True

        except OnlineLicensingError as e:
            self.error = e
            log_error(logger, e)
            return False

        # Keeping base error class at the last to catch any uncaught licensing related issues
        except OnlineLicensingError as e:
            self.error = e
            log_error(logger, e)
            return False

        self.licensing["entitlements"] = entitlements

        # Auto-select the entitlement if only one entitlement is returned from MHLM
        if len(entitlements) == 1:
            self.licensing["entitlement_id"] = entitlements[0]["id"]

        # Successful update
        return True

    # Set the entitlement information on app state as well as the cached file
    async def update_user_selected_entitlement_info(self, entitlement_id):
        self.licensing["entitlement_id"] = entitlement_id
        logger.debug(f"Successfully set {entitlement_id} as the entitlement_id")
        self.persist_config_data()

    def persist_config_data(self):
        """Saves config information to file"""
        if self.licensing is None:
            self.__delete_cached_config_file()

        elif self.licensing["type"] == "oauth":
            self._persist_oauth_config_data()

        elif self.licensing["type"] in ["mhlm", "nlm", "existing_license"]:
            logger.debug("Saving licensing information...")
            config = {
                "licensing": self.licensing,
                "matlab": {"version": self.settings["matlab_version"]},
            }
            self.__write_cached_config_file(config)

    def _persist_oauth_config_data(self):
        """Persist OAuth licensing into the multi-client ``clients`` array.

        The cached config file is shared across integrations, each with its own
        client_id. This loads any existing config, replaces or appends the entry
        for the current client_id (serializing the DPoP key), and writes it back.
        """
        logger.debug("Saving OAuth licensing information...")
        cached_config_file = self.__get_cached_config_file()

        client_id = self.licensing["client_id"]
        dpop_key = self.licensing.get("dpop_key")

        # NOTE: the access token ("token") and its short-lived expiry ("expiry")
        # are deliberately NOT persisted. They are ephemeral and re-derived by
        # refreshing at startup (mirroring the MHLM identity-token model). Only the
        # durable credential (refresh_token + dpop_key) and its computed
        # refresh_token_expiry are persisted.
        client_entry = {
            "client_id": client_id,
            "refresh_token_expiry": self.licensing.get("refresh_token_expiry"),
            "email_addr": self.licensing.get("email_addr"),
            "first_name": self.licensing.get("first_name"),
            "last_name": self.licensing.get("last_name"),
            "display_name": self.licensing.get("display_name"),
            "user_id": self.licensing.get("user_id"),
            "refresh_token": self.licensing.get("refresh_token"),
            "dpop_key": dpop_key.to_dict() if dpop_key else None,
            "entitlements": self.licensing.get("entitlements", []),
            "entitlement_id": self.licensing.get("entitlement_id"),
            "matlab": {"version": self.settings["matlab_version"]},
        }

        # Load any existing clients array so we don't clobber other integrations'
        # tokens that share this config file.
        clients = []
        if cached_config_file.exists():
            try:
                with open(cached_config_file, "r") as f:
                    existing = json.loads(f.read())
                if existing.get("licensing", {}).get("type") == "oauth":
                    clients = existing["licensing"].get("clients", [])
            except Exception:
                clients = []

        # Replace the entry for this client_id if present, else append.
        clients = [c for c in clients if c.get("client_id") != client_id]
        clients.append(client_entry)

        config = {"licensing": {"type": "oauth", "clients": clients}}
        self.__write_cached_config_file(config)

    def create_logs_dir_for_MATLAB(self):
        """Creates the root folder where MATLAB writes the ready file and updates attibutes on self."""

        # NOTE It is not guaranteed that the port will remain free!
        # FIXME Because of https://github.com/http-party/node-http-proxy/issues/1342 the
        # node application in development mode always uses port 31515 to bypass the
        # reverse proxy. Once this is addressed, remove this special case.
        if (
            mwi_env.is_development_mode_enabled()
            and not mwi_env.is_testing_mode_enabled()
        ):
            return 31515
        else:
            mwi_logs_root_dir = self.settings["mwi_logs_root_dir"]
            # Use the app_port number to identify the server as that is user visible
            mwi_logs_dir = mwi_logs_root_dir / str(self.settings["app_port"])

            # Create a folder to hold the matlab_ready_file that will be created by MATLAB to signal readiness
            # This is the same folder to which MATLAB will write logs to.
            mwi_logs_dir.mkdir(parents=True, exist_ok=True)

            # Created by MATLAB when it is ready to service requests
            matlab_ready_file = mwi_logs_dir / CONNECTOR_SECUREPORT_FILENAME

            # Update member variables of AppState class
            self.mwi_logs_dir = mwi_logs_dir
            self.matlab_session_files["matlab_ready_file"] = matlab_ready_file

            logger.debug(f"matlab_session_files:{self.matlab_session_files}")

            # check if the user has provided any code or not
            if self.settings.get("has_custom_code_to_execute"):
                # Keep a reference to the user code output file in the matlab_session_files for cleanup
                user_code_output_file = mwi_logs_dir / USER_CODE_OUTPUT_FILE_NAME
                self.matlab_session_files["startup_code_output_file"] = (
                    user_code_output_file
                )
                logger.info(
                    f"The results of executing MWI_MATLAB_STARTUP_SCRIPT are stored at: {user_code_output_file} "
                )
            return

    def create_server_info_file(self):
        mwi_logs_root_dir = self.settings["mwi_logs_root_dir"]
        # Use the app_port number to identify the server as that is user visible
        mwi_logs_dir = mwi_logs_root_dir / str(self.settings["app_port"])
        # Create a folder to hold the matlab_ready_file that will be created by MATLAB to signal readiness.
        # This is the same folder to which MATLAB will write logs to.
        mwi_logs_dir.mkdir(parents=True, exist_ok=True)

        mwi_server_info_file = mwi_logs_dir / "mwi_server.info"
        mwi_auth_token_str = token_auth.get_mwi_auth_token_access_str(self.settings)
        with open(mwi_server_info_file, "w", encoding="utf-8") as fh:
            fh.write(
                self.settings["mwi_server_url"]
                + mwi_auth_token_str
                + "\n"
                + self.settings["browser_title"]
                + "\n"
            )
        self.mwi_server_session_files["mwi_server_info_file"] = mwi_server_info_file
        logger.debug(f"Server info stored into: {mwi_server_info_file}")

        mwi.logger.log_startup_info(
            title=f"matlab-proxy-app running on {self.settings['app_port']}",
            matlab_urls=_get_server_urls(
                self.settings["mwi_server_url"], mwi_auth_token_str
            ),
        )
        logger.info(f"MATLAB Root: {self.settings['matlab_path']}")

    def clean_up_mwi_server_session(self):
        # Clean up mwi_server_session_files
        try:
            for session_file in self.mwi_server_session_files.items():
                if session_file[1] is not None:
                    logger.debug(f"Deleting:{session_file[1]}")
                    session_file[1].unlink()
        except FileNotFoundError:
            # Files may not exist if cleanup is called before they are created
            pass

    async def __setup_env_for_matlab(self) -> dict:
        """Configure the environment variables required for starting MATLAB by matlab-proxy.

        Returns:
            [dict]: Containing keys as the Env variable names and values are its corresponding values.
        """
        matlab_env = os.environ.copy()

        # Remove MLM_LICENSE_FILE unconditionally before applying licensing env vars.
        # This must happen regardless of licensing type because MLM_LICENSE_FILE has
        # higher precedence than other licensing options in MATLAB. If it's inherited
        # from the user's system environment, it would override the intended licensing
        # configuration on restart. When NLM licensing env variable is set,
        # __get_licensing_env_vars will re-set it to the correct connection string.
        matlab_env.pop("MLM_LICENSE_FILE", None)
        licensing_env = await self.__get_licensing_env_vars()
        matlab_env.update(licensing_env)

        # Env setup related to MATLAB
        ## Update the values only if it does not already exist in the environment
        matlab_env["MW_CRASH_MODE"] = matlab_env.get("MW_CRASH_MODE", "native")
        matlab_env["MATLAB_WORKER_CONFIG_ENABLE_LOCAL_PARCLUSTER"] = matlab_env.get(
            "MATLAB_WORKER_CONFIG_ENABLE_LOCAL_PARCLUSTER", "true"
        )
        matlab_env["MW_DOCROOT"] = os.path.join("ui", "webgui", "src")
        matlab_env["MWAPIKEY"] = self.settings["mwapikey"]

        # For r2020b, r2021a
        matlab_env["MW_CD_ANYWHERE_ENABLED"] = "true"
        # For >= r2021b
        matlab_env["MW_CD_ANYWHERE_DISABLED"] = "false"

        # DDUX info for MATLAB
        matlab_env["MW_CONTEXT_TAGS"] = self.settings.get("mw_context_tags")

        # Update DISPLAY env variable for MATLAB only if it was supplied by Xvfb.
        if system.is_linux():
            if self.settings.get("matlab_display", None):
                matlab_env["DISPLAY"] = self.settings["matlab_display"]
                logger.debug(
                    f"Using the display number supplied by Xvfb process'{matlab_env['DISPLAY']}' for starting MATLAB"
                )
            else:
                if "DISPLAY" in matlab_env:
                    logger.debug(
                        f"Using the existing DISPLAY environment variable with value:{matlab_env['DISPLAY']} for starting MATLAB"
                    )
                else:
                    logger.debug(
                        "No DISPLAY environment variable found. Starting MATLAB without it."
                    )

        # The matlab ready file is written into this location(self.mwi_logs_dir) by MATLAB
        # The mwi_logs_dir is where MATLAB will write any subsequent logs
        matlab_env["MATLAB_LOG_DIR"] = str(self.mwi_logs_dir)

        # Set MW_CONNECTOR_CONTEXT_ROOT
        matlab_env["MW_CONNECTOR_CONTEXT_ROOT"] = self.settings.get("base_url", "/")
        logger.debug(
            f"MW_CONNECTOR_CONTEXT_ROOT is set to: {matlab_env['MW_CONNECTOR_CONTEXT_ROOT']}"
        )

        # Env setup related to logging
        # Very verbose logging in debug or trace mode (trace is lower level than debug, so the below condition will also be true for trace level)
        if logger.isEnabledFor(logging.getLevelName("DEBUG")):
            mwi_log_file = self.settings.get("mwi_log_file", None)
            # If a log file is supplied to write matlab-proxy server logs,
            # use it to write MATLAB logs too.
            if mwi_log_file:
                # Append MATLAB logs to matlab-proxy logs
                matlab_env["MW_DIAGNOSTIC_DEST"] = f"file,append={mwi_log_file}"

            elif system.is_posix():
                matlab_env["MW_DIAGNOSTIC_DEST"] = "stdout"

            else:
                # On windows stdout is not supported yet.
                # So, use the default log file for MATLAB logs
                matlab_logs_file = self.mwi_logs_dir / MATLAB_LOGS_FILE_NAME
                # Write MATLAB logs
                matlab_env["MW_DIAGNOSTIC_DEST"] = f"file={matlab_logs_file}"

            logger.info(
                f"Writing MATLAB process logs to: {matlab_env['MW_DIAGNOSTIC_DEST']}"
            )

        if logger.isEnabledFor(logging.getLevelName("TRACE")):
            trace_spec = ".*=fatal,critical,error,warning;connector::worker.*=all;connector::container::http=all;connector::lifecycle=all;connector::http::server=all"
            existing_spec = matlab_env.get("MW_DIAGNOSTIC_SPEC", "")
            matlab_env["MW_DIAGNOSTIC_SPEC"] = (
                f"{existing_spec};{trace_spec}" if existing_spec else trace_spec
            )

        # TODO Introduce a warmup flag to enable this?
        # matlab_env["CONNECTOR_CONFIGURABLE_WARMUP_TASKS"] = "warmup_hgweb"
        # matlab_env["CONNECTOR_WARMUP"] = "true"

        return matlab_env

    async def __get_licensing_env_vars(self) -> dict:
        """Compute licensing-related environment variables for MATLAB startup.

        Based on the current licensing configuration (self.licensing), returns
        the appropriate environment variables:
        - "mhlm": fetches an access token and sets MLM_WEB_LICENSE, MLM_WEB_USER_CRED,
          MLM_WEB_ID, and MHLM_CONTEXT.
        - "nlm": sets MLM_LICENSE_FILE to the NLM connection string.
        - "existing_license": returns an empty dict (no additional env vars needed).

        Returns:
            dict: Environment variable names mapped to their values.

        Raises:
            OnlineLicensingError: If fetching the access token for mhlm licensing fails.
        """
        licensing_env = {}

        if self.licensing["type"] == "mhlm":
            access_token_data = await mw.fetch_access_token(
                self.settings["mwa_api_endpoint"],
                self.licensing["identity_token"],
                self.licensing["source_id"],
            )
            licensing_env["MLM_WEB_LICENSE"] = "true"
            licensing_env["MLM_WEB_USER_CRED"] = access_token_data["token"]
            licensing_env["MLM_WEB_ID"] = self.licensing["entitlement_id"]
            licensing_env["MHLM_CONTEXT"] = (
                "MATLAB_JAVASCRIPT_DESKTOP"
                if os.getenv(mwi_env.get_env_name_mhlm_context()) is None
                else os.getenv(mwi_env.get_env_name_mhlm_context())
            )

        elif self.licensing["type"] == "oauth":
            # Refresh the token if it is expired or within 1 hour of expiry.
            if self.licensing.get("refresh_token") and self.licensing.get("expiry"):
                try:
                    expiry_window = _parse_expiry(self.licensing["expiry"]) - timedelta(
                        hours=1
                    )
                    if expiry_window <= datetime.now(timezone.utc):
                        await self._refresh_oauth_licensing()
                except OnlineLicensingError:
                    self.__reset_and_delete_cached_config()
                    raise OnlineLicensingError(
                        "OAuth session expired. Please sign in again."
                    )

            licensing_env["MLM_WEB_LICENSE"] = "true"
            licensing_env["MLM_WEB_USER_CRED"] = self.licensing["token"]
            licensing_env["MLM_WEB_ID"] = self.licensing["entitlement_id"]
            licensing_env["MHLM_CONTEXT"] = (
                "MATLAB_JAVASCRIPT_DESKTOP"
                if os.getenv(mwi_env.get_env_name_mhlm_context()) is None
                else os.getenv(mwi_env.get_env_name_mhlm_context())
            )

        elif self.licensing["type"] == "nlm":
            licensing_env["MLM_LICENSE_FILE"] = self.licensing["conn_str"]

        return licensing_env

    def __filter_env_variables(env_vars: dict, prefix: str) -> dict:
        """Removes the keys that starts with the prefix supplied to this function

        Args:
            env_vars (dict): dict to be filtered
            prefix (str): starting characters of the keys to be removed

        Returns:
            dict: dict with filtered keys
        """
        return {
            key: value for key, value in env_vars.items() if not key.startswith(prefix)
        }

    async def __start_window_manager(self, display=None):
        if display is None:
            logger.info("Not starting fluxbox as display is not provided")
            return None

        wm_env = os.environ.copy()
        wm_env["DISPLAY"] = display
        wm_cmd = ["fluxbox", "-screen", "0", "-log", "/dev/null"]

        try:
            logger.info(f"Starting window manager with DISPLAY={wm_env['DISPLAY']}")
            return await asyncio.create_subprocess_exec(
                *wm_cmd, close_fds=False, env=wm_env, stderr=asyncio.subprocess.PIPE
            )

        except Exception as err:
            self.error = WindowManagerError(
                "Unable to start the Fluxbox Window Manager due to the following error: "
                + err
            )
            # Log the error on the console.
            log_error(logger, self.error)

        return None

    async def __start_xvfb_process(self):
        """Private method to start the xvfb process. Will set appropriate
        errors to self.error and return None when any exceptions are raised.

        Returns:
            (asyncio.subprocess.Process) : When Xvfb process is created successfully else None.
        """

        # Start Xvfb process and update display number in settings
        create_xvfb_cmd = self.settings["create_xvfb_cmd"]
        xvfb_cmd, dpipe = create_xvfb_cmd()
        filtered_env_variables = AppState.__filter_env_variables(
            os.environ.copy(), "MWI_"
        )

        try:
            xvfb, display_port = await mw.create_xvfb_process(
                xvfb_cmd, dpipe, filtered_env_variables
            )
            self.settings["matlab_display"] = ":" + str(display_port)

            logger.info(f"Started Xvfb with PID={xvfb.pid} on DISPLAY={display_port}")

            return xvfb

        # If something went wrong ie. exception is raised in starting Xvfb process, capture error for logging
        # and for showing the error on the frontend.

        # FileNotFoundError: is thrown if Xvfb is not found on System Path.
        # XvfbError: is thrown if something went wrong when starting Xvfb process.
        except (FileNotFoundError, XvfbError):
            self.error = XvfbError(
                """Unable to start the Xvfb process. Ensure Xvfb is installed and is available on the System Path. See https://github.com/mathworks/matlab-proxy#requirements for information on Xvfb"""
            )
            # Log the error on the console.
            log_error(logger, self.error)

        # If something else went wrong log the error and exit
        except Exception as err:
            self.error = err
            # Log the error on the console.
            log_error(logger, err)

        return None

    async def __start_matlab_process(self, matlab_env):
        """Starts the matlab process depending on the operating system. If an exception is raised,
        will update self.error and return None else will return the process object.

        Returns:
            (asyncio.subprocess.Process | psutil.Process): If process creation is successful, else return None.
        """
        # If there's no matlab_cmd available, it means that MATLAB is not available on system PATH.
        raw_cmd = self.settings.get("matlab_cmd")
        if not raw_cmd:
            raise MatlabInstallError(
                "Unable to find MATLAB on the system PATH. Add MATLAB to the system PATH, and restart matlab-proxy."
            )
        # Reason for using copy: To not overwrite the existing matlab_cmd.
        # Edge Case this solves: License using MLM -> Unlicense -> License using OL --> previous flags (licmode & file) still stays in matlab cmd.
        matlab_cmd = raw_cmd.copy()
        # Add license mode arguments based on the presence of MLM_LICENSE_FILE in environment
        if "MLM_LICENSE_FILE" in matlab_env:
            matlab_cmd.append("-licmode")
            if mwi_env.Experimental.get_licmode_override():
                matlab_cmd.append(mwi_env.Experimental.get_licmode_override())
                logger.info(f"Using MATLAB license mode arguments: {matlab_cmd}")
            else:
                matlab_cmd.append("file")

        if system.is_posix():
            import pty

            _, slave = pty.openpty()

            # In POSIX systems, the 'matlab' variable is of type asyncio.subprocess.Process()
            matlab = await asyncio.create_subprocess_exec(
                *matlab_cmd,
                env=matlab_env,
                stdin=slave,
                stderr=asyncio.subprocess.PIPE,
            )

            return matlab

        else:
            try:
                # In WINDOWS systems, the 'matlab' variable is of type psutil.Process()
                matlab = await windows.start_matlab(matlab_cmd, matlab_env)

                return matlab

            except UIVisibleFatalError as e:
                self.error = e
                log_error(logger, e)

            except Exception as err:
                self.error = err
                log_error(logger, err)

        # If something went wrong in starting matlab, return None
        return None

    async def __force_stop_matlab(self, error, task):
        """A private method to update self.error and force stop matlab"""
        self.error = MatlabError(error)
        logger.error(f"{task}: {error}")

        # If force_quit is not set to True, stop_matlab() would try to
        # send a HTTP request to the Embedded Connector (which is already "down")
        await self.stop_matlab(force_quit=True)

    async def __track_embedded_connector_state(self):
        """track_embedded_connector_state is an asyncio task to track the status of MATLAB Embedded Connector.
        This task will start and stop with the MATLAB process.
        """
        this_task = "track_embedded_connector_state:"
        logger.debug(f"{this_task}: Starting task...")

        while True:
            if self.embedded_connector_state == "up":
                logger.debug(
                    f"{this_task}: MATLAB Embedded Connector is up, not checking for any errors in MATLABs stderr pipe. Sleeping for 10 seconds..."
                )
                # Embedded connector is up, sleep for 10 seconds and recheck again
                await asyncio.sleep(10)
                continue

            # Embedded connector is down, so check for how long it has been down and error out if necessary
            # embedded_connector_start_time variable is updated by get_matlab_state().
            else:
                # If its not yet set, sleep for 1 second and recheck again
                if not self.embedded_connector_start_time:
                    await asyncio.sleep(1)
                    continue

                else:
                    time_diff = time.time() - self.embedded_connector_start_time
                    if time_diff > self.PROCESS_TIMEOUT:
                        # Since max allowed startup time has elapsed, it means that MATLAB is stuck and is unable to start.
                        # Set the error and stop matlab.
                        user_visible_error = "Unable to start MATLAB.\nTry again by clicking Start MATLAB."

                        if system.is_windows():
                            # In WINDOWS systems, errors are raised as UI windows and cannot be captured programmatically.
                            # So, raise a generic error wherever appropriate
                            generic_error = f"MATLAB did not start in {int(self.PROCESS_TIMEOUT)} seconds. Use Windows Remote Desktop to check for any errors."
                            logger.error(f":{this_task}: {generic_error}")

                            # Stopping the MATLAB process would remove the UI window displaying the error too.
                            # Do not stop the MATLAB or break from the loop (as the error is still unknown)
                            self.error = MatlabError(generic_error)
                            await asyncio.sleep(5)
                            continue

                        else:
                            # If there are no logs after the max startup time has elapsed, it means that MATLAB is stuck and is unable to start.
                            # Set the error and stop matlab.
                            logger.error(
                                f":{this_task}: MATLAB did not start in {int(self.PROCESS_TIMEOUT)} seconds!"
                            )
                            # MATLAB can be stopped on posix systems because the stderr pipe of the MATLAB process is
                            # read (by __matlab_stderr_reader_posix() task) and is logged by matlab-proxy appropriately.
                            await self.__force_stop_matlab(
                                user_visible_error, this_task
                            )
                            # Breaking out of the loop to end this task as matlab-proxy was unable to start MATLAB successfully
                            # even after waiting for self.PROCESS_TIMEOUT
                            break

                    else:
                        logger.debug(
                            f"{this_task}: MATLAB has been in a 'starting' state for {int(time_diff)} seconds. Sleeping for 1 second..."
                        )
                        await asyncio.sleep(1)

    async def __matlab_stderr_reader_posix(self):
        """matlab_stderr_reader_posix is an asyncio task which reads the stderr pipe of the MATLAB process, parses it
        and updates state variables accordingly.
        """
        if system.is_posix():
            matlab = self.processes["matlab"]
            logger.debug("matlab_stderr_reader_posix() task: Starting task...")

            while not matlab.stderr.at_eof():
                logger.debug(
                    "matlab_stderr_reader_posix() task: Waiting to read data from stderr pipe..."
                )
                line = await matlab.stderr.readline()
                if line is None:
                    logger.debug(
                        "matlab_stderr_reader_posix() task: Received data from stderr pipe appending to logs..."
                    )
                    break
                self.logs["matlab"].append(line)
            await self.handle_matlab_output()

    async def __update_matlab_port(self, delay: int):
        """Task to populate matlab_port from the matlab ready file. Times out if max_duration is breached

        Args:
            delay (int): time delay in seconds before retrying the file read operation
        """
        logger.debug(
            f"updating matlab_port information from {self.matlab_session_files['matlab_ready_file']}"
        )
        try:
            await asyncio.wait_for(
                self.__read_matlab_ready_file(delay),
                self.PROCESS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.debug(
                "Timeout error received while updating matlab port, stopping matlab!"
            )
            await self.stop_matlab(force_quit=True)
            self.error = MatlabError(
                "MATLAB startup has timed out. Click Start MATLAB to try again."
            )

    async def __read_matlab_ready_file(self, delay):
        # reads with delays from the file where connector has written its port information
        while not self.matlab_session_files["matlab_ready_file"].exists():
            await asyncio.sleep(delay)

        with open(self.matlab_session_files["matlab_ready_file"]) as f:
            self.matlab_port = int(f.read())
            logger.debug(
                f"MATLAB Ready file successfully read, matlab_port set to: {self.matlab_port}"
            )

    async def start_matlab(self, restart_matlab=False):
        """Start MATLAB.

        Args:
            restart_matlab (bool, optional): Whether to restart MATLAB. Defaults to False.
        """
        # Ensure that previous processes are stopped
        await self.stop_matlab()

        # Acquire lock before setting MATLAB state to 'starting'.

        # The lock is held for a substantial part of this function's execution to prevent asynchronous updates
        # to MATLAB state by other functions/tasks until the lock is released, ensuring consistency. It's released early only in case of exceptions.
        await self.matlab_state_updater_lock.acquire()
        self.set_matlab_state("starting")
        logger.info("Starting MATLAB...")

        # Clear MATLAB errors and logging
        self.error = None
        self.logs["matlab"].clear()

        # Start Xvfb process on linux if possible
        if system.is_linux() and self.settings["is_xvfb_available"]:
            xvfb = await self.__start_xvfb_process()

            # xvfb variable would be None if creation of the process failed.
            # Halt MATLAB process startup by returning early.
            if xvfb is None:
                return

            self.processes["xvfb"] = xvfb

        # Start Window Manager on linux if possible
        if system.is_linux() and self.settings["is_windowmanager_available"]:
            display = self.settings.get("matlab_display", None)
            await self.__start_window_manager(display)

        try:
            # Prepare ready file for the MATLAB process.
            self.create_logs_dir_for_MATLAB()

            # Configure the environment MATLAB needs to start
            matlab_env = await self.__setup_env_for_matlab()

            logger.debug(
                "Prepared ready file and configured the environment for MATLAB startup"
            )

        # If there's something wrong with setting up files or env setup for starting matlab, capture the error for logging
        # and to pass to the front-end. Halt MATLAB process startup by returning early
        except Exception as err:
            # Release lock if an exception occurs as we are returning early and since it will be required by stop_matlab
            await self.matlab_state_updater_lock.release()
            self.error = err
            log_error(logger, err)
            # stop_matlab() does the teardown work by removing any residual files and processes created till now
            # which is Xvfb process creation and ready file for the MATLAB process.
            await self.stop_matlab()
            return

        # Start MATLAB Process
        logger.debug("Starting MATLAB")

        try:
            matlab = await self.__start_matlab_process(matlab_env)

        # If there's an error with starting MATLAB, set the error to the state and matlab to None
        except MatlabInstallError as err:
            log_error(logger, err)
            self.error = err
            matlab = None

        # Release the lock after MATLAB process has started.
        await self.matlab_state_updater_lock.release()

        # matlab variable would be None if creation of the process failed.
        if matlab is None:
            # call self.stop_matlab().This does the teardown work by removing any residual files and processes created till now.
            # Force quitting matlab as something went wrong in starting the matlab process itself.
            await self.stop_matlab(force_quit=True)
            return

        logger.debug(f"Started MATLAB (PID={matlab.pid})")
        self.processes["matlab"] = matlab

        loop = util.get_event_loop()
        # Start all tasks relevant to MATLAB process
        self.matlab_tasks["matlab_stderr_reader_posix"] = loop.create_task(
            self.__matlab_stderr_reader_posix()
        )
        self.matlab_tasks["track_embedded_connector_state"] = loop.create_task(
            self.__track_embedded_connector_state()
        )
        self.matlab_tasks["update_matlab_port"] = loop.create_task(
            self.__update_matlab_port(self.MATLAB_PORT_CHECK_DELAY_IN_SECONDS)
        )
        self.matlab_tasks["update_matlab_state"] = loop.create_task(
            self.__update_matlab_state()
        )

    async def __send_stop_request_to_matlab(self):
        """Private method to send a HTTP request to MATLAB to shutdown gracefully

        Raises:
            Exception: EmbeddedConnectorError if the request fails.
        """

        try:
            data = mwi.embedded_connector.helpers.get_data_to_eval_mcode("exit")
            headers = self._get_token_auth_headers()
            url = mwi.embedded_connector.helpers.get_mvm_endpoint(
                self.settings["mwi_server_url"]
            )

            resp_json = await mwi.embedded_connector.send_request(
                url=url,
                method="POST",
                data=data,
                headers=headers,
            )

            if resp_json["messages"]["EvalResponse"][0]["isError"]:
                raise EmbeddedConnectorError(
                    "Failed to send HTTP request to Embedded connector"
                )

        except Exception as err:
            raise err

    async def stop_matlab(self, force_quit=False):
        """Terminate MATLAB."""

        matlab_state = self.get_matlab_state()

        # Acquire lock before setting MATLAB state to 'stopping'.

        # The lock is held for a substantial part of this function's execution to prevent asynchronous updates
        # to MATLAB state by other functions/tasks until the lock is released, ensuring consistency. It's released early only in case of exceptions.
        await self.matlab_state_updater_lock.acquire()

        self.set_matlab_state("stopping")
        # Clean up session files which determine various states of the server &/ MATLAB.
        # Do this first as stopping MATLAB/Xvfb takes longer and may fail

        # Files won't exist when stop_matlab is called for the first time.
        for (
            session_file_name,
            session_file_path,
        ) in self.matlab_session_files.items():
            if session_file_path is not None:
                self.matlab_session_files[session_file_name] = None
                with contextlib.suppress(FileNotFoundError):
                    logger.debug("Deleting: %s", session_file_path)
                    session_file_path.unlink()

        # In posix systems, variable matlab is an instance of asyncio.subprocess.Process()
        # In windows systems, variable matlab is an instance of psutil.Process()
        matlab = self.processes["matlab"]

        waiters = []
        if matlab is not None:
            if system.is_posix() and matlab.returncode is None:
                # Close the stderr stream to prevent indefinite hanging on it due to a child
                # process inheriting it, fixes https://github.com/mathworks/matlab-proxy/issues/44
                self._close_matlab_stderr_stream(matlab)

                # Sending an exit request to the embedded connector takes time.
                # When MATLAB is in a "starting" state (implies the Embedded connector is not up)
                # OR
                # When force_quit is set to True
                # directly terminate the MATLAB process instead.
                if matlab_state == "starting" or force_quit:
                    logger.debug("Forcing the MATLAB process to terminate...")
                    matlab.terminate()
                    waiters.append(matlab.wait())
                else:
                    logger.debug("Sending HTTP request to stop the MATLAB process...")
                    try:
                        # Send HTTP request
                        await self.__send_stop_request_to_matlab()

                        # Wait for matlab to shutdown gracefully
                        await matlab.wait()

                        assert (
                            matlab.returncode == 0
                        ), "Failed to gracefully shutdown MATLAB via the embedded connector"

                        logger.debug("Stopped the MATLAB process gracefully")

                    except Exception as err:
                        log_error(logger, err)
                        logger.info(
                            "Failed to stop MATLAB gracefully, terminating the process."
                        )
                        try:
                            matlab.terminate()
                            await matlab.wait()
                        except Exception as ex:
                            logger.debug(
                                "Received an exception while terminating matlab: %s", ex
                            )
            else:
                # In a windows system
                if system.is_windows() and matlab.is_running():
                    if matlab_state == "starting" or force_quit:
                        matlab.terminate()
                        matlab.wait()

                    else:
                        # send request to embedded connector to stop matlab.
                        logger.debug(
                            "Sending HTTP request to stop the MATLAB process..."
                        )

                        try:
                            # Send HTTP request
                            await self.__send_stop_request_to_matlab()

                            # Wait for matlab to shutdown gracefully
                            matlab.wait()
                            assert (
                                not matlab.is_running()
                            ), "Failed to gracefully shutdown MATLAB via the embedded connector"

                            logger.debug("Stopped the MATLAB process gracefully")

                        except Exception as err:
                            log_error(logger, err)
                            logger.info(
                                "Failed to stop MATLAB gracefully, terminating the process."
                            )
                            try:
                                matlab.terminate()
                                matlab.wait()
                            except Exception as e:
                                logger.debug(
                                    "Received an exception while terminating matlab: %s",
                                    e,
                                )

        logger.debug("Stopped (any running) MATLAB process.")

        # Terminating Xvfb
        if system.is_posix():
            xvfb = self.processes["xvfb"]
            if xvfb is not None and xvfb.returncode is None:
                logger.debug("Terminating Xvfb (PID=%d)", xvfb.pid)
                xvfb.terminate()
                waiters.append(xvfb.wait())

        if len(waiters) > 0:
            logger.debug("Waiting for MATLAB/Xvfb to terminate")
            for waiter in waiters:
                await waiter

        self.set_matlab_state("down")
        # Release lock for the __update_matlab_state task to determine MATLAB state.
        await self.matlab_state_updater_lock.release()

        # Canceling all MATLAB process related tasks
        await util.cancel_tasks(self.matlab_tasks)

        # After stopping all the tasks, set self.matlab_tasks to empty dict
        self.matlab_tasks = {}

        # Clear logs if MATLAB stopped intentionally
        logger.debug("Clearing logs!")
        self.logs["matlab"].clear()
        logger.debug("Cleared any logs created by the MATLAB process.")

        # Update matlab_port information in the event of intentionally stopping MATLAB
        self.matlab_port = None
        logger.debug("Completed Shutdown!!!")

    def _close_matlab_stderr_stream(self, matlab):
        """
        This method attempts to close the stderr stream associated with the MATLAB process
        to prevent potential resource leaks. It logs a debug message if the stream is
        successfully closed.

        Args:
            matlab: The MATLAB process reference.
        """
        stderr_stream = matlab._transport.get_pipe_transport(sys.stderr.fileno())
        if stderr_stream:
            logger.debug(
                "Closing matlab process stderr stream: %s",
                stderr_stream,
            )
            stderr_stream.close()

    async def handle_matlab_output(self):
        """Parse MATLAB output from stdout and raise errors if any."""
        matlab = self.processes["matlab"]

        # Wait for MATLAB process to exit
        logger.info("Waiting for MATLAB to exit...")
        await matlab.wait()

        rc = self.processes["matlab"].returncode
        logger.info(
            f"MATLAB has shutdown with {'exit' if rc == 0 else 'error'} code: {rc}"
        )

        # Look for errors if MATLAB was not intentionally stopped and had an error code
        if len(self.logs["matlab"]) > 0 and rc != 0:
            err = None
            logs = [log.decode().rstrip() for log in self.logs["matlab"]]

            def parsed_errs():
                if self.licensing["type"] == "nlm":
                    yield mw.parse_nlm_error(logs, self.licensing["conn_str"])
                if self.licensing["type"] == "mhlm":
                    yield mw.parse_mhlm_error(logs)
                yield mw.parse_other_error(logs)

            for err in parsed_errs():
                if err is not None:
                    break

            if err is not None:
                self.error = err
                log_error(logger, err)

    def get_session_status(self, is_desktop, client_id, transfer_session):
        """
        Determines the session status for a client, potentially generating a new client ID.

        This function is responsible for managing and tracking the session status of a client.
        It can generate a new client ID if one is not provided and the conditions are met.
        It also manages the active client status within the session, especially in scenarios
        involving desktop clients and when concurrency checks are enabled.

        Args:
            is_desktop (bool): A flag indicating whether the client is a desktop client.
            client_id (str or None): The client ID. If None, a new client ID may be generated.
            transfer_session (bool): Indicates whether the session should be transferred to this client.

        Returns:
            tuple:
                - A 2-tuple containing the generated client ID (or None if not generated) and
                a boolean indicating whether the client is considered the active client.
                - If concurrency checks are not enabled or the client is not a desktop client, it returns None for both
                the generated client ID and the active client status.
        """
        if IS_CONCURRENCY_CHECK_ENABLED and is_desktop:
            generated_client_id = None
            if not client_id:
                generated_client_id = str(uuid.uuid4())
                client_id = generated_client_id

            if not self.active_client or transfer_session:
                self.active_client = client_id

                if not self.server_tasks.get("detect_client_status", None):
                    # Create the loop to detect the active status of the client
                    loop = util.get_event_loop()
                    self.server_tasks["detect_client_status"] = loop.create_task(
                        self.detect_active_client_status()
                    )

            if self.active_client == client_id:
                is_active_client = True
                self.active_client_request_detected = True
            else:
                is_active_client = False
            return generated_client_id, is_active_client
        return None, None

    async def detect_active_client_status(self, sleep_time=1, max_inactive_count=10):
        """Detects whether the client is online or not by continuously checking if the active client is making requests

        Args:
            sleep_time (int): The time in seconds for which the process waits before checking for the next get_status request from the active client.
            max_inactive_count (int): The maximum number of times the check for the request from the active_client fails before reseting the active client id.
        """
        inactive_count = 0
        while self.active_client:
            # Check if the get_status request from the active client is received or not
            await asyncio.sleep(sleep_time)
            if self.active_client_request_detected:
                self.active_client_request_detected = False
                inactive_count = 0
            else:
                inactive_count = inactive_count + 1
            if inactive_count > max_inactive_count:
                # If no request is received from the active_client for more than 10 seconds then clear the active client id
                inactive_count = 0
                self.active_client = None

        await util.cancel_tasks([self.server_tasks.get("detect_client_status")])
