# Copyright 2026 The MathWorks, Inc.

from .base import License, LicensingType, OnlineLicense
from .existing_license import ExistingLicense
from .mhlm import MHLMLicense
from .nlm import NLMLicense
from .oauth import OAuthLicense

__all__ = [
    "License",
    "LicensingType",
    "OnlineLicense",
    "ExistingLicense",
    "MHLMLicense",
    "NLMLicense",
    "OAuthLicense",
    "license_from_dict",
]


def license_from_dict(data: dict) -> License:
    """Read a mode's durable representation; reject unknown licensing types."""
    license_class = {
        LicensingType.MHLM: MHLMLicense,
        LicensingType.NLM: NLMLicense,
        LicensingType.OAUTH: OAuthLicense,
        LicensingType.EXISTING_LICENSE: ExistingLicense,
    }[LicensingType(data["type"])]
    return license_class.from_dict(data)
