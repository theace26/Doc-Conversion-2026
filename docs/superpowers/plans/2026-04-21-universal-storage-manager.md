# Universal Storage Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual `.env`/`docker-compose.yml` storage configuration with a GUI-driven Storage page, first-run wizard, and runtime network-share management — so non-technical users can onboard in minutes instead of editing Docker files.

**Architecture:** Three layers. **Docker** grants broad read access (`/host/root:ro`) and writable access (`/host/rw`); **application code** enforces write restriction at every file-writing code path via a single `is_write_allowed()` guard; **presentation** consolidates storage configuration onto one Storage page with an optional first-run wizard overlay. Runtime mounts (SMB/NFS) mount dynamically to `/mnt/shares/<name>` using `SYS_ADMIN` cap; mount configs persist in `/etc/markflow/mounts.json` (existing pattern from v0.20.0).

**Tech Stack:** Python 3 / FastAPI (backend), vanilla JS + fetch (frontend), SQLite prefs (config), Fernet + PBKDF2 (credential encryption), smbclient + cifs-utils + nfs-common (mount), pytest (tests).

**Reference spec:** `docs/superpowers/specs/2026-04-21-universal-storage-manager-design.md` (approved 2026-04-21). Read the spec first for design rationale — this plan covers HOW, the spec covers WHY.

**Phases:**

| Phase | Scope | Tasks | Shippable? | Review gate |
|-------|-------|-------|------------|-------------|
| 1 | Backend foundation (host detect, credential store, mount mgr ext, storage mgr, write guard, API, Docker) | 13 | Yes — API usable without UI | **HUMAN GATE** before Phase 2 |
| 2 | Frontend (Storage page, status-bar banner, first-run wizard) | 6 | Yes — end-users can onboard | Code review |
| 3 | Migration & polish (Settings migration, browse ext, tests, help, version bump) | 5 | Yes — final polish | Final review |

---

## File Structure

### New files (Phase 1 — backend)

| File | Responsibility |
|------|----------------|
| `core/host_detector.py` | Detect host OS from `/host/root` filesystem signatures; build quick-access lists; cache result |
| `core/credential_store.py` | Fernet+PBKDF2 encrypted store for SMB/NFS credentials at `/etc/markflow/credentials.enc` |
| `core/storage_manager.py` | Orchestrator: path validation, write-guard enforcement, config persistence |
| `api/routes/storage.py` | Consolidated `/api/storage/*` endpoints (host-info, sources, shares, output, exclusions, wizard, restart) |
| `tests/test_host_detector.py` | Unit tests for OS detection (mock `/host/root`) |
| `tests/test_credential_store.py` | Unit tests for encrypt/decrypt round-trip, key rotation, masking |
| `tests/test_storage_manager.py` | Unit tests for path validation, write guard, config persistence |

### Modified files (Phase 1 — backend)

| File | Change |
|------|--------|
| `core/mount_manager.py` | Multi-mount support (dict of named mounts), discovery (`discover_smb_servers`, `discover_smb_shares`, `discover_nfs_exports`), startup `remount_all_saved()`, health monitoring |
| `core/converter.py` | Call `storage_manager.is_write_allowed()` before file writes |
| `core/bulk_worker.py` | Same write-guard check |
| `core/scheduler.py` | New `_check_mount_health` job (every 5 min) |
| `core/db/preferences.py` | Add `pending_restart_reason`, `pending_restart_since`, `pending_restart_dismissed_until`, `setup_wizard_dismissed`, `host_os_override` defaults |
| `main.py` | Call `remount_all_saved()` in lifespan; mount `storage.router` |
| `docker-compose.yml` | Add `/:/host/root:ro`, `/:/host/rw`, `cap_add: [SYS_ADMIN]` |
| `Dockerfile.base` | Add `smbclient`, `cifs-utils` |

### New files (Phase 2 — frontend)

| File | Responsibility |
|------|----------------|
| `static/storage.html` | Storage page: Quick Access, Sources, Output, Shares, Exclusions, Cloud Prefetch, Browser |
| `static/js/storage.js` | Storage page JS; also renders the first-run wizard overlay |

### Modified files (Phase 2 — frontend)

| File | Change |
|------|--------|
| `static/app.js` | Add "Storage" nav item |
| `static/js/global-status-bar.js` | Render amber restart-required banner when `/api/storage/restart-status` reports pending |
| `static/markflow.css` | Storage page styles + wizard overlay styles |

### Modified files (Phase 3 — migration)

| File | Change |
|------|--------|
| `static/settings.html` | Remove Locations / Location Exclusions / Network Share Mounts / Cloud Prefetch sections; add "Open Storage Page →" link card |
| `api/routes/browse.py` | Add `/host/root` and `/host/rw` to `ALLOWED_BROWSE_ROOTS` |
| `core/path_utils.py` | Update allowed roots list |
| `tests/test_storage_api.py` (NEW) | End-to-end integration tests for `/api/storage/*` endpoints |
| `docs/help/storage.md` (NEW or update) | User-facing docs for the Storage page and wizard |
| `docs/help/_index.json` | Register the new help article |
| `core/version.py` | Bump to v0.25.0 |
| `CLAUDE.md` | Update "Current Version" block |
| `docs/version-history.md` | Append v0.25.0 entry |
| `docs/gotchas.md` | Add gotchas for write-guard coverage, SYS_ADMIN cap, credential key rotation |
| `docs/key-files.md` | Add new `core/*` and `api/routes/storage.py` entries |

---

# PHASE 1 — Foundation (Backend)

## Task 1: Docker infrastructure changes

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Dockerfile.base`

**Context:** These are the broadest-blast-radius changes in the plan. They expose the host filesystem to the container (read-only at `/host/root`, writable at `/host/rw`) and grant `SYS_ADMIN` capability for runtime mounting. The app-level write guard (Task 9) is the ONLY restriction on `/host/rw`. Do NOT deploy Task 1 without Task 9 already merged or staged in the same commit sequence.

- [ ] **Step 1: Add broad mounts + SYS_ADMIN to docker-compose.yml**

Insert into the `volumes:` block of the `markflow` service (before existing mounts):

```yaml
volumes:
  # Universal Storage Manager (v0.25.0) — browse entire host RO; app-level write guard restricts /host/rw
  - /:/host/root:ro
  - /:/host/rw
  # Legacy mounts retained for backward compatibility:
  - ${SOURCE_DIR:-/tmp/markflow-nosource}:/mnt/source:ro
  - ${OUTPUT_DIR:-./output}:/mnt/output-repo
```

Add `cap_add` under the `markflow` service (top level, sibling of `volumes`):

```yaml
cap_add:
  - SYS_ADMIN
```

- [ ] **Step 2: Add smbclient + cifs-utils to Dockerfile.base**

In `Dockerfile.base`, in the existing `apt-get install` block, add these two packages (alphabetical order with existing entries):

```dockerfile
    cifs-utils \
    smbclient \
```

Confirm `nfs-common` is already present — per spec, it is.

- [ ] **Step 3: Verify compose file is valid**

Run: `docker-compose config > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml Dockerfile.base
git commit -m "feat(storage): broad host mounts + SYS_ADMIN cap for Universal Storage Manager"
```

---

## Task 2: Host detector

**Files:**
- Create: `core/host_detector.py`
- Test: `tests/test_host_detector.py`

**Context:** Pure detection module. No dependencies on other Storage Manager components. Runs once at app startup; result cached. Signature priority order matters — WSL has `/Windows/System32` under `/mnt/c`, so WSL must be checked before Linux.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_host_detector.py`:

```python
"""Unit tests for host OS detection."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.host_detector import HostOS, detect_host, _detect_os_from_root


def _mkdir(root: Path, rel: str) -> None:
    (root / rel).mkdir(parents=True, exist_ok=True)


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


def test_detect_windows_native(tmp_path: Path) -> None:
    _mkdir(tmp_path, "Windows/System32")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.WINDOWS_NATIVE


def test_detect_wsl_beats_linux(tmp_path: Path) -> None:
    _mkdir(tmp_path, "mnt/c/Windows/System32")
    _touch(tmp_path, "etc/os-release")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.WSL


def test_detect_macos(tmp_path: Path) -> None:
    _mkdir(tmp_path, "Users")
    _mkdir(tmp_path, "Volumes")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.MACOS


def test_detect_linux(tmp_path: Path) -> None:
    _touch(tmp_path, "etc/os-release")
    assert _detect_os_from_root(str(tmp_path)) is HostOS.LINUX


def test_detect_unknown(tmp_path: Path) -> None:
    assert _detect_os_from_root(str(tmp_path)) is HostOS.UNKNOWN


def test_detect_host_caches(monkeypatch, tmp_path: Path) -> None:
    _touch(tmp_path, "etc/os-release")
    monkeypatch.setattr("core.host_detector.HOST_ROOT", str(tmp_path))
    import core.host_detector as hd
    hd._cache = None  # reset
    a = detect_host()
    b = detect_host()
    assert a is b  # same cached object


def test_quick_access_windows(tmp_path: Path, monkeypatch) -> None:
    _mkdir(tmp_path, "Windows/System32")
    _mkdir(tmp_path, "Users/Alice/Documents")
    _mkdir(tmp_path, "Users/Bob")
    monkeypatch.setattr("core.host_detector.HOST_ROOT", str(tmp_path))
    import core.host_detector as hd
    hd._cache = None
    info = detect_host()
    assert info.os is HostOS.WINDOWS_NATIVE
    paths = [q.path for q in info.quick_access]
    assert any("Alice" in p for p in paths)
    assert any("Bob" in p for p in paths)
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_host_detector.py -v`
Expected: Collection error — `core.host_detector` does not exist.

- [ ] **Step 3: Implement core/host_detector.py**

Create `core/host_detector.py`:

