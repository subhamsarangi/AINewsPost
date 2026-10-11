"""Auth helpers: login, logout, password hashing."""

import hashlib
import secrets
from typing import Optional

from digest import db


class AuthError(Exception):
    """Login/password error (user-facing message)."""
    pass


def hash_password(password: str) -> str:
    """Hash password with PBKDF2."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${key.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    salt, key_hex = hashed.split("$")
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return key.hex() == key_hex


def login(conn, email: str, password: str) -> str:
    """Return user_id (UUID) on success, raise AuthError on failure."""
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = %s", (email,)
    ).fetchone()
    if not row:
        raise AuthError("Email not found.")
    user_id, hashed = row["id"], row["password_hash"]
    if not verify_password(password, hashed):
        raise AuthError("Wrong password.")
    return str(user_id)


def create_user(conn, email: str, password: str) -> str:
    """Create a new user. Return user_id. Raise AuthError if email exists."""
    try:
        hashed = hash_password(password)
        row = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, hashed),
        ).fetchone()
        if not row:
            raise AuthError("Failed to create user.")
        return str(row["id"])
    except db.CONNECTION_ERRORS:
        raise
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise AuthError("Email already in use.")
        raise


def get_user(conn, user_id: str) -> Optional[dict]:
    """Fetch user by id. Return dict or None."""
    row = conn.execute(
        "SELECT id, email, created_at FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    if not row:
        return None
    return {"id": str(row["id"]), "email": row["email"], "created_at": row["created_at"]}
