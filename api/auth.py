"""Authentication and authorization for the AI Team Platform API.

Supports two authentication modes:

1. **API Key** -- static keys configured via ``AI_TEAM_API_KEYS`` env var.
2. **JWT** -- issued after API Key verification; used for subsequent requests.

When ``AI_TEAM_API_KEYS`` is not set, authentication is completely bypassed
(development mode).  This ensures backward compatibility with existing
deployments that do not require auth.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from engine.constants import DEFAULT_JWT_SECRET

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_API_KEYS: Optional[List[str]] = None
_JWT_SECRET: Optional[str] = None
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_MINUTES = 60 * 24  # 24 hours


def _get_api_keys() -> Optional[List[str]]:
    """Return configured API keys, or *None* when auth is disabled."""
    global _API_KEYS
    if _API_KEYS is not None:
        return _API_KEYS if _API_KEYS else None
    raw = os.environ.get("AI_TEAM_API_KEYS", "").strip()
    if not raw:
        _API_KEYS = []  # sentinel: checked, but empty
        return None
    _API_KEYS = [k.strip() for k in raw.split(",") if k.strip()]
    return _API_KEYS if _API_KEYS else None


def _get_jwt_secret() -> str:
    """Return JWT signing secret."""
    global _JWT_SECRET
    if _JWT_SECRET is not None:
        return _JWT_SECRET
    secret = os.environ.get("AI_TEAM_JWT_SECRET", "").strip()
    if not secret:
        if auth_enabled():
            raise RuntimeError(
                "AI_TEAM_JWT_SECRET must be set when AI_TEAM_API_KEYS is configured. "
                "The default secret is insecure for production use."
            )
        secret = DEFAULT_JWT_SECRET
    _JWT_SECRET = secret
    return _JWT_SECRET


def reset_auth_config() -> None:
    """Reset cached auth configuration (useful for tests)."""
    global _API_KEYS, _JWT_SECRET
    _API_KEYS = None
    _JWT_SECRET = None


def auth_enabled() -> bool:
    """Return *True* when API keys are configured (auth is active)."""
    return _get_api_keys() is not None


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT token."""
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("PyJWT is required for authentication. Install it with: pip install PyJWT") from exc

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=_JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and verify a JWT token.  Returns payload dict or raises."""
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("PyJWT is required for authentication.") from exc

    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[Dict[str, Any]]:
    """FastAPI dependency that validates JWT tokens.

    When ``AI_TEAM_API_KEYS`` is not set (development mode), the dependency
    always succeeds and returns ``{"sub": "anonymous"}``.
    """
    if not auth_enabled():
        return {"sub": "anonymous"}

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    return payload


async def verify_ws_token(token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Validate a WebSocket connection token (passed as query param).

    Returns user payload dict on success, or raises on failure.
    When auth is disabled, returns ``{"sub": "anonymous"}``.
    """
    if not auth_enabled():
        return {"sub": "anonymous"}

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    return decode_access_token(token)


# ---------------------------------------------------------------------------
# Login route helper
# ---------------------------------------------------------------------------

async def handle_login(api_key: str) -> Dict[str, str]:
    """Validate *api_key* against configured keys and return a JWT.

    Raises ``HTTPException(401)`` when the key is invalid or auth is disabled.
    """
    keys = _get_api_keys()
    if keys is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is not configured. Set AI_TEAM_API_KEYS to enable auth.",
        )

    if api_key not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    token = create_access_token({"sub": "api-user", "api_key": api_key[:8] + "..."})
    return {"access_token": token, "token_type": "bearer"}
