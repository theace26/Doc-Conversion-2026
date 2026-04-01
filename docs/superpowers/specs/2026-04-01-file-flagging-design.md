# File Flagging & Content Moderation — Design Spec

**Date:** 2026-04-01
**Version target:** v0.16.0
**Status:** Approved design, pending implementation

## Overview

Self-service file flagging system that lets any authenticated user temporarily suppress a file from search results and direct access. Admins manage flagged files through a dedicated page with a three-action escalation ladder: dismiss, extend, or permanently remove (with blocklist). Includes webhook notifications, structured logging, and auto-expiry.

### Motivation

MarkFlow indexes everything on the source mount. Users may discover that sensitive, confidential, or personally identifiable files are accessible without proper authorization. They need a way to immediately suppress access and alert admins, without waiting for mount permission changes.

### What This Solves

- Immediate suppression of sensitive files from search and download
- Admin triage workflow with audit trail
- Permanent blocklist to prevent re-indexing of removed files
- Notification pipeline (webhook + logs) for visibility

### What This Does NOT Solve

- Files already downloaded before flagging (policy problem)
- Access control on the source mount itself (infrastructure problem)
- Data Loss Prevention (separate system)

---

## Data Model

### `file_flags` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | TEXT PK | UUID |
| `source_file_id` | TEXT FK → source_files.id | Which file is flagged |
| `flagged_by_sub` | TEXT NOT NULL | JWT `sub` claim of flagger |
| `flagged_by_email` | TEXT NOT NULL | Email of flagger |
| `reason` | TEXT NOT NULL | Preset: `pii`, `confidential`, `unauthorized`, `other` |
| `note` | TEXT | Optional free-text detail from user |
| `status` | TEXT NOT NULL DEFAULT 'active' | `active`, `extended`, `dismissed`, `expired`, `removed` |
| `expires_at` | DATETIME NOT NULL | Auto-set to now + 14 days on creation |
| `created_at` | DATETIME NOT NULL | When flagged |
| `resolved_at` | DATETIME | When admin acted |
| `resolved_by_email` | TEXT | Admin who resolved |
| `resolution_note` | TEXT | Admin's explanation for their action |

**Indexes:**
- `idx_file_flags_source_status` on `(source_file_id, status)` — fast "is this file flagged?" lookup
- `idx_file_flags_status_expires` on `(status, expires_at)` — auto-expiry scheduler query
- `idx_file_flags_user` on `(flagged_by_email)` — admin filtering by user

### `blocklisted_files` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | TEXT PK | UUID |
| `content_hash` | TEXT | SHA-256 from source_files at time of removal |
| `source_path` | TEXT | Original path at time of removal |
| `reason` | TEXT | Why it was blocklisted (copied from flag reason) |
| `added_by_email` | TEXT NOT NULL | Admin who performed the removal |
| `flag_id` | TEXT FK → file_flags.id | Originating flag for audit trail |
| `created_at` | DATETIME NOT NULL | When blocklisted |

**Indexes:**
- `idx_blocklist_hash` on `(content_hash)` — scanner lookup
- `idx_blocklist_path` on `(source_path)` — scanner lookup

### Meilisearch changes

Add `is_flagged` (boolean, default `false`) as a **filterable attribute** on all 3 indexes (`documents`, `adobe-files`, `transcripts`). Default search queries append filter `is_flagged != true`. Admin queries with `include_flagged=true` bypass this filter.

### File size fix (bundled)

Update `search_indexer.py` to populate `file_size_bytes` from `source_files.file_size_bytes` (original source file size) instead of stat'ing the converted markdown output file.

---

## API Endpoints

### User-facing (SEARCH_USER+)

| Method | Path | Body / Params | Purpose |
|--------|------|---------------|---------|
| `POST` | `/api/flags` | `{ source_file_id, reason, note? }` | Flag a file |
| `GET` | `/api/flags/mine` | — | List caller's active flags |
| `DELETE` | `/api/flags/{flag_id}` | — | Retract own flag (before admin acts) |

**POST /api/flags behavior:**
1. Validate `source_file_id` exists in `source_files`
2. Validate `reason` is one of: `pii`, `confidential`, `unauthorized`, `other`
3. Create `file_flags` row with `status=active`, `expires_at=now+14d`
4. Update Meilisearch: set `is_flagged=true` on matching document
5. Fire webhook (if configured)
6. Log `file_flagged` event
7. Return 201 with flag details

