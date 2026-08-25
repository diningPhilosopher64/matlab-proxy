# Copyright 2020-2026 The MathWorks, Inc.

import asyncio
import os
import select
import urllib.parse
import xml.etree.ElementTree as ET

import aiohttp

from matlab_proxy.default_configuration import config
from matlab_proxy.settings import get_process_startup_timeout
from matlab_proxy.util import mwi
from matlab_proxy.util.mwi import environment_variables as mwi_env
from matlab_proxy.util.mwi.exceptions import (
    EntitlementError,
    MatlabError,
    NetworkLicensingError,
    OnlineLicensingError,
    XvfbError,
)

logger = mwi.logger.get()


def __get_licensing_url():
    """Private function to query for the licensing URL

    Returns:
        String: Licensing URL
    """
    return f"{config['doc_url']}blob/main/MATLAB-Licensing-Info.md"


async def fetch_entitlements(mhlm_api_endpoint, access_token, matlab_release):
    """Asynchronously fetch entitlements from MHLM endpoint. Used when licensing using MHLM.

    Args:
        mhlm_api_endpoint (String): URL of the API endpoint for fetching entitlements from MHLM.
        access_token (String): An access token which was requested by the fetch_acces_token() method
        matlab_release (String): MATLAB Release version installed in the system.
        mhlm_context: Environment specific info sent to the mhlm_api_endpoint

    Raises:
        OnlineLicensingError: Raised when unable to receive proper response from MHLM servers.
        EntitlementError: Raised when no entitlements are present for a license.

    Returns:
        list: Representing a list of Dicts containing the id, label and license_number.
    """
    # Get entitlements for token
    async with aiohttp.ClientSession(trust_env=True) as client_session:
        async with client_session.post(
            mhlm_api_endpoint,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data=aiohttp.FormData(
                {
                    "token": access_token,
                    "release": matlab_release,
                    "coreProduct": "ML",
                    "context": "jupyter",
                    "excludeExpired": "true",
                }
            ),
        ) as res:
            if not res.ok:
                raise OnlineLicensingError(
                    f"Communication with {mhlm_api_endpoint} failed ({res.status}). For more details, see {__get_licensing_url()}."
                )

            root = ET.fromstring(await res.text())
            entitlement_el = root.find("entitlements")

            if entitlement_el is None or len(entitlement_el) == 0:
                raise EntitlementError(
                    f"Your MathWorks account is not linked to a valid license for MATLAB {matlab_release}.\nSign out and login with a licensed user."
                )

            entitlements = entitlement_el.findall("entitlement")

            return [
                {
                    "id": entitlement.find("id").text,
                    "label": entitlement.find("label").text,
                    "license_number": entitlement.find("license_number").text,
                }
                for entitlement in entitlements
            ]


async def fetch_expand_token(mwa_api_endpoint, identity_token, source_id):
    """Asynchronously fetch tokens from MWA API endpoint.

    Args:
        mwa_api_endpoint (String): URL of the MWA API endpoint.
        identity_token (String): Identity token received from MHLM servers by the front end.
        source_id (String): Source ID received from MHLM servers by the front end.

    Raises:
        OnlineLicensingError: When unable to contact MWA API endpoint.

    Returns:
        Dict: Containing User and License expiration details.
    """
    async with aiohttp.ClientSession(trust_env=True) as client_session:
        async with client_session.post(
            f"{mwa_api_endpoint}/tokens",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "accept": "application/json",
                "X_MW_WS_callerId": "desktop-jupyter",
            },
            data=aiohttp.FormData(
                {
                    "tokenString": identity_token,
                    "tokenPolicyName": "R2",
                    "sourceId": source_id,
                }
            ),
        ) as res:
            if not res.ok:
                raise OnlineLicensingError(
                    f"Communication with {mwa_api_endpoint} failed ({res.status}). For more details, see {__get_licensing_url()}."
                )

            data = await res.json()

            return {
                "expiry": data["expirationDate"],
                "first_name": data["referenceDetail"]["firstName"],
                "last_name": data["referenceDetail"]["lastName"],
                "display_name": data["referenceDetail"]["displayName"],
                "user_id": data["referenceDetail"]["userId"],
                "profile_id": data["referenceDetail"]["referenceId"],
            }


