"""Passkey validation and JWT authentication."""

import time

import jwt
from fastapi import HTTPException, Request

from .config import settings


def create_token() -> str:
    """Create a JWT token for a validated beta user."""
    now = time.time()
    payload = {
        "sub": "beta_user",
        "iat": now,
        "exp": now + (settings.jwt_expiry_days * 86400),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def validate_passkey(passkey: str) -> bool:
    """Check if the provided passkey matches the beta passkey."""
    return passkey == settings.beta_passkey


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(request: Request) -> dict:
    """FastAPI dependency that validates the JWT from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]
    return decode_token(token)
