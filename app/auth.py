"""
auth.py
-------
Security layer — JWT token creation and admin authentication dependency.

This module provides:
  - An OAuth2 password-bearer scheme (token URL: /admin/login).
  - create_access_token()  — signs a JWT with HS256.
  - get_current_admin()    — FastAPI dependency that validates an incoming
                             Bearer token and confirms the caller is an admin.

⚠️  Production hardening checklist (before going live):
    1. Move SECRET_KEY to an environment variable (e.g. python-decouple or
       pydantic-settings).  Never commit real secrets to version control.
    2. Replace the hardcoded admin credentials in admin.py with a proper
       User table + hashed passwords (e.g. passlib[bcrypt]).
    3. Consider shorter token expiry + a refresh-token flow.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ⚠️  Replace this with a long, random secret in production.
#     Generate one with:  python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY: str = "SECRET_KEY"

ALGORITHM: str = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # Tokens valid for 1 hour.

# ---------------------------------------------------------------------------
# OAuth2 scheme
# ---------------------------------------------------------------------------

# tokenUrl tells FastAPI (and the Swagger UI "Authorize" button) where to
# POST credentials to obtain a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/login")


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Sign and return a JWT access token.

    Args:
        data:          Payload claims to embed (e.g. ``{"sub": "admin", "role": "admin"}``).
        expires_delta: Optional custom expiry window.  Defaults to
                       ``ACCESS_TOKEN_EXPIRE_MINUTES``.

    Returns:
        A compact, URL-safe JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Admin authentication dependency
# ---------------------------------------------------------------------------

def get_current_admin(token: str = Depends(oauth2_scheme)) -> dict:
    """
    FastAPI dependency — decode the Bearer token and verify admin role.

    Inject this into any endpoint that requires admin authentication:

        @router.post("/", dependencies=[Depends(get_current_admin)])

    or as a typed parameter for access to the payload:

        def my_endpoint(admin: dict = Depends(get_current_admin)): ...

    Args:
        token: Raw Bearer token extracted from the ``Authorization`` header
               by the OAuth2 scheme.

    Returns:
        The decoded JWT payload dict (contains ``sub``, ``role``, ``exp``, etc.).

    Raises:
        HTTPException 401: Token is missing, expired, malformed, or does
                           not carry the ``role: admin`` claim.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in as an admin.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload: dict = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        role: str | None = payload.get("role")
        if role != "admin":
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    return payload
