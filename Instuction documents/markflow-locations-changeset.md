# MarkFlow Changeset: Named Locations
# Friendly path management for bulk source and output directories

**Version:** v1.0
**Targets:** v0.7.1 tag
**Prerequisite:** Phase 7 complete — tagged v0.7.0
**Scope:** Focused changeset — not a full phase. No conversion logic changes.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. This changeset adds a Named Locations system
that replaces raw Docker container path inputs on the bulk job form. It touches the database,
one new API router, the settings page, the bulk page, and a small shared JS module.

Nothing in `core/converter.py`, `core/bulk_worker.py`, `core/bulk_scanner.py`, or any
format handler is modified.

---

## 1. What This Is

Right now the bulk job form asks the user to type raw container paths like `/mnt/source`.
That's fine for a developer who knows Docker but hostile to anyone else.

Named Locations lets the user define friendly aliases:

```
Name: "Company Share"     Path: /mnt/source       Type: Source
Name: "NAS Markdown Repo" Path: /mnt/output-repo   Type: Output
```

The bulk form then shows:

```
Source location   [Company Share ▾]
Output location   [NAS Markdown Repo ▾]
```

The first time the user opens the bulk page with no locations defined, a setup wizard
walks them through adding at least one source and one output location before they can
start a job.

---

## 2. Database

### `core/database.py` (modify)

Add one new table. Existing tables are not modified.

```sql
CREATE TABLE IF NOT EXISTS locations (
    id          TEXT PRIMARY KEY,          -- UUID
    name        TEXT NOT NULL UNIQUE,      -- "Company Share", "NAS Output", etc.
    path        TEXT NOT NULL,             -- container-side path: /mnt/source
    type        TEXT NOT NULL,             -- 'source' | 'output' | 'both'
    notes       TEXT,                      -- optional user note
    created_at  TEXT NOT NULL,             -- ISO-8601
    updated_at  TEXT NOT NULL
);
```

Add helper functions:

```python
async def create_location(name, path, type_, notes=None) -> str
    """Insert new location. Returns id. Raises ValueError if name already exists."""

async def get_location(location_id) -> dict | None

async def list_locations(type_filter=None) -> list[dict]
    """Returns all locations, optionally filtered by type ('source'/'output'/'both').
    'both' locations appear in both source and output lists."""

async def update_location(location_id, **fields) -> None
    """Update name, path, type, or notes. Raises ValueError if new name conflicts."""

async def delete_location(location_id) -> None
    """Delete location. Does NOT cascade to bulk_jobs — job records keep their raw paths."""
```

### Seed locations on first run

On startup (in `main.py` lifespan), after DB init: check if `locations` table is empty.
If empty AND `BULK_SOURCE_PATH` and `BULK_OUTPUT_PATH` env vars are set: auto-create
two seed locations from those env vars so existing installs aren't broken.

```python
# Only runs if table is empty AND env vars are set
if not await list_locations():
    source = os.getenv("BULK_SOURCE_PATH")
    output = os.getenv("BULK_OUTPUT_PATH")
    if source:
        await create_location("Default Source", source, "source")
    if output:
        await create_location("Default Output", output, "output")
```

---

## 3. API

### `api/routes/locations.py` (new file)

Router with prefix `/api/locations`. Mount in `main.py`.

**`GET /api/locations`**

Query param: `type` — optional filter (`source`, `output`, `both`).
Returns all locations (or filtered subset). Always returns a list, never 404.

```json
[
  {
    "id": "...",
    "name": "Company Share",
    "path": "/mnt/source",
    "type": "source",
    "notes": "Read-only SMB share mounted at startup",
    "created_at": "...",
    "updated_at": "..."
  }
]
```

**`POST /api/locations`**

```json
{"name": "Company Share", "path": "/mnt/source", "type": "source", "notes": "..."}
```

Validation:
- `name`: required, 1–80 chars, must be unique (return 409 if name exists)
- `path`: required, must start with `/` (it's a container path — reject Windows paths
  like `C:\...` with a clear error: `"Path must be a container path starting with /. 
  Windows paths like C:\\ are not valid here."`)
- `type`: must be `source`, `output`, or `both`
- `notes`: optional, max 500 chars

