"""DPoP (Demonstrating Proof-of-Possession) implementation for OAuth device flow.

Generates ES256 keypairs and DPoP proof JWTs per RFC 9449.
Uses only the `cryptography` library (no PyJWT dependency).
"""

import base64
import json
import time
import uuid

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_encode_json(obj: dict) -> str:
    return _b64url_encode(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _int_to_bytes_32(n: int) -> bytes:
    return n.to_bytes(32, byteorder="big")


class DPoPKey:
    """Holds an ephemeral ES256 keypair and generates DPoP proof JWTs."""

    def __init__(self):
        self._private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        self._public_key = self._private_key.public_key()
        pub_numbers = self._public_key.public_numbers()
        self._jwk = {
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

        Args:
            method: HTTP method (e.g., "POST")
            url: Full target URL

        Returns:
            Signed DPoP proof JWT string
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

        signing_input = (
            _b64url_encode_json(header) + "." + _b64url_encode_json(payload)
        )

        # Sign with ES256 (ECDSA P-256 + SHA-256)
        der_sig = self._private_key.sign(
            signing_input.encode("ascii"),
            ec.ECDSA(hashes.SHA256()),
        )

        # Convert DER signature to raw r||s (64 bytes) per JWS spec
        raw_sig = _der_to_raw_signature(der_sig)

        return signing_input + "." + _b64url_encode(raw_sig)


def _der_to_raw_signature(der_sig: bytes) -> bytes:
    """Convert a DER-encoded ECDSA signature to raw r||s (64 bytes).

    DER format: 0x30 <len> 0x02 <r_len> <r> 0x02 <s_len> <s>
    """
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    r, s = decode_dss_signature(der_sig)
    return _int_to_bytes_32(r) + _int_to_bytes_32(s)