async def fetch_access_token(mwa_api_endpoint, identity_token, source_id):
    """Asynchronously fetch access token from MWA API endpoint.

    Args:
        mwa_api_endpoint (String): URL of the MWA API endpoint.
        identity_token (String): String representing unique identity
        source_id (String): []

    Raises:
        OnlineLicensingError: When unable to contact MWA API endpoint.

    Returns:
        Dict : Containing the Access token.
    """
    # MWAJ -> Long-running session (90 days), MWAS -> Short-running session (24 hours)
    # It comes with the security risk of being stolen and used by an attacker for an extended period.
    # Hence, it is recommended to use MWAJ only when necessary.
    access_token_type = (
        "MWAJ" if mwi_env.Experimental.is_long_running_session_enabled() else "MWAS"
    )
    logger.debug(f"Requesting access token of type: {access_token_type}")

    async with aiohttp.ClientSession(trust_env=True) as client_session:
        async with client_session.post(
            f"{mwa_api_endpoint}/tokens/access",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "accept": "application/json",
                "X_MW_WS_callerId": "desktop-jupyter",
            },
            data=aiohttp.FormData(
                {
                    "tokenString": identity_token,
                    "type": access_token_type,
                    "sourceId": source_id,
                }
            ),
        ) as res:
            if not res.ok:
                raise OnlineLicensingError(
                    f"Communication with {mwa_api_endpoint} failed ({res.status}). For more details, see {__get_licensing_url()}."
                )

            data = await res.json()

            return {
                "token": data["accessTokenString"],
            }


DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


async def device_authorize(
    oauth_host, client_id, code_challenge, source_id, dpop_key=None
):
    """Initiate the OAuth 2.0 device authorization flow with the MathWorks OAuth server.

    Args:
        oauth_host (str): OAuth server base URL (e.g. "https://signin.mathworks.com").
        client_id (str): The OAuth public client id.
        code_challenge (str): PKCE code challenge (S256 of the code verifier).
        source_id (str): Session tracking id.
        dpop_key (DPoPKey, optional): DPoPKey instance for proof-of-possession.

    Raises:
        OnlineLicensingError: If the endpoint redirects, returns non-JSON, or errors.

    Returns:
        dict: Device authorization response with user_code, verification_uri,
            device_code, expires_in and interval.
    """
    device_auth_endpoint = f"{oauth_host}/oauth2/v1/oauth/device/authorize"

    # MWAJ elevation is scope-driven: adding "token_type:mwaj" requests a
    # long-running (90 day) access token instead of the default MWAS (~24 hours).
    # It comes with the security risk of being stolen and used by an attacker for
    # an extended period, so it is opt-in via MWI_ENABLE_LONG_RUNNING_SESSION.
    scope = "openid profile email"
    if mwi_env.Experimental.is_long_running_session_enabled():
        scope += " token_type:mwaj"
    logger.debug(f"Requesting device authorization with scope: {scope}")

    payload = {
        "client_id": client_id,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "source_id": source_id,
    }

    headers = {"Content-Type": "application/json"}
    if dpop_key:
        headers["DPoP"] = dpop_key.generate_proof("POST", device_auth_endpoint)

    async with (
        aiohttp.ClientSession(trust_env=True) as client_session,
        client_session.post(
            device_auth_endpoint,
            json=payload,
            headers=headers,
            allow_redirects=False,
        ) as resp,
    ):
        # Reject redirects - the OAuth server should respond directly. A
        # redirect usually means the device flow is not available here.
        if resp.status in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "unknown")
            raise OnlineLicensingError(
                f"Device authorization endpoint not available (redirect to: {location})."
            )

        if resp.status != 200:
            raise OnlineLicensingError(
                f"Device authorization failed: HTTP {resp.status}"
            )

        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise OnlineLicensingError(
                "Device authorization returned a non-JSON response."
            )

        return await resp.json()


async def check_device_auth_status(oauth_host, device_code, client_id):
    """Check device authorization status using the lightweight GET endpoint.

    This is cheaper than the token endpoint and doesn't consume token rate limits.

    Args:
        oauth_host (str): OAuth server base URL.
        device_code (str): The device code from device authorization.
        client_id (str): The OAuth client id.

    Returns:
        dict: With a "status" field: "PENDING", "AUTHORIZED", "TOKEN_ISSUED",
            "DENIED" or "EXPIRED".
    """
    params = urllib.parse.urlencode(
        {"device_code": device_code, "client_id": client_id}
    )
    url = f"{oauth_host}/oauth2/v1/oauth/device/authstatus?{params}"

    async with (
        aiohttp.ClientSession(trust_env=True) as client_session,
        client_session.get(url) as resp,
    ):
        if resp.status != 200:
            text = await resp.text()
            raise OnlineLicensingError(
                f"Auth status check failed: {resp.status} - {text[:200]}"
            )
        return await resp.json()


