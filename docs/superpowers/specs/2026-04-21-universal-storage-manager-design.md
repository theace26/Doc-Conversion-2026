# Universal Storage Manager — Design Spec

**Date:** 2026-04-21
**Status:** Approved
**Phases:** 3 (independently shippable)
**Estimated scope:** ~4,000 lines across ~20 files

---

## Problem

MarkFlow requires users to manually edit `.env` and `docker-compose.yml` to
configure storage paths before the container starts. This creates a barrier for
non-technical users who don't understand Docker, container paths, or volume
mounts. Network shares require knowing IP addresses, protocols, and share
names. There is no first-run guidance — the user must already know what to do.

Storage configuration is also fragmented across multiple UI locations:
Locations, NFS Mounts, and Cloud Prefetch sections on the Settings page, plus
the Bulk Convert page source/output fields, plus the `.env` file.

## Solution

A Universal Storage Manager that lets users browse the host filesystem and
network shares entirely from the MarkFlow web GUI, with:

- Auto-detection of host OS (Windows, WSL, Linux, macOS)
- OS-native file browser view with raw tree fallback
- Network share discovery (SMB/NFS scan) + manual entry
- Encrypted credential storage with auto-remount on restart
- Path validation (exists, readable, writable, disk space)
- First-run setup wizard for day-one onboarding
- Persistent restart notification when changes require container restart
- Consolidated Storage page replacing fragmented Settings sections

---

## Architecture

Three layers:

```
PRESENTATION ─── Storage page + first-run wizard overlay
                 Filesystem browser, network discovery UI,
                 source/output selection, credential management,
                 restart notification banner

SERVICE ──────── core/storage_manager.py (orchestrator)
                 core/host_detector.py (OS detection + quick access)
                 core/credential_store.py (Fernet encryption)
                 core/mount_manager.py (extended: multi-mount, discovery)
                 api/routes/storage.py (new consolidated API)

DOCKER ───────── Broad mounts in docker-compose.yml:
                   /:/host/root:ro    (browse everything, read-only)
                   /:/host/rw         (write to configured output only)
                 cap_add: SYS_ADMIN   (runtime NFS/SMB mounts)
                 Runtime mounts at /mnt/shares/<name>
```

**Key principle:** Docker provides broad access. The application layer
restricts what gets used. All write operations are guarded at the code level
to the configured output path only — enforced in `converter.py` and
`bulk_worker.py`.

---

## Component Designs

### 1. Docker Layer Changes

**docker-compose.yml** additions:

```yaml
volumes:
  - /:/host/root:ro          # Read-only browse of entire host filesystem
  - /:/host/rw               # Writable — app-level guard restricts to output dir
  # Existing mounts retained for backward compatibility:
  - ${SOURCE_DIR:-/tmp/markflow-nosource}:/mnt/source:ro
  - ${OUTPUT_DIR:-./output}:/mnt/output-repo

cap_add:
  - SYS_ADMIN                # Required for runtime NFS/SMB mounts
```

**Dockerfile.base** additions:

```dockerfile
# Network share discovery + mounting
smbclient \
cifs-utils \
```

(`nfs-common` is already installed.)

**Backward compatibility:** Existing `DRIVE_C`, `DRIVE_D`, `MOUNTED_DRIVES`,
`SOURCE_DIR`, `OUTPUT_DIR` env vars continue to work. The browse API
recognizes both `/host/root/...` paths and legacy `/host/c` paths. Users who
prefer manual `.env` configuration are unaffected.

### 2. Host OS Detection

**New file:** `core/host_detector.py`

Detection uses filesystem signatures at `/host/root`:

```
Priority order:
1. /host/root/Windows/System32 exists         -> WINDOWS_NATIVE
2. /host/root/mnt/c/Windows/System32 exists   -> WSL
3. /host/root/Users AND /host/root/Volumes    -> MACOS
4. /host/root/etc/os-release exists           -> LINUX
5. None match                                 -> UNKNOWN
```

**Exported interface:**

```python
class HostOS(Enum):
    WINDOWS_NATIVE = "windows"
    WSL = "wsl"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"

@dataclass
class HostInfo:
    os: HostOS
    quick_access: list[QuickAccessEntry]  # name, path, icon, item_count
    drive_letters: list[str]              # Windows/WSL only: ['C', 'D']
    home_dirs: list[str]                  # Detected user home directories
    external_drives: list[str]            # macOS /Volumes/*, Linux /media/*

def detect_host() -> HostInfo:
    """Detect host OS and build quick access locations. Cached after first call."""
```

**Quick Access entries per OS:**