Returns 201 with created location.

**`GET /api/locations/{id}`**

Returns single location or 404.

**`PUT /api/locations/{id}`**

Same validation as POST. Returns updated location.
409 if new name conflicts with a different existing location.

**`DELETE /api/locations/{id}`**

Returns 204. If location is referenced by any `bulk_jobs` record (by matching path),
return 409 with:
```json
{
  "error": "location_in_use",
  "message": "This location is used by 3 bulk job(s). Delete those jobs first or remove this location anyway.",
  "job_count": 3,
  "force_url": "/api/locations/{id}?force=true"
}
```
If `?force=true` query param is included: delete anyway (jobs keep their raw path strings).

**`GET /api/locations/validate`**

Query param: `path` — checks if a container path is accessible from inside the container.

```json
{
  "path": "/mnt/source",
  "accessible": true,
  "readable": true,
  "writable": false,
  "exists": true,
  "file_count_estimate": 84231
}
```

Implementation:
- `exists`: `Path(path).exists()`
- `readable`: try `os.listdir(path)` — catch `PermissionError`
- `writable`: try `Path(path / ".markflow_write_test").touch()` then delete — catch errors
- `file_count_estimate`: `sum(1 for _ in Path(path).rglob("*") if _.is_file())` — but cap
  at 10 seconds using `asyncio.wait_for`. If it times out: return `file_count_estimate: null`.
- If path doesn't start with `/`: return `{"accessible": false, "error": "not_a_container_path"}`

### `api/models.py` (modify)

Add Pydantic models:
```python
class LocationCreate(BaseModel):
    name: str
    path: str
    type: Literal["source", "output", "both"]
    notes: str | None = None

class LocationUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    type: Literal["source", "output", "both"] | None = None
    notes: str | None = None

class LocationResponse(BaseModel):
    id: str
    name: str
    path: str
    type: str
    notes: str | None
    created_at: str
    updated_at: str
```

---

## 4. Bulk API Change

### `api/routes/bulk.py` (modify)

**`POST /api/bulk/jobs`** — accept location IDs in addition to raw paths:

```json
{
  "source_location_id": "...",
  "output_location_id": "...",
  "worker_count": 4,
  "fidelity_tier": 2,
  "ocr_mode": "auto",
  "include_adobe": true
}
```

Either `source_location_id` OR `source_path` is accepted (backwards compatible).
If `source_location_id` is provided: look up the location, resolve to its `path`.
If the location doesn't exist: return 422 with `"Location not found: {id}"`.

Same for output. The resolved paths are stored in `bulk_jobs` as before — the location
is resolved at job creation time, not stored by reference. This means deleting a location
doesn't break existing job history.

Update `api/models.py` `BulkJobCreate` to reflect:
```python
class BulkJobCreate(BaseModel):
    source_path: str | None = None
    source_location_id: str | None = None
    output_path: str | None = None
    output_location_id: str | None = None
    worker_count: int = 4
    fidelity_tier: int = 2
    ocr_mode: str = "auto"
    include_adobe: bool = True

    @model_validator(mode="after")
    def require_source_and_output(self):
        has_source = bool(self.source_path or self.source_location_id)
        has_output = bool(self.output_path or self.output_location_id)
        if not has_source:
            raise ValueError("Provide either source_path or source_location_id")
        if not has_output:
            raise ValueError("Provide either output_path or output_location_id")
        return self
```

---

## 5. Frontend

### `static/locations.html` (new page)

Standalone locations management page. Linked from Settings and the bulk wizard.
Uses `markflow.css` and `app.js`. Nav bar included.

Layout:
```
┌──────────────────────────────────────────────────────────┐
│  MarkFlow      [Convert] [Bulk] [Search] [History] [Settings] │
├──────────────────────────────────────────────────────────┤
│  Locations                              [+ Add Location]  │
│                                                          │
│  Source Locations                                        │
│  ─────────────────────────────────────────────────────  │
│  📁 Company Share                                        │
│     /mnt/source  ·  Read-only SMB share                  │
│     ✓ Accessible  ·  ~84,000 files             [Edit] [Delete] │
│                                                          │
│  Output Locations                                        │
│  ─────────────────────────────────────────────────────  │
│  📁 NAS Markdown Repo                                    │
│     /mnt/output-repo  ·  Synology NAS                   │
│     ✓ Accessible  ·  Writable                  [Edit] [Delete] │
│                                                          │
│  Both (Source & Output)                                  │
│  ─────────────────────────────────────────────────────  │
│  (empty)                                                 │
└──────────────────────────────────────────────────────────┘
```

