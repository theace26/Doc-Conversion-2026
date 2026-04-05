"""
Mount configuration endpoints.

GET  /api/settings/mounts       — Current mount configs + live status
POST /api/settings/mounts/test  — Test a mount config without applying
POST /api/settings/mounts/apply — Apply config: remount + update fstab + persist
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

import structlog

from core.mount_manager import (
    MountConfig,
    MountManager,
    SMBCredentials,
    KerberosConfig,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/settings/mounts", tags=["mounts"])

_manager = MountManager()

# -- Request / Response models --


class MountConfigRequest(BaseModel):
    protocol: str  # "smb" | "nfsv3" | "nfsv4"
    server: str
    share_path: str
    mount_point: str
    read_only: bool = True
    # SMB fields
    smb_username: str | None = None
    smb_password: str | None = None
    # NFSv4 Kerberos fields
    nfs_kerberos: bool = False
    kerberos_realm: str | None = None
    kerberos_keytab: str | None = None

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v not in ("smb", "nfsv3", "nfsv4"):
            raise ValueError("protocol must be 'smb', 'nfsv3', or 'nfsv4'")
        return v

    def to_mount_config(self) -> MountConfig:
        smb_creds = None
        if self.protocol == "smb" and self.smb_username:
            smb_creds = SMBCredentials(
                username=self.smb_username,
                password=self.smb_password or "",
            )

        kerberos = None
        if self.protocol == "nfsv4" and self.nfs_kerberos:
            kerberos = KerberosConfig(
                realm=self.kerberos_realm or "",
                keytab_path=self.kerberos_keytab or "/etc/krb5.keytab",
            )

        return MountConfig(
            protocol=self.protocol,
            server=self.server,
            share_path=self.share_path,
            mount_point=self.mount_point,
            read_only=self.read_only,
            smb_credentials=smb_creds,
            kerberos=kerberos,
        )


class ApplyRequest(BaseModel):
    role: str  # "source" or "output"
    config: MountConfigRequest

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("source", "output"):
            raise ValueError("role must be 'source' or 'output'")
        return v


# -- Endpoints --


@router.get("")
async def get_mounts():
    """Return current mount configurations and live status."""
    configs = _manager.load_config()
    result = {}

    for role in ("source", "output"):
        cfg = configs.get(role)
        if cfg:
            status = _manager.get_mount_status(cfg.mount_point)
            result[role] = {**cfg.to_dict(), **status}
        else:
            result[role] = None

    return result


@router.post("/test")
async def test_mount(req: MountConfigRequest):
    """Test a mount configuration without applying it."""
    try:
        config = req.to_mount_config()
        config.validate()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result = _manager.test_connection(config)
    return {
        "reachable": result.reachable,
        "mountable": result.mountable,
        "readable": result.readable,
        "message": result.message,
        "latency_ms": round(result.latency_ms, 1),
    }


@router.post("/apply")
async def apply_mount(req: ApplyRequest):
    """Apply a mount config: remount the share, update fstab, persist to JSON."""
    try:
        config = req.config.to_mount_config()
        config.validate()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Check no bulk job is running before remounting
    from core.bulk_worker import get_active_jobs
    active = get_active_jobs()
    if active:
        raise HTTPException(
            status_code=409,
            detail="Cannot remount while a bulk job is running. Stop the job first.",
        )

    # Live remount
    mount_result = _manager.mount(config)
    if not mount_result.success:
        return {
            "success": False,
            "message": mount_result.message,
            "command": mount_result.command,
        }

    # Update fstab
    fstab_ok = _manager.apply_to_fstab(config)

    # Persist config
    _manager.save_config(req.role, config)

    return {
        "success": True,
        "message": "Mounted and saved",
        "fstab_updated": fstab_ok,
        "command": mount_result.command,
    }
