# Bug Log

MarkFlow keeps a running list of every known bug at
[`docs/bug-log.md`](https://github.com/theace26/Doc-Conversion-2026/blob/main/docs/bug-log.md)
in the source tree. It's a forward-looking register — "what's broken
right now" — that's status-tracked from discovery through release.

If you hit something that doesn't seem to work the way you expect,
check this file first. There's a good chance it's already on the
list with a planned fix.

## What's in it

Each bug has:

- A **stable ID** like `BUG-007` (so you can reference it in
  conversations or commits)
- A **status**: `open` (no plan yet), `planned (vX.Y.Z)`,
  `in-progress`, `shipped-vX.Y.Z` (closed but kept for history),
  or `wontfix` (deliberately left alone, with rationale)
- A **severity**: `critical`, `high`, `medium`, or `low`
- A **one-line summary** (what's broken from your point of view)
- **Details** with the file/line where relevant + a link to the
  plan that fixes it (if a plan exists)

The file is organized into two sections:

- **Open / Planned** at the top — what you'd care about now, grouped
  by upcoming release.
- **Shipped (history)** below — every bug that's been closed, with
  the version that contains the fix. Kept for posterity so you can
  trace "when did X get fixed?" without grepping the changelog.

## Related artifacts

The bug-log doesn't replace the other docs — it points to them:

| Doc | What it adds |
|---|---|
| [What's New](/help.html#whats-new) | Per-release narrative for shipped fixes |
| [`docs/version-history.md`](https://github.com/theace26/Doc-Conversion-2026/blob/main/docs/version-history.md) | Engineer-facing detailed changelog |
| [`docs/gotchas.md`](https://github.com/theace26/Doc-Conversion-2026/blob/main/docs/gotchas.md) | Subsystem-organized prevention guide ("how to not recreate this bug") |
| [`docs/security-audit.md`](https://github.com/theace26/Doc-Conversion-2026/blob/main/docs/security-audit.md) | Formal security-findings inventory; bug-log references findings by ID |
| `docs/superpowers/plans/*.md` | Implementation plans linked from each bug row |

## Workflow when a bug is found

1. **Triage**: a row gets added to the bug-log with `status: open`.
2. **Plan**: if a fix is non-trivial, a plan file is written under
   `docs/superpowers/plans/`. The bug row's status changes to
   `planned (vX.Y.Z)` and links to the plan.
3. **Ship**: when the release lands, the bug row moves to the
   **Shipped (history)** section with `status: shipped-vX.Y.Z`. The
   `version-history.md` entry covers the narrative + technical
   detail.
4. **Prevent**: if the fix exposed a class of bug worth not
   recreating, a row gets added to `gotchas.md` in the relevant
   subsystem section.

## Reporting a bug

If you find something that's not in the bug-log, file it via your
usual channel (GitHub Issues if your deployment uses them, or your
internal tracker). Include:

- What you did (steps to reproduce)
- What you expected to happen
- What actually happened (screenshots help)
- Which version of MarkFlow you're on (visible at the bottom of the
  Admin page or via `/api/version`)

The maintainer will add it to the bug-log once it's confirmed.

## Severity examples

| Severity | Example |
|---|---|
| **critical** | Bulk pipeline writes silently to the wrong path; lifecycle scanner never sees converted files. |
| **high** | Convert page rejects every upload because the write guard rejects the default output path. |
| **medium** | Right-click context menu on Batch Management doesn't fire on touch-screen devices. |
| **low** | Pluralization wrong on "1 files" / "0 files". |