| OS | Entries |
|----|---------|
| WINDOWS_NATIVE | Drive roots (C:, D:, ...), `C:/Users/*` home dirs |
| WSL | `/home/*`, `/mnt/c`, `/mnt/d`, Windows user dirs via `/mnt/c/Users` |
| MACOS | `/Users/*`, `/Volumes/*` (external drives, NAS mounts) |
| LINUX | `/home/*`, `/mnt/*`, `/media/*`, `/srv` |
| All | Currently mounted network shares, previously configured locations |

Detection runs once at startup, result cached in module-level variable.
API exposes it at `GET /api/storage/host-info`. User can override via
`host_os_override` DB preference (set from the Storage page dropdown).

### 3. Storage Manager

**New file:** `core/storage_manager.py`

Orchestrator that coordinates host detection, path validation, mount
management, and config persistence.

**Path validation:**

| Check | Source (input) | Output | Failure message |
|-------|---------------|--------|-----------------|
| Path exists | Required | Required | "This folder doesn't exist" |
| Readable | Required | Required | "MarkFlow can't read this folder" |
| Writable | Skip | Required | "MarkFlow can't write to this folder — check permissions" |
| Has files | Warn if empty | Skip | "This folder is empty — are you sure?" |
| Disk space | Skip | Warn if < 1 GB | "Low disk space on output drive (820 MB free)" |
| Same path | Reject | Reject | "Input and output can't be the same folder" |
| Nested path | Reject | Reject | "Output folder is inside the input folder — this can cause loops" |
| Path length | Warn if > 240 chars | Warn | "Very long path — some files may fail on Windows" |

Validation runs in `asyncio.to_thread` to avoid blocking on slow NAS stat
calls. Returns a `ValidationResult` dataclass with `ok: bool`, `warnings: list`,
`errors: list`, `stats: dict` (file_count, free_space_bytes, etc.).

**Write guard enforcement:**

`storage_manager.py` exposes:

```python
def is_write_allowed(path: str) -> bool:
    """True only if path is under the configured output directory."""
```

Called by `converter.py` and `bulk_worker.py` before any file write. This is
the application-level restriction that makes the broad `/host/rw` mount safe.

**Config persistence:**

All storage configuration persists to DB preferences (existing system) plus
mount configs to `/etc/markflow/mounts.json` (existing pattern). The DB is
the source of truth for source locations, output path, exclusions, and cloud
prefetch settings. The JSON file is the source of truth for network mount
configs (already established in v0.20.0).

### 4. Credential Store

**New file:** `core/credential_store.py`

```
Encryption:  Fernet (AES-128-CBC + HMAC-SHA256)
Key:         PBKDF2(SECRET_KEY, salt=<random 16 bytes>, iterations=100_000)
Storage:     /etc/markflow/credentials.enc
Format:      JSON blob encrypted as a single Fernet token
```

**Stored structure:**

```json
{
  "salt": "<base64 16 bytes>",
  "shares": {
    "nas-docs": {
      "protocol": "smb",
      "username": "markflow_svc",
      "password": "<plaintext inside encrypted blob>"
    }
  }
}
```

**Interface:**

```python
class CredentialStore:
    def __init__(self, secret_key: str, path: str = "/etc/markflow/credentials.enc"): ...
    def save_credentials(self, share_name: str, protocol: str, username: str, password: str) -> None: ...
    def get_credentials(self, share_name: str) -> tuple[str, str] | None: ...  # (username, password)
    def delete_credentials(self, share_name: str) -> None: ...
    def list_shares(self) -> list[str]: ...
```

**UX rules:**
- Passwords never sent to browser unless user clicks "Edit" on a specific share
- API returns masked passwords (`****`) by default
- `GET /api/storage/shares` returns share list with masked credentials
- `GET /api/storage/shares/<name>/credentials` returns decrypted (admin only)
- On `SECRET_KEY` change: startup logs clear error, Storage page shows
  "Credentials need to be re-entered" per affected share

### 5. Extended Mount Manager

**Modified file:** `core/mount_manager.py`

Extensions to existing class:

**Multi-mount support:**
- Remove the 2-role limitation (`source`/`output` only)
- Mount configs keyed by user-chosen name (e.g., `nas-docs`, `archive`)
- Each mount gets its own mount point at `/mnt/shares/<name>`
- Config stored in `mounts.json` as a dict of named mounts

**Network discovery:**

