# NFS Mount Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NFS (v3/v4) as a mount protocol alongside SMB/CIFS, configurable in both the setup script and the Settings UI with live remounting.

**Architecture:** New `core/mount_manager.py` provides a protocol-agnostic abstraction over mount/unmount/test operations. `api/routes/mounts.py` exposes REST endpoints. The Settings page gains a "Storage Connections" section. Setup script gains protocol selection. A host-side helper script handles privileged mount operations.

**Tech Stack:** Python 3.12, FastAPI, vanilla JS, bash, `nfs-common` system package.

**Spec:** `docs/superpowers/specs/2026-04-05-nfs-mount-support-design.md`

---

### Task 1: Mount Manager — Config Models and fstab Generation

**Files:**
- Create: `core/mount_manager.py`
- Create: `tests/test_mount_manager.py`

This task builds the data models and the pure-function fstab/command generation. No actual mounting — all testable without root.

- [ ] **Step 1: Write failing tests for fstab generation**

Create `tests/test_mount_manager.py`:

```python
"""Tests for mount_manager — config models and command generation."""

import pytest
from core.mount_manager import (
    MountConfig,
    SMBCredentials,
    KerberosConfig,
    MountManager,
)


class TestFstabGeneration:
    """Test fstab entry generation for each protocol."""

    def test_smb_fstab_entry(self):
        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="storage_folder",
            mount_point="/mnt/source-share",
            read_only=True,
            smb_credentials=SMBCredentials(username="markflow", password="test"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert entry.startswith("//192.168.1.17/storage_folder")
        assert "/mnt/source-share" in entry
        assert "cifs" in entry
        assert "ro" in entry
        assert "credentials=/etc/markflow-smb-credentials" in entry
        assert "_netdev" in entry
        assert "x-systemd.automount" in entry

    def test_smb_rw_fstab_entry(self):
        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="markflow",
            mount_point="/mnt/markflow-output",
            read_only=False,
            smb_credentials=SMBCredentials(username="markflow", password="test"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert "rw" in entry
        assert "ro" not in entry.split("rw")[0]  # no stray 'ro' before 'rw'

    def test_nfsv3_fstab_entry(self):
        cfg = MountConfig(
            protocol="nfsv3",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert entry.startswith("192.168.1.17:/volume1/storage")
        assert "/mnt/source-share" in entry
        assert "nfs" in entry
        assert "nfs4" not in entry
        assert "ro" in entry
        assert "hard" in entry
        assert "intr" in entry
        assert "_netdev" in entry

    def test_nfsv4_fstab_entry(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert "nfs4" in entry
        assert "sec=krb5" not in entry

    def test_nfsv4_kerberos_fstab_entry(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
            kerberos=KerberosConfig(realm="EXAMPLE.COM", keytab_path="/etc/krb5.keytab"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert "nfs4" in entry
        assert "sec=krb5" in entry


class TestMountCommandGeneration:
    """Test mount command generation for each protocol."""

    def test_smb_mount_command(self):
        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="storage_folder",
            mount_point="/mnt/source-share",
            read_only=True,
            smb_credentials=SMBCredentials(username="markflow", password="test"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "mount -t cifs" in cmd
        assert "//192.168.1.17/storage_folder" in cmd
        assert "/mnt/source-share" in cmd

    def test_nfsv3_mount_command(self):
        cfg = MountConfig(
            protocol="nfsv3",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "mount -t nfs " in cmd
        assert "192.168.1.17:/volume1/storage" in cmd

    def test_nfsv4_mount_command(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "mount -t nfs4" in cmd

    def test_nfsv4_kerberos_mount_command(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
            kerberos=KerberosConfig(realm="EXAMPLE.COM", keytab_path="/etc/krb5.keytab"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "sec=krb5" in cmd


class TestConfigValidation:
    """Test MountConfig validation."""

    def test_smb_requires_credentials(self):
        with pytest.raises(ValueError, match="SMB.*credentials"):
            MountConfig(
                protocol="smb",
                server="192.168.1.17",
                share_path="share",
                mount_point="/mnt/test",
                read_only=True,
            ).validate()

    def test_nfs_rejects_credentials(self):
        cfg = MountConfig(
            protocol="nfsv3",
            server="192.168.1.17",
            share_path="/export",
            mount_point="/mnt/test",
            read_only=True,
        )
        cfg.validate()  # should not raise

    def test_empty_server_rejected(self):
        with pytest.raises(ValueError, match="[Ss]erver"):
            MountConfig(
                protocol="nfsv3",
                server="",
                share_path="/export",
                mount_point="/mnt/test",
                read_only=True,
            ).validate()

    def test_empty_share_rejected(self):
        with pytest.raises(ValueError, match="[Ss]hare"):
            MountConfig(
                protocol="nfsv3",
                server="192.168.1.17",
                share_path="",
                mount_point="/mnt/test",
                read_only=True,
            ).validate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_mount_manager.py -v`