**Add / Edit location** — inline form that expands below the button (not a separate page):
```
Name        [____________________________]
Path        [____________________________]  [Check Access]
Type        [Source ▾]
Notes       [____________________________]  (optional)
            [Save]  [Cancel]
```

The "Check Access" button calls `GET /api/locations/validate?path=...` and shows an inline
result below the path input:
```
✓ Accessible · Read-only · ~84,000 files
✗ Path not found — check the container mount
✗ Not a container path — use /mnt/... not C:\...
```

Show the validation result before the user saves, but don't block saving
(they might be adding a location for a path that isn't mounted yet).

**Delete** — inline confirmation (not a dialog):
```
[Delete]  →  "Delete 'Company Share'? [Confirm] [Cancel]"
```
If 409 (location in use): show
`"Used by 3 jobs. [Delete anyway] [Cancel]"` — "Delete anyway" sends `?force=true`.

**Accessibility badges** on each location card: fetched from validate endpoint on page load.
Show a spinner while fetching, then ✓ or ✗. Don't block the page render waiting for these.

### `static/bulk.html` (modify)

Replace the raw path text inputs with location dropdowns.

**If locations exist:**
```
Source location   [Company Share ▾]          [Manage locations ↗]
Output location   [NAS Markdown Repo ▾]       [Manage locations ↗]
```

Dropdown options come from `GET /api/locations?type=source` and `GET /api/locations?type=output`.
"Both" type locations appear in both dropdowns.

If a location type has only one option: pre-select it automatically.

**If NO locations exist (first time):**

Hide the job form entirely. Show the setup wizard instead:

```
┌──────────────────────────────────────────────────────┐
│  Before you can run a bulk job, you need to set up   │
│  at least one source location and one output         │
│  location.                                           │
│                                                      │
│  Locations are friendly names for the folder paths   │
│  that MarkFlow reads from and writes to. These are   │
│  paths inside the Docker container — not Windows     │
│  paths.                                              │
│                                                      │
│  [Set Up Locations →]                                │
└──────────────────────────────────────────────────────┘
```

"Set Up Locations →" links to `locations.html?setup=true`.

**If locations exist but one type is missing** (has source, no output or vice versa):

Show a partial warning inline above the form:
```
⚠ No output locations defined yet.  [Add one →]
```
The missing dropdown shows `(none available)` and is disabled. Start button is disabled
until both dropdowns have a valid selection.

**"Manage locations" link** next to each dropdown opens `locations.html` in a new tab.
On returning to bulk.html (focus event): refresh the dropdowns from the API.

### `static/settings.html` (modify)

Add a "Locations" section at the top of the settings page (above Conversion settings):

```
Locations
─────────────────────────────────────────────────────────
Define source and output paths for bulk conversion jobs.

[Manage Locations →]        (links to locations.html)

2 locations configured: 1 source · 1 output
```

The count is fetched from `GET /api/locations` on page load.

### `static/app.js` (modify)

Add a shared `LocationPicker` helper that bulk.html uses for its dropdowns:

```javascript
// Fetches locations of a given type and populates a <select> element
async function populateLocationSelect(selectEl, type, selectedId = null) {
    const locations = await apiFetch(`/api/locations?type=${type}`);
    selectEl.innerHTML = "";
    if (locations.length === 0) {
        selectEl.innerHTML = '<option value="" disabled selected>(none available)</option>';
        selectEl.disabled = true;
        return;
    }
    locations.forEach(loc => {
        const opt = document.createElement("option");
        opt.value = loc.id;
        opt.textContent = loc.name;
        opt.dataset.path = loc.path;
        if (loc.id === selectedId) opt.selected = true;
        selectEl.appendChild(opt);
    });
    selectEl.disabled = false;
    // Auto-select if only one option
    if (locations.length === 1) selectEl.value = locations[0].id;
}
```

---

## 6. Navigation Update

Add "Locations" link to the nav bar in `markflow.css` / all user-facing pages. Place it
under Settings (it's an admin/config concern):

```html
<a href="/locations.html" class="nav-link">Locations</a>
```

Or — keep the nav clean and only link to Locations from the Settings page and bulk wizard.
Your call — document the decision in CLAUDE.md either way.

---

## 7. Tests

### `tests/test_locations.py` (new)

**API tests:**
- [ ] `POST /api/locations` creates a location, returns 201
- [ ] `POST /api/locations` with duplicate name returns 409
- [ ] `POST /api/locations` with Windows path `C:\foo` returns 422 with clear message
- [ ] `POST /api/locations` with `type=invalid` returns 422
- [ ] `GET /api/locations` returns all locations
- [ ] `GET /api/locations?type=source` returns only source and both locations
- [ ] `GET /api/locations?type=output` returns only output and both locations
- [ ] `PUT /api/locations/{id}` updates name and path
- [ ] `PUT /api/locations/{id}` with conflicting name returns 409
- [ ] `DELETE /api/locations/{id}` returns 204
- [ ] `DELETE /api/locations/{id}` in use returns 409 with job_count
- [ ] `DELETE /api/locations/{id}?force=true` deletes even if in use
- [ ] `GET /api/locations/validate?path=/mnt/source` returns accessibility info
- [ ] `GET /api/locations/validate?path=C:\foo` returns `not_a_container_path` error

**Bulk job integration:**
- [ ] `POST /api/bulk/jobs` with `source_location_id` resolves to location path
- [ ] `POST /api/bulk/jobs` with nonexistent `source_location_id` returns 422
- [ ] `POST /api/bulk/jobs` with neither `source_path` nor `source_location_id` returns 422

**Database helpers:**
- [ ] `create_location()` raises `ValueError` on duplicate name
- [ ] `list_locations(type_filter="source")` returns source + both locations
- [ ] `delete_location()` removes the record

---

## 8. Done Criteria

- [ ] `locations` table created on startup
- [ ] CRUD API for locations works (`POST`, `GET`, `PUT`, `DELETE`)
- [ ] `GET /api/locations/validate` returns accessibility info
- [ ] Windows path rejected with clear error message
- [ ] `POST /api/bulk/jobs` accepts `source_location_id` / `output_location_id`
- [ ] Bulk form shows location dropdowns when locations exist
- [ ] Bulk form shows setup wizard when no locations exist
- [ ] First-time wizard on `locations.html?setup=true` is clear and functional
- [ ] "Check Access" button on location form shows inline validation result
- [ ] Settings page shows location count with link to locations page
- [ ] Seed locations created from env vars on first run if table is empty
- [ ] All prior 450+ tests still passing
- [ ] New tests: 20+ covering locations API and bulk integration
- [ ] `docker-compose up` → no startup errors

---

## 9. CLAUDE.md Update

After done criteria pass, add to Current Status:

```markdown
**v0.7.1** — Named Locations system: friendly aliases for container paths used in bulk jobs.
  First-run wizard guides setup. Bulk form uses dropdowns instead of raw path inputs.
  Backwards compatible with BULK_SOURCE_PATH / BULK_OUTPUT_PATH env vars.
```

Add to Gotchas:
```markdown
- **Locations validate endpoint timeout**: `file_count_estimate` walks the directory tree
  capped at 10 seconds via asyncio.wait_for. If it times out, returns null — not an error.
  Don't treat null file_count_estimate as a failure in tests.

- **Locations type filter includes 'both'**: GET /api/locations?type=source returns locations
  with type='source' AND type='both'. The filter is "show me what I can use as a source",
  not "show me locations where type exactly equals source".
```

Tag: `git tag v0.7.1 && git push origin v0.7.1`

---

## 10. Output Cap Note

This changeset is small enough to complete in 2–3 turns:

1. **Turn 1**: DB schema + helpers + `api/routes/locations.py` + bulk API change + tests
2. **Turn 2**: `static/locations.html` + bulk.html modifications + settings.html addition +
   app.js helper
3. **Turn 3**: Integration check, fix failures, CLAUDE.md update, tag
