# Copyright 2026 The MathWorks, Inc.

"""OAuth device flow, credentials, token parsing, refresh, and serialization."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

import aiohttp

from matlab_proxy import constants
from matlab_proxy.util import mw, mwi
from matlab_proxy.util.dpop import DPoPKey

from .base import LicensingType, OnlineLicense, parse_expiry

if TYPE_CHECKING:
    from matlab_proxy.settings import Settings

logger = mwi.logger.get()

# Used when the OAuth server does not specify a device-code polling interval.
DEFAULT_POLL_INTERVAL_SECONDS = 5


class DeviceAuthStatus(str, Enum):
    PENDING = "PENDING"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    AUTHORIZED = "AUTHORIZED"
    TOKEN_ISSUED = "TOKEN_ISSUED"
    UNKNOWN = "UNKNOWN"


@dataclass
class DeviceFlowState:
    """Transient secrets, polling state, and session for one authorization flow."""

    code_verifier: str | None = field(default=None, repr=False)
    code_challenge: str | None = None
    oauth_session_id: str | None = None
    dpop_key: DPoPKey | None = field(default=None, repr=False)
    device_code: str | None = field(default=None, repr=False)
    device_code_interval: int | None = None
    device_auth_last_check: float | None = None
    device_auth_cached_status: DeviceAuthStatus | None = None
    # Echo these fields on pending polls so a page refresh can rehydrate the flow.
    device_user_code: str | None = None
    device_verification_uri: str | None = None
    device_verification_uri_complete: str | None = None
    # Absolute wall-clock deadline, in epoch seconds.
    device_code_expiry: float | None = None
    _session: aiohttp.ClientSession | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @property
    def in_progress(self) -> bool:
        return bool(self.device_code and self.code_verifier)

    @property
    def is_authorized(self) -> bool:
        """Whether the user approved the flow, so the device code can be exchanged."""
        return self.device_auth_cached_status in (
            DeviceAuthStatus.AUTHORIZED,
            DeviceAuthStatus.TOKEN_ISSUED,
        )

    def start(self) -> None:
        """Generate the PKCE pair and DPoP key for a new authorization request.

        The SAME DPoP key must be reused for token exchange and all subsequent
        refreshes. The session ID is kept if a flow restarts before it ends.
        """
        self.code_verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(self.code_verifier.encode()).digest()
        self.code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        self.dpop_key = DPoPKey()
        self.oauth_session_id = self.oauth_session_id or secrets.token_hex(8)

    def record_authorization(self, response: dict) -> int:
        """Store the server's device authorization response.

        The device_code is kept server-side and is NEVER sent to the frontend.
        The user-facing fields and an absolute deadline are kept so that pending
        polls can re-serve them. This lets the frontend rehydrate the same
        code/URL/countdown after a page refresh instead of starting a new flow.

        Returns:
            int: Lifetime of the device code, in seconds.
        """
        self.device_code = response["device_code"]
        self.device_code_interval = response.get(
            "interval", DEFAULT_POLL_INTERVAL_SECONDS
        )
        self.device_auth_last_check = None
        self.device_auth_cached_status = None
        expires_in = response.get(
            "expires_in", constants.OAUTH_DEVICE_CODE_LIFESPAN_SECONDS
        )
        self.device_user_code = response["user_code"]
        self.device_verification_uri = response["verification_uri"]
        self.device_verification_uri_complete = response.get(
            "verification_uri_complete"
        )
        self.device_code_expiry = time.time() + expires_in
        return expires_in

    def is_expired(self) -> bool:
        return (
            self.device_code_expiry is not None
            and time.time() >= self.device_code_expiry
        )

    def should_check_status(self, now: float) -> bool:
        """Whether to query the OAuth server instead of re-serving PENDING.

        The frontend polls every second, but the OAuth server must only be
        queried every `interval` seconds, as it specified.
        """
        last_check = self.device_auth_last_check or 0
        interval = self.device_code_interval or DEFAULT_POLL_INTERVAL_SECONDS
        return (
            now - last_check >= interval
            or self.device_auth_cached_status != DeviceAuthStatus.PENDING
        )

    async def check_auth_status(self, oauth_host: str, client_id: str) -> dict:
        """Check authorization using a session reused until this flow is cleared."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                trust_env=True,
                # Polling is stateless; do not retain cookies across requests.
                cookie_jar=aiohttp.DummyCookieJar(),
            )
        return await mw.check_device_auth_status(
            oauth_host, self.device_code, client_id, client_session=self._session
        )

    def record_status(self, status: str, now: float) -> DeviceAuthStatus:
        try:
            parsed = DeviceAuthStatus(status)
        except ValueError:
            # Preserve the server's unknown-status behavior: keep waiting.
            parsed = DeviceAuthStatus.UNKNOWN
        self.device_auth_last_check = now
        self.device_auth_cached_status = parsed
        return parsed

    def display_fields(self) -> dict:
        """The user-facing fields, with the time remaining on the device code."""
        display = {
            "user_code": self.device_user_code,
            "verification_uri": self.device_verification_uri,
            "verification_uri_complete": self.device_verification_uri_complete,
        }
        if self.device_code_expiry is not None:
            display["expires_in"] = max(0, int(self.device_code_expiry - time.time()))
        return display

    async def clear(self) -> None:
        """Discard all flow state and close its polling session.

        A terminal outcome must leave no sign-in secrets behind, including PKCE,
        DPoP, and the session ID. The durable OAuth license retains its own DPoP
        key for later refreshes.
        """
        session = self._session
        for member in fields(self):
            setattr(self, member.name, None)
        if session is not None:
            await session.close()