Expected: ImportError — `core.mount_manager` does not exist.

- [ ] **Step 3: Implement mount_manager.py — models and generation**

Create `core/mount_manager.py`:

```python
"""
Mount manager — protocol-agnostic abstraction for network file share mounts.

Supports SMB/CIFS, NFSv3, and NFSv4 (with optional Kerberos).
Generates mount commands, fstab entries, and manages config persistence.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

# Allowed mount point prefixes — never mount outside these
_ALLOWED_MOUNT_PREFIXES = ("/mnt/",)

_SMB_CREDENTIALS_PATH = "/etc/markflow-smb-credentials"


@dataclass
class SMBCredentials:
    username: str
    password: str  # transient — written to credentials file, not stored in config JSON


@dataclass
class KerberosConfig:
    realm: str
    keytab_path: str


@dataclass
class MountConfig:
    protocol: Literal["smb", "nfsv3", "nfsv4"]
    server: str
    share_path: str
    mount_point: str
    read_only: bool
    smb_credentials: SMBCredentials | None = None
    kerberos: KerberosConfig | None = None
    extra_options: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        """Raise ValueError if config is invalid."""
        if not self.server or not self.server.strip():
            raise ValueError("Server address is required")
        if not self.share_path or not self.share_path.strip():
            raise ValueError("Share path is required")
        if not self.mount_point or not self.mount_point.strip():
            raise ValueError("Mount point is required")
        if not any(self.mount_point.startswith(p) for p in _ALLOWED_MOUNT_PREFIXES):
            raise ValueError(f"Mount point must start with one of {_ALLOWED_MOUNT_PREFIXES}")
        if self.protocol == "smb" and not self.smb_credentials:
            raise ValueError("SMB protocol requires credentials (username/password)")
        if self.kerberos and self.protocol != "nfsv4":
            raise ValueError("Kerberos is only supported with NFSv4")

    def to_dict(self) -> dict:
        """Serialize for JSON config (excludes passwords)."""
        d = {
            "protocol": self.protocol,
            "server": self.server,
            "share_path": self.share_path,
            "mount_point": self.mount_point,
            "read_only": self.read_only,
        }
        if self.smb_credentials:
            d["smb_username"] = self.smb_credentials.username
        if self.kerberos:
            d["nfs_kerberos"] = True
            d["kerberos_realm"] = self.kerberos.realm
            d["kerberos_keytab"] = self.kerberos.keytab_path
        else:
            d["nfs_kerberos"] = False
        if self.extra_options:
            d["extra_options"] = self.extra_options
        return d

    @classmethod
    def from_dict(cls, d: dict) -> MountConfig:
        """Deserialize from JSON config."""
        smb_creds = None
        if d.get("smb_username"):
            smb_creds = SMBCredentials(username=d["smb_username"], password="")

        kerberos = None
        if d.get("nfs_kerberos"):
            kerberos = KerberosConfig(
                realm=d.get("kerberos_realm", ""),
                keytab_path=d.get("kerberos_keytab", "/etc/krb5.keytab"),
            )

        return cls(
            protocol=d["protocol"],
            server=d["server"],
            share_path=d["share_path"],
            mount_point=d["mount_point"],
            read_only=d.get("read_only", True),
            smb_credentials=smb_creds,
            kerberos=kerberos,
            extra_options=d.get("extra_options", {}),
        )


@dataclass
class MountResult:
    success: bool
    message: str
    command: str
    fstab_entry: str


@dataclass
class TestResult:
    reachable: bool
    mountable: bool
    readable: bool
    message: str
    latency_ms: float


class MountManager:
    """Manages network mount configuration, testing, and execution."""

    def __init__(self, config_path: str = "/etc/markflow/mounts.json"):
        self.config_path = Path(config_path)

    # -- Command / fstab generation (pure, no side effects) --

    def generate_mount_command(self, config: MountConfig) -> str:
        """Generate the mount shell command for a config."""
        config.validate()
        rw_flag = "ro" if config.read_only else "rw"

        if config.protocol == "smb":
            opts = f"credentials={_SMB_CREDENTIALS_PATH},{rw_flag},iocharset=utf8,uid=1000,gid=1000,noperm,_netdev"
            return f"mount -t cifs //{config.server}/{config.share_path} {config.mount_point} -o {opts}"

        elif config.protocol == "nfsv3":
            opts = f"{rw_flag},hard,intr,_netdev"
            return f"mount -t nfs -o {opts} {config.server}:{config.share_path} {config.mount_point}"

        elif config.protocol == "nfsv4":
            opts = f"{rw_flag},hard,intr,_netdev"
            if config.kerberos:
                opts += ",sec=krb5"
            return f"mount -t nfs4 -o {opts} {config.server}:{config.share_path} {config.mount_point}"

        raise ValueError(f"Unknown protocol: {config.protocol}")

    def generate_fstab_entry(self, config: MountConfig) -> str:
        """Generate an /etc/fstab line for a config."""
        config.validate()
        rw_flag = "ro" if config.read_only else "rw"
        systemd_opts = "_netdev,x-systemd.automount,x-systemd.mount-timeout=30"

        if config.protocol == "smb":
            source = f"//{config.server}/{config.share_path}"
            opts = f"credentials={_SMB_CREDENTIALS_PATH},{rw_flag},iocharset=utf8,uid=1000,gid=1000,noperm,{systemd_opts}"
            return f"{source}  {config.mount_point}  cifs  {opts}  0  0"

        elif config.protocol == "nfsv3":
            source = f"{config.server}:{config.share_path}"
            opts = f"{rw_flag},hard,intr,{systemd_opts}"
            return f"{source}  {config.mount_point}  nfs  {opts}  0  0"

        elif config.protocol == "nfsv4":
            source = f"{config.server}:{config.share_path}"
            opts = f"{rw_flag},hard,intr,{systemd_opts}"
            if config.kerberos:
                opts += ",sec=krb5"
            return f"{source}  {config.mount_point}  nfs4  {opts}  0  0"

        raise ValueError(f"Unknown protocol: {config.protocol}")

    # -- Config persistence --

    def save_config(self, role: str, config: MountConfig) -> None:
        """Save mount config for a role ('source' or 'output') to JSON."""
        all_configs = self._load_config_raw()
        all_configs[role] = config.to_dict()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(all_configs, indent=2) + "\n")
        log.info("mount_config_saved", role=role, protocol=config.protocol)

    def load_config(self) -> dict[str, MountConfig]:
        """Load all mount configs from JSON. Returns empty dict if file missing."""
        raw = self._load_config_raw()
        result = {}
        for role, d in raw.items():
            try:
                result[role] = MountConfig.from_dict(d)
            except (KeyError, TypeError) as exc:
                log.warning("mount_config_parse_error", role=role, error=str(exc))
        return result

    def _load_config_raw(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {}

    # -- Live mount operations --

    def mount(self, config: MountConfig, dry_run: bool = False) -> MountResult:
        """Mount a share. If dry_run=True, return command without executing."""
        config.validate()
        cmd = self.generate_mount_command(config)
        fstab = self.generate_fstab_entry(config)

        if dry_run:
            return MountResult(
                success=True,
                message="Dry run — command generated but not executed",
                command=cmd,
                fstab_entry=fstab,
            )

        # Write SMB credentials file if needed
        if config.protocol == "smb" and config.smb_credentials:
            self._write_smb_credentials(config.smb_credentials)

        # Ensure mount point exists
        Path(config.mount_point).mkdir(parents=True, exist_ok=True)

        # Unmount first if already mounted
        self._unmount_quiet(config.mount_point)

        # Execute mount
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                log.info("mount_success", mount_point=config.mount_point, protocol=config.protocol)
                return MountResult(success=True, message="Mounted successfully", command=cmd, fstab_entry=fstab)
            else:
                error = result.stderr.strip() or result.stdout.strip() or "Unknown mount error"
                log.error("mount_failed", mount_point=config.mount_point, error=error)
                return MountResult(success=False, message=error, command=cmd, fstab_entry=fstab)
        except subprocess.TimeoutExpired:
            return MountResult(success=False, message="Mount timed out after 30 seconds", command=cmd, fstab_entry=fstab)
        except Exception as exc:
            return MountResult(success=False, message=str(exc), command=cmd, fstab_entry=fstab)

    def unmount(self, mount_point: str) -> bool:
        """Unmount a share. Returns True on success."""
        try:
            result = subprocess.run(
                ["umount", mount_point], capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _unmount_quiet(self, mount_point: str) -> None:
        """Unmount if mounted, ignore errors."""
        subprocess.run(["umount", mount_point], capture_output=True, timeout=10)

    def test_connection(self, config: MountConfig) -> TestResult:
        """Test a mount config by pinging the server and optionally doing a trial mount."""
        import os
        import tempfile

        config.validate()

        # Step 1: Check server reachability
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "3", config.server],
                capture_output=True, text=True, timeout=5,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            reachable = result.returncode == 0
        except Exception:
            latency_ms = (time.monotonic() - t0) * 1000
            reachable = False

        if not reachable:
            return TestResult(
                reachable=False, mountable=False, readable=False,
                message=f"Server {config.server} is not reachable",
                latency_ms=latency_ms,
            )

        # Step 2: Trial mount to a temp directory
        tmp_mount = tempfile.mkdtemp(prefix="markflow_mount_test_")
        test_config = MountConfig(
            protocol=config.protocol,
            server=config.server,
            share_path=config.share_path,
            mount_point=tmp_mount,
            read_only=True,  # always test as read-only
            smb_credentials=config.smb_credentials,
            kerberos=config.kerberos,
        )

        mount_result = self.mount(test_config)
        if not mount_result.success:
            self._cleanup_temp_mount(tmp_mount)
            return TestResult(
                reachable=True, mountable=False, readable=False,
                message=f"Server reachable but mount failed: {mount_result.message}",
                latency_ms=latency_ms,
            )

        # Step 3: Check readability
        try:
            entries = os.listdir(tmp_mount)
            readable = len(entries) > 0
            msg = f"Connected — {len(entries)} entries visible" if readable else "Mounted but share appears empty"
        except OSError as exc:
            readable = False
            msg = f"Mounted but cannot list contents: {exc}"

        # Cleanup
        self._cleanup_temp_mount(tmp_mount)

        return TestResult(
            reachable=True, mountable=True, readable=readable,
            message=msg, latency_ms=latency_ms,
        )

    def apply_to_fstab(self, config: MountConfig) -> bool:
        """Add or update fstab entry for this mount point. Returns True on success."""
        config.validate()
        new_entry = self.generate_fstab_entry(config)
        fstab_path = Path("/etc/fstab")

        try:
            lines = fstab_path.read_text().splitlines()
        except PermissionError:
            log.error("fstab_read_denied")
            return False

        # Remove existing entry for this mount point
        filtered = [
            line for line in lines
            if config.mount_point not in line or line.strip().startswith("#")
        ]
        filtered.append(new_entry)

        try:
            fstab_path.write_text("\n".join(filtered) + "\n")
            log.info("fstab_updated", mount_point=config.mount_point)
            return True
        except PermissionError:
            log.error("fstab_write_denied")
            return False

    def get_mount_status(self, mount_point: str) -> dict:
        """Check if a mount point is currently mounted and its filesystem type."""
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == mount_point:
                        return {"mounted": True, "fs_type": parts[2], "source": parts[0]}
        except (OSError, PermissionError):
            pass
        return {"mounted": False, "fs_type": None, "source": None}

    def _write_smb_credentials(self, creds: SMBCredentials) -> None:
        """Write SMB credentials to the system credentials file."""
        creds_content = f"username={creds.username}\npassword={creds.password}\n"
        creds_path = Path(_SMB_CREDENTIALS_PATH)
        try:
            creds_path.write_text(creds_content)
            creds_path.chmod(0o600)
        except PermissionError:
            log.warning("smb_credentials_write_denied", path=str(creds_path))

    def _cleanup_temp_mount(self, tmp_mount: str) -> None:
        """Unmount and remove temp mount directory."""
        self._unmount_quiet(tmp_mount)
        try:
            Path(tmp_mount).rmdir()
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_mount_manager.py -v`
Expected: All 12 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /opt/doc-conversion-2026
git add core/mount_manager.py tests/test_mount_manager.py
git commit -m "feat(mount): add MountManager with config models, fstab/command generation, and tests"
```

---

### Task 2: Mount Manager — Config Persistence Tests

**Files:**
- Modify: `tests/test_mount_manager.py`

- [ ] **Step 1: Add config persistence tests**

Append to `tests/test_mount_manager.py`:

```python
import json


