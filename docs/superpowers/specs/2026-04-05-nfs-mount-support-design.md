# NFS Protocol Support + Mount Settings UI

**Date:** 2026-04-05
**Version:** 0.20.0 (target)
**Status:** Approved

---

## Problem

MarkFlow only supports SMB/CIFS mounts, hardcoded in setup scripts. Users with
Linux-native NAS setups (TrueNAS, Synology with NFS exports, plain Linux servers)
must manually configure NFS outside of MarkFlow. There is no UI to change mount
configuration after initial setup.

## Goals

1. Add NFS (v3 and v4) as a mount protocol option alongside SMB/CIFS
2. NFSv4 optionally supports Kerberos authentication (breakout UI when selected)
3. Mount config available in setup script (initial provisioning) AND settings UI (runtime)
4. Live remounting from the UI, structured so config-generation mode is a flag flip
5. Persist mount config to `/etc/markflow/mounts.json`; passwords stay in credentials files

## Non-Goals

- iSCSI, WebDAV, S3/FUSE, SSHFS support (not needed for bulk file scanning)
- Automatic NAS discovery (mDNS/Avahi) — user provides server IP
- Multi-NAS support (still two mounts: source + output)

---

## Architecture

### New Components

| Component | Purpose |
|-----------|---------|
| `core/mount_manager.py` | Mount abstraction: config model, mount/unmount/test, fstab generation |
| `tools/markflow-mount-helper.sh` | Host-side privileged helper for mount operations |
| `api/routes/mounts.py` | REST endpoints for mount config, test, apply |
| `static/settings.html` (modified) | New "Storage Connections" section |
| `setup-markflow.sh` (modified) | Protocol selection during initial setup |
| `Scripts/proxmox/setup-markflow.sh` (modified) | Canonical copy of setup script |

### Mount Manager (`core/mount_manager.py`)

```python
@dataclass
class SMBCredentials:
    username: str
    password: str  # only used transiently; written to credentials file, not stored in memory

@dataclass
class KerberosConfig:
    realm: str           # e.g. "EXAMPLE.COM"
    keytab_path: str     # e.g. "/etc/krb5.keytab"

@dataclass
class MountConfig:
    protocol: Literal["smb", "nfsv3", "nfsv4"]
    server: str
    share_path: str
    mount_point: str
    read_only: bool
    smb_credentials: SMBCredentials | None = None   # SMB only
    kerberos: KerberosConfig | None = None          # NFSv4 only
    extra_options: dict[str, str] = field(default_factory=dict)

@dataclass
class MountResult:
    success: bool
    message: str
    command: str         # the mount command that was/would be run
    fstab_entry: str     # the fstab line that was/would be written

@dataclass
class TestResult:
    reachable: bool      # server responds
    mountable: bool      # mount succeeded to temp path
    readable: bool       # at least one entry in mounted dir
    message: str
    latency_ms: float

class MountManager:
    def __init__(self, config_path: str = "/etc/markflow/mounts.json"):
        self.config_path = Path(config_path)

    def mount(self, config: MountConfig, dry_run: bool = False) -> MountResult: ...
    def unmount(self, mount_point: str) -> bool: ...
    def test_connection(self, config: MountConfig) -> TestResult: ...
    def get_active_mounts(self) -> dict[str, MountConfig]: ...   # "source"/"output" keys
    def generate_fstab_entry(self, config: MountConfig) -> str: ...
    def apply_to_fstab(self, config: MountConfig) -> bool: ...
    def save_config(self, role: str, config: MountConfig) -> None: ...  # role = "source"|"output"
    def load_config(self) -> dict[str, MountConfig]: ...
```

**Mount command generation by protocol:**

| Protocol | Command |
|----------|---------|
| SMB | `mount -t cifs //server/share /mnt/point -o credentials=/etc/markflow-smb-credentials,ro,iocharset=utf8,uid=1000,gid=1000,noperm,_netdev` |
| NFSv3 | `mount -t nfs -o ro,hard,intr,_netdev server:/export /mnt/point` |
| NFSv4 | `mount -t nfs4 -o ro,hard,intr,_netdev server:/export /mnt/point` |
| NFSv4+Krb | `mount -t nfs4 -o ro,hard,intr,_netdev,sec=krb5 server:/export /mnt/point` |

