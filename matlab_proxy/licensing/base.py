# Copyright 2026 The MathWorks, Inc.

"""Shared licensing types and explicit serialization interfaces."""

import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from matlab_proxy.util.mwi import environment_variables as mwi_env

if TYPE_CHECKING:
    from matlab_proxy.settings import Settings


class LicensingType(str, Enum):
    MHLM = "mhlm"
    NLM = "nlm"
    OAUTH = "oauth"
    EXISTING_LICENSE = "existing_license"


def parse_expiry(expiry: str) -> datetime:
    """Parse the ISO timestamp variants returned by OAuth and MHLM.

    Python 3.10's fromisoformat does not accept offsets such as +0000. Keep
    strptime fallbacks for those responses, with and without fractional seconds.
    """
    try:
        return datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(expiry, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized expiry timestamp format: {expiry!r}")


@dataclass
class License(ABC):
    type: ClassVar[LicensingType]

    def to_dict(self) -> dict:
        """Serialize durable licensing data for the existing cache format."""
        return {"type": self.type.value, **asdict(self)}

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict) -> "License":
        """Deserialize durable licensing data."""

    @abstractmethod
    def is_complete(self) -> bool:
        """Whether the selected mode has enough information to start MATLAB."""

    def to_public_dict(self) -> dict:
        """Serialize only the information that may be sent to the browser."""
        return {"type": self.type.value}

    async def get_environment(self, settings: "Settings") -> dict:
        """Return the licensing variables to pass to MATLAB."""
        return {}

    def parse_error(self, logs: list[str]):
        """Return a mode-specific licensing error, if one appears in MATLAB output."""
        return None


@dataclass
class OnlineLicense(License):
    email_addr: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    user_id: str | None = None
    entitlements: list[dict] = field(default_factory=list)
    entitlement_id: str | None = None

    def set_entitlements(self, entitlements: list[dict]) -> None:
        self.entitlements = entitlements
        if len(entitlements) == 1:
            self.entitlement_id = entitlements[0]["id"]

    def to_public_dict(self) -> dict:
        return {
            "type": self.type.value,
            "emailAddress": self.email_addr,
            "entitlements": self.entitlements,
            "entitlementId": self.entitlement_id,
        }

    def _environment(self, token: str) -> dict:
        return {
            "MLM_WEB_LICENSE": "true",
            "MLM_WEB_USER_CRED": token,
            "MLM_WEB_ID": self.entitlement_id,
            "MHLM_CONTEXT": os.getenv(
                mwi_env.get_env_name_mhlm_context(), "MATLAB_JAVASCRIPT_DESKTOP"
            ),
        }