class TestConfigPersistence:
    """Test save/load of mount configs to JSON."""

    def test_save_and_load_smb(self, tmp_path):
        config_file = tmp_path / "mounts.json"
        mgr = MountManager(config_path=str(config_file))

        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="storage_folder",
            mount_point="/mnt/source-share",
            read_only=True,
            smb_credentials=SMBCredentials(username="markflow", password="secret"),
        )
        mgr.save_config("source", cfg)

        loaded = mgr.load_config()
        assert "source" in loaded
        assert loaded["source"].protocol == "smb"
        assert loaded["source"].server == "192.168.1.17"
        assert loaded["source"].share_path == "storage_folder"
        assert loaded["source"].read_only is True

        # Password should NOT be in the JSON file
        raw = json.loads(config_file.read_text())
        assert "password" not in json.dumps(raw)
        assert "smb_username" in raw["source"]

    def test_save_and_load_nfsv4_kerberos(self, tmp_path):
        config_file = tmp_path / "mounts.json"
        mgr = MountManager(config_path=str(config_file))

        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
            kerberos=KerberosConfig(realm="EXAMPLE.COM", keytab_path="/etc/krb5.keytab"),
        )
        mgr.save_config("source", cfg)

        loaded = mgr.load_config()
        assert loaded["source"].protocol == "nfsv4"
        assert loaded["source"].kerberos is not None
        assert loaded["source"].kerberos.realm == "EXAMPLE.COM"

    def test_save_both_roles(self, tmp_path):
        config_file = tmp_path / "mounts.json"
        mgr = MountManager(config_path=str(config_file))

        source = MountConfig(
            protocol="nfsv3", server="10.0.0.1", share_path="/data",
            mount_point="/mnt/source-share", read_only=True,
        )
        output = MountConfig(
            protocol="smb", server="10.0.0.2", share_path="output",
            mount_point="/mnt/markflow-output", read_only=False,
            smb_credentials=SMBCredentials(username="user", password="pass"),
        )
        mgr.save_config("source", source)
        mgr.save_config("output", output)

        loaded = mgr.load_config()
        assert loaded["source"].protocol == "nfsv3"
        assert loaded["output"].protocol == "smb"

    def test_load_missing_file(self, tmp_path):
        config_file = tmp_path / "nonexistent.json"
        mgr = MountManager(config_path=str(config_file))
        loaded = mgr.load_config()
        assert loaded == {}
