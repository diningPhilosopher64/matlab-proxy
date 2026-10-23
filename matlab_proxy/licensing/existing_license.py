# Copyright 2026 The MathWorks, Inc.

from dataclasses import dataclass
from typing import ClassVar

from .base import License, LicensingType


@dataclass
class ExistingLicense(License):
    type: ClassVar[LicensingType] = LicensingType.EXISTING_LICENSE

    @classmethod
    def from_dict(cls, data: dict) -> "ExistingLicense":
        return cls()

    def is_complete(self) -> bool:
        return True
