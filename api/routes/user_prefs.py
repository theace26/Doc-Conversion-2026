"""Per-user preferences GET/PUT endpoints. Spec §10.

Distinct from api/routes/preferences.py (system-level singleton prefs).
"""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException, Depends

from core.user_prefs import get_user_prefs, set_user_prefs
from core.auth import get_current_user, AuthenticatedUser
from core.db.connection import get_db_path

router = APIRouter(prefix="/api/user-prefs", tags=["user-prefs"])


@router.get("")
async def read_user_prefs(user: AuthenticatedUser = Depends(get_current_user)) -> dict:
    db = get_db_path()
    return await get_user_prefs(db, user.sub)


@router.put("")
async def write_user_prefs(
    payload: dict[str, Any],
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    db = get_db_path()
    try:
        await set_user_prefs(db, user.sub, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await get_user_prefs(db, user.sub)