```

- [ ] **Step 2: Run tests**

Run: `cd /opt/doc-conversion-2026 && python -m pytest tests/test_mount_manager.py -v`
Expected: All 16 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /opt/doc-conversion-2026
git add tests/test_mount_manager.py
git commit -m "test(mount): add config persistence tests"
```

---

### Task 3: API Routes for Mount Config

**Files:**
- Create: `api/routes/mounts.py`
- Modify: `main.py` (add router include)

- [ ] **Step 1: Create the mounts API route module**

Create `api/routes/mounts.py`:

```python
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
```

- [ ] **Step 2: Register the router in main.py**

In `main.py`, add near the other route imports (around line 215-230):

```python
from api.routes import mounts as mounts_routes
```

And add after the last `app.include_router(...)` call (around line 299):

```python
app.include_router(mounts_routes.router)
```

- [ ] **Step 3: Run a quick smoke test**

Run: `cd /opt/doc-conversion-2026 && python -c "from api.routes.mounts import router; print('Router loaded:', router.prefix)"`
Expected: `Router loaded: /api/settings/mounts`

- [ ] **Step 4: Commit**

```bash
cd /opt/doc-conversion-2026
git add api/routes/mounts.py main.py
git commit -m "feat(mount): add REST API endpoints for mount config, test, and apply"
```