**fstab entry generation by protocol:**

| Protocol | fstab line |
|----------|-----------|
| SMB | `//server/share  /mnt/point  cifs  credentials=/etc/markflow-smb-credentials,ro,iocharset=utf8,uid=1000,gid=1000,noperm,_netdev,x-systemd.automount,x-systemd.mount-timeout=30  0  0` |
| NFSv3 | `server:/export  /mnt/point  nfs  ro,hard,intr,_netdev,x-systemd.automount,x-systemd.mount-timeout=30  0  0` |
| NFSv4 | `server:/export  /mnt/point  nfs4  ro,hard,intr,_netdev,x-systemd.automount,x-systemd.mount-timeout=30  0  0` |
| NFSv4+Krb | `server:/export  /mnt/point  nfs4  ro,hard,intr,_netdev,sec=krb5,x-systemd.automount,x-systemd.mount-timeout=30  0  0` |

**`dry_run` mode:** When `dry_run=True`, `mount()` returns the `MountResult` with
`command` and `fstab_entry` populated but does not execute anything. This is the
future config-generation path — flip the flag and the same code produces output
for manual application.

### Host Privilege Strategy

Containers cannot run `mount` without elevated privileges. Two modes:

**Mode 1 — Mount helper (recommended):**
`tools/markflow-mount-helper.sh` runs on the host with root privileges. The
container communicates via a bind-mounted Unix socket at `/var/run/markflow-mount.sock`.
The helper validates commands (only allows `mount`/`umount` to `/mnt/source*` and
`/mnt/*output*` paths) and executes them.

**Mode 2 — Privileged container (simpler, less secure):**
Container runs with `--cap-add SYS_ADMIN --device /dev/fuse`. Mount operations
execute directly inside the container. Setup script asks which mode during install.

`MountManager` auto-detects which mode is available:
1. Check for mount helper socket → use helper
2. Check for `SYS_ADMIN` capability → mount directly
3. Neither → `dry_run` mode only, return commands for manual execution

### API Endpoints (`api/routes/mounts.py`)

```
GET  /api/settings/mounts
  → { "source": { MountConfig + status }, "output": { MountConfig + status } }

POST /api/settings/mounts/test
  body: { MountConfig fields }
  → { TestResult }

POST /api/settings/mounts/apply
  body: { "role": "source"|"output", ...MountConfig fields }
  → { MountResult }
  Side effects: remounts share, updates fstab, saves to mounts.json
```

All endpoints require admin auth (existing auth middleware).

### Settings UI

New "Storage Connections" section appended to the existing Settings page
(`static/settings.html`).

```
┌─ Storage Connections ─────────────────────────────────────────┐
│                                                               │
│  Source Mount (/mnt/source)                        [mounted ●]│
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Protocol:  ( ) SMB/CIFS  ( ) NFSv3  ( ) NFSv4           │ │
│  │ Server:    [192.168.1.17          ]                      │ │
│  │ Share:     [storage_folder        ]                      │ │
│  │                                                          │ │
│  │ ── SMB Credentials ─── (shown when SMB selected)         │ │
│  │ Username:  [markflow              ]                      │ │
│  │ Password:  [••••••••              ]                      │ │
│  │                                                          │ │
│  │ ── Kerberos ────────── (shown when NFSv4 selected)       │ │
│  │ ☐ Enable Kerberos authentication                         │ │
│  │   Realm:   [EXAMPLE.COM           ]  (shown when checked)│ │
│  │   Keytab:  [/etc/krb5.keytab      ]  (shown when checked)│ │
│  │                                                          │ │
│  │ [Test Connection]  [Apply & Remount]                      │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  Output Mount (/mnt/output)                       [mounted ●] │
│  │ (identical fields)                                       │ │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

- Radio buttons for protocol toggle show/hide relevant credential sections
- NFSv4 Kerberos checkbox is a breakout — reveals realm + keytab fields
- "Test Connection" calls `POST /api/settings/mounts/test`, shows inline result
- "Apply & Remount" calls `POST /api/settings/mounts/apply`, shows success/error
- Mount status indicator (green dot / red dot) pulled from `GET /api/settings/mounts`

### Setup Script Changes

`setup-markflow.sh` gains an interactive protocol menu:

```bash
echo "Select mount protocol for SOURCE share:"
echo "  1) SMB/CIFS (Windows/Samba shares)"
echo "  2) NFSv3 (Linux NFS exports)"
echo "  3) NFSv4 (Linux NFS v4 exports)"
read -p "Choice [1]: " PROTO_CHOICE

