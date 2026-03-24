"""
Auth info endpoint.

GET /api/auth/me — Returns the current user's identity and role.
"""

from fastapi import APIRouter, Depends

from core.auth import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def auth_me(user: AuthenticatedUser = Depends(get_current_user)):
    """Return the current user's identity. No role guard — used by frontend to discover role."""
    return {
        "sub": user.sub,
        "email": user.email,
        "role": user.role.value,
        "is_service_account": user.is_service_account,
    }