---

### Task 4: Settings UI — Storage Connections Section

**Files:**
- Modify: `static/settings.html` (insert new section before the closing `</form>`)

- [ ] **Step 1: Add the Storage Connections HTML section**

In `static/settings.html`, insert the following **before** line 995 (the `<!-- Actions -->` div with Save/Reset buttons). Find the `</details>` that closes the last settings section (around line 993) and add after it:

```html
      <!-- Storage Connections section -->
      <details class="settings-section" id="storage-connections-section">
      <summary>Storage Connections</summary>
      <div class="card">
        <p class="text-sm text-muted" style="margin:0 0 1rem">
          Configure network shares for source files and conversion output.
          Changes take effect immediately when you click Apply.
        </p>

        <!-- Source mount -->
        <fieldset style="border:1px solid var(--border);border-radius:6px;padding:1rem;margin-bottom:1.5rem">
          <legend style="font-weight:600;font-size:0.9rem;padding:0 0.5rem">
            Source Mount
            <span id="mount-status-source" class="text-sm" style="margin-left:0.5rem"></span>
          </legend>

          <div class="form-group">
            <label>Protocol</label>
            <div style="display:flex;gap:1.5rem;margin:0.25rem 0">
              <label><input type="radio" name="mount-source-proto" value="smb" checked onchange="toggleMountFields('source')"> SMB/CIFS</label>
              <label><input type="radio" name="mount-source-proto" value="nfsv3" onchange="toggleMountFields('source')"> NFSv3</label>
              <label><input type="radio" name="mount-source-proto" value="nfsv4" onchange="toggleMountFields('source')"> NFSv4</label>
            </div>
          </div>

          <div class="form-group">
            <label for="mount-source-server">Server (IP or hostname)</label>
            <input type="text" id="mount-source-server" placeholder="192.168.1.17">
          </div>

          <div class="form-group">
            <label for="mount-source-share">Share / Export Path</label>
            <input type="text" id="mount-source-share" placeholder="storage_folder or /volume1/data">
          </div>

          <div id="mount-source-smb-fields">
            <div class="form-group">
              <label for="mount-source-smb-user">Username</label>
              <input type="text" id="mount-source-smb-user" placeholder="markflow">
            </div>
            <div class="form-group">
              <label for="mount-source-smb-pass">Password</label>
              <input type="password" id="mount-source-smb-pass" placeholder="********">
            </div>
          </div>

          <div id="mount-source-krb-fields" hidden>
            <div class="form-group">
              <label class="toggle" style="gap:0.5rem">
                <input type="checkbox" id="mount-source-krb-enable" onchange="toggleKerberosFields('source')">
                <span class="toggle-track"></span>
                <span>Enable Kerberos authentication</span>
              </label>
            </div>
            <div id="mount-source-krb-details" hidden>
              <div class="form-group">
                <label for="mount-source-krb-realm">Realm</label>
                <input type="text" id="mount-source-krb-realm" placeholder="EXAMPLE.COM">
              </div>
              <div class="form-group">
                <label for="mount-source-krb-keytab">Keytab Path</label>
                <input type="text" id="mount-source-krb-keytab" value="/etc/krb5.keytab">
              </div>
            </div>
          </div>

          <div style="display:flex;gap:0.5rem;align-items:center;margin-top:0.75rem">
            <button type="button" class="btn btn-ghost btn-sm" onclick="testMount('source')">Test Connection</button>
            <button type="button" class="btn btn-primary btn-sm" onclick="applyMount('source')">Apply &amp; Remount</button>
            <span id="mount-source-result" class="text-sm" style="margin-left:0.5rem"></span>
          </div>
        </fieldset>

        <!-- Output mount -->
        <fieldset style="border:1px solid var(--border);border-radius:6px;padding:1rem">
          <legend style="font-weight:600;font-size:0.9rem;padding:0 0.5rem">
            Output Mount
            <span id="mount-status-output" class="text-sm" style="margin-left:0.5rem"></span>
          </legend>

          <div class="form-group">
            <label>Protocol</label>
            <div style="display:flex;gap:1.5rem;margin:0.25rem 0">
              <label><input type="radio" name="mount-output-proto" value="smb" checked onchange="toggleMountFields('output')"> SMB/CIFS</label>
              <label><input type="radio" name="mount-output-proto" value="nfsv3" onchange="toggleMountFields('output')"> NFSv3</label>
              <label><input type="radio" name="mount-output-proto" value="nfsv4" onchange="toggleMountFields('output')"> NFSv4</label>
            </div>
          </div>

          <div class="form-group">
            <label for="mount-output-server">Server (IP or hostname)</label>
            <input type="text" id="mount-output-server" placeholder="192.168.1.17">
          </div>

          <div class="form-group">
            <label for="mount-output-share">Share / Export Path</label>
            <input type="text" id="mount-output-share" placeholder="markflow or /volume1/markflow">
          </div>

          <div id="mount-output-smb-fields">
            <div class="form-group">
              <label for="mount-output-smb-user">Username</label>
              <input type="text" id="mount-output-smb-user" placeholder="markflow">
            </div>
            <div class="form-group">
              <label for="mount-output-smb-pass">Password</label>
              <input type="password" id="mount-output-smb-pass" placeholder="********">
            </div>
          </div>

          <div id="mount-output-krb-fields" hidden>
            <div class="form-group">
              <label class="toggle" style="gap:0.5rem">
                <input type="checkbox" id="mount-output-krb-enable" onchange="toggleKerberosFields('output')">
                <span class="toggle-track"></span>
                <span>Enable Kerberos authentication</span>
              </label>
            </div>
            <div id="mount-output-krb-details" hidden>
              <div class="form-group">
                <label for="mount-output-krb-realm">Realm</label>
                <input type="text" id="mount-output-krb-realm" placeholder="EXAMPLE.COM">
              </div>
              <div class="form-group">
                <label for="mount-output-krb-keytab">Keytab Path</label>
                <input type="text" id="mount-output-krb-keytab" value="/etc/krb5.keytab">
              </div>
            </div>
          </div>

          <div style="display:flex;gap:0.5rem;align-items:center;margin-top:0.75rem">
            <button type="button" class="btn btn-ghost btn-sm" onclick="testMount('output')">Test Connection</button>
            <button type="button" class="btn btn-primary btn-sm" onclick="applyMount('output')">Apply &amp; Remount</button>
            <span id="mount-output-result" class="text-sm" style="margin-left:0.5rem"></span>
          </div>
        </fieldset>
      </div>

      </details>
```