case $PROTO_CHOICE in
  2) # NFSv3
     read -p "NFS server IP/hostname: " NFS_SERVER
     read -p "Export path (e.g. /volume1/storage): " NFS_EXPORT
     # Write nfs fstab entry
     ;;
  3) # NFSv4
     read -p "NFS server IP/hostname: " NFS_SERVER
     read -p "Export path: " NFS_EXPORT
     read -p "Enable Kerberos? [y/N]: " KRB_ENABLE
     if [ "$KRB_ENABLE" = "y" ]; then
       read -p "Kerberos realm: " KRB_REALM
       read -p "Keytab path [/etc/krb5.keytab]: " KRB_KEYTAB
     fi
     ;;
  *) # SMB (default, existing flow)
     ;;
esac
```

Same flow repeated for OUTPUT share. Writes `mounts.json` after both are configured.

### Package Dependencies

Added to `Dockerfile.base`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    nfs-common \
    && rm -rf /var/lib/apt/lists/*
```

Kerberos packages (`krb5-user`) installed conditionally by setup script on the host
VM only (not in the container — Kerberos auth happens at the kernel/mount level).

### Config Persistence (`/etc/markflow/mounts.json`)

```json
{
  "source": {
    "protocol": "smb",
    "server": "192.168.1.17",
    "share_path": "storage_folder",
    "mount_point": "/mnt/source-share",
    "read_only": true,
    "smb_username": "markflow"
  },
  "output": {
    "protocol": "nfsv4",
    "server": "192.168.1.17",
    "share_path": "/volume1/markflow",
    "mount_point": "/mnt/markflow-output",
    "read_only": false,
    "nfs_kerberos": false
  }
}
```

- Passwords never stored in JSON — SMB passwords in `/etc/markflow-smb-credentials`
- Kerberos keytab path is stored; the keytab file itself is managed externally
- Config file created by setup script, updated by settings UI

### Integration with Existing Code

- `core/storage_probe.py` already detects NFS mounts via `/proc/mounts` — no changes needed
- `core/health.py` drive checks work on any mounted filesystem — no changes needed
- `core/bulk_scanner.py` `verify_source_mount()` checks path existence + readability — protocol-agnostic, no changes needed
- Docker compose volume mounts use host paths that are already protocol-agnostic

### Error Handling

- **Server unreachable:** `test_connection` pings server first, reports latency or timeout
- **Export not found:** Mount fails with clear "export path not found" message
- **Permission denied (NFS):** Reports that the server export ACL needs the client IP
- **Kerberos failure:** Reports ticket/keytab issues with actionable message
- **Mount helper unavailable:** Falls back to dry_run mode, shows commands to run manually
- **Active scan during remount:** Refuses to remount if a bulk job is running

### Testing

- Unit tests for `MountManager.generate_fstab_entry()` and command generation (no root needed)
- Unit tests for `MountConfig` validation (bad IPs, empty paths, conflicting options)
- Integration test for `test_connection` against a mock mount helper
- Manual test checklist: SMB→NFS migration, NFS→SMB migration, Kerberos toggle

---

## Files Changed Summary

| File | Change |
|------|--------|
| `core/mount_manager.py` | NEW — mount abstraction layer |
| `api/routes/mounts.py` | NEW — REST endpoints |
| `tools/markflow-mount-helper.sh` | NEW — host-side privileged helper |
| `static/settings.html` | ADD — Storage Connections section |
| `setup-markflow.sh` | MODIFY — protocol selection menu |
| `Scripts/proxmox/setup-markflow.sh` | MODIFY — canonical copy |
| `Dockerfile.base` | MODIFY — add `nfs-common` package |
| `core/version.py` | MODIFY — bump version |
