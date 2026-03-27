# MarkFlow Changeset: Directory Browser
# Browse local drives from the web UI when selecting source and output locations

**Version:** v1.0
**Targets:** v0.7.2 tag
**Prerequisite:** Named Locations changeset complete — tagged v0.7.1
**Scope:** Focused changeset. One new API endpoint, one reusable UI widget, docker-compose
update, and integration into the Locations page. No conversion logic changes.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. This changeset solves a specific UX problem:
the user cannot browse their local Windows filesystem from the Locations page because the
container only sees what is explicitly mounted. The solution has two parts:

1. Mount Windows drives broadly into the container at known paths
2. Add a server-side directory listing API + a client-side folder picker widget

The folder picker is used on `locations.html` when adding or editing a location path.
It is NOT used anywhere else unless a future changeset explicitly extends it.

---

## 1. Docker Compose — Drive Mounts

### `docker-compose.yml` (modify)

Mount common Windows drive letters into the container under `/host/`. All mounts are
read-only — MarkFlow never writes to source drives.

```yaml
services:
  app:
    volumes:
      - markflow-db:/app/data
      - ./logs:/app/logs
      - ./output:/app/output
      # Host drive mounts — read-only
      # Add or remove drive letters to match your machine
      - C:/:/host/c:ro
      - D:/:/host/d:ro
      # Output repo — read-write (user configures this path)
      - C:/Users/${USERNAME:-user}/markflow-output:/mnt/output-repo
```

Add a comment block above the drive mounts:

```yaml
      # ---------------------------------------------------------------
      # HOST DRIVE MOUNTS
      # These make your Windows drives visible inside the container at
      # /host/c, /host/d, etc. Add a line for each drive letter you
      # want MarkFlow to be able to read from.
      #
      # Format: DriveLetter:/:/host/driveletter:ro
      # Example for E: drive: E:/:/host/e:ro
      #
      # Docker Desktop must have file sharing enabled for each drive.
      # Settings → Resources → File Sharing
      # ---------------------------------------------------------------
```

### `.env.example` (modify)

Add:
```bash
# Drive letters mounted into the container (comma-separated, lowercase)
# Add a volume entry in docker-compose.yml for each letter listed here
MOUNTED_DRIVES=c,d
```

### `README.md` or `docs/drive-setup.md` (new)

Create a short setup doc:

```markdown
# Mounting Your Drives

MarkFlow runs inside Docker and can only access folders you explicitly share with it.

## Setup (Windows)

1. Open Docker Desktop → Settings → Resources → File Sharing
2. Add each drive you want MarkFlow to read from (C:\, D:\, etc.)
3. Click Apply & Restart

4. In docker-compose.yml, add a volume line for each drive:
      - C:/:/host/c:ro
      - D:/:/host/d:ro

5. Restart MarkFlow:
      docker-compose down && docker-compose up -d

## In MarkFlow

Once drives are mounted, go to Locations and click "Browse" to
pick a folder visually — no need to type container paths manually.

Your drives appear as:
  C:\ → /host/c
  D:\ → /host/d

## Output Folder

Your output folder needs to be writable. The default is:
  C:\Users\{YourName}\markflow-output → /mnt/output-repo

Change this in docker-compose.yml if you want output elsewhere.
```

---

## 2. Backend — Directory Browser API

### `api/routes/browse.py` (new file)

Router with prefix `/api/browse`. Mount in `main.py`.

**`GET /api/browse`**

Query params:
- `path` — container-side path to list. Default: `/host` (shows available drive mounts).
- `show_files` — `true`/`false` (default `false`). When false, only directories are returned.
  The folder picker only needs directories. Files are shown only if explicitly requested.

Response:
```json
{
  "path": "/host/c/Users/Xerxes/T86_Work",
  "parent": "/host/c/Users/Xerxes",
  "is_root": false,
  "entries": [
    {
      "name": "k_drv_test",
      "path": "/host/c/Users/Xerxes/T86_Work/k_drv_test",
      "type": "directory",
      "readable": true,
      "item_count": 142
    },
    {
      "name": "old_project",
      "path": "/host/c/Users/Xerxes/T86_Work/old_project",
      "type": "directory",
      "readable": true,
      "item_count": 38
    }
  ],
  "drives": [
    {"name": "C:", "path": "/host/c", "mounted": true},
    {"name": "D:", "path": "/host/d", "mounted": true},
    {"name": "E:", "path": "/host/e", "mounted": false}
  ]
}
```

**Field details:**

`path` — the path that was listed (normalized, no trailing slash)