async def exchange_device_token(
    token_url, device_code, client_id, code_verifier, dpop_key=None
):
    """Exchange a device code for tokens (single attempt, no polling).

    Called after authstatus returns AUTHORIZED or TOKEN_ISSUED.

    Args:
        token_url (str): The OAuth token endpoint URL.
        device_code (str): The device code from device authorization.
        client_id (str): The OAuth client id.
        code_verifier (str): The PKCE code verifier.
        dpop_key (DPoPKey, optional): DPoPKey instance for proof-of-possession.

    Returns:
        dict: Token response containing access_token, refresh_token, mwa_token, etc.
    """
    payload = {
        "grant_type": DEVICE_CODE_GRANT_TYPE,
        "device_code": device_code,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if dpop_key:
        headers["DPoP"] = dpop_key.generate_proof("POST", token_url)

    async with (
        aiohttp.ClientSession(trust_env=True) as client_session,
        client_session.post(
            token_url, data=urllib.parse.urlencode(payload), headers=headers
        ) as resp,
    ):
        if resp.status != 200:
            try:
                error_response = await resp.json()
            except Exception:
                error_response = {}
            error = error_response.get("error", f"HTTP {resp.status}")
            raise OnlineLicensingError(f"Token exchange failed: {error}")

        from pprint import pprint

        print("\n\n Hello \n\n")
        pprint(await resp.json())

        return await resp.json()


async def refresh_oauth_token(refresh_url, client_id, refresh_token, dpop_key=None):
    """Refresh an OAuth access token using the refresh token.

    Device flow uses SAT-based refresh tokens - no correlation_id is needed.
    IMPORTANT: SAT refresh tokens rotate on every refresh. The response contains
    a NEW refresh_token that MUST be stored, replacing the old one.

    Args:
        refresh_url (str): The OAuth refresh endpoint URL.
        client_id (str): The OAuth client id.
        refresh_token (str): The current refresh token.
        dpop_key (DPoPKey, optional): MUST be the same key used during device
            authorization.

    Returns:
        dict: New token response containing a new access_token AND a new
            refresh_token (rotated).
    """
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    headers = {"Content-Type": "application/json"}
    if dpop_key:
        headers["DPoP"] = dpop_key.generate_proof("POST", refresh_url)

    async with (
        aiohttp.ClientSession(trust_env=True) as client_session,
        client_session.post(refresh_url, json=payload, headers=headers) as resp,
    ):
        if resp.status != 200:
            try:
                error_response = await resp.json()
            except Exception:
                error_response = {}
            error = error_response.get("error", f"HTTP {resp.status}")
            raise OnlineLicensingError(f"Token refresh failed: {error}")
        return await resp.json()


async def revoke_oauth_token(revoke_url, client_id, refresh_token, dpop_key=None):
    """Revoke an OAuth refresh token (RFC 7009), invalidating the server-side session.

    Called on sign-out for the device flow. matlab-proxy is a public/DPoP client,
    so revocation is authenticated with a DPoP proof signed by the SAME key that
    was used during device authorization (no client_secret).

    Per RFC 7009 the server always returns HTTP 200, so this is best-effort: a
    non-200 or network error is logged but not raised - local licensing state is
    cleared regardless.

    Args:
        revoke_url (str): The OAuth revoke endpoint URL.
        client_id (str): The OAuth client id that owns the token.
        refresh_token (str): The refresh token to revoke.
        dpop_key (DPoPKey, optional): MUST be the same key used during device
            authorization (the server verifies the jkt binding).

    Returns:
        bool: True if the server acknowledged the request (HTTP 200), else False.
    """
    payload = {
        "token": refresh_token,
        "token_type_hint": "refresh_token",
        "client_id": client_id,
    }

    headers = {"Content-Type": "application/json"}
    if dpop_key:
        headers["DPoP"] = dpop_key.generate_proof("POST", revoke_url)

    try:
        async with (
            aiohttp.ClientSession(trust_env=True) as client_session,
            client_session.post(revoke_url, json=payload, headers=headers) as resp,
        ):
            if resp.status != 200:
                logger.warning(f"Token revocation returned HTTP {resp.status}.")
                return False
            print("\n\n\n Successfully hit the revoke endpoint....")
            return True
    except Exception as e:
        # Best-effort: never block sign-out on a revoke failure.
        logger.warning(f"Token revocation request failed: {e}")
        return False


def range_matlab_connector_ports():
    """Generator of acceptable ports for MATLAB Connector.
        Allowed ports conform to the regex: [3,6]1[5-9][1-9][1-9]

    Yields:
        Int : Representing a Port number.
    """
    for p1 in (3, 6):
        p2 = 1
        for p3 in range(5, 10):
            for p4 in range(1, 10):
                for p5 in range(1, 10):
                    yield int(f"{p1}{p2}{p3}{p4}{p5}")


def parse_nlm_error(logs, conn_str):
    """Parses error logs and returns NLM specific errors

    Args:
        logs (List): An array containing error logs.
        conn_str (String): The connection string of NLM.

    Returns:
        List: Containing NLM specific errors.
    """
    nlm_logs = []
    start = False
    for log in logs:
        if start is False:
            if "License checkout failed" in log:
                start = True
                nlm_logs.append(log)
        else:
            if "Diagnostic Information" in log:
                return NetworkLicensingError(
                    f"License checkout from {conn_str} failed. For more details, see {__get_licensing_url()}.",
                    logs=nlm_logs,
                )
            nlm_logs.append(log)
    return None


def parse_mhlm_error(logs):
    """Parses error logs and returns MHLM specific errors

    Args:
        logs (List): An array containing error logs.

    Returns:
        List: Containing MHLM specific errors.
    """
    mhlm_logs = None
    start = False
    for log in logs:
        if "License Manager Error" in log:
            start = True
            mhlm_logs = [log]

        if start is True:
            mhlm_logs.append(log)

    if mhlm_logs is not None:
        return OnlineLicensingError(
            f"Usage of MathWorks Online Licensing failed. For more details, see {__get_licensing_url()}.",
            logs=mhlm_logs,
        )
    return None


def parse_other_error(logs):
    """Returns a MATLAB specific error.

    Args:
        logs (List): An array containing error logs.

    Returns:
        MatlabError: An instance of MatlabError class with logs.
    """
    return MatlabError(
        "MATLAB returned an unexpected error. For more details, see the log below.",
        logs=logs,
    )


async def create_xvfb_process(xvfb_cmd, pipe, env=None):
    """Creates the Xvfb process.

    The Xvfb process is run with '-displayfd' flag set. This makes Xvfb choose an available
    display number and write it into the provided write descriptor. ie: pipe[1]

    We read this display number from the read descriptor.
    For this, we have 2 things to consider:
        1. How many bytes to read from the read descriptor. This is handled by the variable number_of_bytes.

        2. For how long to read from the read descriptor. We wait for atmost 10 seconds for Xvfb to write
           the display number using the 'select' package.


    Args:
        xvfb_cmd (List): A list containing the command to run the Xvfb process
        pipe (List): A list containing a pair of file descriptor.
        env (Dict): A Dict containing environment variables for the Xvfb process.

    Returns:
        List: Containing the Xvfb process object, and display number on which Xvfb process has started.
    """

    # Creates subprocess asynchronously with environment variables defined in matlab_env
    # Pipe errors, if any, to the process object instead of stdout.
    xvfb = await asyncio.create_subprocess_exec(
        *xvfb_cmd, close_fds=False, env=env, stderr=asyncio.subprocess.PIPE
    )

    read_descriptor, write_descriptor = pipe
    number_of_bytes = 200

    logger.debug("Waiting for XVFB process to initialize and provide Display Number")

    # Wait for timeout specified by matlab-proxy for launching processes.
    ready_descriptors, _, _ = select.select(
        [read_descriptor], [], [], get_process_startup_timeout()
    )

    # If read_descriptor is in ready_descriptors, read from it.
    if read_descriptor in ready_descriptors:
        logger.debug("Reading display number from the read descriptor.")
        line = os.read(read_descriptor, number_of_bytes).decode("utf-8")
        # Xvfb process writes the display number and adds a new line character ('\n') at the end. Removing it with .strip()
        display_port = line.strip()

    else:
        # Check for errors and raise exception.
        error = ""
        while not xvfb.stderr.at_eof():
            line = await xvfb.stderr.readline()
            error += line.decode("utf-8")

        await xvfb.wait()
        raise XvfbError(f"Unable to start the Xvfb process: \n {error}")

    # Close the read and write descriptors.
    os.close(read_descriptor)
    os.close(write_descriptor)

    return xvfb, display_port