```python
"""Host OS detection from /host/root filesystem signatures.

Runs once at startup; cached. Used by Storage Manager to build OS-appropriate
quick-access lists and drive-letter mappings.
"""
from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

HOST_ROOT = "/host/root"


class HostOS(Enum):
    WINDOWS_NATIVE = "windows"
    WSL = "wsl"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"


@dataclass
class QuickAccessEntry:
    name: str
    path: str
    icon: str = "folder"
    item_count: int | None = None


@dataclass
class HostInfo:
    os: HostOS
    quick_access: list[QuickAccessEntry] = field(default_factory=list)
    drive_letters: list[str] = field(default_factory=list)
    home_dirs: list[str] = field(default_factory=list)
    external_drives: list[str] = field(default_factory=list)


_cache: HostInfo | None = None


def _detect_os_from_root(root: str) -> HostOS:
    """Detect OS from filesystem signatures under `root`. Priority matters."""
    if os.path.isdir(os.path.join(root, "Windows", "System32")):
        return HostOS.WINDOWS_NATIVE
    if os.path.isdir(os.path.join(root, "mnt", "c", "Windows", "System32")):
        return HostOS.WSL
    if os.path.isdir(os.path.join(root, "Users")) and os.path.isdir(os.path.join(root, "Volumes")):
        return HostOS.MACOS
    if os.path.isfile(os.path.join(root, "etc", "os-release")):
        return HostOS.LINUX
    return HostOS.UNKNOWN


def _safe_listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except (OSError, PermissionError):
        return []


def _count_items(path: str) -> int | None:
    try:
        return len(os.listdir(path))
    except (OSError, PermissionError):
        return None


def _drive_letters(root: str) -> list[str]:
    """Windows drive letters exposed via `/host/root/<letter>` (container shim) or `/mnt/<letter>` (WSL)."""
    letters: list[str] = []
    for letter in string.ascii_uppercase:
        for candidate in (os.path.join(root, letter.lower()), os.path.join(root, "mnt", letter.lower())):
            if os.path.isdir(candidate):
                letters.append(letter)
                break
    return letters


def _build_quick_access(host_os: HostOS, root: str) -> tuple[list[QuickAccessEntry], list[str], list[str], list[str]]:
    qa: list[QuickAccessEntry] = []
    drive_letters: list[str] = []
    home_dirs: list[str] = []
    external_drives: list[str] = []

    if host_os is HostOS.WINDOWS_NATIVE:
        drive_letters = _drive_letters(root)
        for letter in drive_letters:
            drive_path = os.path.join(root, letter.lower())
            qa.append(QuickAccessEntry(name=f"{letter}:", path=drive_path, icon="drive"))
        users_dir = os.path.join(root, "Users")
        for user in _safe_listdir(users_dir):
            home = os.path.join(users_dir, user)
            if os.path.isdir(home) and not user.startswith("."):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user", item_count=_count_items(home)))
    elif host_os is HostOS.WSL:
        drive_letters = _drive_letters(root)
        for letter in drive_letters:
            qa.append(QuickAccessEntry(name=f"{letter}:", path=os.path.join(root, "mnt", letter.lower()), icon="drive"))
        home_root = os.path.join(root, "home")
        for user in _safe_listdir(home_root):
            home = os.path.join(home_root, user)
            if os.path.isdir(home):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user"))
    elif host_os is HostOS.MACOS:
        users_dir = os.path.join(root, "Users")
        for user in _safe_listdir(users_dir):
            home = os.path.join(users_dir, user)
            if os.path.isdir(home) and user not in ("Shared",) and not user.startswith("."):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user"))
        volumes_dir = os.path.join(root, "Volumes")
        for vol in _safe_listdir(volumes_dir):
            vpath = os.path.join(volumes_dir, vol)
            if os.path.isdir(vpath):
                external_drives.append(vpath)
                qa.append(QuickAccessEntry(name=vol, path=vpath, icon="external"))
    elif host_os is HostOS.LINUX:
        home_root = os.path.join(root, "home")
        for user in _safe_listdir(home_root):
            home = os.path.join(home_root, user)
            if os.path.isdir(home):
                home_dirs.append(home)
                qa.append(QuickAccessEntry(name=user, path=home, icon="user"))
        for base in ("mnt", "media", "srv"):
            bpath = os.path.join(root, base)
            for entry in _safe_listdir(bpath):
                epath = os.path.join(bpath, entry)
                if os.path.isdir(epath):
                    external_drives.append(epath)
                    qa.append(QuickAccessEntry(name=f"/{base}/{entry}", path=epath, icon="external"))

    return qa, drive_letters, home_dirs, external_drives


def detect_host() -> HostInfo:
    """Detect host OS and build quick-access list. Cached after first call."""
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.isdir(HOST_ROOT):
        log.warning("host_root_missing", path=HOST_ROOT)
        _cache = HostInfo(os=HostOS.UNKNOWN)
        return _cache
    host_os = _detect_os_from_root(HOST_ROOT)
    qa, drives, homes, externals = _build_quick_access(host_os, HOST_ROOT)
    _cache = HostInfo(os=host_os, quick_access=qa, drive_letters=drives, home_dirs=homes, external_drives=externals)
    log.info("host_detected", os=host_os.value, drives=drives, home_count=len(homes))
    return _cache


def reset_cache() -> None:
    """Test hook to force re-detection."""
    global _cache
    _cache = None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_host_detector.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/host_detector.py tests/test_host_detector.py
git commit -m "feat(storage): host OS detector with quick-access list builder"
```

---

## Task 3: Credential store

**Files:**
- Create: `core/credential_store.py`
- Test: `tests/test_credential_store.py`

**Context:** Fernet + PBKDF2 encryption for SMB/NFS credentials. Threat model: attacker with file access but not env vars. Matches MarkFlow's existing JWT secret model. `cryptography` is already a transitive dependency via JWT — confirm with `pip show cryptography` before implementing.

- [ ] **Step 1: Confirm `cryptography` is available**

Run: `python -c "import cryptography.fernet; print('ok')"` (from project root, inside the running container or venv).
Expected: `ok`. If missing, add `cryptography>=42.0.0` to `requirements.txt`.

- [ ] **Step 2: Write failing tests**

Create `tests/test_credential_store.py`:

```python
"""Unit tests for the encrypted credential store."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.credential_store import CredentialStore


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    return CredentialStore(secret_key="test-secret-0123456789abcdef", path=str(tmp_path / "creds.enc"))


def test_save_then_get_round_trip(store: CredentialStore) -> None:
    store.save_credentials("nas-docs", "smb", "alice", "p@ssw0rd")
    creds = store.get_credentials("nas-docs")
    assert creds == ("alice", "p@ssw0rd")


def test_get_missing_returns_none(store: CredentialStore) -> None:
    assert store.get_credentials("never-saved") is None


def test_list_shares(store: CredentialStore) -> None:
    store.save_credentials("a", "smb", "u1", "p1")
    store.save_credentials("b", "nfs", "u2", "p2")
    assert set(store.list_shares()) == {"a", "b"}


def test_delete_credentials(store: CredentialStore) -> None:
    store.save_credentials("x", "smb", "u", "p")
    store.delete_credentials("x")
    assert store.get_credentials("x") is None
    assert "x" not in store.list_shares()


def test_file_is_encrypted_on_disk(store: CredentialStore, tmp_path: Path) -> None:
    store.save_credentials("share", "smb", "alice", "topsecretpass")
    raw = (tmp_path / "creds.enc").read_bytes()
    assert b"alice" not in raw
    assert b"topsecretpass" not in raw


def test_wrong_key_fails_to_decrypt(tmp_path: Path) -> None:
    path = str(tmp_path / "c.enc")
    s1 = CredentialStore(secret_key="key-one-0123456789abcdef", path=path)
    s1.save_credentials("share", "smb", "u", "p")
    s2 = CredentialStore(secret_key="key-two-0123456789abcdef", path=path)
    # Different key → load fails → behaves as empty
    assert s2.get_credentials("share") is None
    assert s2.list_shares() == []


def test_persists_across_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "c.enc")
    s1 = CredentialStore(secret_key="same-key-0123456789abcdef", path=path)
    s1.save_credentials("persistent", "smb", "bob", "pw")
    s2 = CredentialStore(secret_key="same-key-0123456789abcdef", path=path)
    assert s2.get_credentials("persistent") == ("bob", "pw")
```

- [ ] **Step 3: Run tests — expect ImportError**

Run: `pytest tests/test_credential_store.py -v`
Expected: Collection error — module missing.

- [ ] **Step 4: Implement `core/credential_store.py`**

Create `core/credential_store.py`:

```python
"""Fernet-encrypted credential store for SMB/NFS shares.

Threat model: attacker gains file-read access but not process environment.
Key derivation: PBKDF2(SECRET_KEY, salt, 100_000 iterations) via cryptography.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = structlog.get_logger(__name__)

_DEFAULT_PATH = "/etc/markflow/credentials.enc"
_ITERATIONS = 100_000
_SALT_BYTES = 16


class CredentialStore:
    """Load/save encrypted credentials to disk. Thread-safe for intra-process access."""

    def __init__(self, secret_key: str, path: str = _DEFAULT_PATH) -> None:
        if not secret_key:
            raise ValueError("secret_key is required")
        self._secret = secret_key.encode("utf-8")
        self._path = path
        self._lock = threading.Lock()

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS)
        return base64.urlsafe_b64encode(kdf.derive(self._secret))

    def _load(self) -> dict:
        if not os.path.isfile(self._path):
            return {"salt": base64.b64encode(secrets.token_bytes(_SALT_BYTES)).decode("ascii"), "shares": {}}
        try:
            raw = Path(self._path).read_bytes()
            header, _, payload = raw.partition(b"\n")
            salt_b64 = header.decode("ascii").strip()
            salt = base64.b64decode(salt_b64)
            f = Fernet(self._derive_key(salt))
            data = json.loads(f.decrypt(payload).decode("utf-8"))
            return {"salt": salt_b64, "shares": data.get("shares", {})}
        except (InvalidToken, json.JSONDecodeError, ValueError, OSError) as exc:
            log.warning("credential_store_load_failed", path=self._path, error=str(exc))
            return {"salt": base64.b64encode(secrets.token_bytes(_SALT_BYTES)).decode("ascii"), "shares": {}}

    def _save(self, blob: dict) -> None:
        salt = base64.b64decode(blob["salt"])
        f = Fernet(self._derive_key(salt))
        payload = f.encrypt(json.dumps({"shares": blob["shares"]}).encode("utf-8"))
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob["salt"].encode("ascii") + b"\n" + payload)
        os.replace(tmp, self._path)

    def save_credentials(self, share_name: str, protocol: str, username: str, password: str) -> None:
        if not share_name or not protocol:
            raise ValueError("share_name and protocol are required")
        with self._lock:
            blob = self._load()
            blob["shares"][share_name] = {"protocol": protocol, "username": username, "password": password}
            self._save(blob)

    def get_credentials(self, share_name: str) -> tuple[str, str] | None:
        with self._lock:
            blob = self._load()
            entry = blob["shares"].get(share_name)
            if not entry:
                return None
            return entry.get("username", ""), entry.get("password", "")

    def delete_credentials(self, share_name: str) -> None:
        with self._lock:
            blob = self._load()
            blob["shares"].pop(share_name, None)
            self._save(blob)

    def list_shares(self) -> list[str]:
        with self._lock:
            blob = self._load()
            return sorted(blob["shares"].keys())
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_credential_store.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add core/credential_store.py tests/test_credential_store.py
git commit -m "feat(storage): Fernet-encrypted credential store for SMB/NFS shares"
```

