# Copyright 2026 The MathWorks, Inc.

"""Unit tests for matlab_proxy/util/dpop.py (DPoP proof generation, RFC 9449)."""

import base64
import json

from cryptography.hazmat.primitives.asymmetric import ec

from matlab_proxy.util import dpop
from matlab_proxy.util.dpop import DPoPKey


def _b64url_decode(segment: str) -> bytes:
    """Base64url-decode a JWT segment, restoring the stripped padding."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def test_b64url_encode_strips_padding():
    """_b64url_encode must produce padding-free base64url (per JWS spec)."""
    # b"\x00" base64-encodes to "AA==" - the padding must be stripped.
    assert dpop._b64url_encode(b"\x00") == "AA"
    assert "=" not in dpop._b64url_encode(b"any-bytes-here-123")


def test_int_to_bytes_32_is_fixed_width():
    """P-256 coordinates must always encode to exactly 32 big-endian bytes."""
    assert dpop._int_to_bytes_32(1) == b"\x00" * 31 + b"\x01"
    assert len(dpop._int_to_bytes_32(2**200)) == 32


def test_jwk_has_expected_ec_public_fields():
    """The public JWK exposes only the EC public parameters (never the private key)."""
    jwk = DPoPKey().jwk

    assert jwk["kty"] == "EC"
    assert jwk["crv"] == "P-256"
    # x and y are the 32-byte coordinates, base64url-encoded.
    assert len(_b64url_decode(jwk["x"])) == 32
    assert len(_b64url_decode(jwk["y"])) == 32
    # The JWK must not leak any private component.
    assert "d" not in jwk


def test_generate_proof_produces_three_part_jwt():
    """A DPoP proof is a compact JWS: header.payload.signature."""
    proof = DPoPKey().generate_proof("POST", "https://signin.mathworks.com/token")

    parts = proof.split(".")
    assert len(parts) == 3


def test_generate_proof_header_and_payload_contents():
    """The proof header/payload must carry the RFC 9449 required claims."""
    method = "POST"
    url = "https://signin.mathworks.com/oauth2/v1/oauth/token"
    key = DPoPKey()

    header_seg, payload_seg, _ = key.generate_proof(method, url).split(".")
    header = json.loads(_b64url_decode(header_seg))
    payload = json.loads(_b64url_decode(payload_seg))

    assert header["typ"] == "dpop+jwt"
    assert header["alg"] == "ES256"
    assert header["jwk"] == key.jwk

    assert payload["htm"] == method
    assert payload["htu"] == url
    assert isinstance(payload["iat"], int)
    assert payload["jti"]  # non-empty unique id


def test_generate_proof_jti_is_unique_per_call():
    """Each proof must carry a fresh jti to prevent replay."""
    key = DPoPKey()
    _, payload_a, _ = key.generate_proof("GET", "https://x").split(".")
    _, payload_b, _ = key.generate_proof("GET", "https://x").split(".")

    jti_a = json.loads(_b64url_decode(payload_a))["jti"]
    jti_b = json.loads(_b64url_decode(payload_b))["jti"]
    assert jti_a != jti_b


def test_generate_proof_signature_verifies_against_public_key():
    """The raw r||s signature must verify against the key's own public key."""
    key = DPoPKey()
    proof = key.generate_proof("POST", "https://signin.mathworks.com/token")
    header_seg, payload_seg, sig_seg = proof.split(".")

    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    raw_sig = _b64url_decode(sig_seg)
    assert len(raw_sig) == 64  # r (32) || s (32)

    # Re-encode raw r||s into DER for the cryptography verify API.
    r = int.from_bytes(raw_sig[:32], "big")
    s = int.from_bytes(raw_sig[32:], "big")
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from cryptography.hazmat.primitives import hashes

    der_sig = encode_dss_signature(r, s)
    # Does not raise => signature is valid.
    key._public_key.verify(der_sig, signing_input, ec.ECDSA(hashes.SHA256()))


def test_to_dict_from_dict_roundtrip_preserves_key():
    """A key serialized via to_dict() and restored via from_dict() must be identical."""
    original = DPoPKey()
    serialized = original.to_dict()

    assert "private_key_pem" in serialized
    assert serialized["private_key_pem"].startswith("-----BEGIN PRIVATE KEY-----")

    restored = DPoPKey.from_dict(serialized)

    # Same public key (same JWK) => same underlying private key.
    assert restored.jwk == original.jwk
    # And the restored key round-trips back to the identical PEM.
    assert restored.to_dict() == serialized


def test_from_dict_restored_key_signs_verifiably():
    """A restored key must still produce valid signatures (refresh reuses the key)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    restored = DPoPKey.from_dict(DPoPKey().to_dict())

    header_seg, payload_seg, sig_seg = restored.generate_proof(
        "POST", "https://signin.mathworks.com/refresh"
    ).split(".")
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")

    raw_sig = _b64url_decode(sig_seg)
    r = int.from_bytes(raw_sig[:32], "big")
    s = int.from_bytes(raw_sig[32:], "big")
    # Does not raise => the restored key produced a valid ES256 signature.
    restored._public_key.verify(
        encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256())
    )