`parent` — parent directory path. At `/host`, parent is null and `is_root` is true.

`is_root` — true only when path is `/host` (the drive selector level)

`entries` — sorted: directories first, then files (if `show_files=true`), each alphabetical.
- `readable`: whether `os.listdir()` succeeds on the entry
- `item_count`: `len(os.listdir(entry_path))` — count of immediate children. Cap at 10ms per
  entry using a quick timeout; return `null` if too slow. Never recurse for this count.

`drives` — always returned regardless of current path. Shows which drive letters are mounted
at `/host/`. Detected by checking `MOUNTED_DRIVES` env var (comma-separated list of drive
letters, e.g. `c,d,e`). `mounted: true` means `/host/{letter}` exists and is accessible.

**Error responses:**

- Path doesn't exist: 404 `{"error": "not_found", "path": "..."}`
- Path exists but not readable: 403 `{"error": "not_readable", "path": "...", "message": "Permission denied"}`
- Path is outside `/host` and not `/mnt/output-repo`: 403 `{"error": "path_not_allowed",
  "message": "Browsing is restricted to mounted drives (/host/) and the output repo (/mnt/output-repo)"}`
- Path contains `..` traversal: 400 `{"error": "invalid_path", "message": "Path traversal not allowed"}`

**Security rules (non-negotiable):**

The browse endpoint must enforce these before any filesystem access:

```python
ALLOWED_BROWSE_ROOTS = ["/host", "/mnt/output-repo"]

def _validate_browse_path(path: str) -> Path:
    """
    Raises HTTPException if path is not allowed.
    Rules:
      1. Resolve to absolute path (no .. traversal)
      2. Must be under one of ALLOWED_BROWSE_ROOTS
      3. Must not contain null bytes
    """
    if "\x00" in path:
        raise HTTPException(400, "invalid_path")
    resolved = Path(path).resolve()
    if not any(str(resolved).startswith(root) for root in ALLOWED_BROWSE_ROOTS):
        raise HTTPException(403, {"error": "path_not_allowed", ...})
    return resolved
```

**Implementation notes:**

- Use `asyncio.to_thread(os.listdir, path)` — directory listing is blocking I/O.
- Catch `PermissionError` per entry — one unreadable folder never fails the whole listing.
- Never follow symlinks outside the allowed roots (use `os.lstat()` not `os.stat()`).
- Sort: case-insensitive, directories before files.
- Item count: wrap each `os.listdir(entry)` in a `try/except` — return `null` on any error.

---

## 3. Frontend — Folder Picker Widget

### `static/js/folder-picker.js` (new file)

A self-contained reusable widget. No external dependencies. Imported by `locations.html`.

The widget renders a modal dialog with a two-panel layout:
- Left panel: drive list (always visible)
- Right panel: current directory contents

```
┌─────────────────────────────────────────────────────────┐
│  Select a Folder                                    [✕]  │
├─────────────┬───────────────────────────────────────────┤
│  Drives     │  📁 /host/c/Users/Xerxes/T86_Work         │
│  ─────────  │  ← Back                                   │
│  💾 C:      │  ─────────────────────────────────────────│
│  💾 D:      │  📁 k_drv_test          142 items         │
│             │  📁 old_project          38 items         │
│             │  📁 archive              12 items         │
│             │                                           │
├─────────────┴───────────────────────────────────────────┤
│  Selected: /host/c/Users/Xerxes/T86_Work/k_drv_test     │
│                                    [Cancel]  [Select]   │
└─────────────────────────────────────────────────────────┘
```

#### Widget API

```javascript
class FolderPicker {
    /**
     * @param {Object} options
     * @param {string} options.title         - Dialog title (default: "Select a Folder")
     * @param {string} options.initialPath   - Path to open at (default: "/host")
     * @param {Function} options.onSelect    - Called with selected path string when user confirms
     * @param {Function} options.onCancel    - Called when user cancels (optional)
     * @param {"source"|"output"|"any"} options.mode
     *   "source"  → only show /host/* paths (read-only source folders)
     *   "output"  → only show /mnt/output-repo/* paths (writable output)
     *   "any"     → show both (default)
     */
    constructor(options) { ... }

    open() { ... }    // Show the dialog
    close() { ... }   // Hide the dialog
}
```

#### Behavior

**Navigation:**
- Clicking a folder navigates into it (fetches `/api/browse?path=...`)
- "← Back" navigates to `parent` path from the API response
- Clicking a drive letter in the left panel navigates to `/host/{letter}`
- Keyboard: arrow keys move selection, Enter navigates into folder, Backspace goes up,
  Escape closes dialog

