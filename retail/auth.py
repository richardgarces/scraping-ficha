from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path

COOKIE = "retail_session"
SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-z0-9._-]{2,32}$")
_PBKDF2_ROUNDS = 180_000
DEFAULT_ADMIN = "admin"
DEFAULT_ADMIN_PASSWORD = "Ragr13798"


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value))


def valid_login(value: str) -> bool:
    return valid_email(value) or bool(USERNAME_RE.match(value))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    raw = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), raw, _PBKDF2_ROUNDS)
    return f"pbkdf2$sha256${_PBKDF2_ROUNDS}${raw.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 5 or parts[0] != "pbkdf2":
        return False
    try:
        rounds = int(parts[2])
        salt = bytes.fromhex(parts[3])
        expected = bytes.fromhex(parts[4])
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return hmac.compare_digest(digest, expected)


def session_secret() -> bytes:
    env = os.environ.get("RETAIL_SECRET")
    if env:
        return env.encode()
    path = Path("output/secret.local")
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value + "\n")
    return value.encode()


def sign_session(user_id: str, *, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = f"{user_id}.{issued}"
    sig = hmac.new(session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_session(token: str | None, *, now: int | None = None, max_age: int = SESSION_DAYS * 86400) -> str | None:
    if not token or token.count(".") != 2:
        return None
    user_id, issued_raw, sig = token.split(".", 2)
    payload = f"{user_id}.{issued_raw}"
    expected = hmac.new(session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        issued = int(issued_raw)
    except ValueError:
        return None
    current = int(now if now is not None else time.time())
    if current - issued > max_age or issued > current + 60:
        return None
    return user_id or None


def admin_email() -> str:
    return normalize_email(os.environ.get("RETAIL_ADMIN_EMAIL") or DEFAULT_ADMIN)


def admin_password() -> str:
    return os.environ.get("RETAIL_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD


def safe_next(value: str | None, default: str = "/") -> str:
    raw = str(value or "").strip()
    if raw.startswith("/") and not raw.startswith("//") and "://" not in raw and "\\" not in raw:
        return raw
    return default
