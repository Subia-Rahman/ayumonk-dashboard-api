from __future__ import annotations
import base64
import hashlib
import hmac
import secrets

from fastapi.security import OAuth2PasswordBearer

from jose import JWTError, jwt
from fastapi import HTTPException, status

from authentication_service.app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=settings.AUTH_TOKEN_URL)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 100_000
    derived_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode("utf-8")
    hash_b64 = base64.b64encode(derived_key).decode("utf-8")
    return f"pbkdf2_sha256${iterations}${salt_b64}${hash_b64}"

def verify_password(password: str, stored_password: str) -> bool:
    if not stored_password:
        return False

    if not stored_password.startswith("pbkdf2_sha256$"):
        return password == stored_password

    try:
        _, iteration_text, salt_b64, hash_b64 = stored_password.split("$", 3)
        iterations = int(iteration_text)
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected_hash = base64.b64decode(hash_b64.encode("utf-8"))
    except (ValueError, TypeError, base64.binascii.Error):
        return False

    candidate_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate_hash, expected_hash)

SECRET_KEY = "demo_secret_key"
ALGORITHM = "HS256"

def verify_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
