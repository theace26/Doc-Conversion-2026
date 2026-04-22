"""Universal Storage Manager API (v0.25.0).

Consolidated `/api/storage/*` surface that powers the Storage page UI:

- Host detection + quick-access list
- Path validation (source / output)
- Sources / output / exclusions CRUD
- Network shares: list, add, remove, discover, test, credentials
- Mount health (5-min scheduler tick state)
- Pending-restart banner state
- First-run wizard trigger + dismiss

All endpoints require the MANAGER role minimum; ADMIN is required for
clear-text credential reads and wizard reset.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.auth import UserRole, require_role
from core.credential_store import CredentialStore
from core.db.preferences import set_preference
from core.host_detector import detect_host
from core.mount_manager import (
    MountConfig,
    SMBCredentials,
    discover_nfs_exports,
    discover_smb_servers,
    discover_smb_shares,
    get_mount_manager,
    mount_health,
)
from core.preferences_cache import get_cached_preference, invalidate_preference
from core import storage_manager as sm
from core.storage_manager import PathRole

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/storage", tags=["storage"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _credential_store() -> CredentialStore:
    """Build a CredentialStore using the process SECRET_KEY."""
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise HTTPException(503, "SECRET_KEY env var not set — credential store unavailable")
    return CredentialStore(secret_key=secret)


def _mask(value: str) -> str:
    """Return '****' if value is non-empty, else ''. Used to hide stored creds in lists."""
    return "****" if value else ""


async def _set_pref(key: str, value: str) -> None:
    """Write-through preference setter: DB write then cache invalidate."""
    await set_preference(key, value)
    invalidate_preference(key)


# ── Host info ────────────────────────────────────────────────────────────────


@router.get("/host-info")
async def get_host_info(user=Depends(require_role(UserRole.MANAGER))) -> dict[str, Any]:
    info = detect_host()
    override = await get_cached_preference("host_os_override", default="")
    return {
        "os": override or info.os.value,
        "auto_detected_os": info.os.value,
        "drive_letters": info.drive_letters,
        "home_dirs": info.home_dirs,
        "external_drives": info.external_drives,
        "quick_access": [
            {"name": q.name, "path": q.path, "icon": q.icon, "item_count": q.item_count}
            for q in info.quick_access
        ],
    }


# ── Path validation ──────────────────────────────────────────────────────────


class ValidateRequest(BaseModel):
    path: str
    role: str = Field(pattern="^(source|output)$")


@router.post("/validate")
async def validate(req: ValidateRequest, user=Depends(require_role(UserRole.MANAGER))) -> dict[str, Any]:
    role = PathRole.SOURCE if req.role == "source" else PathRole.OUTPUT
    result = await sm.validate_path(req.path, role)
    return {
        "ok": result.ok,
        "warnings": result.warnings,
        "errors": result.errors,
        "stats": result.stats,
    }


# ── Sources ──────────────────────────────────────────────────────────────────


class SourceIn(BaseModel):
    path: str
    label: str = ""


@router.get("/sources")
async def list_sources(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    raw = await get_cached_preference("storage_sources_json", default="[]")
    return {"sources": json.loads(raw or "[]")}


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(src: SourceIn, user=Depends(require_role(UserRole.MANAGER))) -> dict:
    raw = await get_cached_preference("storage_sources_json", default="[]")
    existing = json.loads(raw or "[]")
    v = await sm.validate_path(src.path, PathRole.SOURCE)
    if not v.ok:
        raise HTTPException(400, detail={"errors": v.errors, "warnings": v.warnings})
    sid = str(len(existing) + 1)
    entry = {"id": sid, "path": src.path, "label": src.label or src.path}
    existing.append(entry)
    await _set_pref("storage_sources_json", json.dumps(existing))
    return entry


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_source(source_id: str, user=Depends(require_role(UserRole.MANAGER))) -> None:
    raw = await get_cached_preference("storage_sources_json", default="[]")
    existing = json.loads(raw or "[]")
    existing = [s for s in existing if s.get("id") != source_id]
    await _set_pref("storage_sources_json", json.dumps(existing))


# ── Output ───────────────────────────────────────────────────────────────────


class OutputIn(BaseModel):
    path: str


@router.get("/output")
async def get_output(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    return {"path": sm.get_output_path() or ""}


@router.put("/output")
async def set_output(out: OutputIn, user=Depends(require_role(UserRole.MANAGER))) -> dict:
    v = await sm.validate_path(out.path, PathRole.OUTPUT)
    if not v.ok:
        raise HTTPException(400, detail={"errors": v.errors, "warnings": v.warnings})
    await sm.save_output_path(out.path)
    return {"ok": True, "path": out.path}


# ── Exclusions ───────────────────────────────────────────────────────────────


class ExclusionIn(BaseModel):
    path_prefix: str


@router.get("/exclusions")
async def list_exclusions(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    raw = await get_cached_preference("storage_exclusions_json", default="[]")
    return {"exclusions": json.loads(raw or "[]")}


@router.post("/exclusions", status_code=status.HTTP_201_CREATED)
async def add_exclusion(ex: ExclusionIn, user=Depends(require_role(UserRole.MANAGER))) -> dict:
    raw = await get_cached_preference("storage_exclusions_json", default="[]")
    existing = json.loads(raw or "[]")
    eid = str(len(existing) + 1)
    entry = {"id": eid, "path_prefix": ex.path_prefix}
    existing.append(entry)
    await _set_pref("storage_exclusions_json", json.dumps(existing))
    return entry


@router.delete("/exclusions/{ex_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_exclusion(ex_id: str, user=Depends(require_role(UserRole.MANAGER))) -> None:
    raw = await get_cached_preference("storage_exclusions_json", default="[]")
    existing = json.loads(raw or "[]")
    existing = [e for e in existing if e.get("id") != ex_id]
    await _set_pref("storage_exclusions_json", json.dumps(existing))


# ── Network shares ───────────────────────────────────────────────────────────


class ShareIn(BaseModel):
    # v0.29.0 SELF-H1: name pattern is enforced at the API layer so we can't
    # save credentials under a key like '../../evil' that the mount layer
    # later sanitizes to something different (credential/mount key mismatch).
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    protocol: str = Field(pattern="^(smb|nfsv3|nfsv4)$")
    server: str = Field(min_length=1, max_length=253)
    share: str = Field(default="", max_length=1024)
    username: str = Field(default="", max_length=256)
    password: str = Field(default="", max_length=512)
    options: dict = Field(default_factory=dict)


class DiscoverIn(BaseModel):
    """v0.29.0 SELF-H3: explicit shape beats `payload: dict`.

    scope='subnet' uses `subnet`; scope='server' uses `server`+`protocol`
    (+ optional username/password for SMB authenticated listing).
    """
    scope: str = Field(pattern="^(subnet|server)$")
    subnet: str = Field(default="", max_length=64)
    server: str = Field(default="", max_length=253)
    protocol: str = Field(default="smb", pattern="^(smb|nfs)$")
    username: str = Field(default="", max_length=256)
    password: str = Field(default="", max_length=512)


@router.get("/shares")
async def list_shares(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    mgr = get_mount_manager()
    shares_cfg = mgr._load_config_v2().get("shares", {})
    return {
        "shares": [
            {
                "name": name,
                "protocol": cfg.get("protocol"),
                "server": cfg.get("server"),
                "share_path": cfg.get("share_path", cfg.get("share", "")),
                "username": _mask(cfg.get("smb_username", "")),
                "password": _mask("x"),
                "status": mount_health.get(name, {"ok": None}),
            }
            for name, cfg in shares_cfg.items()
        ]
    }


@router.post("/shares", status_code=status.HTTP_201_CREATED)
async def add_share(share: ShareIn, user=Depends(require_role(UserRole.MANAGER))) -> dict:
    mgr = get_mount_manager()
    # v0.29.0 SELF-H2: reject servers that start with '-' so they can't be
    # interpreted as a subprocess flag by smbclient / mount.cifs / mount.nfs.
    if share.server.startswith("-"):
        raise HTTPException(400, detail={"error": "server must not start with '-'"})

    # Persist credentials FIRST so a remount-after-restart sees them
    creds_saved = False
    if share.username or share.password:
        _credential_store().save_credentials(
            share.name, share.protocol, share.username, share.password,
        )
        creds_saved = True

    smb_creds = None
    if share.protocol == "smb":
        smb_creds = SMBCredentials(username=share.username, password=share.password)
    cfg = MountConfig(
        protocol=share.protocol,
        server=share.server,
        share_path=share.share,
        # mount_named() will override this with /mnt/shares/<name>:
        mount_point=f"/mnt/shares/{share.name}",
        read_only=share.options.get("read_only", True),
        smb_credentials=smb_creds,
        extra_options=share.options.get("extra_options", {}),
        display_name=share.name,
    )
    try:
        result = await asyncio.to_thread(mgr.mount_named, share.name, cfg)
    except Exception as exc:
        # v0.29.0 SELF-H4: if mount setup raises, roll back the credential
        # we just persisted so we don't leave an orphan.
        if creds_saved:
            try:
                _credential_store().delete_credentials(share.name)
            except Exception:
                log.warning("credential_rollback_failed", share=share.name)
        raise HTTPException(500, detail={"error": "mount setup failed"}) from exc

    if not getattr(result, "success", False):
        # v0.29.0 SELF-H4: mount failed (bad creds / server unreachable) —
        # delete the orphan credential.
        if creds_saved:
            try:
                _credential_store().delete_credentials(share.name)
            except Exception:
                log.warning("credential_rollback_failed", share=share.name)
        raise HTTPException(400, detail={"error": getattr(result, "message", "mount failed")})
    mgr.save_config(share.name, cfg)
    return {"ok": True, "name": share.name}


@router.delete("/shares/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_share(name: str, user=Depends(require_role(UserRole.MANAGER))) -> None:
    mgr = get_mount_manager()
    await asyncio.to_thread(mgr.unmount_named, name)
    # Remove from mounts.json
    doc = mgr._load_config_v2()
    doc.get("shares", {}).pop(name, None)
    mgr.config_path.parent.mkdir(parents=True, exist_ok=True)
    mgr.config_path.write_text(json.dumps(doc, indent=2) + "\n")
    try:
        _credential_store().delete_credentials(name)
    except Exception as exc:  # noqa: BLE001 — credential cleanup is best-effort
        log.warning("credential_cleanup_failed", share=name, error=str(exc))


@router.post("/shares/discover")
async def discover(payload: DiscoverIn, user=Depends(require_role(UserRole.MANAGER))) -> dict:
    if payload.scope == "subnet":
        if not payload.subnet:
            raise HTTPException(400, "subnet is required")
        servers = await discover_smb_servers(payload.subnet)
        return {"servers": servers}
    # scope == "server"
    if not payload.server:
        raise HTTPException(400, "server is required")
    # v0.29.0 SELF-H2: reject server values that start with '-' so showmount
    # or smbclient don't interpret them as flags. Hostnames / IPs never
    # legitimately start with '-', so this is safe to reject outright.
    if payload.server.startswith("-"):
        raise HTTPException(400, "server must not start with '-'")
    if payload.protocol == "smb":
        shares = await discover_smb_shares(
            payload.server,
            username=payload.username,
            password=payload.password,
        )
    else:
        shares = await discover_nfs_exports(payload.server)
    return {"shares": shares}


@router.post("/shares/{name}/test")
async def test_share(name: str, user=Depends(require_role(UserRole.MANAGER))) -> dict:
    mgr = get_mount_manager()
    try:
        mp = mgr.share_mount_point(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    try:
        items = await asyncio.to_thread(os.listdir, mp)
        return {"ok": True, "item_count": len(items)}
    except Exception as exc:  # noqa: BLE001 — surface mount-point errors verbatim
        return {"ok": False, "error": str(exc)}


@router.get("/shares/{name}/credentials")
async def get_share_creds(name: str, user=Depends(require_role(UserRole.ADMIN))) -> dict:
    creds = _credential_store().get_credentials(name)
    if not creds:
        raise HTTPException(404, "no credentials saved")
    return {"username": creds[0], "password": creds[1]}


# ── Health, restart, wizard ──────────────────────────────────────────────────


@router.get("/health")
async def health(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    return {"mounts": mount_health}


@router.get("/restart-status")
async def restart_status(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    reason = await get_cached_preference("pending_restart_reason", default="")
    since = await get_cached_preference("pending_restart_since", default="")
    dismissed_until = await get_cached_preference("pending_restart_dismissed_until", default="")
    return {"reason": reason, "since": since, "dismissed_until": dismissed_until}


@router.post("/restart-dismiss")
async def restart_dismiss(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await _set_pref("pending_restart_dismissed_until", until)
    return {"dismissed_until": until}


@router.get("/wizard-status")
async def wizard_status(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    if os.environ.get("SKIP_FIRST_RUN_WIZARD") or os.environ.get("DEV_BYPASS_AUTH") == "true":
        return {"show": False, "reason": "env-suppressed"}
    if await get_cached_preference("setup_wizard_dismissed", default="") == "true":
        return {"show": False, "reason": "dismissed"}
    sources = json.loads(await get_cached_preference("storage_sources_json", default="[]") or "[]")
    output = sm.get_output_path()
    if sources or output:
        return {"show": False, "reason": "configured"}
    return {"show": True}


@router.post("/wizard-dismiss")
async def wizard_dismiss(user=Depends(require_role(UserRole.MANAGER))) -> dict:
    await _set_pref("setup_wizard_dismissed", "true")
    return {"ok": True}


@router.delete("/wizard-dismiss")
async def wizard_reopen(user=Depends(require_role(UserRole.ADMIN))) -> dict:
    await _set_pref("setup_wizard_dismissed", "")
    return {"ok": True}
