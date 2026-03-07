from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional


_SCHEME = "pbkdf2_sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16


def is_password_hash(value: Optional[str]) -> bool:
    text = str(value or "")
    parts = text.split("$")
    if len(parts) != 4:
        return False
    scheme, iterations_text, salt_hex, digest_hex = parts
    if scheme != _SCHEME:
        return False
    try:
        iterations = int(iterations_text)
    except Exception:
        return False
    if iterations <= 0:
        return False
    if not salt_hex or not digest_hex:
        return False
    return True


def hash_password(password: str, *, salt_hex: Optional[str] = None, iterations: int = _ITERATIONS) -> str:
    raw_password = str(password or "")
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"), salt, int(iterations))
    return f"{_SCHEME}${int(iterations)}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    text = str(stored_hash or "")
    if not is_password_hash(text):
        return False
    scheme, iterations_text, salt_hex, digest_hex = text.split("$", 3)
    if scheme != _SCHEME:
        return False
    try:
        expected = hash_password(password, salt_hex=salt_hex, iterations=int(iterations_text))
    except Exception:
        return False
    return hmac.compare_digest(expected, text)
