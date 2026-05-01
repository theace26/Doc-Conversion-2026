# Role-based UI gating — apply `roleGte` consistently across pages

**Status:** punch-list, to be addressed from workstation. Surfaced 2026-04-30 while reviewing Task 19's role-raise (search.rebuild_index: SEARCH_USER → MANAGER); the user noted that UX elements should be **hidden** for roles that can't access the underlying function, not just return 403 on click.

## Current state (already in place)

- `GET /api/auth/me` returns the current user's identity + role (`api/routes/auth.py:14-15`).
- `static/app.js:188` defines `roleGte(userRole, minRole)` (hierarchy lookup against `ROLE_HIERARCHY`).
- At least `static/settings.html:1570` already calls `/api/auth/me` and uses the result to gate UI.

So the building blocks exist — this is **applying the helper consistently across pages**, not building from scratch.

## What needs to happen

1. **Audit every page in `static/*.html`** for action buttons / form fields / nav links / links-to-admin-pages whose target endpoint requires a role above SEARCH_USER. Each one should be conditionally hidden when `roleGte(userRole, requiredRole)` is false.
2. **Establish a canonical pattern** for declaring the required role on each UI element. Two reasonable options:
   - HTML data attribute: `data-min-role="MANAGER"` + a single page-level helper that walks the tree and `display: none`s elements where the user's role is below the requirement.
   - Per-page imperative gate: `if (!roleGte(role, "MANAGER")) document.getElementById("rebuild-btn").hidden = true;` — simpler but more code.
3. **Add nav-level gating** so Admin/Settings sub-sections that the user can't act on don't appear at all.
4. **Decide what to do for the "this exists but you can't do it" UX**: hide entirely (less informative) vs disable + tooltip (more transparent). User's request implies hide entirely; tooltip-on-disable is the conservative alternative for items where the user might wonder where the button went.

## Endpoints to start from (role guards in current code)

Quick reference — what's already gated and at what role:

- `MANAGER` — bulk job management (`api/routes/bulk.py`), trash empty/restore-all (`api/routes/trash.py`), pipeline run-now/pause (`api/routes/pipeline.py`), search rebuild (Task 19), DB backup/restore (`api/routes/db_backup.py`), all admin routes (`api/routes/admin.py`), storage management (`api/routes/storage.py`).
- `OPERATOR` — convert-selected (`api/routes/pipeline.py`), batch management (`api/routes/analysis.py`), trash list (`api/routes/trash.py`), active-ops cancel (Phase 2 endpoints).
- `SEARCH_USER` — read-only search endpoints, /api/auth/me.

A grep of `require_role(UserRole.MANAGER)` and `require_role(UserRole.OPERATOR)` against `api/routes/*.py` enumerates all the endpoints that would benefit from UI gating; the corresponding `data-min-role` annotations on `static/*.html` close the loop.

## Why now

Task 19 raised the role on `POST /api/search/index/rebuild` from SEARCH_USER to MANAGER. Without UI gating, a SEARCH_USER who clicks "Rebuild Index" in the Settings UI now hits a 403. Hiding the button entirely is the better UX — and once the pattern is established, every future role-raise (or new role-gated action) becomes a one-line annotation.

## Suggested implementation order

1. **Foundation pass**: extend `app.js` with a single `gateUiByRole(userRole, root=document)` helper that walks `[data-min-role]` elements and hides the ones the user lacks access to. Wire it into the existing `/api/auth/me` boot path.
2. **Pages with single-role homogeneity** (whole page hidden if below required role): admin.html, settings.html — small per-page change.
3. **Pages with mixed-role buttons**: bulk.html, trash.html, history.html, search.html — annotate per-button with `data-min-role="MANAGER"` etc.
4. **Nav**: hide admin-only nav links for non-admins; same `data-min-role` pattern on nav anchors.
5. **Tooltip-on-disable variant**: optional follow-up if some buttons should remain visible-but-disabled with explanatory tooltip (e.g., "Requires Manager role").

## Out of scope

- This doc is a punch-list, not a plan-with-tasks-and-tests. When the workstation pass picks it up, it should produce a Phase-shaped plan (probably as a new `docs/superpowers/plans/2026-MM-DD-role-based-ui-gating.md` follow-up that supersedes this one).
- Fixing the underlying server-side role decisions (was SEARCH_USER → MANAGER on rebuild correct?) is orthogonal — this doc only covers the UI's reflection of whatever the server enforces.