```python
def discover_smb_servers(subnet: str, timeout: int = 10) -> list[dict]:
    """Scan subnet for SMB servers. Returns [{ip, hostname, shares: [...]}]."""
    # Uses: smbclient -L //ip -N (no auth probe)

def discover_smb_shares(server: str, username: str = "", password: str = "") -> list[dict]:
    """List shares on a specific SMB server. Returns [{name, type, comment}]."""
    # Uses: smbclient -L //server -U user%pass

def discover_nfs_exports(server: str) -> list[dict]:
    """List NFS exports on a server. Returns [{path, allowed_hosts}]."""
    # Uses: showmount -e server
```

Discovery runs in `asyncio.to_thread` with a hard timeout (15 seconds for
subnet scan, 5 seconds for single-server probe).

**Startup remount:**

```python
async def remount_all_saved() -> dict[str, bool]:
    """Re-mount all saved network shares. Called during app lifespan startup.
    Returns {share_name: success} dict. Failures logged but don't block startup."""
```

Added to `main.py` lifespan, after DB init but before scheduler start.
Uses credentials from `CredentialStore`. Failures produce a warning log
and a banner on the Storage page ("2 of 3 shares failed to reconnect").

**Mount health monitoring:**

New scheduler job (`_check_mount_health`) runs every 5 minutes:
- Checks each configured share via `get_mount_status()`
- For mounted shares: probe readability with `os.listdir()` (1s timeout)
- For unmounted shares: attempt auto-remount (max 3 retries per hour)
- Updates `mount_health` in-memory dict consumed by Storage page status dots

### 6. API Routes

**New file:** `api/routes/storage.py`

```
GET  /api/storage/host-info          — Host OS, quick access, drive letters
GET  /api/storage/browse             — Filesystem browser (extends existing browse API)
POST /api/storage/validate           — Validate a path (exists, readable, writable, space)
GET  /api/storage/sources            — List configured source locations
POST /api/storage/sources            — Add a source location
DELETE /api/storage/sources/{id}     — Remove a source location
GET  /api/storage/output             — Current output directory config
PUT  /api/storage/output             — Change output directory
GET  /api/storage/shares             — List network shares (with masked credentials)
POST /api/storage/shares             — Add/mount a network share
PUT  /api/storage/shares/{name}      — Update share config
DELETE /api/storage/shares/{name}    — Unmount and remove a share
POST /api/storage/shares/discover    — Discover shares on network
POST /api/storage/shares/{name}/test — Test connection for a specific share
GET  /api/storage/shares/{name}/credentials — Decrypted credentials (admin only)
GET  /api/storage/exclusions         — List location exclusions
POST /api/storage/exclusions         — Add an exclusion
DELETE /api/storage/exclusions/{id}  — Remove an exclusion
GET  /api/storage/health             — Mount health status for all shares
GET  /api/storage/restart-status     — Pending restart info (reason, since, dismissed_until)
POST /api/storage/restart-dismiss    — Dismiss restart notification for 1 hour
POST /api/storage/wizard-dismiss     — Mark first-run wizard as dismissed
DELETE /api/storage/wizard-dismiss   — Clear dismissal (re-enables auto-trigger)
GET  /api/storage/wizard-status     — Whether wizard should show (checks all conditions)
```

**Browse endpoint** extends the existing `/api/browse` logic but operates on
`/host/root` paths. The existing `/api/browse` remains for backward
compatibility. New browse adds:
- OS-native path translation (show `C:\Users\...` for Windows hosts)
- Item count and basic stats per directory
- File type icons based on extension

**Auth:** All routes require `MANAGER` role minimum. Credential decryption
requires `ADMIN`. Consistent with existing MarkFlow auth patterns.

### 7. Restart Notification System

**When triggered:** Output directory change (requires docker-compose volume
rebind or broad mount path update). Network share changes do NOT trigger
restart (handled at runtime).

**Storage:**
- `pending_restart_reason` DB preference (string, nullable)
- `pending_restart_since` DB preference (ISO timestamp, nullable)
- `pending_restart_dismissed_until` DB preference (ISO timestamp, nullable)

**UI component:** Rendered by `global-status-bar.js` (already manages pipeline
status banners). Amber background, distinct from red (pipeline disabled) and
blue (info) banners.

```
+------------------------------------------------------------------+
|  WARNING: RESTART REQUIRED — Output directory changed to          |
|  D:\MarkFlow-Output. Restart the container to apply.             |
|                                                                  |
|  [ Restart Now ]    [ Remind Me Later ]     Changed 15 min ago   |
+------------------------------------------------------------------+
```

**Behavior:**
- Shows on every page (injected by global-status-bar.js)
- "Remind Me Later" sets `dismissed_until` to now + 1 hour
- "Restart Now" shows the terminal command:
  `docker-compose down && docker-compose up -d`
  (Docker socket restart is out of scope — too much security surface)
