"""
core/auth.py — JWT validation and role-based access control.

UnionCore is the identity provider. This module only validates tokens it issues.
Never imports route-level code. No circular imports.
"""

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Callable

import structlog
from fastapi import Depends, HTTPException, Request

log = structlog.get_logger(__name__)

# ── Environment ──────────────────────────────────────────────────────────────

DEV_BYPASS_AUTH = os.getenv("DEV_BYPASS_AUTH", "false").lower() == "true"


def _get_jwt_secret() -> str:
    return os.getenv("UNIONCORE_JWT_SECRET", "")


def _get_api_key_salt() -> str:
    return os.getenv("API_KEY_SALT", "")


# ── Role hierarchy ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SEARCH_USER = "search_user"
    OPERATOR = "operator"
    MANAGER = "manager"
    ADMIN = "admin"


_HIERARCHY = [UserRole.SEARCH_USER, UserRole.OPERATOR, UserRole.MANAGER, UserRole.ADMIN]


def role_satisfies(role: UserRole, required: UserRole) -> bool:
    """Return True if `role` meets or exceeds `required`."""
    return _HIERARCHY.index(role) >= _HIERARCHY.index(required)


# ── Authenticated user ──────────────────────────────────────────────────────

@dataclass
class AuthenticatedUser:
    sub: str
    email: str
    role: UserRole
    is_service_account: bool = False


# ── JWT verification ────────────────────────────────────────────────────────

async def verify_token(token: str, secret: str) -> AuthenticatedUser:
    """Decode and validate an HS256 JWT. Returns AuthenticatedUser on success."""
    from jose import JWTError, jwt

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError as exc:
        log.warning("auth.jwt_invalid", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    role_str = payload.get("role")
    if not role_str:
        raise HTTPException(status_code=403, detail="Token missing 'role' claim.")

    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail=f"Unknown role: '{role_str}'. Expected one of: {[r.value for r in UserRole]}",
        )

    return AuthenticatedUser(
        sub=payload.get("sub", ""),
        email=payload.get("email", ""),
        role=role,
    )


# ── API key verification ───────────────────────────────────────────────────

def hash_api_key(raw_key: str, salt: str) -> str:
    """Hash a raw API key with BLAKE2b + salt."""
    return hashlib.blake2b(
        raw_key.encode() + salt.encode(), digest_size=32
    ).hexdigest()


async def verify_api_key(key: str) -> AuthenticatedUser:
    """Validate an API key against the database. Returns service account user."""
    from core.database import get_api_key_by_hash, touch_api_key, DB_PATH

    salt = _get_api_key_salt()
    if not salt:
        raise HTTPException(status_code=401, detail="API key auth not configured.")

    key_hash = hash_api_key(key, salt)
    row = await get_api_key_by_hash(key_hash)

    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    if not row.get("is_active"):
        raise HTTPException(status_code=401, detail="API key has been revoked.")

    # Update last_used_at asynchronously
    await touch_api_key(row["key_id"])

    return AuthenticatedUser(
        sub=row["key_id"],
        email="service@markflow",
        role=UserRole.SEARCH_USER,
        is_service_account=True,
    )


# ── FastAPI dependency: get current user ────────────────────────────────────

async def get_current_user(request: Request) -> AuthenticatedUser:
    """
    FastAPI dependency. Resolution order:
    1. DEV_BYPASS_AUTH=true → admin
    2. X-API-Key header → service account
    3. Authorization: Bearer <token> → JWT user
    4. Neither → 401

    The resolved user is stashed on `request.state.user` so the
    RequestContextMiddleware can record per-user "last seen" activity
    after the response is generated (v0.22.13).
    """
    if DEV_BYPASS_AUTH:
        user = AuthenticatedUser(
            sub="dev", email="dev@local", role=UserRole.ADMIN, is_service_account=False
        )
        request.state.user = user
        return user

    # Check X-API-Key header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        user = await verify_api_key(api_key)
        request.state.user = user
        return user

    # Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        secret = _get_jwt_secret()
        if not secret:
            raise HTTPException(status_code=401, detail="JWT auth not configured.")
        user = await verify_token(token, secret)
        request.state.user = user
        return user

    raise HTTPException(status_code=401, detail="Authentication required.")


# ── Role guard dependency factory ───────────────────────────────────────────

def require_role(minimum: UserRole):
    """
    Returns a FastAPI dependency that enforces a minimum role.

    Usage:
        @router.get("/something")
        async def endpoint(user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER))):
            ...
    """
    async def _check(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not role_satisfies(user.role, minimum):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient role. Requires '{minimum.value}' or higher.",
            )
        return user

    return _check


# ── JWT role claim extraction (parallel to UserRole; do not merge) ──────────

class Role(IntEnum):
    """Role hierarchy. Defined upstream in UnionCore; MarkFlow consumes via JWT.

    Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §11
    """
    MEMBER = 0
    OPERATOR = 1
    ADMIN = 2


_ROLE_BY_NAME = {
    "member": Role.MEMBER,
    "operator": Role.OPERATOR,
    "admin": Role.ADMIN,
}


def extract_role(claims: dict) -> Role:
    """Return the Role from a JWT claims dict.

    Defensive: missing or unknown role -> MEMBER (least privilege).
    Case-insensitive on the role string.
    """
    raw = (claims.get("role") or "").strip().lower()
    return _ROLE_BY_NAME.get(raw, Role.MEMBER)
