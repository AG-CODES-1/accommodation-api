"""
routers/admin.py
----------------
Presentation layer — admin authentication endpoint.

Routes
------
  POST /admin/login    Accept credentials and return a signed JWT token.

⚠️  The hardcoded admin credentials below are for MVP/development only.
    In production, replace with a hashed-password lookup against a User table.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth import create_access_token

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)

# ---------------------------------------------------------------------------
# Hardcoded admin credentials (MVP only — replace in production)
# ---------------------------------------------------------------------------

_ADMIN_USERNAME: str = "admin"
_ADMIN_PASSWORD: str = "password123"


# ---------------------------------------------------------------------------
# POST /admin/login — Issue a JWT token
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    summary="Admin login",
    description=(
        "Authenticate with admin credentials and receive a signed JWT Bearer token. "
        "Pass this token in the ``Authorization: Bearer <token>`` header to access "
        "protected endpoints (``POST /allocations/`` and ``DELETE /allocations/{id}``)."
    ),
)
def admin_login(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> dict:
    """
    Validate admin credentials and issue a JWT access token.

    Uses OAuth2 ``application/x-www-form-urlencoded`` format so that the
    Swagger UI "Authorize" button works out of the box.

    Args:
        form_data: Parsed form body containing ``username`` and ``password``.

    Returns:
        A JSON object with ``access_token`` and ``token_type`` fields,
        conforming to the OAuth2 bearer token response spec.

    Raises:
        HTTPException 401: Credentials are incorrect.
    """
    if (
        form_data.username != _ADMIN_USERNAME
        or form_data.password != _ADMIN_PASSWORD
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={
            "sub":  _ADMIN_USERNAME,   # Subject claim — identifies the principal.
            "role": "admin",           # Role claim — checked by get_current_admin().
        }
    )

    return {
        "access_token": token,
        "token_type":   "bearer",
    }
