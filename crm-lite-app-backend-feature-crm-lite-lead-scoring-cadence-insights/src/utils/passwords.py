"""Password hashing for employee login (see POST /auth/login). bcrypt
directly rather than passlib — passlib's bcrypt backend has had version-
compatibility issues with recent bcrypt releases, and this only needs two
functions."""
import secrets
import string

import bcrypt

_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_temp_password(length: int = 16) -> str:
    """A one-time password for a newly-provisioned employee, emailed to them
    (see admin_service.create_employee()) — must_change_password forces them
    to replace it with one only they know on first login."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash — never let a bad stored value 500 a login
        # attempt; it should just fail like a wrong password would.
        return False