@dataclass
class OAuthLicense(OnlineLicense):
    type: ClassVar[LicensingType] = LicensingType.OAUTH
    client_id: str | None = None
    token: str | None = field(default=None, repr=False)
    expiry: str | None = None
    refresh_token: str | None = field(default=None, repr=False)
    refresh_token_expiry: str | None = None
    dpop_key: DPoPKey | None = field(default=None, repr=False, compare=False)

    # The cache format for each client entry, besides the separately serialized
    # DPoP key. Access tokens and their short-lived expiry are re-derived on
    # restore, mirroring the MHLM identity-token model, so they are excluded.
    # A new field is not persisted until it is added here.
    PERSISTED_FIELDS: ClassVar[tuple[str, ...]] = (
        "email_addr",
        "first_name",
        "last_name",
        "display_name",
        "user_id",
        "entitlements",
        "entitlement_id",
        "client_id",
        "refresh_token",
        "refresh_token_expiry",
    )

    @classmethod
    def from_dict(cls, data: dict) -> "OAuthLicense":
        # Access tokens are never restored, even from an older cache.
        values = {name: data[name] for name in cls.PERSISTED_FIELDS if name in data}
        key = data.get("dpop_key")
        return cls(**values, dpop_key=DPoPKey.from_dict(key) if key else None)

    def to_dict(self) -> dict:
        # Avoid asdict: it deep-copies the private key and would include access tokens.
        data = {name: getattr(self, name) for name in self.PERSISTED_FIELDS}
        data["dpop_key"] = self.dpop_key.to_dict() if self.dpop_key else None
        return {"type": self.type.value, **data}

    @classmethod
    def from_token_response(
        cls,
        response: dict,
        *,
        client_id: str,
        dpop_key: DPoPKey | None,
        previous: "OAuthLicense | None" = None,
    ) -> "OAuthLicense":
        token = response.get("mwa_token", response)
        identity = token.get("referenceDetail") or {}
        lifetime = response.get("refresh_expires_in")
        expiry = (
            (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()
            if lifetime is not None
            else None
        )
        user_fields = {
            name: identity.get(key, getattr(previous, name, None))
            for name, key in (
                ("email_addr", "email"),
                ("first_name", "firstName"),
                ("last_name", "lastName"),
                ("display_name", "displayName"),
                ("user_id", "userId"),
            )
        }
        return cls(
            client_id=(
                previous.client_id if previous and previous.client_id else client_id
            ),
            token=token.get("accessTokenString", response.get("access_token")),
            expiry=token.get("expirationDate"),
            refresh_token=response.get("refresh_token"),
            refresh_token_expiry=expiry,
            dpop_key=dpop_key,
            entitlement_id=previous.entitlement_id if previous else None,
            **user_fields,
        )

    def is_complete(self) -> bool:
        # Gate on the durable credential, not the access token or its expiry.
        # Access tokens are ephemeral and re-derived at startup, so they may
        # legitimately be absent here. A refresh token and selected entitlement
        # are enough to regard licensing as configured.
        return all(
            value is not None
            for value in (self.client_id, self.refresh_token, self.entitlement_id)
        )

    def can_refresh(self) -> bool:
        if not self.refresh_token:
            logger.debug("Cached OAuth entry has no refresh token; sign-in required.")
            return False
        if self.refresh_token_expiry is not None:
            try:
                if parse_expiry(self.refresh_token_expiry) <= datetime.now(
                    timezone.utc
                ):
                    logger.debug(
                        "Cached OAuth refresh token expired; sign-in required."
                    )
                    return False
            except ValueError:
                # This is a predictive gate only. For unknown expiry values,
                # the refresh endpoint remains the authority on token validity.
                logger.debug(
                    "Could not parse cached refresh_token_expiry; attempting refresh."
                )
        return True

    def needs_refresh(self) -> bool:
        return bool(self.refresh_token and self.expiry) and (
            parse_expiry(self.expiry) - timedelta(hours=1) <= datetime.now(timezone.utc)
        )

    async def update_entitlements(self, settings: "Settings") -> None:
        self.set_entitlements(
            await mw.fetch_entitlements(
                settings.mhlm_api_endpoint, self.token, settings.matlab_version
            )
        )

    async def refresh(self, settings: "Settings") -> "OAuthLicense":
        """Exchange the durable credential using the original DPoP key.

        The OAuth server requires the same key used during device authorization.
        SAT refresh tokens rotate, so the caller must persist the returned license
        to replace the old refresh token and its expiry.
        """
        response = await mw.refresh_oauth_token(
            f"{settings.oauth_endpoint}/oauth2/v1/oauth/refresh",
            self.client_id or settings.oauth_client_id,
            self.refresh_token,
            dpop_key=self.dpop_key,
        )
        licensing = self.from_token_response(
            response,
            client_id=settings.oauth_client_id,
            dpop_key=self.dpop_key,
            previous=self,
        )
        await licensing.update_entitlements(settings)
        return licensing

    async def revoke(self, settings: "Settings") -> None:
        if self.refresh_token:
            await mw.revoke_oauth_token(
                f"{settings.oauth_endpoint}/oauth2/v1/oauth/revoke",
                self.client_id,
                self.refresh_token,
                dpop_key=self.dpop_key,
            )

    async def get_environment(self, settings: "Settings") -> dict:
        return self._environment(self.token)
