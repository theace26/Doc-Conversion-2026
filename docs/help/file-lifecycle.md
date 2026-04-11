# File Lifecycle & Versioning

MarkFlow doesn't just convert your documents once — it tracks them over time. When files in your source share change, get moved, or get deleted, MarkFlow detects it and keeps a history.

## How Change Detection Works

A background scanner runs every 15 minutes during business hours. It walks through your source document share and compares what it finds to its records:

- **New files** are flagged for conversion on the next bulk job
- **Modified files** (changed content or timestamp) trigger a re-conversion and a new version record
- **Moved files** are detected by matching content — if the same content appears at a new path, MarkFlow links them
- **Deleted files** enter a grace period before being trashed

> **Tip:** The scanner only runs during business hours (Mon–Fri, 6 AM – 6 PM by default). You can change these hours in Settings.

### Adding a new exclusion marks existing files for deletion

Worth knowing before you add an entry to **Excluded paths** in
Settings → Files and Locations: the scanner enforces exclusions by
**skipping those subtrees during its walk**. On the next scan, any
file you previously had under that path will look "disappeared" to
the scanner — because it's in MarkFlow's records but wasn't seen in
the walk — and will enter the soft-delete pipeline described below.

This is normal and intended. An exclusion means "stop tracking these
files entirely," not "just stop scanning them from now on." The
cascade has the usual 36-hour grace period and 60-day trash retention,
so nothing is permanently deleted immediately — but if you only meant
to silence future scans (without dropping the existing records), the
exclusion is the wrong tool. Remove the exclusion before the grace
period expires and the scanner will restore everything on its next
pass.

## The Soft-Delete Pipeline

When a file disappears from the source share, MarkFlow doesn't immediately delete its converted output. Instead, it goes through a careful pipeline:

| Stage | Duration | What Happens |
|-------|----------|-------------|
| **Active** | Normal state | File is in the source share and converted output is current |
| **Marked for Deletion** | 36 hours (default) | File disappeared from source. Output kept in case it reappears |
| **In Trash** | 60 days (default) | Grace period expired. Moved to the `.trash/` directory |
| **Purged** | After trash retention | Permanently deleted from disk |

If a file reappears during the grace period, it's automatically restored to active status.

## Version History

Every time MarkFlow detects a change in a source file, it records a new version:

- The version number increments (1, 2, 3...)
- A summary of what changed is generated
- A unified diff patch is stored so you can see exactly what text changed
- The content hash at each version is recorded

You can view version history for any file by clicking it in the history page and looking at the version timeline.

## Trash Management

The Trash page shows all files currently in the trash:

1. **Restore** — move a file back to active status
2. **Purge** — permanently delete a file immediately
3. **Empty Trash** — purge all trashed files at once

> **Warning:** Purging is permanent. There is no undo.

### Automatic purge *(v0.23.6)*

MarkFlow also runs an automatic daily purge at 04:00 local time
that permanently deletes every trashed file older than the
**Trash retention** window (default 60 days). The job:

- Is gated on the **Auto-purge aged trash** toggle under
  Settings → File Lifecycle (on by default)
- Yields to active bulk jobs — like every other scheduled
  maintenance task
- Reports purge counts and bytes freed to the activity log as
  `trash_auto_purge`

Turn **Auto-purge aged trash** off if your retention rules
require an admin to make the delete decision manually. Turning
it off doesn't stop the **Empty Trash** button from working —
it only disables the automatic schedule.

## Settings

| Setting | Default | What It Does |
|---------|---------|-------------|
| Scanner enabled | On | Whether the background scanner runs |
| Scan interval | 15 minutes | How often to scan during business hours |
| Business hours start | 06:00 | When scanning begins each weekday |
| Business hours end | 18:00 | When scanning stops each weekday |
| Grace period | 36 hours | How long before a missing file moves to trash |
| Trash retention | 60 days | How long files stay in trash before auto-purge |
| **Auto-purge aged trash** *(v0.23.6)* | On | Master switch for the daily 04:00 auto-purge job |

## Related

- [Bulk Repository Conversion](/help.html#bulk-conversion)
- [Administration](/help.html#admin-tools)
- [Settings Reference](/help.html#settings-guide)
