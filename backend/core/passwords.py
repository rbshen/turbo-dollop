"""Password hashing for the login accounts (docs/specs/auth.md): stdlib `hashlib.scrypt`, a random salt per password, the
parameters inside the stored string so they can be raised later without invalidating old hashes, and a constant-time compare.

Stored form: ``scrypt$<N>$<r>$<p>$<salt, urlsafe base64>$<derived key, urlsafe base64>``. A hash is never logged, returned by the
API or put in an exception message. `verify_password` returns False for anything it cannot parse (a corrupt row is a failed
login, never a 500). `needs_rehash` tells a login that the stored parameters are weaker than today's, so the hash can be upgraded
with the password in hand."""

import base64
import binascii
import hashlib
import hmac
import secrets

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

# N = 2**15, r = 8, p = 1 is about 32 MiB and ~100 ms per hash on this class of machine (OWASP's scrypt floor is N = 2**17 at r = 8,
# or 2**15 with p = 3 -- raise N here and every hash is upgraded on its owner's next login).
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
_MAXMEM = 128 * 1024 * 1024
# Parameters read back from a stored string are bounded, so a corrupt or hostile row cannot ask for gigabytes of memory.
_MAX_N = 2**20
_MAX_R = 32
_MAX_P = 16
_SCHEME = "scrypt"


class WeakPasswordError(ValueError):
    """The password does not meet the policy; the message is safe to show the operator."""


def validate_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"The password must be at most {MAX_PASSWORD_LENGTH} characters.")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=KEY_BYTES)


def hash_password(password: str, *, n: int | None = None, r: int | None = None, p: int | None = None) -> str:
    """The scrypt string for `password` (policy NOT checked here: the CLI calls `validate_password_policy` first). Parameters default
    to the module constants, read at call time (tests lower them)."""
    n, r, p = n or SCRYPT_N, r or SCRYPT_R, p or SCRYPT_P
    salt = secrets.token_bytes(SALT_BYTES)
    return f"{_SCHEME}${n}${r}${p}${_b64(salt)}${_b64(_derive(password, salt, n, r, p))}"


def _parse(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        n_i, r_i, p_i = int(n), int(r), int(p)
        if scheme != _SCHEME or not (1 < n_i <= _MAX_N and n_i & (n_i - 1) == 0 and 1 <= r_i <= _MAX_R and 1 <= p_i <= _MAX_P):
            return None
        return n_i, r_i, p_i, _unb64(salt), _unb64(key)
    except (ValueError, binascii.Error, AttributeError):
        return None


def verify_password(password: str, stored: str | None) -> bool:
    parsed = _parse(stored) if stored else None
    if parsed is None:
        return False
    n, r, p, salt, key = parsed
    try:
        derived = _derive(password, salt, n, r, p)
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derived, key)


def needs_rehash(stored: str) -> bool:
    parsed = _parse(stored)
    if parsed is None:
        return False
    n, r, p, _, key = parsed
    return n < SCRYPT_N or r < SCRYPT_R or p < SCRYPT_P or len(key) != KEY_BYTES


_dummy_hash: str | None = None


def dummy_verify(password: str) -> None:
    """Spend the cost of one verification against a throwaway hash, so a login for an unknown (or locked, or inactive) user takes as
    long as a wrong password for a real one. The dummy hash is built once, with the current parameters."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _dummy_hash)