- [ ] **Step 2: Add the JavaScript for mount operations**

In the `<script>` block of `settings.html` (after line 1016), add the following functions before the closing `</script>` tag:

```javascript
    // -- Storage Connections --

    function toggleMountFields(role) {
      const proto = document.querySelector('input[name="mount-' + role + '-proto"]:checked').value;
      const smbFields = document.getElementById('mount-' + role + '-smb-fields');
      const krbFields = document.getElementById('mount-' + role + '-krb-fields');

      smbFields.hidden = proto !== 'smb';
      krbFields.hidden = proto !== 'nfsv4';

      if (proto !== 'nfsv4') {
        document.getElementById('mount-' + role + '-krb-enable').checked = false;
        toggleKerberosFields(role);
      }
    }

    function toggleKerberosFields(role) {
      const enabled = document.getElementById('mount-' + role + '-krb-enable').checked;
      document.getElementById('mount-' + role + '-krb-details').hidden = !enabled;
    }

    function getMountConfig(role) {
      const proto = document.querySelector('input[name="mount-' + role + '-proto"]:checked').value;
      const config = {
        protocol: proto,
        server: document.getElementById('mount-' + role + '-server').value.trim(),
        share_path: document.getElementById('mount-' + role + '-share').value.trim(),
        mount_point: role === 'source' ? '/mnt/source-share' : '/mnt/markflow-output',
        read_only: role === 'source',
      };

      if (proto === 'smb') {
        config.smb_username = document.getElementById('mount-' + role + '-smb-user').value.trim();
        config.smb_password = document.getElementById('mount-' + role + '-smb-pass').value;
      }

      if (proto === 'nfsv4') {
        config.nfs_kerberos = document.getElementById('mount-' + role + '-krb-enable').checked;
        if (config.nfs_kerberos) {
          config.kerberos_realm = document.getElementById('mount-' + role + '-krb-realm').value.trim();
          config.kerberos_keytab = document.getElementById('mount-' + role + '-krb-keytab').value.trim();
        }
      }

      return config;
    }

    function showMountResult(role, msg, ok) {
      var el = document.getElementById('mount-' + role + '-result');
      el.textContent = msg;
      el.style.color = ok ? 'var(--ok)' : 'var(--error)';
      setTimeout(function() { el.textContent = ''; }, 8000);
    }

    async function testMount(role) {
      var config = getMountConfig(role);
      showMountResult(role, 'Testing...', true);
      try {
        var res = await fetch('/api/settings/mounts/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        var data = await res.json();
        if (res.ok) {
          var icon = data.readable ? '\u2705' : data.mountable ? '\u26a0\ufe0f' : '\u274c';
          showMountResult(role, icon + ' ' + data.message + ' (' + data.latency_ms + 'ms)', data.readable);
        } else {
          showMountResult(role, data.detail || 'Test failed', false);
        }
      } catch (err) {
        showMountResult(role, 'Error: ' + err.message, false);
      }
    }

    async function applyMount(role) {
      var config = getMountConfig(role);
      if (!config.server || !config.share_path) {
        showMountResult(role, 'Server and share path are required', false);
        return;
      }
      showMountResult(role, 'Applying...', true);
      try {
        var res = await fetch('/api/settings/mounts/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role: role, config: config }),
        });
        var data = await res.json();
        if (res.ok && data.success) {
          showMountResult(role, '\u2705 Mounted and saved', true);
          loadMountStatus();
        } else {
          showMountResult(role, data.message || data.detail || 'Apply failed', false);
        }
      } catch (err) {
        showMountResult(role, 'Error: ' + err.message, false);
      }
    }

    async function loadMountStatus() {
      try {
        var res = await fetch('/api/settings/mounts');
        if (!res.ok) return;
        var data = await res.json();

        var roles = ['source', 'output'];
        for (var i = 0; i < roles.length; i++) {
          var role = roles[i];
          var info = data[role];
          var statusEl = document.getElementById('mount-status-' + role);
          if (!info) {
            statusEl.textContent = '\u25cb not configured';
            statusEl.style.color = 'var(--text-muted)';
            continue;
          }

          if (info.mounted) {
            statusEl.textContent = '\u25cf mounted (' + info.fs_type + ')';
            statusEl.style.color = 'var(--ok)';
          } else {
            statusEl.textContent = '\u25cf not mounted';
            statusEl.style.color = 'var(--error)';
          }

          // Populate form fields from saved config
          var protoRadio = document.querySelector('input[name="mount-' + role + '-proto"][value="' + info.protocol + '"]');
          if (protoRadio) {
            protoRadio.checked = true;
            toggleMountFields(role);
          }
          document.getElementById('mount-' + role + '-server').value = info.server || '';
          document.getElementById('mount-' + role + '-share').value = info.share_path || '';

          if (info.protocol === 'smb' && info.smb_username) {
            document.getElementById('mount-' + role + '-smb-user').value = info.smb_username;
          }
          if (info.protocol === 'nfsv4' && info.nfs_kerberos) {
            document.getElementById('mount-' + role + '-krb-enable').checked = true;
            toggleKerberosFields(role);
            if (info.kerberos_realm) document.getElementById('mount-' + role + '-krb-realm').value = info.kerberos_realm;
            if (info.kerberos_keytab) document.getElementById('mount-' + role + '-krb-keytab').value = info.kerberos_keytab;
          }
        }
      } catch (err) {
        console.warn('Failed to load mount status:', err);
      }
    }

    // Load mount status on page load
    loadMountStatus();
```