- Banner auto-clears on next startup when config matches reality
- Polling: status bar checks `/api/storage/restart-status` every 60 seconds

### 8. Storage Page UI

**New file:** `static/storage.html`
**New file:** `static/js/storage.js`

**Page header:** Title "Storage", OS detection badge ("Detected: Windows"),
and a "Run Setup Wizard" button (top-right) that re-opens the first-run
wizard overlay at any time.

**Page sections (all collapsible, same pattern as Settings page):**

1. **Quick Access** — OS-detected common locations as clickable cards
2. **Source Locations** — Table of configured scan sources with health dots
3. **Output Directory** — Current output path with validation status + change button
4. **Network Shares** — Table of shares with status, credentials (masked), actions
5. **Location Exclusions** — Prefix-match exclusion paths
6. **Cloud Prefetch** — Settings migrated from Settings page
7. **Filesystem Browser** — Expandable tree browser, triggered by any "Browse" button

**Filesystem browser features:**
- Tree navigation with breadcrumb path bar
- OS-native display (drive letters on Windows, `/home` on Linux)
- "Switch to Raw Tree View" toggle for power users
- Directory item count + permission indicators
- "Use as Source" / "Use as Output" action buttons
- Validation spinner on path selection (1-2 seconds)
- Green checkmark or red error with plain-English explanation

**Nav bar:** New "Storage" item added between existing items. Icon: folder/drive.

### 9. First-Run Wizard

**Trigger condition:**
```python
show_wizard = (
    no_source_locations_configured
    and no_output_directory_configured
    and not get_preference("setup_wizard_dismissed")
    and not os.getenv("SKIP_FIRST_RUN_WIZARD")
    and not os.getenv("DEV_BYPASS_AUTH") == "true"
)
```

When `DEV_BYPASS_AUTH=true` (the dev mode flag already used throughout
MarkFlow), the wizard is suppressed entirely. Power users who configure
storage manually via `.env` never see it.

**Wizard steps (modal overlay on Storage page):**

```
Step 1: Welcome
        "Welcome to MarkFlow"
        Detected: {OS} host {with drives C:, D: | with /home/user}
        "Let's set up where your files are."
        [ Get Started ]  [ Skip — I'll configure manually ]

Step 2: Select Source
        "Where are the files you want to convert?"
        [Embedded filesystem browser]
        Validation feedback inline
        [ Use This Folder ]  [ Back ]

Step 3: Select Output
        "Where should converted files go?"
        [Embedded filesystem browser]
        Validation: writable check, free space display
        [ Use This Folder ]  [ Back ]

Step 4: Network Shares (optional)
        "Do you have files on a network drive or NAS?"
        [ Add a Network Share ]  [ Skip for Now ]
        If adding: inline share config form with Test button

Step 5: Summary
        "You're all set!"
        Source: D:\T86_Work\k_drv (12,847 files)
        Output: D:\Doc-Conv_Output (142 GB free)
        Shares: nas-docs (mounted)
        [ Start Using MarkFlow ]
```

**"Skip — I'll configure manually"** on step 1:
- Sets `setup_wizard_dismissed = true` in DB preferences
- Closes overlay, shows full Storage page in management mode
- Wizard never reappears

**Re-run from Storage page:** A "Run Setup Wizard" button appears in the
page header (top-right, next to the OS detection badge). Clicking it
re-opens the wizard overlay regardless of `setup_wizard_dismissed` state.
This lets a user reconfigure from scratch without clearing preferences
manually. The wizard pre-fills any already-configured values so existing
config isn't lost — the user can step through and change only what they want.

**Admin reset:** `DELETE /api/storage/wizard-dismiss` clears the preference
so the wizard auto-triggers on next page load (for testing or new-user
onboarding scenarios).

### 10. Settings Page Migration

**Sections moving from Settings to Storage page:**
- Locations (source paths + Browse + Check Access)
- Location Exclusions (prefix-match paths)
- Network Share Mounts (SMB/NFS config forms)
- Cloud Prefetch (enabled, concurrency, rate limit, timeout, probe settings)

**Sections remaining on Settings page:**
- Conversion (OCR thresholds, fidelity, workers, password brute force)
- Pipeline (auto-convert, batch sizing, master switch, startup delay)
- Search & Indexing (Meilisearch, vector search, preview settings)
- LLM Providers (AI Assist model, tokens)
- File Lifecycle (grace period, trash retention)
- Logging (log levels, rotation)
- Auth & Security (JWT, API keys, roles)
- All other non-storage sections

