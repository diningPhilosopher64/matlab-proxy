# Copyright 2026 The MathWorks, Inc.

"""Tests of the durable cache and public licensing interfaces."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from matlab_proxy.licensing import (
    ExistingLicense,
    LicensingType,
    MHLMLicense,
    NLMLicense,
    OAuthLicense,
    license_from_dict,
)
from matlab_proxy.licensing.base import parse_expiry
from matlab_proxy.licensing.cache import LicensingCache
from matlab_proxy.licensing.oauth import DeviceFlowState
from matlab_proxy.settings import Settings
from matlab_proxy.util.dpop import DPoPKey


@pytest.mark.parametrize(
    "licensing",
    [
        ExistingLicense(),
        NLMLicense(conn_str="27000@license-server"),
        MHLMLicense(
            identity_token="identity-secret",
            source_id="source",
            email_addr="user@example.com",
            expiry="2030-01-01T00:00:00Z",
            entitlements=[{"id": "license-1"}],
            entitlement_id="license-1",
        ),
    ],
)
def test_license_json_round_trip(licensing):
    restored = license_from_dict(json.loads(json.dumps(licensing.to_dict())))
    assert restored == licensing
    assert restored.type is licensing.type
    assert restored.is_complete()


def test_unknown_license_type_is_rejected():
    with pytest.raises(ValueError):
        license_from_dict({"type": "invalid_type"})


def test_oauth_round_trip_keeps_durable_credentials_only():
    key = DPoPKey()
    licensing = OAuthLicense(
        client_id="integration",
        token="access-secret",
        expiry="2030-01-01T00:00:00Z",
        refresh_token="refresh-secret",
        refresh_token_expiry="2031-01-01T00:00:00Z",
        dpop_key=key,
        email_addr="user@example.com",
        entitlement_id="license-1",
    )
    data = json.loads(json.dumps(licensing.to_dict()))
    assert "token" not in data
    assert "expiry" not in data
    restored = license_from_dict(data)
    assert restored.type is LicensingType.OAUTH
    assert restored.refresh_token == "refresh-secret"
    assert restored.dpop_key.to_dict() == key.to_dict()
    assert restored.token is None
    assert restored.expiry is None
    assert restored.is_complete()
    assert restored.to_dict() == data
    assert restored.to_public_dict() == {
        "type": "oauth",
        "emailAddress": "user@example.com",
        "entitlements": [],
        "entitlementId": "license-1",
    }
    assert "access-secret" not in repr(licensing)
    assert "refresh-secret" not in repr(licensing)


def test_oauth_deserialization_discards_legacy_access_token():
    restored = OAuthLicense.from_dict(
        {
            "client_id": "integration",
            "token": "stale-access-token",
            "expiry": "2030-01-01T00:00:00Z",
            "refresh_token": "refresh-secret",
        }
    )
    assert restored.token is None
    assert restored.expiry is None
    assert restored.can_refresh()


def test_refresh_response_preserves_identity_selection_and_key():
    previous = OAuthLicense(
        client_id="original-client",
        email_addr="user@example.com",
        first_name="Jane",
        entitlement_id="license-2",
        dpop_key=DPoPKey(),
    )
    refreshed = OAuthLicense.from_token_response(
        {"access_token": "new-access", "refresh_token": "new-refresh"},
        client_id="configured-client",
        dpop_key=previous.dpop_key,
        previous=previous,
    )
    assert refreshed.client_id == "original-client"
    assert refreshed.email_addr == "user@example.com"
    assert refreshed.first_name == "Jane"
    assert refreshed.entitlement_id == "license-2"
    assert refreshed.dpop_key is previous.dpop_key
    assert refreshed.token == "new-access"
    assert refreshed.refresh_token == "new-refresh"
    assert refreshed.refresh_token_expiry is None


@pytest.mark.parametrize(
    "timestamp",
    [
        "2030-01-01T00:00:00Z",
        "2030-01-01T00:00:00.000+0000",
        "2030-01-01T00:00:00+00:00",
        "2030-01-01T00:00:00+0000",
    ],
)
def test_expiry_formats(timestamp):
    assert parse_expiry(timestamp) == datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_expired_refresh_token_does_not_attempt_restore():
    licensing = OAuthLicense(
        refresh_token="refresh-secret",
        refresh_token_expiry=(
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat(),
    )
    assert not licensing.can_refresh()
    licensing.refresh_token_expiry = "unknown"
    assert licensing.can_refresh()


def test_oauth_cache_updates_and_removes_only_selected_client(tmp_path):
    cache = LicensingCache(tmp_path / "config.json")
    first = OAuthLicense(client_id="first", refresh_token="first-refresh")
    second = OAuthLicense(client_id="second", refresh_token="second-refresh")
    cache.save(first, "R2024b")
    cache.save(second, "R2025a")
    first.refresh_token = "rotated-first-refresh"
    cache.save(first, "R2024b")
    clients = cache.read()["licensing"]["clients"]
    assert len(clients) == 2
    assert (
        next(c for c in clients if c["client_id"] == "first")["refresh_token"]
        == "rotated-first-refresh"
    )
    cache.remove_oauth_client("first")
    # A literal entry in the existing cache format, so an accidental field addition
    # or removal fails this test.
    assert cache.read() == {
        "licensing": {
            "type": "oauth",
            "clients": [
                {
                    "client_id": "second",
                    "refresh_token_expiry": None,
                    "email_addr": None,
                    "first_name": None,
                    "last_name": None,
                    "display_name": None,
                    "user_id": None,
                    "refresh_token": "second-refresh",
                    "dpop_key": None,
                    "entitlements": [],
                    "entitlement_id": None,
                    "matlab": {"version": "R2025a"},
                }
            ],
        }
    }
    cache.remove_oauth_client("second")
    assert not cache.path.exists()


def test_cache_load_uses_selected_clients_license_and_matlab_version(tmp_path):
    cache = LicensingCache(tmp_path / "config.json")
    cache.save(OAuthLicense(client_id="first", refresh_token="first-refresh"), "R2024b")
    cache.save(
        OAuthLicense(client_id="second", refresh_token="second-refresh"), "R2025a"
    )

    loaded = cache.load("second")

    assert loaded.matlab_version == "R2025a"
    assert loaded.licensing.client_id == "second"
    assert loaded.licensing.refresh_token == "second-refresh"
    assert cache.load("unknown-client") is None
    assert cache.load(None) is None
    assert len(cache.read()["licensing"]["clients"]) == 2


def test_settings_conversion_preserves_runtime_objects():
    from matlab_proxy.settings import create_xvfb_cmd

    settings = Settings(matlab_version="R2024b", create_xvfb_cmd=create_xvfb_cmd)
    restored = Settings.from_dict(settings.to_dict())
    assert restored.create_xvfb_cmd is create_xvfb_cmd
    assert restored.matlab_version == "R2024b"
    with pytest.raises(TypeError):
        Settings.from_dict({"misspelled_setting": True})
    assert not hasattr(settings, "device_code")
    assert not hasattr(settings, "dpop_key")


@pytest.mark.parametrize("invalid", [[], {}, {"licensing": None}, {"licensing": []}])
def test_oauth_sign_in_replaces_invalid_cache(tmp_path, invalid):
    cache = LicensingCache(tmp_path / "config.json")
    cache.path.write_text(json.dumps(invalid))
    licensing = OAuthLicense(client_id="integration", refresh_token="refresh-secret")
    cache.save(licensing, "R2024b")
    clients = cache.read()["licensing"]["clients"]
    assert len(clients) == 1
    assert clients[0]["client_id"] == "integration"


async def test_mutable_defaults_and_device_state_are_per_instance():
    first = Settings(oauth_client_id="first")
    second = Settings(oauth_client_id="second")
    first.warnings.append("warning")
    first.env_config["extension_name"] = "first"
    flow = DeviceFlowState(code_verifier="secret", dpop_key=DPoPKey())
    await flow.clear()
    assert first.oauth_client_id == "first"
    assert flow.code_verifier is None
    assert flow.dpop_key is None
    assert second.warnings == []
    assert second.env_config == {}
    first_license, second_license = MHLMLicense(), MHLMLicense()
    first_license.entitlements.append({"id": "license-1"})
    assert second_license.entitlements == []
