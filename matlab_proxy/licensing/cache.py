# Copyright 2026 The MathWorks, Inc.

"""Licensing cache shared by MATLAB integrations on this host."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from matlab_proxy.util import mwi

from . import license_from_dict
from .base import License, LicensingType
from .oauth import OAuthLicense

logger = mwi.logger.get()


@dataclass
class CachedLicense:
    licensing: License
    matlab_version: str | None


class LicensingCache:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict:
        config = json.loads(self.path.read_text())
        if not isinstance(config, dict) or not isinstance(
            config.get("licensing"), dict
        ):
            raise ValueError("Invalid licensing cache")
        return config

    def delete(self) -> None:
        logger.debug("Deleting any cached config files!")
        self.path.unlink(missing_ok=True)

    def load(self, client_id: str | None) -> CachedLicense | None:
        """Deserialize cached licensing, selecting this integration's OAuth entry.

        OAuth caches have no top-level MATLAB version: each client entry owns
        its version and credentials. Other modes use the shared top-level version.
        """
        logger.debug("Found cached licensing information...")
        config = self.read()
        data = config["licensing"]
        if LicensingType(data["type"]) == LicensingType.OAUTH:
            return self._load_oauth_client(data, client_id)
        if LicensingType(data["type"]) == LicensingType.NLM:
            logger.debug("Using cached NLM licensing to start MATLAB")
        elif LicensingType(data["type"]) == LicensingType.EXISTING_LICENSE:
            logger.debug("Using cached existing license to start MATLAB")
        return CachedLicense(
            license_from_dict(data), config.get("matlab", {}).get("version")
        )

    def _load_oauth_client(
        self, data: dict, client_id: str | None
    ) -> CachedLicense | None:
        if not client_id:
            logger.debug(
                "Cached OAuth licensing present but no oauth_client_id in config. "
                "Ignoring cached data."
            )
            return None
        entry = next(
            (
                client
                for client in data.get("clients", [])
                if client.get("client_id") == client_id
            ),
            None,
        )
        if entry is None:
            logger.debug(
                f"No cached OAuth token for client_id '{client_id}'. Sign-in required."
            )
            return None
        # Access tokens are not persisted. Rebuild the durable credential here;
        # restore must exchange it for a fresh access/refresh pair before startup.
        return CachedLicense(
            OAuthLicense.from_dict(entry), entry.get("matlab", {}).get("version")
        )

    def _write(self, config: dict) -> None:
        """Write durable credentials with owner-only file permissions.

        The cache contains OAuth refresh tokens and DPoP private keys, or the
        MHLM identity token. Do not tighten the shared parent directory: sibling
        certs/, ports/, and proxy_manager/ subtrees belong to jmp and other
        integrations, potentially running under different user IDs. Restricting
        the parent could prevent those clients from accessing their own state.

        chmod is best-effort: on Windows it only toggles the read-only bit, and
        a file owned by another user may reject the change. Log and continue in
        those cases. Another, older integration may later rewrite the file under
        its own umask, so these permissions hold only until the next writer.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(config))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            logger.debug("Could not tighten permissions on %s.", self.path)

    def save(self, licensing: License, matlab_version: str | None) -> None:
        data = licensing.to_dict()
        if isinstance(licensing, OAuthLicense):
            logger.debug("Saving OAuth licensing information...")
            # Preserve other integrations' credentials in the shared clients array.
            clients = []
            try:
                existing = self.read().get("licensing", {})
                if existing.get("type") == LicensingType.OAUTH:
                    clients = existing.get("clients", [])
            except (OSError, ValueError):
                pass
            entry = {key: value for key, value in data.items() if key != "type"}
            entry["matlab"] = {"version": matlab_version}
            clients = [c for c in clients if c.get("client_id") != licensing.client_id]
            clients.append(entry)
            config = {
                "licensing": {"type": LicensingType.OAUTH.value, "clients": clients}
            }
        else:
            logger.debug("Saving licensing information...")
            config = {"licensing": data, "matlab": {"version": matlab_version}}
        self._write(config)

    def remove_oauth_client(self, client_id: str) -> None:
        """Remove one integration's credentials; delete the file when none remain."""
        if not self.path.exists():
            return
        try:
            config = self.read()
        except (OSError, ValueError):
            self.delete()
            return
        licensing = config.get("licensing", {})
        if licensing.get("type") != LicensingType.OAUTH:
            return
        clients = [
            c for c in licensing.get("clients", []) if c.get("client_id") != client_id
        ]
        if clients:
            licensing["clients"] = clients
            self._write(config)
        else:
            self.delete()