**DELETE /api/flags/{flag_id} behavior:**
- Only the original flagger can retract (match `flagged_by_sub`)
- Only if `status=active` (can't retract after admin action)
- Restores Meilisearch `is_flagged=false` (unless another active flag exists on same file)
- Log `flag_retracted`

### Admin-facing (ADMIN)

| Method | Path | Body / Params | Purpose |
|--------|------|---------------|---------|
| `GET` | `/api/flags` | `status`, `flagged_by`, `reason`, `format`, `path_prefix`, `date_from`, `date_to`, `sort_by`, `sort_dir`, `page`, `per_page` | List all flags (filtered) |
| `GET` | `/api/flags/{flag_id}` | — | Single flag detail |
| `PUT` | `/api/flags/{flag_id}/dismiss` | `{ resolution_note? }` | Dismiss flag, restore access |
| `PUT` | `/api/flags/{flag_id}/extend` | `{ days, resolution_note? }` | Extend suppression |
| `PUT` | `/api/flags/{flag_id}/remove` | `{ resolution_note? }` | Hard-remove + blocklist |
| `GET` | `/api/flags/blocklist` | `page`, `per_page` | View blocklisted files |
| `DELETE` | `/api/flags/blocklist/{id}` | — | Un-blocklist (allows re-indexing) |
| `GET` | `/api/flags/stats` | — | Counts by status for dashboard KPI |

### Modified existing endpoints

**`GET /api/search/all`:**
- Adds `is_flagged != true` to Meilisearch filter by default
- New query param `include_flagged=true` — ADMIN role only, bypasses flag filter

**`GET /api/search/source/{index}/{doc_id}`:**
- Before serving file, query `file_flags` for active/extended flag on matching source_file_id
- If flagged: return 403 `{ "detail": "This file has been flagged for review" }`

**`GET /api/search/download/{index}/{doc_id}`:**
- Same 403 check as source endpoint

**`POST /api/search/batch-download`:**
- Silently exclude flagged files from ZIP
- Include `skipped_flagged` count in response body

---

## Workflows

### Flag Flow

```
User flags file
  -> file_flags row created (status=active, expires_at=now+14d)
  -> Meilisearch: set is_flagged=true on matching doc
  -> structlog event: "file_flagged" { file_id, source_path, user, reason }
  -> Webhook POST (if flag_webhook_url configured)
  -> File immediately hidden from search + blocked from download/view
```

### Admin: Dismiss

```
Admin dismisses flag
  -> file_flags: status='dismissed', resolved_at=now, resolved_by_email set
  -> Meilisearch: set is_flagged=false (if no other active flags on same file)
  -> Log: "flag_dismissed" { flag_id, file_id, admin }
  -> Webhook POST
```

### Admin: Extend

```
Admin extends flag
  -> file_flags: status='extended', expires_at updated to new date
  -> File stays hidden
  -> Log: "flag_extended" { flag_id, file_id, new_expires_at, admin }
  -> Webhook POST
```

### Admin: Remove

```
Admin removes file
  -> file_flags: status='removed', resolved_at=now
  -> blocklisted_files row created (content_hash + source_path from source_files)
  -> Meilisearch: delete document from index entirely
  -> source_files row kept intact (audit trail)
  -> Log: "file_removed_and_blocklisted" { flag_id, file_id, content_hash, source_path }
  -> Webhook POST
```

### Auto-Expiry (Scheduler)

Hourly job in `scheduler.py`:

```
Query: file_flags WHERE status IN ('active', 'extended') AND expires_at < now
  -> Set status='expired'
  -> Meilisearch: set is_flagged=false (if no other active flags on same file)
  -> Log: "flag_expired" { flag_id, file_id }
```

### Blocklist Enforcement (Scanners)

During both bulk scan and lifecycle scan:

```
For each discovered file:
  -> Compute content_hash (already done)
  -> Check blocklisted_files WHERE content_hash=? OR source_path=?
  -> If match: skip file, log "blocklisted_file_skipped" { path, matched_by }
```

---

## Notification

### Webhook

New preference: `flag_webhook_url` (TEXT, MANAGER+ to configure on Settings page).

Payload for all flag events:

```json
{
  "event": "file_flagged | flag_dismissed | flag_extended | flag_expired | file_removed_and_blocklisted",
  "flag_id": "uuid",
  "file": {
    "source_file_id": "uuid",
    "source_path": "/mnt/source/...",
    "source_filename": "quarterly-report.xlsx"
  },
  "actor": {
    "email": "user@example.com",
    "role": "SEARCH_USER"
  },
  "reason": "pii",
  "note": "Contains SSNs in column D",
  "status": "active",
  "expires_at": "2026-04-15T...",
  "timestamp": "2026-04-01T..."
}
```

**Behavior:** Fire-and-forget. 3-second timeout. Failures logged as `webhook_delivery_failed` but do not block the flag action. No retries in v1.

### Logging

All flag events logged via structlog with event names listed above. These flow into the existing rotating log files and log archive system.

---

## UI

### Search Results: Flag Button

Each search result card gets a small flag icon button alongside the existing checkbox. Clicking opens a modal:

- **Reason dropdown:** "Contains PII", "Confidential / Privileged", "Not Authorized to Share", "Other"
- **Optional note:** single-line text input
- **Submit / Cancel** buttons

On submit: result card fades out, toast message "File flagged -- hidden from search for 14 days."

### Search Results: File Size Fix

Result meta row displays source file size (from updated Meilisearch field) instead of markdown output size.

### Flagged Files Admin Page (`flagged.html`)

Linked from admin nav. Requires ADMIN role.

**Summary bar:** Active | Extended | Dismissed (30d) | Expired (30d) | Removed (30d)

**Filters:**

| Filter | Type | Purpose |
|--------|------|---------|
| Flagged by (user) | Dropdown / autocomplete | Spot abuse patterns |
| Reason | Multi-select chips | Triage by category |
| Status | Multi-select chips | Active / Extended / Dismissed / Expired / Removed |
| Date range | Date picker (from / to) | Time-based filtering |
| File format | Dropdown | Format-based triage |
| Source path prefix | Text input | Filter by directory / share |

**Sort options:**

| Sort by | Default | Purpose |
|---------|---------|---------|
| Expires date | Soonest first | **Default** — act on urgent flags |
| Flagged date | Newest first | See latest flags |
| File name | A-Z | Find specific file |
| Reason | Grouped | Batch-process same category |
| Flagged by | Grouped | Review one user's flags |

**Active flags table columns:**

| Column | Content |
|--------|---------|
| File | Source filename (linked to viewer) |
| Path | Truncated source path |
| Reason | Badge chip (PII / Confidential / Unauthorized / Other) |
| Note | User's note if any |
| Flagged By | Email |
| Flagged | Relative time |
| Expires | Relative time + date |
| Actions | Dismiss / Extend / Remove buttons |

**Action behaviors:**
- **Extend:** inline dropdown — 30 / 60 / 90 days / Indefinite
- **Remove:** confirmation dialog — "This will permanently remove the file from search and blocklist it from future indexing. Continue?" with optional resolution note
- **Dismiss:** optional resolution note

**History tab:** shows resolved flags (dismissed / expired / removed) with same filters, sorted by resolved date (newest first).

### Admin Dashboard KPI (`admin.html`)

New "Flagged Files" card showing count of active flags, linking to `flagged.html`.

---

## Preferences

| Key | Type | Default | Role | Purpose |
|-----|------|---------|------|---------|
| `flag_webhook_url` | text | empty | MANAGER+ | Webhook endpoint for flag events |
| `flag_default_expiry_days` | number | 14 | MANAGER+ | Default flag duration |

---

## Flag Reason Presets

| Value | Display Label |
|-------|---------------|
| `pii` | Contains PII |
| `confidential` | Confidential / Privileged |
| `unauthorized` | Not Authorized to Share |
| `other` | Other |

Stored as enum-like strings in `file_flags.reason`. The preset list is defined in the API route and the frontend — adding new reasons requires a code change (intentional, to keep the taxonomy controlled).

---

## Edge Cases

**Multiple flags on same file:** Supported. Each flag is independent. File stays hidden as long as ANY flag has `status` in (`active`, `extended`). Meilisearch `is_flagged` is only set to `false` when the last active/extended flag is resolved or expires.

**User flags then admin removes, then another user flags the same path:** The file is already blocklisted. The new flag is created (for audit) but the file is already gone from the index. If the blocklist entry is later removed, the flag still exists and will suppress re-indexed results.

**File re-scanned while flagged:** Scanner finds the file, creates/updates `source_files` row as normal, but `search_indexer.py` checks `file_flags` and sets `is_flagged=true` in Meilisearch. The flag survives re-indexing.

**Index rebuild:** `search_indexer.py` rebuild path must check `file_flags` and set `is_flagged=true` for any file with an active/extended flag. This is the source-of-truth re-derivation.

**Flag on file that spans multiple indexes:** A file might be in `documents` and also have entries in `transcripts` (e.g., a video). Flag applies to the `source_file_id`, so all index entries for that file are suppressed. The Meilisearch update must hit all indexes where the file appears.

---

## New Files

| File | Purpose |
|------|---------|
| `api/routes/flags.py` | Flag API endpoints (user + admin) |
| `core/flag_manager.py` | Flag business logic, blocklist checks, Meilisearch sync |
| `static/flagged.html` | Admin flagged files page |

## Modified Files

| File | Change |
|------|--------|
| `core/database.py` | Add `file_flags` + `blocklisted_files` tables, helper functions |
| `core/search_indexer.py` | Add `is_flagged` attribute, fix `file_size_bytes` source |
| `core/scheduler.py` | Add hourly flag expiry job |
| `core/bulk_scanner.py` | Add blocklist check during scan |
| `api/routes/search.py` | Add flag filter to search, 403 checks on source/download |
| `static/search.html` | Add flag button per result, flag modal |
| `static/admin.html` | Add flagged files KPI card |
| `static/app.js` | Flag modal logic, API calls |
| `main.py` | Mount flags router |
| `Dockerfile` | No changes expected |