- [ ] **Step 3: Verify the page loads**

Run: `curl -s http://localhost:8000/settings.html | grep -c 'Storage Connections'`
Expected: `1`

- [ ] **Step 4: Commit**

```bash
cd /opt/doc-conversion-2026
git add static/settings.html
git commit -m "feat(mount): add Storage Connections section to Settings UI"
```

---

### Task 5: Setup Script — Protocol Selection

**Files:**
- Modify: `Scripts/proxmox/setup-markflow.sh`

- [ ] **Step 1: Replace the hardcoded SMB section with protocol selection**

In `Scripts/proxmox/setup-markflow.sh`, replace section 4 (lines 76-106 approximately — from the comment `# Set up SMB/CIFS mounts` through `sudo mount -a`) with the new protocol-aware section. See the spec at `docs/superpowers/specs/2026-04-05-nfs-mount-support-design.md` for the setup script flow.

The new section should:
1. Prompt for source share protocol (1=SMB, 2=NFSv3, 3=NFSv4)
2. Prompt for output share protocol
3. Install `nfs-common` if any NFS protocol selected
4. Prompt for Kerberos config if NFSv4 selected (install `krb5-user` if yes)
5. Prompt for server, share path for each mount
6. Only create SMB credentials file if SMB is selected
7. Generate appropriate fstab entries using a helper function
8. Write `/etc/markflow/mounts.json` config file
9. Run `mount -a`