---

## Task 4: Mount Manager — multi-mount support

**Files:**
- Modify: `core/mount_manager.py`

**Context:** Existing MountManager supports 2 named roles (`source`, `output`). Extend to an arbitrary dict of named mounts, each at `/mnt/shares/<name>`. Existing MountConfig dataclass is extended, not replaced, to preserve backward compatibility with saved `mounts.json` files.

- [ ] **Step 1: Read the existing file**

Open `core/mount_manager.py`. Locate `MountConfig` (~line 40) and `MountManager` (~line 129).

- [ ] **Step 2: Add `/mnt/shares/<name>` mount-point helper**

In `MountManager`, add:

```python
SHARES_ROOT = "/mnt/shares"

@staticmethod
def share_mount_point(name: str) -> str:
    """Compute mount point for a named share. Name is sanitized to a safe path segment."""
    safe = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip("-_")
    if not safe:
        raise ValueError(f"invalid share name: {name!r}")
    return f"{MountManager.SHARES_ROOT}/{safe}"
```

- [ ] **Step 3: Add `mount_named()` method**

```python
async def mount_named(self, name: str, config: MountConfig) -> MountResult:
    """Mount a named share at /mnt/shares/<name>. Creates the mount point if needed."""
    mount_point = self.share_mount_point(name)
    os.makedirs(mount_point, exist_ok=True)
    # Reuse the underlying _mount_smb / _mount_nfs helpers, passing mount_point.
    return await self._mount_one(config, mount_point)
```

(If an existing `_mount_smb` / `_mount_nfs` helper takes a hard-coded path, refactor to accept `mount_point` as a parameter. Keep existing `source` / `output` mount roles working by calling through `mount_named` with synthetic names `"source"` / `"output"` when the legacy code paths invoke the legacy API.)

- [ ] **Step 4: Add `unmount_named()` method**

```python
async def unmount_named(self, name: str) -> bool:
    mount_point = self.share_mount_point(name)
    return await self._unmount(mount_point)
```

- [ ] **Step 5: Extend `mounts.json` schema to dict of named entries**

Current schema (likely):
```json
{"source": {...}, "output": {...}}
```

Target schema:
```json
{
  "_schema_version": 2,
  "shares": {
    "nas-docs": {"protocol": "smb", "server": "10.0.0.5"},
    "archive": {"protocol": "nfs"}
  }
}
```

Add a migration helper:

```python
def _migrate_mounts_json(raw: dict) -> dict:
    """v1 (flat) → v2 (shares dict). v1 entries with known roles become named shares."""
    if raw.get("_schema_version") == 2:
        return raw
    shares: dict[str, dict] = {}
    for role, cfg in raw.items():
        if role.startswith("_"):
            continue
        if isinstance(cfg, dict) and cfg:
            shares[role] = cfg
    return {"_schema_version": 2, "shares": shares}
```

Call this helper when loading `mounts.json`.

- [ ] **Step 6: Write a minimal smoke test**

Append to (or create) `tests/test_mount_manager.py`:

```python
def test_share_mount_point_sanitizes() -> None:
    from core.mount_manager import MountManager
    assert MountManager.share_mount_point("nas-docs") == "/mnt/shares/nas-docs"
    assert MountManager.share_mount_point("a b") == "/mnt/shares/ab"
    with pytest.raises(ValueError):
        MountManager.share_mount_point("///")


def test_migrate_v1_to_v2() -> None:
    from core.mount_manager import _migrate_mounts_json
    v1 = {"source": {"protocol": "smb", "server": "x"}}
    v2 = _migrate_mounts_json(v1)
    assert v2["_schema_version"] == 2
    assert "source" in v2["shares"]
    # idempotent
    assert _migrate_mounts_json(v2) == v2
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_mount_manager.py -v`
Expected: all passing (existing + new).

- [ ] **Step 8: Commit**

```bash
git add core/mount_manager.py tests/test_mount_manager.py
git commit -m "feat(storage): mount_manager multi-mount support with /mnt/shares/<name>"
```

---

## Task 5: Mount Manager — network discovery

**Files:**
- Modify: `core/mount_manager.py`

**Context:** Discovery uses `smbclient -L` and `showmount -e`. All calls go through `asyncio.to_thread` with hard timeouts. Never scan automatically — discovery is user-initiated.

- [ ] **Step 1: Write failing tests (discovery functions)**

Append to `tests/test_mount_manager.py`:

```python
import asyncio
from unittest.mock import patch


def test_discover_smb_shares_parses_output() -> None:
    from core.mount_manager import _parse_smbclient_shares
    sample = """
        Sharename       Type      Comment
        ---------       ----      -------
        Documents       Disk      Shared docs
        Backups         Disk
        print$          Disk      Printer Drivers
        IPC$            IPC       IPC Service
    """
    shares = _parse_smbclient_shares(sample)
    names = [s["name"] for s in shares]
    assert "Documents" in names
    assert "Backups" in names
    assert "IPC$" not in names  # IPC/ADMIN shares excluded


def test_discover_nfs_exports_parses_output() -> None:
    from core.mount_manager import _parse_showmount_output
    sample = """Export list for 10.0.0.5:
/exports/data    10.0.0.0/24
/exports/media   *
"""
    exports = _parse_showmount_output(sample)
    assert {"path": "/exports/data", "allowed_hosts": "10.0.0.0/24"} in exports
    assert {"path": "/exports/media", "allowed_hosts": "*"} in exports


def test_discover_smb_servers_timeout(monkeypatch) -> None:
    from core import mount_manager as mm
    async def slow(*a, **kw):
        await asyncio.sleep(30)
    monkeypatch.setattr(mm, "_probe_smb_host", slow)
    result = asyncio.run(mm.discover_smb_servers("10.0.0.0/30", timeout=1))
    # Completes within the timeout, returns whatever probes finished
    assert isinstance(result, list)
```

- [ ] **Step 2: Implement discovery helpers in `core/mount_manager.py`**

```python
import re
import subprocess

_IPC_SHARES = {"IPC$", "ADMIN$", "print$"}


def _parse_smbclient_shares(output: str) -> list[dict]:
    """Parse `smbclient -L //server -N` output into share descriptors."""
    shares: list[dict] = []
    in_block = False
    for line in output.splitlines():
        line_s = line.rstrip()
        if "Sharename" in line_s and "Type" in line_s:
            in_block = True
            continue
        if in_block:
            if not line_s.strip() or set(line_s.strip()) == {"-", " "}:
                in_block = False
                continue
            parts = re.split(r"\s{2,}", line_s.strip(), maxsplit=2)
            if len(parts) < 2:
                continue
            name, share_type = parts[0], parts[1]
            if name in _IPC_SHARES:
                continue
            comment = parts[2] if len(parts) == 3 else ""
            shares.append({"name": name, "type": share_type, "comment": comment})
    return shares


def _parse_showmount_output(output: str) -> list[dict]:
    exports: list[dict] = []
    for line in output.splitlines():
        line_s = line.strip()
        if not line_s or line_s.lower().startswith("export list"):
            continue
        parts = re.split(r"\s+", line_s, maxsplit=1)
        if len(parts) == 2:
            exports.append({"path": parts[0], "allowed_hosts": parts[1]})
        elif len(parts) == 1:
            exports.append({"path": parts[0], "allowed_hosts": ""})
    return exports


