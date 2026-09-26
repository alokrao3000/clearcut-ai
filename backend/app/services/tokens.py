"""Bearer tokens for context-view links.

A context-view URL is the only credential its recipient has, so it is treated like a
password: generated from `secrets`, stored only as a SHA-256 digest, and compared in
constant time. The plaintext exists exactly once, in the response that creates it.

SHA-256 rather than a slow KDF on purpose. These are 256-bit random strings, not
user-chosen secrets, so there is nothing for an offline attacker to guess faster than
brute force, and a public view has to verify on every page load and every image request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32
HINT_LENGTH = 8


def mint() -> tuple[str, str, str]:
    """Return (plaintext, digest, hint). Only the digest and hint are safe to store."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, digest(token), token[:HINT_LENGTH]


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def matches(token: str, stored_digest: str) -> bool:
    return hmac.compare_digest(digest(token), stored_digest)