**Selection:**
- Single-click highlights a folder (updates the "Selected:" footer bar)
- Double-click selects AND confirms (same as single-click + [Select] button)
- [Select] button is disabled until a folder is highlighted
- The currently-open directory itself can be selected via a "Select this folder" option
  at the top of the right panel:
  ```
  📁 Select current folder: /host/c/Users/Xerxes/T86_Work   ← click to highlight
  ─────────────────────────────────────────────────────
  📁 k_drv_test     142 items
  ...
  ```

**Drive panel:**
- Mounted drives show in blue with a 💾 icon
- Unmounted drives show grayed out with a tooltip: "Not mounted — add to docker-compose.yml"
- Clicking an unmounted drive shows an inline help message in the right panel:
  ```
  Drive D: is not mounted.

  To mount it, add this line to your docker-compose.yml:
      - D:/:/host/d:ro

  Then restart: docker-compose down && docker-compose up -d
  ```

**Loading states:**
- Spinner in the right panel while fetching
- If fetch fails: "Could not read this folder — permission denied" with a ← Back button
- Never leaves the panel blank or broken

**Output mode:**
- When `mode: "output"`, the left panel shows `/mnt/output-repo` instead of drive letters
- User can browse and select any subfolder of the output repo as their output location
- The "Select current folder" option at `/mnt/output-repo` level allows selecting the root

**Styling:**
- Uses CSS variables from `markflow.css` — no hardcoded colors
- Dialog uses `<dialog>` element with `showModal()` / `close()`
- Backdrop via `::backdrop` pseudo-element
- Max width: 680px. Max height: 500px. Scrollable right panel.
- Folder rows: hover state, selected state (accent background)
- Font: `var(--font-mono)` for paths, `var(--font-sans)` for labels and buttons

---

## 4. Locations Page Integration

### `static/locations.html` (modify)

**Import the widget:**
```html
<script src="/static/js/folder-picker.js"></script>
```

**Add "Browse..." button next to the Path input** in the Add/Edit location form:

```html
<div class="form-group">
  <label>Path</label>
  <div class="input-with-action">
    <input type="text" id="loc-path" placeholder="/host/c/Users/..." />
    <button type="button" class="btn btn-ghost" id="browse-btn">Browse...</button>
  </div>
  <div id="path-validate-result"></div>  <!-- inline validation result -->
</div>
```

**Wire up the Browse button:**

```javascript
document.getElementById("browse-btn").addEventListener("click", () => {
    const currentType = document.getElementById("loc-type").value; // source/output/both
    const mode = currentType === "output" ? "output"
               : currentType === "source" ? "source"
               : "any";

    const picker = new FolderPicker({
        title: "Select Folder",
        mode: mode,
        initialPath: document.getElementById("loc-path").value || "/host",
        onSelect: (path) => {
            document.getElementById("loc-path").value = path;
            // Trigger the existing "Check Access" validation automatically
            validatePath(path);
        }
    });
    picker.open();
});
```

**Type select change handler** — when the user changes the location type, update the
Browse button mode. If the path input already has a value that's incompatible with the
new type (e.g., path is `/mnt/output-repo/...` but type changed to `source`), clear
the path input and show a soft message: "Path cleared — source locations must be under /host/".

**Auto-open Browse on first-time setup:**
When `locations.html?setup=true` is in the URL and there are no locations yet, auto-open
the folder picker for the source location immediately after page load (don't make the user
click Browse manually on first launch).

---

## 5. Bulk Page — Path Display

### `static/bulk.html` (modify)

When a location is selected from a dropdown, show its resolved container path as a
small hint below the dropdown:

```
Source location   [k_drv_test ▾]
                  /host/c/Users/Xerxes/T86_Work/k_drv_test
```

This gives technically-minded users visibility into the actual path being used, without
requiring everyone to understand container paths to operate the UI.

---

## 6. Health Check Extension

### `core/health.py` (modify)

Add mounted drives to the health check response:

```json
"drives": {
  "status": "ok",
  "mounted": [
    {"letter": "C", "path": "/host/c", "accessible": true},
    {"letter": "D", "path": "/host/d", "accessible": true}
  ],
  "unmounted": ["E", "F"]
}
```

Detected via `MOUNTED_DRIVES` env var. A drive is accessible if `Path("/host/{letter}").exists()`
and `os.listdir("/host/{letter}")` succeeds.

### `static/debug.html` (modify)

