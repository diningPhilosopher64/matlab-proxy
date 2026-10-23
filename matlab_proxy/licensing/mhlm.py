# Copyright 2026 The MathWorks, Inc.

from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, ClassVar

from matlab_proxy.util import mw

from .base import LicensingType, OnlineLicense, parse_expiry

if TYPE_CHECKING:
    from matlab_proxy.settings import Settings


@dataclass
class MHLMLicense(OnlineLicense):
    type: ClassVar[LicensingType] = LicensingType.MHLM
    identity_token: str | None = field(default=None, repr=False)
    source_id: str | None = None
    expiry: str | None = None
    profile_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MHLMLicense":
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})

    @classmethod
    async def sign_in(
        cls,
        settings: "Settings",
        identity_token,
        email_addr,
        source_id,
        entitlements=None,
        entitlement_id=None,
    ) -> "MHLMLicense":
        token = await mw.fetch_expand_token(
            settings.mwa_api_endpoint, identity_token, source_id
        )
        return cls(
            identity_token=identity_token,
            source_id=source_id,
            email_addr=email_addr,
            expiry=token["expiry"],
            first_name=token["first_name"],
            last_name=token["last_name"],
            display_name=token["display_name"],
            user_id=token["user_id"],
            profile_id=token["profile_id"],
            entitlements=list(entitlements or []),
            entitlement_id=entitlement_id,
        )

    def is_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.identity_token,
                self.source_id,
                self.expiry,
                self.entitlement_id,
            )
        )

    def is_cache_valid(self) -> bool:
        return bool(self.expiry) and (
            parse_expiry(self.expiry) - timedelta(hours=1) > datetime.now(timezone.utc)
        )

    async def update_entitlements(self, settings: "Settings") -> None:
        token = await mw.fetch_access_token(
            settings.mwa_api_endpoint, self.identity_token, self.source_id
        )
        self.set_entitlements(
            await mw.fetch_entitlements(
                settings.mhlm_api_endpoint, token["token"], settings.matlab_version
            )
        )

    def parse_error(self, logs: list[str]):
        return mw.parse_mhlm_error(logs)

    async def get_environment(self, settings: "Settings") -> dict:
        token = await mw.fetch_access_token(
            settings.mwa_api_endpoint, self.identity_token, self.source_id
        )
        return self._environment(token["token"])
