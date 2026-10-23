# Copyright 2026 The MathWorks, Inc.

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from matlab_proxy.util import mw

from .base import License, LicensingType

if TYPE_CHECKING:
    from matlab_proxy.settings import Settings


@dataclass
class NLMLicense(License):
    type: ClassVar[LicensingType] = LicensingType.NLM
    conn_str: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "NLMLicense":
        return cls(conn_str=data.get("conn_str"))

    def is_complete(self) -> bool:
        return self.conn_str is not None

    def to_public_dict(self) -> dict:
        return {"type": self.type.value, "connectionString": self.conn_str}

    async def get_environment(self, settings: "Settings") -> dict:
        return {"MLM_LICENSE_FILE": self.conn_str}

    def parse_error(self, logs: list[str]):
        return mw.parse_nlm_error(logs, self.conn_str)