Add drive mounts to the System Health section — one pill per mounted drive:
`C: ✓`, `D: ✓`, unmounted drives show as gray `E: —`.

---

## 7. Tests

### `tests/test_browse.py` (new)

- [ ] `GET /api/browse` with no path returns `/host` listing with drives
- [ ] `GET /api/browse?path=/host/c` returns directory listing
- [ ] `GET /api/browse?path=/host/c/Users` returns entries with item_count
- [ ] `GET /api/browse?path=/nonexistent` returns 404
- [ ] `GET /api/browse?path=/etc` returns 403 (outside allowed roots)
- [ ] `GET /api/browse?path=/host/../etc` returns 400 (path traversal)
- [ ] `GET /api/browse?path=/host/c/unreadable` returns 403 (mock PermissionError)
- [ ] `GET /api/browse?show_files=true` includes files in entries
- [ ] `GET /api/browse?show_files=false` returns only directories
- [ ] Null byte in path returns 400
- [ ] Symlink pointing outside allowed root is not followed
- [ ] `drives` array reflects `MOUNTED_DRIVES` env var correctly
- [ ] Unmounted drive shows `mounted: false` in drives array

### `tests/test_browse_security.py` (new)

Security-focused tests — these are non-negotiable:

- [ ] `path=/../../../etc/passwd` → 400 or 403, no file contents returned
- [ ] `path=/host/c/../../../../etc` → 400 or 403
- [ ] `path=%2Fetc%2Fpasswd` (URL-encoded) → 400 or 403
- [ ] `path=/host\x00/c` (null byte) → 400
- [ ] `path=/proc/self/environ` → 403
- [ ] `path=/app/data` → 403 (DB directory not browsable)
- [ ] `path=/app` → 403 (app source not browsable)
- [ ] Response never contains content of files, only directory entry names

---

## 8. Done Criteria

- [ ] `docker-compose.yml` mounts `C:/` and `D:/` at `/host/c` and `/host/d` read-only
- [ ] `docs/drive-setup.md` explains how to add additional drives
- [ ] `GET /api/browse?path=/host/c` returns correct directory listing
- [ ] Path traversal and out-of-bounds paths return 400/403, never file contents
- [ ] `FolderPicker` widget opens, navigates, and returns selected path
- [ ] Unmounted drives show grayed out with setup instructions
- [ ] Browse button on locations form opens picker and populates path input
- [ ] "Check Access" runs automatically after picker selection
- [ ] First-time setup (`?setup=true`) auto-opens the picker
- [ ] Bulk page shows resolved path hint below location dropdown
- [ ] Debug dashboard shows drive mount status pills
- [ ] All prior tests still passing
- [ ] New security tests all pass
- [ ] `docker-compose up` on a fresh Windows 11 machine: drives visible at `/host/c` etc.

---

## 9. CLAUDE.md Update

After done criteria pass:

```markdown
**v0.7.2** — Directory browser: Windows drives mounted at /host/c, /host/d etc.
  Browse endpoint (GET /api/browse) with path traversal protection.
  FolderPicker widget on Locations page — no need to type container paths manually.
  Unmounted drives show setup instructions inline.
```

Add to Gotchas:
```markdown
- **Browse API allowed roots**: Only /host/* and /mnt/output-repo are browsable.
  Any path outside these roots returns 403. This is enforced in _validate_browse_path()
  before any filesystem access. Do not relax this without security review.

- **Drive detection via env var**: MOUNTED_DRIVES env var (e.g. "c,d,e") tells the
  browse API which drive letters to show in the drives list. A drive showing as
  "unmounted" means /host/{letter} doesn't exist or isn't readable — not that the
  Windows drive doesn't exist.

- **item_count can be null**: Directory entry item_count is best-effort. Permission
  errors or slow directories return null. Never treat null as 0 in the UI.

- **FolderPicker uses <dialog> element**: showModal() / close() API. Backdrop via
  ::backdrop pseudo-element. No polyfill — requires Chrome 98+ / Firefox 98+.
  Docker Desktop's bundled browser meets this requirement.
```

Tag: `git tag v0.7.2 && git push origin v0.7.2`

---

## 10. Output Cap Note

Fits in 2 turns:

1. **Turn 1**: `docker-compose.yml` changes, `api/routes/browse.py`, `core/health.py`
   extension, `tests/test_browse.py`, `tests/test_browse_security.py`
2. **Turn 2**: `static/js/folder-picker.js`, `locations.html` modifications,
   `bulk.html` path hint, `debug.html` drive pills, `docs/drive-setup.md`,
   CLAUDE.md update, tag
