# Copyright 2025-2026 The MathWorks, Inc.

"""DPoP (Demonstrating Proof-of-Possession) implementation for OAuth device flow.

Generates ES256 keypairs and DPoP proof JWTs per RFC 9449.
Uses only the ``cryptography`` library (no PyJWT dependency).

A single DPoPKey is used for device authorization, token exchange, and all
subsequent token refreshes for a given client_id. The OAuth server requires the
SAME key for refresh that was used during device authorization, so the private
key is serialized (PEM) and persisted in the cached config per client.
"""

import base64
import json
import time
import uuid

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def _b64url_encode(data: bytes) -> str:
    """Base64url-encode bytes without padding (per JWS spec)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_encode_json(obj: dict) -> str:
    """Compactly serialize a dict to JSON and base64url-encode it."""
    return _b64url_encode(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _int_to_bytes_32(n: int) -> bytes:
    """Encode an integer as exactly 32 big-endian bytes (P-256 coordinate size)."""
    return n.to_bytes(32, byteorder="big")


class DPoPKey:
    """Holds an ES256 keypair and generates DPoP proof JWTs."""

    def __init__(self):
        self._private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        self._public_key = self._private_key.public_key()
        self._jwk = self.__build_jwk(self._public_key)

    @staticmethod
    def __build_jwk(public_key) -> dict:
        """Builds the public JWK representation for an EC public key."""
        pub_numbers = public_key.public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url_encode(_int_to_bytes_32(pub_numbers.x)),
            "y": _b64url_encode(_int_to_bytes_32(pub_numbers.y)),
        }

    @property
    def jwk(self) -> dict:
        return self._jwk

    def generate_proof(self, method: str, url: str) -> str:
        """Generate a DPoP proof JWT for the given HTTP method and URL.

        The proof contains:
        - Header: typ=dpop+jwt, alg=ES256, jwk=<public key>
        - Payload: htm=<method>, htu=<url>, iat=<now>, jti=<uuid>
        """
        header = {
            "typ": "dpop+jwt",
            "alg": "ES256",
            "jwk": self._jwk,
        }
        payload = {
            "htm": method,
            "htu": url,
            "iat": int(time.time()),
            "jti": str(uuid.uuid4()),
        }

        signing_input = _b64url_encode_json(header) + "." + _b64url_encode_json(payload)

        # Sign with ES256 (ECDSA P-256 + SHA-256)
        der_sig = self._private_key.sign(
            signing_input.encode("ascii"),
            ec.ECDSA(hashes.SHA256()),
        )

        # Convert DER signature to raw r||s (64 bytes) per JWS spec
        r, s = decode_dss_signature(der_sig)
        raw_sig = _int_to_bytes_32(r) + _int_to_bytes_32(s)

        return signing_input + "." + _b64url_encode(raw_sig)

    def to_dict(self) -> dict:
        """Serialize the private key for persistence in the cached config."""
        pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return {"private_key_pem": pem.decode("ascii")}

    @classmethod
    def from_dict(cls, data: dict) -> "DPoPKey":
        """Restore a DPoPKey from persisted data (the inverse of to_dict)."""
        instance = cls.__new__(cls)
        instance._private_key = serialization.load_pem_private_key(
            data["private_key_pem"].encode("ascii"), password=None
        )
        instance._public_key = instance._private_key.public_key()
        instance._jwk = cls.__build_jwk(instance._public_key)
        return instance