async def discover_smb_shares(server: str, username: str = "", password: str = "") -> list[dict]:
    def _run() -> list[dict]:
        cmd = ["smbclient", "-L", f"//{server}", "-g"]
        if username:
            cmd.extend(["-U", f"{username}%{password}"])
        else:
            cmd.append("-N")
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return _parse_smbclient_shares(out.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            log.warning("smb_discovery_failed", server=server, error=str(exc))
            return []
    return await asyncio.to_thread(_run)


async def discover_nfs_exports(server: str) -> list[dict]:
    def _run() -> list[dict]:
        try:
            out = subprocess.run(["showmount", "-e", server], capture_output=True, text=True, timeout=5)
            return _parse_showmount_output(out.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            log.warning("nfs_discovery_failed", server=server, error=str(exc))
            return []
    return await asyncio.to_thread(_run)


async def _probe_smb_host(ip: str, timeout: float = 1.5) -> dict | None:
    """Quick port-445 probe + hostname resolution. Returns None if not reachable."""
    def _probe() -> dict | None:
        import socket
        try:
            with socket.create_connection((ip, 445), timeout=timeout):
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except socket.herror:
                    hostname = ip
                return {"ip": ip, "hostname": hostname}
        except (OSError, socket.timeout):
            return None
    return await asyncio.to_thread(_probe)


async def discover_smb_servers(subnet: str, timeout: int = 10) -> list[dict]:
    """Scan subnet for SMB servers (port 445). `subnet` is CIDR like '10.0.0.0/24'."""
    import ipaddress
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []
    hosts = [str(h) for h in net.hosts()]
    if len(hosts) > 256:
        hosts = hosts[:256]  # safety cap
    tasks = [_probe_smb_host(h) for h in hosts]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except asyncio.TimeoutError:
        results = []
    return [r for r in results if isinstance(r, dict)]
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_mount_manager.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add core/mount_manager.py tests/test_mount_manager.py
git commit -m "feat(storage): SMB/NFS network discovery (smbclient -L, showmount -e)"
```

---

## Task 6: Mount Manager — startup remount + health monitoring

**Files:**
- Modify: `core/mount_manager.py`
- Modify: `core/scheduler.py`

**Context:** `remount_all_saved()` is called from the lifespan in Task 13. Health check runs every 5 minutes under `core/scheduler.py` — existing scheduler has 17 jobs after v0.23.6; this makes it 18. Health job MUST yield to active bulk jobs (existing pattern — see `get_all_active_jobs()` calls in other scheduler jobs).

- [ ] **Step 1: Implement `remount_all_saved()`**

Append to `MountManager`:

```python
async def remount_all_saved(self, credential_store) -> dict[str, bool]:
    """Re-mount every share in mounts.json using credential_store. Called in lifespan startup.

    Failures logged but do NOT block startup. Returns {share_name: ok}.
    """
    result: dict[str, bool] = {}
    shares = self._load_mounts_json().get("shares", {})
    for name, cfg in shares.items():
        try:
            creds = credential_store.get_credentials(name) if credential_store else None
            username, password = creds if creds else ("", "")
            mc = MountConfig(
                protocol=cfg.get("protocol", "smb"),
                server=cfg.get("server", ""),
                share=cfg.get("share", ""),
                username=username,
                password=password,
                options=cfg.get("options", {}),
            )
            mr = await self.mount_named(name, mc)
            result[name] = bool(getattr(mr, "ok", False))
        except Exception as exc:  # noqa: BLE001 — never block startup
            log.warning("remount_failed", share=name, error=str(exc))
            result[name] = False
    log.info("startup_remount_complete", result=result)
    return result
```

- [ ] **Step 2: Implement health check**

```python
# Module-level health state — read by the Storage page status dots
mount_health: dict[str, dict] = {}  # {name: {"ok": bool, "last_check": iso, "error": str|None}}


async def check_mount_health(manager: "MountManager") -> None:
    """Probe each mounted share with a 1-second listdir. Update mount_health dict."""
    from datetime import datetime, timezone
    for name in list(manager._load_mounts_json().get("shares", {}).keys()):
        mp = manager.share_mount_point(name)
        ok, err = True, None
        def _probe(path: str = mp) -> tuple[bool, str | None]:
            try:
                os.listdir(path)
                return True, None
            except (OSError, PermissionError) as exc:
                return False, str(exc)
        try:
            ok, err = await asyncio.wait_for(asyncio.to_thread(_probe), timeout=1.5)
        except asyncio.TimeoutError:
            ok, err = False, "probe timeout"
        mount_health[name] = {"ok": ok, "last_check": datetime.now(timezone.utc).isoformat(), "error": err}
```

- [ ] **Step 3: Register health job in `core/scheduler.py`**

Locate the scheduler setup (near where other 5-minute jobs are registered). Add:

```python
from core.mount_manager import check_mount_health, get_mount_manager

async def _mount_health_job():
    # Yield to active bulk jobs (MarkFlow convention — see docs/gotchas.md "database is locked")
    from core.bulk_worker import get_all_active_jobs
    if any(j.state in ("scanning", "running", "paused") for j in get_all_active_jobs().values()):
        return
    await check_mount_health(get_mount_manager())

scheduler.add_job(_mount_health_job, "interval", minutes=5, id="mount_health", max_instances=1, coalesce=True)
```

- [ ] **Step 4: Smoke test**

Append to `tests/test_mount_manager.py`:

```python
def test_mount_health_dict_is_module_level() -> None:
    from core.mount_manager import mount_health
    assert isinstance(mount_health, dict)
```

- [ ] **Step 5: Commit**

```bash
git add core/mount_manager.py core/scheduler.py tests/test_mount_manager.py
git commit -m "feat(storage): startup remount + 5-minute mount health probe"
```

---

## Task 7: Storage Manager — path validation

**Files:**
- Create: `core/storage_manager.py`
- Test: `tests/test_storage_manager.py`

**Context:** Validation runs in `asyncio.to_thread` to avoid blocking on slow NAS stat calls. Returns a `ValidationResult` dataclass. Error messages are USER-FACING — keep them plain English.

- [ ] **Step 1: Write failing tests**

Create `tests/test_storage_manager.py`:

```python
"""Unit tests for Storage Manager."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


def test_validate_missing_path(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path / "nonexistent"), PathRole.SOURCE))
    assert not result.ok
    assert any("doesn't exist" in e for e in result.errors)


def test_validate_readable_source(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path), PathRole.SOURCE))
    assert result.ok


def test_validate_empty_folder_warns(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path), PathRole.SOURCE))
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_validate_writable_output(tmp_path: Path) -> None:
    from core.storage_manager import validate_path, PathRole
    result = asyncio.run(validate_path(str(tmp_path), PathRole.OUTPUT))
    assert result.ok


def test_validate_same_path_rejected() -> None:
    from core.storage_manager import check_source_output_conflict
    errors = check_source_output_conflict("/a/b", "/a/b")
    assert any("same folder" in e.lower() for e in errors)


def test_validate_nested_path_rejected() -> None:
    from core.storage_manager import check_source_output_conflict
    errors = check_source_output_conflict("/a", "/a/sub")
    assert any("inside" in e.lower() for e in errors)


def test_long_path_warns() -> None:
    from core.storage_manager import _warn_long_path
    assert _warn_long_path("/a" * 200) is not None
    assert _warn_long_path("/short") is None
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_storage_manager.py -v`
Expected: collection errors.

- [ ] **Step 3: Implement the validation surface of `core/storage_manager.py`**

Create `core/storage_manager.py` (Tasks 7-9 all add to this file):

```python
"""Storage Manager: path validation, write-guard enforcement, config persistence."""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_LOW_SPACE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB
_LONG_PATH_CHARS = 240


class PathRole(Enum):
    SOURCE = "source"
    OUTPUT = "output"


@dataclass
class ValidationResult:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _warn_long_path(path: str) -> str | None:
    if len(path) > _LONG_PATH_CHARS:
        return "Very long path — some files may fail on Windows (260-char limit)."
    return None


def check_source_output_conflict(source: str, output: str) -> list[str]:
    errors: list[str] = []
    if not source or not output:
        return errors
    try:
        s = os.path.realpath(source)
        o = os.path.realpath(output)
    except OSError:
        return errors
    if s == o:
        errors.append("Input and output can't be the same folder.")
    elif o.startswith(s + os.sep):
        errors.append("Output folder is inside the input folder — this can cause loops.")
    elif s.startswith(o + os.sep):
        errors.append("Input folder is inside the output folder — this can cause loops.")
    return errors


def _validate_sync(path: str, role: PathRole) -> ValidationResult:
    res = ValidationResult(ok=False)
    if not path:
        res.errors.append("No path provided.")
        return res
    if not os.path.exists(path):
        res.errors.append(f"This folder doesn't exist: {path}")
        return res
    if not os.path.isdir(path):
        res.errors.append("This path is a file, not a folder.")
        return res
    if not os.access(path, os.R_OK):
        res.errors.append("MarkFlow can't read this folder — check permissions.")
        return res

    warn = _warn_long_path(path)
    if warn:
        res.warnings.append(warn)

    try:
        entries = os.listdir(path)
        res.stats["item_count"] = len(entries)
        if role is PathRole.SOURCE and not entries:
            res.warnings.append("This folder is empty — are you sure?")
    except OSError as exc:
        res.errors.append(f"MarkFlow can't list this folder: {exc}")
        return res

    if role is PathRole.OUTPUT:
        if not os.access(path, os.W_OK):
            res.errors.append("MarkFlow can't write to this folder — check permissions.")
            return res
        try:
            du = shutil.disk_usage(path)
            res.stats["free_space_bytes"] = du.free
            if du.free < _LOW_SPACE_BYTES:
                mb = du.free // (1024 * 1024)
                res.warnings.append(f"Low disk space on output drive ({mb} MB free).")
        except OSError:
            pass

    res.ok = True
    return res


async def validate_path(path: str, role: PathRole) -> ValidationResult:
    """Validate a path for its intended role. Runs in a thread to tolerate slow NAS stat."""
    return await asyncio.to_thread(_validate_sync, path, role)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_storage_manager.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/storage_manager.py tests/test_storage_manager.py
git commit -m "feat(storage): path validation with readable/writable/space/conflict checks"
```

---

## Task 8: Storage Manager — write guard + config persistence

**Files:**
- Modify: `core/storage_manager.py`
- Modify: `tests/test_storage_manager.py`

**Context:** The `is_write_allowed()` function is THE application-level security boundary for the broad `/host/rw` mount. Coverage in converter.py and bulk_worker.py is mandatory (Task 9). Configuration persists to DB preferences (existing `core/db/preferences.py`).

- [ ] **Step 1: Write failing tests for write guard**

Append to `tests/test_storage_manager.py`:

```python
def test_write_allowed_inside_output(monkeypatch, tmp_path: Path) -> None:
    from core import storage_manager as sm
    monkeypatch.setattr(sm, "_cached_output_path", str(tmp_path))
    assert sm.is_write_allowed(str(tmp_path / "sub" / "file.md"))


def test_write_denied_outside_output(monkeypatch, tmp_path: Path) -> None:
    from core import storage_manager as sm
    monkeypatch.setattr(sm, "_cached_output_path", str(tmp_path))
    assert not sm.is_write_allowed("/etc/passwd")


def test_write_denied_when_no_output_configured(monkeypatch) -> None:
    from core import storage_manager as sm
    monkeypatch.setattr(sm, "_cached_output_path", None)
    assert not sm.is_write_allowed("/anywhere/file")


def test_write_denied_for_symlink_escape(monkeypatch, tmp_path: Path) -> None:
    from core import storage_manager as sm
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    link = output / "escape"
    link.symlink_to(outside)
    monkeypatch.setattr(sm, "_cached_output_path", str(output))
    # Target that resolves outside output must be denied
    assert not sm.is_write_allowed(str(link / "file.md"))
```

- [ ] **Step 2: Run the new tests — expect failures**

Run: `pytest tests/test_storage_manager.py -k write -v`
Expected: collection error / AttributeError on `is_write_allowed`.

- [ ] **Step 3: Implement write guard + config surface**

Append to `core/storage_manager.py`:

```python
# ---------- Write guard ----------

_cached_output_path: str | None = None


class StorageWriteDenied(PermissionError):
    """Raised when a write target falls outside the configured output directory."""


def set_output_path(path: str | None) -> None:
    """Update the configured output directory. Called by the config layer."""
    global _cached_output_path
    _cached_output_path = os.path.realpath(path) if path else None
    log.info("output_path_updated", path=_cached_output_path)


def get_output_path() -> str | None:
    return _cached_output_path


def is_write_allowed(target_path: str) -> bool:
    """True iff target resolves to a location inside the configured output directory.

    SECURITY: This is the sole application-level restriction on the broad /host/rw
    Docker mount. Must be called before every file write in converter.py,
    bulk_worker.py, and any new write path.
    """
    if not _cached_output_path or not target_path:
        return False
    try:
        target_real = os.path.realpath(target_path)
    except OSError:
        return False
    base = _cached_output_path.rstrip(os.sep)
    return target_real == base or target_real.startswith(base + os.sep)


# ---------- Config persistence ----------

async def load_config_from_db() -> None:
    """Populate in-memory caches from DB prefs. Call during lifespan startup."""
    from core.preferences_cache import get_cached_preference
    output = await get_cached_preference("storage_output_path", default=None)
    set_output_path(output)
    log.info("storage_config_loaded", output=output)


async def save_output_path(path: str) -> None:
    """Persist output path to DB prefs + update in-memory cache + flag pending restart."""
    from datetime import datetime, timezone
    from core.preferences_cache import set_cached_preference
    old = _cached_output_path
    await set_cached_preference("storage_output_path", path)
    set_output_path(path)
    if old is not None and old != _cached_output_path:
        await set_cached_preference("pending_restart_reason", f"Output directory changed to {path}")
        await set_cached_preference("pending_restart_since", datetime.now(timezone.utc).isoformat())
        await set_cached_preference("pending_restart_dismissed_until", "")
```

Confirm that `core/preferences_cache.py` exposes async `get_cached_preference` / `set_cached_preference`. If the actual names differ, match the existing API — do not introduce new names.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_storage_manager.py -v`
Expected: all pass (11 tests across validation + guard).

- [ ] **Step 5: Commit**

```bash
git add core/storage_manager.py tests/test_storage_manager.py
git commit -m "feat(storage): write guard + config persistence (output-path cache)"
```

---

## Task 9: Write guard enforcement in converter + bulk_worker

**Files:**
- Modify: `core/converter.py`
- Modify: `core/bulk_worker.py`

**Context:** This is the critical security gate. Every file write in these two modules must call `is_write_allowed()` first. Missing coverage = sandbox escape. A code review after this task is mandatory (gate documented in the spec).

- [ ] **Step 1: Identify write call sites in converter.py**

Run: `grep -nE "open\(.*['\"]w|Path\(.*\)\.write_|shutil\.(copy|move)|os\.rename|os\.replace" core/converter.py`

Record the exact line numbers (leave as temporary TODO comments in the code if helpful):

```
core/converter.py:<line> — description
core/converter.py:<line> — description
```

- [ ] **Step 2: Wrap each write in a guard check**

Pattern to apply at each call site (example shown — apply to ALL write sites):

```python
from core.storage_manager import is_write_allowed, StorageWriteDenied  # add to imports

# ...existing code...

if not is_write_allowed(target_path):
    log.error("write_denied", target=target_path)
    raise StorageWriteDenied(f"Write denied — target outside configured output dir: {target_path}")

# existing write call follows:
with open(target_path, "w") as f:
    pass  # existing body
```

- [ ] **Step 3: Repeat for `core/bulk_worker.py`**

Same `grep` command, same wrapping pattern.

- [ ] **Step 4: Add coverage test**

Create `tests/test_write_guard_coverage.py`:

```python
"""Static check: every file-write call in converter.py / bulk_worker.py has a preceding guard."""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.mark.parametrize("target", ["core/converter.py", "core/bulk_worker.py"])
def test_all_writes_guarded(target: str) -> None:
    src = Path(target).read_text()
    write_patterns = [
        r"\bopen\([^)]*['\"][wa][b+]?['\"]",
        r"\.write_text\(",
        r"\.write_bytes\(",
        r"\bshutil\.copy[a-z]*\(",
        r"\bshutil\.move\(",
        r"\bos\.rename\(",
        r"\bos\.replace\(",
    ]
    combined = re.compile("|".join(write_patterns))
    for m in combined.finditer(src):
        start = max(0, src.rfind("\n", 0, m.start()) - 500)
        preceding = src[start:m.start()]
        assert "is_write_allowed(" in preceding or "# write-guard:skip" in preceding, (
            f"Unguarded write in {target} at char {m.start()}: {src[m.start():m.end()]!r}"
        )
```

The `# write-guard:skip` comment is an explicit opt-out for paths that are provably internal (e.g., writing to `/tmp`). Use sparingly; each must be justified.

- [ ] **Step 5: Run the coverage test**

Run: `pytest tests/test_write_guard_coverage.py -v`
Expected: pass. If it fails, fix the unguarded site before continuing.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -x --tb=short`
Expected: Pre-existing tests still pass. Task 9's write-guard may surface latent bugs — if a write fails because output isn't configured, that's the correct behavior; update the test's fixture to call `sm.set_output_path(str(tmp_path))`.

- [ ] **Step 7: Commit**

```bash
git add core/converter.py core/bulk_worker.py core/storage_manager.py tests/test_write_guard_coverage.py
git commit -m "feat(storage): enforce write guard at all converter + bulk_worker write sites"
```

---

## Task 10: API routes — host-info, browse, validate, sources, output, exclusions

**Files:**
- Create: `api/routes/storage.py`

**Context:** This is the larger half of the route surface. All routes require MANAGER role minimum. Path-traversal protection and null-byte rejection inherit from existing `browse.py` patterns — use `core/path_utils.py` helpers where possible.

- [ ] **Step 1: Create the router skeleton**

Create `api/routes/storage.py`:

```python
"""Consolidated Storage Manager API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.auth import Role, require_role
from core.host_detector import detect_host
from core.preferences_cache import get_cached_preference, set_cached_preference
from core import storage_manager as sm
from core.storage_manager import PathRole

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/storage", tags=["storage"])


# ---------- Host info ----------

@router.get("/host-info")
async def get_host_info(user=Depends(require_role(Role.MANAGER))) -> dict[str, Any]:
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


# ---------- Path validation ----------

class ValidateRequest(BaseModel):
    path: str
    role: str = Field(pattern="^(source|output)$")


@router.post("/validate")
async def validate(req: ValidateRequest, user=Depends(require_role(Role.MANAGER))) -> dict[str, Any]:
    role = PathRole.SOURCE if req.role == "source" else PathRole.OUTPUT
    result = await sm.validate_path(req.path, role)
    return {"ok": result.ok, "warnings": result.warnings, "errors": result.errors, "stats": result.stats}
```

- [ ] **Step 2: Add sources endpoints**

Append:

```python
# ---------- Sources ----------

class SourceIn(BaseModel):
    path: str
    label: str = ""


@router.get("/sources")
async def list_sources(user=Depends(require_role(Role.MANAGER))) -> dict:
    raw = await get_cached_preference("storage_sources_json", default="[]")
    import json
    return {"sources": json.loads(raw or "[]")}


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(src: SourceIn, user=Depends(require_role(Role.MANAGER))) -> dict:
    import json
    existing = json.loads(await get_cached_preference("storage_sources_json", default="[]") or "[]")
    v = await sm.validate_path(src.path, PathRole.SOURCE)
    if not v.ok:
        raise HTTPException(400, detail={"errors": v.errors, "warnings": v.warnings})
    sid = str(len(existing) + 1)
    entry = {"id": sid, "path": src.path, "label": src.label or src.path}
    existing.append(entry)
    await set_cached_preference("storage_sources_json", json.dumps(existing))
    return entry


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_source(source_id: str, user=Depends(require_role(Role.MANAGER))) -> None:
    import json
    existing = json.loads(await get_cached_preference("storage_sources_json", default="[]") or "[]")
    existing = [s for s in existing if s.get("id") != source_id]
    await set_cached_preference("storage_sources_json", json.dumps(existing))
```

- [ ] **Step 3: Add output + exclusions endpoints**

Append:

```python
# ---------- Output ----------

class OutputIn(BaseModel):
    path: str


@router.get("/output")
async def get_output(user=Depends(require_role(Role.MANAGER))) -> dict:
    return {"path": sm.get_output_path() or ""}


@router.put("/output")
async def set_output(out: OutputIn, user=Depends(require_role(Role.MANAGER))) -> dict:
    v = await sm.validate_path(out.path, PathRole.OUTPUT)
    if not v.ok:
        raise HTTPException(400, detail={"errors": v.errors, "warnings": v.warnings})
    await sm.save_output_path(out.path)
    return {"ok": True, "path": out.path}


# ---------- Exclusions ----------

class ExclusionIn(BaseModel):
    path_prefix: str


@router.get("/exclusions")
async def list_exclusions(user=Depends(require_role(Role.MANAGER))) -> dict:
    import json
    raw = await get_cached_preference("storage_exclusions_json", default="[]")
    return {"exclusions": json.loads(raw or "[]")}


@router.post("/exclusions", status_code=status.HTTP_201_CREATED)
async def add_exclusion(ex: ExclusionIn, user=Depends(require_role(Role.MANAGER))) -> dict:
    import json
    existing = json.loads(await get_cached_preference("storage_exclusions_json", default="[]") or "[]")
    eid = str(len(existing) + 1)
    entry = {"id": eid, "path_prefix": ex.path_prefix}
    existing.append(entry)
    await set_cached_preference("storage_exclusions_json", json.dumps(existing))
    return entry


@router.delete("/exclusions/{ex_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_exclusion(ex_id: str, user=Depends(require_role(Role.MANAGER))) -> None:
    import json
    existing = json.loads(await get_cached_preference("storage_exclusions_json", default="[]") or "[]")
    existing = [e for e in existing if e.get("id") != ex_id]
    await set_cached_preference("storage_exclusions_json", json.dumps(existing))
```

- [ ] **Step 4: Smoke test (manual, later in Task 13)**

Full integration tests for this router come in Phase 3 Task 22.

- [ ] **Step 5: Commit**

```bash
git add api/routes/storage.py
git commit -m "feat(storage): API — host-info, validate, sources, output, exclusions"
```

---

## Task 11: API routes — shares, discovery, credentials, health, restart, wizard

**Files:**
- Modify: `api/routes/storage.py`
- Modify: `core/mount_manager.py` (if needed for a getter)

**Context:** Completes the API surface. `wizard-status` encapsulates the trigger condition from the spec. `restart-dismiss` sets an ISO timestamp 1 hour in the future.

- [ ] **Step 1: Add shares endpoints**

Append to `api/routes/storage.py`:

```python
# ---------- Shares ----------

import asyncio
import os as _os
from core.mount_manager import (
    get_mount_manager,
    discover_smb_servers,
    discover_smb_shares,
    discover_nfs_exports,
    mount_health,
    MountConfig,
)
from core.credential_store import CredentialStore


class ShareIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    protocol: str = Field(pattern="^(smb|nfs)$")
    server: str
    share: str = ""
    username: str = ""
    password: str = ""
    options: dict = {}


def _credential_store() -> CredentialStore:
    secret = _os.environ.get("SECRET_KEY", "")
    return CredentialStore(secret_key=secret)


def _mask(value: str) -> str:
    return "****" if value else ""


@router.get("/shares")
async def list_shares(user=Depends(require_role(Role.MANAGER))) -> dict:
    mgr = get_mount_manager()
    shares_cfg = mgr._load_mounts_json().get("shares", {})
    return {
        "shares": [
            {
                "name": name,
                "protocol": cfg.get("protocol"),
                "server": cfg.get("server"),
                "share": cfg.get("share", ""),
                "username": _mask(cfg.get("username", "")),
                "password": _mask("x"),
                "status": mount_health.get(name, {"ok": None}),
            }
            for name, cfg in shares_cfg.items()
        ]
    }


@router.post("/shares", status_code=status.HTTP_201_CREATED)
async def add_share(share: ShareIn, user=Depends(require_role(Role.MANAGER))) -> dict:
    mgr = get_mount_manager()
    # Persist credentials first
    if share.username or share.password:
        _credential_store().save_credentials(share.name, share.protocol, share.username, share.password)
    cfg = MountConfig(
        protocol=share.protocol,
        server=share.server,
        share=share.share,
        username=share.username,
        password=share.password,
        options=share.options,
    )
    result = await mgr.mount_named(share.name, cfg)
    if not getattr(result, "ok", False):
        raise HTTPException(400, detail={"error": getattr(result, "error", "mount failed")})
    mgr._save_share_config(share.name, {
        "protocol": share.protocol,
        "server": share.server,
        "share": share.share,
        "options": share.options,
    })
    return {"ok": True, "name": share.name}


@router.delete("/shares/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_share(name: str, user=Depends(require_role(Role.MANAGER))) -> None:
    mgr = get_mount_manager()
    await mgr.unmount_named(name)
    mgr._remove_share_config(name)
    _credential_store().delete_credentials(name)


@router.post("/shares/discover")
async def discover(payload: dict, user=Depends(require_role(Role.MANAGER))) -> dict:
    scope = payload.get("scope", "subnet")
    if scope == "subnet":
        subnet = payload.get("subnet", "")
        servers = await discover_smb_servers(subnet)
        return {"servers": servers}
    if scope == "server":
        server = payload.get("server", "")
        protocol = payload.get("protocol", "smb")
        if protocol == "smb":
            shares = await discover_smb_shares(
                server,
                username=payload.get("username", ""),
                password=payload.get("password", ""),
            )
        else:
            shares = await discover_nfs_exports(server)
        return {"shares": shares}
    raise HTTPException(400, "scope must be subnet or server")


@router.post("/shares/{name}/test")
async def test_share(name: str, user=Depends(require_role(Role.MANAGER))) -> dict:
    mgr = get_mount_manager()
    mp = mgr.share_mount_point(name)
    try:
        items = await asyncio.to_thread(_os.listdir, mp)
        return {"ok": True, "item_count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.get("/shares/{name}/credentials")
async def get_share_creds(name: str, user=Depends(require_role(Role.ADMIN))) -> dict:
    creds = _credential_store().get_credentials(name)
    if not creds:
        raise HTTPException(404, "no credentials saved")
    return {"username": creds[0], "password": creds[1]}
```

(Add `_save_share_config` and `_remove_share_config` helpers to `core/mount_manager.py` if they don't exist — both operate on the v2 `mounts.json` schema from Task 4.)

- [ ] **Step 2: Add health + restart + wizard endpoints**

```python
# ---------- Health, restart, wizard ----------

from datetime import timedelta
import json as _json


@router.get("/health")
async def health(user=Depends(require_role(Role.MANAGER))) -> dict:
    return {"mounts": mount_health}


@router.get("/restart-status")
async def restart_status(user=Depends(require_role(Role.MANAGER))) -> dict:
    reason = await get_cached_preference("pending_restart_reason", default="")
    since = await get_cached_preference("pending_restart_since", default="")
    dismissed_until = await get_cached_preference("pending_restart_dismissed_until", default="")
    return {"reason": reason, "since": since, "dismissed_until": dismissed_until}


@router.post("/restart-dismiss")
async def restart_dismiss(user=Depends(require_role(Role.MANAGER))) -> dict:
    until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await set_cached_preference("pending_restart_dismissed_until", until)
    return {"dismissed_until": until}


@router.get("/wizard-status")
async def wizard_status(user=Depends(require_role(Role.MANAGER))) -> dict:
    if _os.environ.get("SKIP_FIRST_RUN_WIZARD") or _os.environ.get("DEV_BYPASS_AUTH") == "true":
        return {"show": False, "reason": "env-suppressed"}
    if await get_cached_preference("setup_wizard_dismissed", default="") == "true":
        return {"show": False, "reason": "dismissed"}
    sources = _json.loads(await get_cached_preference("storage_sources_json", default="[]") or "[]")
    output = sm.get_output_path()
    if sources or output:
        return {"show": False, "reason": "configured"}
    return {"show": True}


@router.post("/wizard-dismiss")
async def wizard_dismiss(user=Depends(require_role(Role.MANAGER))) -> dict:
    await set_cached_preference("setup_wizard_dismissed", "true")
    return {"ok": True}


@router.delete("/wizard-dismiss")
async def wizard_reopen(user=Depends(require_role(Role.ADMIN))) -> dict:
    await set_cached_preference("setup_wizard_dismissed", "")
    return {"ok": True}
```

- [ ] **Step 3: Commit**

```bash
git add api/routes/storage.py core/mount_manager.py
git commit -m "feat(storage): API — shares, discovery, credentials, health, restart, wizard"
```

---

## Task 12: DB preference defaults

**Files:**
- Modify: `core/db/preferences.py`

**Context:** Add defaults for the new preferences referenced by the API. They must exist in `DEFAULT_PREFERENCES` so `_seed_defaults()` populates them on fresh installs.

- [ ] **Step 1: Add new entries to `DEFAULT_PREFERENCES`**

Open `core/db/preferences.py`. In the `DEFAULT_PREFERENCES` dict, add:

```python
    # --- Universal Storage Manager (v0.25.0) ---
    "storage_output_path": "",
    "storage_sources_json": "[]",
    "storage_exclusions_json": "[]",
    "pending_restart_reason": "",
    "pending_restart_since": "",
    "pending_restart_dismissed_until": "",
    "setup_wizard_dismissed": "",
    "host_os_override": "",
```

- [ ] **Step 2: Smoke test — fresh preferences include the new keys**

```python
def test_storage_defaults_present() -> None:
    from core.db.preferences import DEFAULT_PREFERENCES
    for k in (
        "storage_output_path",
        "storage_sources_json",
        "storage_exclusions_json",
        "pending_restart_reason",
        "setup_wizard_dismissed",
    ):
        assert k in DEFAULT_PREFERENCES
```

Add to a sensible existing test module (e.g., `tests/test_preferences_defaults.py` if it exists, else append to `tests/test_storage_manager.py`).

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_storage_manager.py -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add core/db/preferences.py tests/test_storage_manager.py
git commit -m "feat(storage): default DB prefs for storage config + wizard + restart"
```

---

## Task 13: main.py wiring + lifespan startup

**Files:**
- Modify: `main.py`

**Context:** Lifespan order: DB init → `storage_manager.load_config_from_db()` → `mount_manager.remount_all_saved()` → scheduler start. Re-mounts happen AFTER DB init (to read stored configs) but BEFORE scheduler (because the health job reads mount state). Route mount is separate and goes with the other `include_router` calls.

- [ ] **Step 1: Import the router and storage manager**

In `main.py` near the other route imports:

```python
from api.routes import storage as storage_routes
from core import storage_manager as sm
from core.mount_manager import get_mount_manager
from core.credential_store import CredentialStore
```

- [ ] **Step 2: Mount the router**

In the `include_router` block (~line 336+):

```python
app.include_router(storage_routes.router)
```

- [ ] **Step 3: Wire into lifespan**

In the `async def lifespan(app: FastAPI):` body, AFTER DB init but BEFORE `scheduler.start()`, add:

```python
# Universal Storage Manager startup (v0.25.0)
try:
    await sm.load_config_from_db()
except Exception as exc:  # noqa: BLE001
    log.warning("storage_config_load_failed", error=str(exc))

try:
    creds = CredentialStore(secret_key=os.environ.get("SECRET_KEY", ""))
    remount_result = await get_mount_manager().remount_all_saved(creds)
    log.info("storage_remount_complete", result=remount_result)
except Exception as exc:  # noqa: BLE001 — never block startup
    log.warning("storage_remount_failed", error=str(exc))
```

- [ ] **Step 4: Confirm the app boots**

Run (from inside the container, or locally if your setup allows):

```
python -c "import main; print('import ok')"
```

Expected: `import ok`. Any ImportError means a missing dependency — fix before proceeding.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(storage): lifespan — load config, remount saved shares, mount router"
```

---

## PHASE 1 HUMAN GATE

Before starting Phase 2, **stop here** and request human review of:

1. Write-guard coverage in converter.py + bulk_worker.py (Task 9 coverage test PASSES, but human eyes on grep output).
2. docker-compose.yml diff (Task 1 — broad mounts + SYS_ADMIN).
3. Credential store key-rotation behavior (Task 3 — wrong key behaves as empty, not error).
4. Smoke test the API: `curl` the new endpoints with a MANAGER-role token.

Agenda-worthy questions to raise:
- Does the `/host/rw` mount need SELinux relabeling on any target OS?
- Is `SECRET_KEY` rotation documented anywhere the user will see? (If not, Phase 3 docs should cover it.)

Proceed to Phase 2 only after explicit approval.

---

# PHASE 2 — UI (Frontend)

## Task 14: Storage page HTML + CSS skeleton

**Files:**
- Create: `static/storage.html`
- Modify: `static/markflow.css`

**Context:** Match the visual/structural pattern of `static/settings.html`. All sections collapsible. Accessibility: proper semantic HTML, buttons (not divs), labels associated with inputs.

- [ ] **Step 1: Create `static/storage.html`**

Use the existing `static/settings.html` as a structural template. Reuse CSS classes (`.card`, `.section-header`, `.table-compact`, `.badge`, `.btn`, `.btn-danger`) from `static/markflow.css`.

Key landmarks:

```html
<header class="page-header">
  <h1>Storage</h1>
  <span id="host-os-badge" class="badge">Detecting…</span>
  <button id="btn-run-wizard" class="btn">Run Setup Wizard</button>
</header>

<section id="quick-access" class="card collapsible"></section>
<section id="sources" class="card collapsible"></section>
<section id="output" class="card collapsible"></section>
<section id="shares" class="card collapsible"></section>
<section id="exclusions" class="card collapsible"></section>
<section id="cloud-prefetch" class="card collapsible"></section>

<div id="fs-browser-modal" class="modal" hidden></div>
<div id="wizard-modal" class="modal" hidden></div>
```

Populate each section with a heading, a summary-counts div, and a slot for JS-rendered content. Do NOT build content inline — let `storage.js` render it (Task 15). Wizard markup is added in Task 17.

- [ ] **Step 2: Add storage-specific styles to `static/markflow.css`**

Add a new section `/* ===== Storage page ===== */` with styles for:
- `.quick-access-grid` — responsive card grid
- `.mount-status-dot` — green/amber/red status indicator
- `.fs-breadcrumb`
- `.wizard-step`
- `.restart-banner` (for status bar use in Task 18)

- [ ] **Step 3: Commit**

```bash
git add static/storage.html static/markflow.css
git commit -m "feat(storage): Storage page HTML + CSS skeleton"
```

---

## Task 15: Storage page JS — host info, browser, sources, output, exclusions

**Files:**
- Create: `static/js/storage.js`

**Context:** Vanilla JS. Use `fetch` against the `/api/storage/*` endpoints from Task 10. Auth cookie is sent automatically. Use the existing `parseUTC()` helper (in `app.js`) for any timestamps from the backend — do NOT use `new Date(iso)` directly per the CLAUDE.md gotcha. Never assign `innerHTML` from fetched data — build nodes with `document.createElement` or use `textContent` / `replaceChildren` for safe clearing.

- [ ] **Step 1: Skeleton + host info loader**

```js
// static/js/storage.js
(async function initStorage() {
  const badge = document.getElementById('host-os-badge');
  try {
    const res = await fetch('/api/storage/host-info');
    if (!res.ok) throw new Error(res.statusText);
    const info = await res.json();
    badge.textContent = `Detected: ${prettyOS(info.os)}`;
    renderQuickAccess(info.quick_access);
  } catch (e) {
    badge.textContent = 'OS unknown';
    console.warn('host-info failed', e);
  }
  wireBrowser();
  loadSources();
  loadOutput();
  loadExclusions();
  document.getElementById('btn-run-wizard').addEventListener('click', openWizard);
})();

function prettyOS(code) {
  return ({windows: 'Windows', wsl: 'Windows (WSL)', macos: 'macOS', linux: 'Linux', unknown: 'Unknown'})[code] || code;
}
```

- [ ] **Step 2: Safe list-clearing helper + row builder**

```js
function clearChildren(el) {
  el.replaceChildren();
}

function makeRow(cells) {
  const tr = document.createElement('tr');
  for (const c of cells) {
    const td = document.createElement('td');
    if (c instanceof Node) td.appendChild(c);
    else td.textContent = String(c ?? '');
    tr.appendChild(td);
  }
  return tr;
}
```

All further rendering functions use `clearChildren` + `appendChild` — never `innerHTML` on fetched data.

- [ ] **Step 3: Sources / output / exclusions CRUD**

Implement `loadSources`, `addSource`, `removeSource`, `loadOutput`, `setOutput`, `loadExclusions`, `addExclusion`, `removeExclusion` using fetch + `/api/storage/*` routes. Render into the DOM elements from Task 14. Each uses `clearChildren()` + `appendChild(makeRow(...))`.

- [ ] **Step 4: Filesystem browser**

Recursive tree with breadcrumb. Reuse `/api/browse` endpoint (to be extended in Phase 3 Task 21 to accept `/host/root` paths — until then, the browser works against legacy paths only).

Key behaviors:
- Click a directory → fetch children, expand
- "Use as Source" / "Use as Output" buttons per directory
- Validation spinner while `/api/storage/validate` is pending

Render by building `<li>` nodes with `createElement` + `textContent`. Never concatenate paths into a template string and assign to a parent container.

- [ ] **Step 5: Commit**

```bash
git add static/js/storage.js
git commit -m "feat(storage): Storage page JS — host info, browser, sources/output/exclusions"
```

---

## Task 16: Storage page JS — shares, discovery, credentials

**Files:**
- Modify: `static/js/storage.js`

**Context:** Network share config form with protocol radios (SMB/NFS), server/share/user/pass inputs, Test button. Discovery UI: "Scan My Network" (subnet scan) + manual "Server" probe. Like Task 15, render all list/table data with `createElement`, never string concatenation.

- [ ] **Step 1: Share list rendering**

```js
async function loadShares() {
  const res = await fetch('/api/storage/shares');
  const { shares } = await res.json();
  const tbody = document.querySelector('#shares-table tbody');
  clearChildren(tbody);
  for (const s of shares) tbody.appendChild(shareRow(s));
}

function shareRow(s) {
  const statusDot = document.createElement('span');
  statusDot.className = 'mount-status-dot ' + (s.status?.ok ? 'ok' : s.status?.ok === false ? 'err' : 'unknown');
  const editBtn = document.createElement('button');
  editBtn.className = 'btn';
  editBtn.textContent = 'Edit';
  editBtn.addEventListener('click', () => openShareEditor(s.name));
  const rmBtn = document.createElement('button');
  rmBtn.className = 'btn btn-danger';
  rmBtn.textContent = 'Remove';
  rmBtn.addEventListener('click', () => removeShare(s.name));
  const actions = document.createElement('div');
  actions.append(editBtn, rmBtn);
  return makeRow([s.name, s.protocol, s.server, statusDot, actions]);
}
```

- [ ] **Step 2: Add-share form**

Button opens a modal. On submit:
```js
await fetch('/api/storage/shares', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({name, protocol, server, share, username, password}),
});
```
Poll `/api/storage/health` after a successful add for up to 10 seconds to show the first health result.

- [ ] **Step 3: Discovery UI**

Two buttons in the Shares section:
1. "Scan my network" — prompts for subnet (default from host IP if detectable), calls `POST /api/storage/shares/discover` with `{scope: 'subnet', subnet}`.
2. "Probe a server" — server address input, calls `{scope: 'server', server, protocol}`.

Results render as a clickable list (built via `createElement`). Clicking a discovered share pre-fills the add-share form.

- [ ] **Step 4: Credentials edit flow**

Edit button on a share row opens the form with fields pre-filled from `GET /api/storage/shares/{name}/credentials` (admin-only; non-admin sees masked). Save button calls `POST /api/storage/shares` (upsert).

- [ ] **Step 5: Commit**

```bash
git add static/js/storage.js
git commit -m "feat(storage): Storage page JS — shares, discovery, credentials"
```

---

## Task 17: First-run wizard overlay

**Files:**
- Modify: `static/js/storage.js`
- Modify: `static/storage.html` (wizard markup)
- Modify: `static/markflow.css` (wizard styles)

**Context:** Wizard is an overlay on the Storage page, not a separate page. Triggers on first visit when `/api/storage/wizard-status` returns `show: true`. Button in the Storage page header also opens it.

- [ ] **Step 1: Wizard markup in `static/storage.html`**

Populate `#wizard-modal` with 5 steps, each a `<div class="wizard-step" data-step="N" hidden></div>`. Step 1 (welcome), 2 (source), 3 (output), 4 (network — optional), 5 (summary). Use semantic `<section>` or `<div>` with `<h2>` / `<p>` / form fields. Buttons: `Continue`, `Back`, `Skip`.

- [ ] **Step 2: Wizard JS**

```js
async function maybeAutoOpenWizard() {
  const r = await fetch('/api/storage/wizard-status').then(r => r.json());
  if (r.show) openWizard();
}

function openWizard() {
  showStep(1);
  document.getElementById('wizard-modal').hidden = false;
}

function showStep(n) {
  for (const el of document.querySelectorAll('.wizard-step')) {
    el.hidden = Number(el.dataset.step) !== n;
  }
}

async function wizardSkip() {
  await fetch('/api/storage/wizard-dismiss', { method: 'POST' });
  closeWizard();
}

function closeWizard() {
  document.getElementById('wizard-modal').hidden = true;
}
```

Each step's "Continue" button validates (calling `/api/storage/validate`) before advancing.

On step 5, "Start Using MarkFlow" closes the wizard; it does NOT set `setup_wizard_dismissed` (re-opening via the header button should always work; natural dismissal happens because sources/output are now configured and `wizard-status` returns `{show: false, reason: "configured"}`).

- [ ] **Step 3: Call `maybeAutoOpenWizard()` from the init IIFE**

In the init block from Task 15, after `loadExclusions()`:
```js
  maybeAutoOpenWizard();
```

- [ ] **Step 4: Commit**

```bash
git add static/js/storage.js static/storage.html static/markflow.css
git commit -m "feat(storage): first-run wizard overlay (5-step onboarding)"
```

---

## Task 18: Global status bar restart banner + nav item

**Files:**
- Modify: `static/js/global-status-bar.js`
- Modify: `static/app.js`

**Context:** Status bar already polls for pipeline state. Add a second poll for restart state. Banner should be visually distinct from existing pipeline banners (amber, not red or blue). Build banner DOM nodes with `createElement` — do not inject HTML strings.

- [ ] **Step 1: Add restart poll to `global-status-bar.js`**

```js
async function pollRestartStatus() {
  try {
    const r = await fetch('/api/storage/restart-status');
    if (!r.ok) return;
    const { reason, since, dismissed_until } = await r.json();
    if (!reason) { hideRestartBanner(); return; }
    if (dismissed_until && parseUTC(dismissed_until) > new Date()) { hideRestartBanner(); return; }
    showRestartBanner(reason, since);
  } catch (_) { /* ignore */ }
}
setInterval(pollRestartStatus, 60_000);
pollRestartStatus();

function showRestartBanner(reason, sinceISO) {
  let banner = document.getElementById('restart-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'restart-banner';
    banner.className = 'restart-banner';
    document.body.prepend(banner);
  }
  banner.replaceChildren();
  const title = document.createElement('strong');
  title.textContent = 'RESTART REQUIRED — ';
  const msg = document.createElement('span');
  msg.textContent = reason;
  const dismiss = document.createElement('button');
  dismiss.textContent = 'Remind Me Later';
  dismiss.addEventListener('click', async () => {
    await fetch('/api/storage/restart-dismiss', { method: 'POST' });
    hideRestartBanner();
  });
  const meta = document.createElement('span');
  meta.className = 'meta';
  meta.textContent = sinceISO ? ` (changed ${relTime(parseUTC(sinceISO))})` : '';
  banner.append(title, msg, meta, dismiss);
}

function hideRestartBanner() {
  const b = document.getElementById('restart-banner');
  if (b) b.remove();
}
```

- [ ] **Step 2: Add Storage nav item in `static/app.js`**

Locate the nav bar definition. Add (in alphabetical or logical position — before "Settings"):

```js
{ href: '/storage.html', label: 'Storage', icon: 'folder' },
```

- [ ] **Step 3: Commit**

```bash
git add static/js/global-status-bar.js static/app.js
git commit -m "feat(storage): global status-bar restart banner + Storage nav item"
```

---

## Task 19: Phase 2 manual smoke

**Files:** none (manual test)

**Context:** Phase 2 UI needs human exercise before Phase 3 migration removes Settings-page sections users may still expect.

- [ ] **Step 1: Rebuild container**

```bash
docker-compose build && docker-compose up -d
```

- [ ] **Step 2: Exercise each section**

Open `http://localhost:8000/storage.html`. Verify:
- [ ] OS badge shows the correct host OS
- [ ] Quick Access cards list your home dir / drive letters
- [ ] Filesystem browser navigates /host/root without 403
- [ ] Add a source, add an output — see them persist after a page reload
- [ ] Add an SMB share (if you have one) — see green status dot within 5 min
- [ ] Discovery: "Scan my network" returns hits on the expected subnet
- [ ] First-run wizard: clear via `DELETE /api/storage/wizard-dismiss` then reload — wizard auto-opens
- [ ] Change output → amber banner appears on other pages within 60s
- [ ] "Remind me later" on the banner hides it for 1 hour

- [ ] **Step 3: No code change — report results to human gate**

Phase 3 begins only after all smoke tests pass.

---

# PHASE 3 — Migration & Polish

## Task 20: Settings page — remove storage sections, add link card

**Files:**
- Modify: `static/settings.html`

**Context:** The spec calls out exactly which sections move (Locations, Location Exclusions, Network Share Mounts, Cloud Prefetch) and which stay. Don't delete JS handlers that are still referenced by remaining sections — verify each handler before removing.

- [ ] **Step 1: Identify sections to remove**

Search `static/settings.html` for the four section anchors. Record the line ranges.

- [ ] **Step 2: Replace with a link card**

At the top of the Settings page (first card position):

```html
<section class="card">
  <h2>Storage</h2>
  <p>
    Manage source locations, output directory, network shares, and cloud prefetch
    settings on the Storage page.
  </p>
  <a class="btn btn-primary" href="/storage.html">Open Storage Page →</a>
</section>
```

Remove the four storage-section blocks. Keep any handlers in the Settings JS that are ONLY used by those sections (clean them up); keep handlers shared with remaining sections.

- [ ] **Step 3: Smoke test the Settings page**

Reload `/settings.html`. Confirm:
- Storage link card visible at top
- Remaining sections (Conversion, Pipeline, Search, LLM Providers, Lifecycle, Logging, Auth) render without JS errors
- DevTools console: no `Uncaught ReferenceError` or 404s

- [ ] **Step 4: Commit**

```bash
git add static/settings.html
git commit -m "refactor(settings): remove storage sections, link to Storage page"
```

---

## Task 21: Browse API extension + path_utils

**Files:**
- Modify: `api/routes/browse.py`
- Modify: `core/path_utils.py`

**Context:** The existing `ALLOWED_BROWSE_ROOTS = ["/host", "/mnt/output-repo"]` already permits `/host/root` via prefix match, but confirm. Update `core/path_utils.py` to make the write guard authoritative (not the browse guard).

- [ ] **Step 1: Confirm browse allowed-roots**

Open `api/routes/browse.py:23`. Verify `ALLOWED_BROWSE_ROOTS` still includes `/host`. Add a clarifying comment noting the two subpaths:

```python
# /host covers both /host/root (read-only browse) and /host/rw (write target)
ALLOWED_BROWSE_ROOTS = ["/host", "/mnt/output-repo"]
```

No change to the list itself — `/host/root` and `/host/rw` are prefix-covered by `/host`.

- [ ] **Step 2: Update `core/path_utils.py`**

If `core/path_utils.py` has its own allowed-roots list, align it with browse.py. If it has write-specific helpers, make them defer to `storage_manager.is_write_allowed()` rather than duplicating the logic.

- [ ] **Step 3: Commit**

```bash
git add api/routes/browse.py core/path_utils.py
git commit -m "refactor(storage): unify browse + write-guard allowed-roots"
```

---

## Task 22: Integration tests for storage API

**Files:**
- Create: `tests/test_storage_api.py`

**Context:** End-to-end HTTP tests for `/api/storage/*`. Use FastAPI's TestClient pattern (follow existing `tests/test_api_*.py` conventions). Mock `CredentialStore` with an in-memory implementation for speed.

- [ ] **Step 1: Write the integration tests**

```python
"""Integration tests for /api/storage/* endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Mock SECRET_KEY and credential store path; bypass auth per DEV_BYPASS_AUTH
    monkeypatch.setenv("SECRET_KEY", "test-" + "x" * 32)
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    from main import app
    return TestClient(app)


def test_host_info(client):
    r = client.get("/api/storage/host-info")
    assert r.status_code == 200
    body = r.json()
    assert "os" in body
    assert "quick_access" in body


def test_validate_missing_path(client):
    r = client.post("/api/storage/validate", json={"path": "/nonexistent", "role": "source"})
    assert r.status_code == 200
    assert not r.json()["ok"]


def test_add_and_remove_source(client, tmp_path):
    r = client.post("/api/storage/sources", json={"path": str(tmp_path), "label": "test"})
    assert r.status_code == 201
    sid = r.json()["id"]
    r2 = client.get("/api/storage/sources")
    assert any(s["id"] == sid for s in r2.json()["sources"])
    r3 = client.delete(f"/api/storage/sources/{sid}")
    assert r3.status_code == 204


def test_set_output_triggers_restart_flag(client, tmp_path):
    # Setting output for the first time does NOT set the flag; changing it does.
    client.put("/api/storage/output", json={"path": str(tmp_path)})
    new = tmp_path / "other"
    new.mkdir()
    client.put("/api/storage/output", json={"path": str(new)})
    r = client.get("/api/storage/restart-status")
    assert r.json()["reason"]


def test_wizard_status_suppressed_in_dev_bypass(client):
    r = client.get("/api/storage/wizard-status")
    assert r.json()["show"] is False
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_storage_api.py -v`
Expected: 5 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_storage_api.py
git commit -m "test(storage): integration tests for /api/storage/* endpoints"
```

---

## Task 23: Help article

**Files:**
- Create (or modify): `docs/help/storage.md`
- Modify: `docs/help/_index.json`

**Context:** In-app help drawer. Match existing help article style (see `docs/help/getting-started.md` for tone).

- [ ] **Step 1: Write `docs/help/storage.md`**

Sections: Overview, First-time setup, Changing source/output, Adding a network share, Troubleshooting (mount failures, restart-required banner). Keep under ~300 lines.

- [ ] **Step 2: Register in `docs/help/_index.json`**

Add an entry for `storage.md` in the TOC, positioned between "Document Conversion" and "Bulk Conversion".

- [ ] **Step 3: Verify it renders**

Reload `/help.html`. Navigate to the new article. Check formatting.

- [ ] **Step 4: Commit**

```bash
git add docs/help/storage.md docs/help/_index.json
git commit -m "docs(help): Storage page help article"
```

---

## Task 24: Version bump, CLAUDE.md, gotchas, version-history

**Files:**
- Modify: `core/version.py`
- Modify: `CLAUDE.md`
- Modify: `docs/version-history.md`
- Modify: `docs/gotchas.md`
- Modify: `docs/key-files.md`

**Context:** Per project convention, each release moves the outgoing "Current Version" block from CLAUDE.md into version-history.md, and CLAUDE.md gets the new version block.

- [ ] **Step 1: Bump version**

In `core/version.py` set `VERSION = "0.25.0"`.

- [ ] **Step 2: Write v0.25.0 entry in `docs/version-history.md`**

Full context entry at the top (before the existing v0.24.2 block). Include:
- Problem statement (barrier for non-technical users)
- Solution overview (three layers: Docker / app / UI)
- Files created
- Files modified
- Security notes (SYS_ADMIN, /host/rw, write guard coverage)
- New gotchas added

- [ ] **Step 3: Move v0.24.2 block from CLAUDE.md into version-history.md**

Paste v0.24.2 into version-history.md below the new v0.25.0 entry. Replace CLAUDE.md's "Current Version" with v0.25.0 summary (~30-60 lines).

- [ ] **Step 4: Add gotchas**

Append to `docs/gotchas.md` under a new "Universal Storage Manager" section:

```
- The `/host/rw` mount is SECURITY-CRITICAL: every write in converter.py /
  bulk_worker.py / transcript_formatter.py MUST call
  storage_manager.is_write_allowed() before opening in write mode. Missing
  coverage = container-level sandbox escape. Covered today by
  tests/test_write_guard_coverage.py — keep it green.
- SYS_ADMIN cap is required for runtime NFS/SMB mount; dropping it
  silently breaks mount_manager.mount_named() with a cryptic
  "operation not permitted". Keep it in docker-compose.yml.
- SECRET_KEY rotation invalidates credentials.enc: on first startup after
  a key change, remount_all_saved() will log "credential_store_load_failed"
  for every share. Users must re-enter passwords via the Storage page. Do NOT
  auto-delete the file — the user may have a backup key.
- mounts.json schema v1 → v2 migration is one-way: v2 writes always
  use the {_schema_version: 2, shares: {...}} envelope. If you roll back
  across v0.25.0, copy mounts.json aside first.
```

- [ ] **Step 5: Update key-files.md**

Add rows for the new files (`core/host_detector.py`, `core/credential_store.py`, `core/storage_manager.py`, `api/routes/storage.py`, `static/storage.html`, `static/js/storage.js`).

- [ ] **Step 6: Commit**

```bash
git add core/version.py CLAUDE.md docs/version-history.md docs/gotchas.md docs/key-files.md
git commit -m "release: v0.25.0 — Universal Storage Manager"
```

---

# Self-Review Checklist

Run through before declaring the plan complete:

- [ ] **Spec coverage**: Every section in `2026-04-21-universal-storage-manager-design.md` maps to at least one task. Spec §1 (Docker) → Task 1. §2 (Host detection) → Task 2. §3 (Storage Manager) → Tasks 7–9. §4 (Credential Store) → Task 3. §5 (Mount Manager) → Tasks 4–6. §6 (API) → Tasks 10–11. §7 (Restart Notification) → Tasks 11 (API) + 18 (UI). §8 (Storage Page) → Tasks 14–16. §9 (First-Run Wizard) → Task 17. §10 (Settings Migration) → Task 20.
- [ ] **No placeholders**: no "TODO", "implement later", "fill in details" outside of justified `<line>` line-number references the engineer will discover.
- [ ] **Type consistency**: `ValidationResult`, `PathRole`, `HostInfo`, `MountConfig` used consistently. `is_write_allowed()` (not `is_allowed_write`). `share_mount_point()` consistently spelled.
- [ ] **Bite-sized steps**: each step is 2-5 minutes.
- [ ] **TDD**: Tasks 2, 3, 5, 7, 8, 9, 12, 22 lead with a failing test.

---

# Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-21-universal-storage-manager.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — Fresh implementer subagent per task, two-stage review (spec then quality) after each. Best for large plans where controller context budget matters.
2. **Inline Execution** — Batch execution in this session using `superpowers:executing-plans`, with checkpoints for review.

**Phase-gate recommendation:** Regardless of execution style, STOP at the Phase 1 HUMAN GATE after Task 13. Phase 1 is security-sensitive (broad mounts + SYS_ADMIN + write guard). Human review of the write-guard grep output and compose diff before exposing the broad mount is non-negotiable.
