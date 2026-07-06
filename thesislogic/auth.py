"""Credential-backed users and matter-scoped sessions.

Design choices carried from field experience with legal deployments:
  - protected routes derive user_id/matter_id from the session token, never
    from caller-supplied JSON, so matter isolation cannot be bypassed;
  - sessions expire on a TTL;
  - repeated failed logins trigger a temporary lockout.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

_PBKDF2_ITERATIONS = 240_000


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def register_user(db: sqlite3.Connection, user_id: str, password: str, display_name: str = "",
                  role: str = "attorney") -> dict:
    user_id = user_id.strip()
    if not user_id or not password:
        raise AuthError("user_id and password are required", 400)
    if len(password) < 10:
        raise AuthError("password must be at least 10 characters", 400)
    existing = db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if existing:
        raise AuthError("user already exists", 409)
    # First user in a fresh install becomes admin so setup needs no back door.
    count = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    effective_role = "admin" if count == 0 else role
    db.execute(
        "INSERT INTO users (user_id, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
        (user_id, display_name or user_id, hash_password(password), effective_role),
    )
    db.commit()
    return {"user_id": user_id, "display_name": display_name or user_id, "role": effective_role}


def create_session(db: sqlite3.Connection, user_id: str, password: str, matter_id: str,
                   ttl_seconds: int, lockout_threshold: int, lockout_seconds: int) -> dict:
    row = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise AuthError("invalid credentials")
    if row["locked_until"]:
        locked_until = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if locked_until > _now():
            raise AuthError("account temporarily locked; try again later", 423)
    if not verify_password(password, row["password_hash"]):
        attempts = row["failed_attempts"] + 1
        locked_until = _iso(_now() + timedelta(seconds=lockout_seconds)) if attempts >= lockout_threshold else None
        db.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                   (0 if locked_until else attempts, locked_until, user_id))
        db.commit()
        raise AuthError("invalid credentials")
    matter_id = (matter_id or "general").strip()
    db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE user_id = ?", (user_id,))
    # Rotate: opening a new session for the same user+matter replaces the old one.
    db.execute("DELETE FROM sessions WHERE user_id = ? AND matter_id = ?", (user_id, matter_id))
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions (token, user_id, matter_id, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, matter_id, _iso(_now() + timedelta(seconds=ttl_seconds))),
    )
    # Ensure matter + membership exist.
    db.execute("INSERT OR IGNORE INTO matters (matter_id, created_by) VALUES (?, ?)", (matter_id, user_id))
    db.execute("INSERT OR IGNORE INTO matter_members (matter_id, user_id) VALUES (?, ?)", (matter_id, user_id))
    db.commit()
    return {
        "token": token,
        "user_id": user_id,
        "matter_id": matter_id,
        "display_name": row["display_name"],
        "role": row["role"],
    }


def resolve_session(db: sqlite3.Connection, token: str) -> dict:
    if not token:
        raise AuthError("missing bearer token")
    row = db.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise AuthError("invalid or expired session")
    expires = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if expires < _now():
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        db.commit()
        raise AuthError("invalid or expired session")
    user = db.execute("SELECT display_name, role FROM users WHERE user_id = ?", (row["user_id"],)).fetchone()
    return {
        "user_id": row["user_id"],
        "matter_id": row["matter_id"],
        "display_name": user["display_name"] if user else row["user_id"],
        "role": user["role"] if user else "attorney",
    }
