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
    # Universal Storage Manager — optional human-readable label for the share.
    # Legacy "source"/"output" roles leave this as None (the role is the name).
    # Named shares in /mnt/shares/<name> use this to round-trip the display label.
    display_name: str | None = None

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
        if self.display_name:
            d["display_name"] = self.display_name
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
            display_name=d.get("display_name"),
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


# -- mounts.json schema migration --
#
# v1 (flat, pre-Universal Storage Manager):
#     {"source": {...mountcfg...}, "output": {...mountcfg...}}
#
# v2 (Universal Storage Manager):
#     {"_schema_version": 2,
#      "shares": {"source": {...}, "output": {...}, "nas-docs": {...}, ...}}
#
# v1 role-keys (source / output) become entries under shares. The migration
# is idempotent: passing a v2 dict returns it unchanged.

_MOUNTS_SCHEMA_VERSION = 2


def _migrate_mounts_json(raw: dict) -> dict:
    """v1 (flat) -> v2 (shares dict). v1 entries with known roles become named shares."""
    if not isinstance(raw, dict):
        return {"_schema_version": _MOUNTS_SCHEMA_VERSION, "shares": {}}
    if raw.get("_schema_version") == _MOUNTS_SCHEMA_VERSION:
        return raw
    shares: dict[str, dict] = {}
    for role, cfg in raw.items():
        if isinstance(role, str) and role.startswith("_"):
            continue
        if isinstance(cfg, dict) and cfg:
            shares[role] = cfg
    return {"_schema_version": _MOUNTS_SCHEMA_VERSION, "shares": shares}


class MountManager:
    """Manages network mount configuration, testing, and execution."""

    SHARES_ROOT = "/mnt/shares"

    def __init__(self, config_path: str = "/etc/markflow/mounts.json"):
        self.config_path = Path(config_path)

    # -- Named-share mount-point helpers (Universal Storage Manager) --

    @staticmethod
    def share_mount_point(name: str) -> str:
        """Compute mount point for a named share.

        Name is sanitized to a safe path segment: only [A-Za-z0-9_-] survives,
        and leading/trailing '-' / '_' are stripped. Raises ValueError if the
        sanitized name is empty (e.g. from '///' or whitespace-only input).
        """
        if not isinstance(name, str):
            raise ValueError(f"invalid share name: {name!r}")
        safe = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip("-_")
        if not safe:
            raise ValueError(f"invalid share name: {name!r}")
        return f"{MountManager.SHARES_ROOT}/{safe}"

    def mount_named(self, name: str, config: MountConfig, dry_run: bool = False) -> MountResult:
        """Mount a named share at /mnt/shares/<name>.

        Overrides config.mount_point with the canonical /mnt/shares/<name> path
        and reuses the existing mount() path. Creates the mount point if needed
        (only when dry_run=False — dry_run stays side-effect-free so it can be
        called from unit tests on hosts where /mnt is read-only).
        """
        mount_point = self.share_mount_point(name)
        # Override the supplied config's mount_point so all downstream
        # validation / command generation / fstab use the canonical path.
        config.mount_point = mount_point
        if not config.display_name:
            config.display_name = name
        if not dry_run:
            Path(mount_point).mkdir(parents=True, exist_ok=True)
        return self.mount(config, dry_run=dry_run)

    def unmount_named(self, name: str) -> bool:
        """Unmount a named share by logical name (resolves to /mnt/shares/<name>)."""
        mount_point = self.share_mount_point(name)
        return self.unmount(mount_point)

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
    #
    # On disk, the file is always written in v2 schema:
    #     {"_schema_version": 2, "shares": {name: {...cfg...}, ...}}
    # v1 files (flat {role: cfg}) are auto-migrated on first read.
    # The public save_config(name, cfg) / load_config() API is unchanged:
    # it still takes/returns a flat mapping of share-name -> MountConfig,
    # so existing callers (api/routes/mounts.py iterating "source"/"output")
    # keep working.

    def save_config(self, name: str, config: MountConfig) -> None:
        """Save mount config under a share name (e.g. 'source', 'output', 'nas-docs')."""
        doc = self._load_config_v2()
        shares = doc.setdefault("shares", {})
        shares[name] = config.to_dict()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(doc, indent=2) + "\n")
        log.info("mount_config_saved", name=name, protocol=config.protocol)

    def load_config(self) -> dict[str, MountConfig]:
        """Load all mount configs from JSON. Returns empty dict if file missing.

        Returns a flat mapping {share_name: MountConfig}. v1 files are
        auto-migrated to v2 on read (but not rewritten to disk until the
        next save_config call).
        """
        doc = self._load_config_v2()
        result: dict[str, MountConfig] = {}
        for name, d in doc.get("shares", {}).items():
            try:
                result[name] = MountConfig.from_dict(d)
            except (KeyError, TypeError) as exc:
                log.warning("mount_config_parse_error", name=name, error=str(exc))
        return result

    def save_named(self, name: str, config: MountConfig) -> None:
        """Alias for save_config() — more natural when working with named shares."""
        self.save_config(name, config)

    def _load_config_v2(self) -> dict:
        """Load the mounts.json document, migrating v1 -> v2 in memory if needed."""
        return _migrate_mounts_json(self._load_config_raw())

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

        # Step 1: Check server reachability via TCP socket probe.
        # We try the protocol-appropriate port instead of ping because
        # the container image doesn't ship the ping binary.
        import socket

        port = {"smb": 445, "nfsv3": 2049, "nfsv4": 2049}.get(config.protocol, 2049)
        t0 = time.monotonic()
        try:
            sock = socket.create_connection((config.server, port), timeout=3)
            sock.close()
            latency_ms = (time.monotonic() - t0) * 1000
            reachable = True
        except (OSError, socket.timeout):
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
