"""GET /api/me — authenticated user identity + role.

Spec: docs/superpowers/specs/2026-04-28-ux-overhaul-search-as-home-design.md §1, §11
"""
from __future__ import annotations
import os
import subprocess
from fastapi import APIRouter, Depends

from core.auth import get_current_user, AuthenticatedUser, UserRole
from core.version import __version__

router = APIRouter(prefix="/api/me", tags=["identity"])


def _git_short_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd="/app",
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return os.environ.get("BUILD_SHA", "unknown")


def _git_branch() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd="/app",
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return os.environ.get("BUILD_BRANCH", "unknown")


_BUILD = {
    "version": __version__,
    "branch": _git_branch(),
    "sha": _git_short_sha(),
    "date": os.environ.get("BUILD_DATE", "dev"),
}

# UserRole (4-tier) → UI role string (3-tier). MANAGER satisfies OPERATOR.
_ROLE_TIER: dict[UserRole, str] = {
    UserRole.SEARCH_USER: "member",
    UserRole.OPERATOR: "operator",
    UserRole.MANAGER: "operator",
    UserRole.ADMIN: "admin",
}


@router.get("")
async def get_me(user: AuthenticatedUser = Depends(get_current_user)):
    """Return the authenticated user's identity, role, and build info."""
    return {
        "user_id": user.sub,
        "email": user.email,
        "name": user.email or user.sub,
        "role": _ROLE_TIER.get(user.role, "member"),
        "scope": "IBEW Local 46",
        "build": _BUILD,
    }