- [ ] **Step 2: Sync the canonical copy to ~/setup-markflow.sh**

```bash
cp /opt/doc-conversion-2026/Scripts/proxmox/setup-markflow.sh ~/setup-markflow.sh
```

- [ ] **Step 3: Commit**

```bash
cd /opt/doc-conversion-2026
git add Scripts/proxmox/setup-markflow.sh
git commit -m "feat(mount): add NFS protocol selection to setup script"
```

---

### Task 6: Dockerfile — Add nfs-common Package

**Files:**
- Modify: `Dockerfile.base`

- [ ] **Step 1: Read the current Dockerfile.base**

Read `Dockerfile.base` and find the `apt-get install` block.

- [ ] **Step 2: Add nfs-common to the package list**

Add `nfs-common` to the existing `apt-get install` line in `Dockerfile.base`. Find the main package install block and add `nfs-common \` to the list.

- [ ] **Step 3: Commit**

```bash
cd /opt/doc-conversion-2026
git add Dockerfile.base
git commit -m "feat(mount): add nfs-common to base image for NFS mount support"
```

---

### Task 7: Version Bump, Docs Update, Final Commit

**Files:**
- Modify: `core/version.py`
- Modify: `CLAUDE.md`
- Modify: `docs/version-history.md`

- [ ] **Step 1: Bump version**

In `core/version.py`, change `__version__` to `"0.20.0"`.

- [ ] **Step 2: Add version history entry**

Add to top of `docs/version-history.md` (after the `---`):

```markdown
## v0.20.0 — NFS Mount Support + Mount Settings UI (2026-04-05)

**Feature:** Network mount configuration is no longer hardcoded to SMB/CIFS. MarkFlow
now supports SMB/CIFS, NFSv3, and NFSv4 (with optional Kerberos) as mount protocols.

**New components:**
- `core/mount_manager.py` — Protocol-agnostic mount abstraction. Generates mount commands
  and fstab entries, handles live mount/unmount, tests connections, persists config to
  `/etc/markflow/mounts.json`. Supports `dry_run=True` for config-generation mode.
- `api/routes/mounts.py` — REST endpoints: GET status, POST test, POST apply.
- Settings UI "Storage Connections" section — radio buttons for protocol, conditional
  SMB credentials / NFSv4 Kerberos fields, test and apply buttons.
- Setup script protocol selection — choose SMB/NFSv3/NFSv4 during initial VM provisioning.

**Files changed:**
- `core/mount_manager.py` — NEW
- `api/routes/mounts.py` — NEW
- `tests/test_mount_manager.py` — NEW
- `static/settings.html` — Storage Connections section
- `Scripts/proxmox/setup-markflow.sh` — protocol selection menu
- `Dockerfile.base` — added `nfs-common` package
- `main.py` — register mounts router
- `core/version.py` — bump to 0.20.0
```

- [ ] **Step 3: Update CLAUDE.md current status**

Replace the "Current Status" section heading and first paragraph with v0.20.0 info, push v0.19.6.11 to "Previous".

- [ ] **Step 4: Commit and push**

```bash
cd /opt/doc-conversion-2026
git add core/version.py CLAUDE.md docs/version-history.md
git commit -m "feat: NFS mount support with settings UI (v0.20.0)"
git push
```

---

### Task 8: Rebuild, Deploy, Verify

**Files:** None (operational)

- [ ] **Step 1: Rebuild base image (adds nfs-common)**

```bash
cd /opt/doc-conversion-2026
docker build -f Dockerfile.base -t markflow-base:latest .
```

Note: This is slow (base image rebuild). Only needed because we added `nfs-common`.

- [ ] **Step 2: Refresh container**

```bash
~/refresh-markflow.sh
```

- [ ] **Step 3: Verify API endpoint**

```bash
curl -s http://localhost:8000/api/settings/mounts | python3 -m json.tool
```

Expected: JSON with `source` and `output` keys (may be null if no config exists yet).

- [ ] **Step 4: Verify Settings UI**

Open `http://<VM_IP>:8000/settings.html` in browser. Scroll to "Storage Connections" section. Verify:
- Radio buttons switch between SMB/NFSv3/NFSv4
- SMB fields show for SMB, Kerberos fields show for NFSv4
- Test Connection and Apply buttons are present

- [ ] **Step 5: Run test suite**

```bash
cd /opt/doc-conversion-2026
python -m pytest tests/test_mount_manager.py -v
```

Expected: All tests pass.