**Migration approach:** The Settings page sections are removed and replaced
with a single link card:

```
Storage
  Manage source locations, output directory, network shares,
  and cloud prefetch settings on the Storage page.
  [ Open Storage Page -> ]
```

This preserves discoverability for users who go to Settings looking for
storage config.

---

## Execution Phases

### Phase 1 — Foundation (backend)

New files:
- `core/host_detector.py`
- `core/storage_manager.py`
- `core/credential_store.py`
- `api/routes/storage.py`
- `tests/test_host_detector.py`
- `tests/test_credential_store.py`
- `tests/test_storage_manager.py`

Modified files:
- `core/mount_manager.py` (multi-mount, discovery, health, startup remount)
- `docker-compose.yml` (root mounts, SYS_ADMIN cap)
- `Dockerfile.base` (add smbclient, cifs-utils)
- `main.py` (startup remount in lifespan, mount storage routes)
- `core/scheduler.py` (mount health check job)
- `core/bulk_worker.py` (write guard check)
- `core/converter.py` (write guard check)

**Parallel agent opportunities:**
- Agent A: `host_detector.py` + its tests (independent module, no deps)
- Agent B: `credential_store.py` + its tests (independent module, needs only SECRET_KEY)
- Agent C: `mount_manager.py` extensions (discovery, multi-mount, health)
- Sequential after A+B+C: `storage_manager.py` (imports all three)
- Agent D (parallel with above): Docker file changes (compose, Dockerfile.base)
- Sequential last: `api/routes/storage.py` + `main.py` wiring

### Phase 2 — UI (frontend)

New files:
- `static/storage.html`
- `static/js/storage.js`

Modified files:
- `static/app.js` (nav bar addition)
- `static/js/global-status-bar.js` (restart notification banner)
- `static/markflow.css` (storage page styles, wizard overlay styles)

**Parallel agent opportunities:**
- Agent A: Storage page HTML structure + CSS (layout, sections, browser)
- Agent B: Restart notification banner in global-status-bar.js (independent)
- Sequential after A: storage.js (needs HTML structure finalized)
- Sequential last: First-run wizard overlay (needs storage.js working)

### Phase 3 — Migration & Polish

Modified files:
- `static/settings.html` (remove storage sections, add link card)
- `static/settings.html` JS (remove mount/location JS handlers)
- `api/routes/browse.py` (add `/host/root` to allowed roots)
- `core/path_utils.py` (update allowed roots for write guard)

New files:
- `tests/test_storage_api.py` (integration tests)

**Parallel agent opportunities:**
- Agent A: Settings page section removal + link card
- Agent B: Browse API extension + path_utils update
- Agent C: Integration tests
- Sequential last: End-to-end smoke test, version bump, docs update

---

## Security Considerations

- **Broad rw mount:** The `/host/rw` mount gives the container theoretical
  write access to the entire host filesystem. The application-level write
  guard (`storage_manager.is_write_allowed()`) is the sole enforcement
  layer. This guard must be called in every code path that writes files:
  `converter.py`, `bulk_worker.py`, `transcript_formatter.py`, and any
  future write paths. A code review checkpoint in Phase 1 must verify
  complete coverage.

- **SYS_ADMIN capability:** Required for `mount` syscall inside the
  container. Grants more privilege than default containers. Acceptable for
  a self-hosted internal tool; would need review for multi-tenant deployment.

- **Credential encryption:** Fernet + PBKDF2 is the standard pattern for
  application-level secret storage. The threat model is "attacker gets the
  credentials file but not the environment variables" — `SECRET_KEY` is the
  key material. This matches the existing JWT secret model in MarkFlow.

- **Network discovery:** Subnet scanning probes ports 445 (SMB) and 2049
  (NFS) on the local network. This is standard service discovery but could
  trigger network IDS alerts. Discovery is user-initiated only (button click),
  never automatic.

- **Path validation:** All browse and validation endpoints inherit the
  existing path traversal protection (null byte rejection, `..` blocking,
  symlink escape detection) from `browse.py`. The new `/host/root` root
  is added to `ALLOWED_BROWSE_ROOTS`.

---

## Out of Scope

- Docker socket mounting / automatic container restart (too much security surface)
- Multi-tenant isolation (this is a single-org self-hosted tool)
- Cloud storage APIs (S3, Azure Blob) — only filesystem-mounted shares
- Windows-native Docker (non-WSL) — extremely rare, not worth the complexity
- Remote deployment orchestration — this manages storage on the local host only
