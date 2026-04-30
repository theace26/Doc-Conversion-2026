"""Generate phase_model_plan.xlsx — Claude Code model recommendations per phase
for the UX Overhaul and Active Operations Registry (System Unifier) work.

Run:  python3 build_phase_model_plan.py
Output: phase_model_plan.xlsx (same dir)
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT = Path(__file__).parent / "phase_model_plan.xlsx"

HEADERS = ["Phase", "Source plan file", "Implementer model", "Reviewer model", "Reasoning"]

UX_OVERHAUL = [
    (
        "Plan 1A — Foundation Setup",
        "2026-04-28-ux-overhaul-foundation-setup.md",
        "Sonnet",
        "Opus",
        "Foundation work: aiosqlite migration for the user_preferences table, JWT role-claim "
        "parsing, design-token CSS, prefs server module + endpoints. Schema and auth-claim "
        "mistakes are expensive to undo once data lands, so spend once on Opus review even "
        "though Sonnet handles the implementation comfortably.",
    ),
    (
        "Plan 1B — Static Chrome",
        "2026-04-28-ux-overhaul-static-chrome.md",
        "Haiku",
        "Haiku",
        "Four pure-presentational vanilla-JS components (top-nav, version-chip, avatar, "
        "layout-icon), each ≤100 LOC, no state, no async, no server interaction. Pattern is "
        "repetitive and the safe-DOM rules are explicit. Cheapest tier on both sides; the "
        "review just spot-checks for innerHTML and pattern adherence.",
    ),
    (
        "Plan 1C — Stateful Chrome",
        "2026-04-28-ux-overhaul-stateful-chrome.md",
        "Sonnet",
        "Sonnet",
        "Prefs client (localStorage cache + 500ms debounced PUT), telemetry helper (fire-and-"
        "forget), avatar/layout popovers with click-outside + Escape. Subtle async + event-"
        "lifecycle but well-bounded. Sonnet/Sonnet — popover bugs are visible and easy to spot "
        "at this tier; Opus is overkill.",
    ),
    (
        "Plan 2A — Document Card + Density Modes",
        "2026-04-28-ux-overhaul-document-card.md",
        "Haiku",
        "Sonnet",
        "Presentational card component with three density modes driven by CSS variables and "
        "MFPrefs. Implementation is mechanical given the explicit mockups, but bumping reviewer "
        "to Sonnet because density toggle interacts with the prefs system landed in 1C — worth "
        "verifying the binding is correct, not just the visuals.",
    ),
    (
        "Plan 2B — Card Interactions",
        "2026-04-28-ux-overhaul-card-interactions.md",
        "Sonnet",
        "Sonnet",
        "Hover preview popover, right-click context menu, multi-select observable state, bulk "
        "action bar, folder-browse page wrapping it all. Multiple interaction systems coexisting "
        "without listener leaks is the failure mode here. Sonnet handles the orchestration; "
        "Sonnet review catches missed cleanup paths.",
    ),
    (
        "Plan 3 — Search-as-Home Page",
        "2026-04-28-ux-overhaul-search-as-home.md",
        "Sonnet",
        "Sonnet",
        "Feature-flagged replacement of static/index.html with three layout modes (Maximal / "
        "Recent / Minimal). Both flag-on and flag-off paths must work — flag-off keeps legacy "
        "Convert page live, so rollback is cheap. Not security-critical, doesn't touch DB or "
        "auth, so Sonnet/Sonnet is the right floor.",
    ),
    (
        "Plan 4 — IA Shift",
        "2026-04-28-ux-overhaul-ia-shift.md",
        "Sonnet",
        "Opus",
        "New /api/me endpoint, real role binding via UnionCore JWT (replaces the hardcoded "
        "role='admin' placeholder), Activity dashboard gated by core.auth.Role. This is the "
        "auth surface — role-gating bugs are security issues. Opus reviewer once to verify the "
        "gate is enforced on every protected endpoint, not just the obvious ones.",
    ),
]

SYSTEM_UNIFIER = [
    (
        "Phase 0 — Pre-flight reconnaissance (Tasks 0.1–0.7)",
        "2026-04-28-active-operations-registry.md",
        "Haiku",
        "Haiku",
        "Read-only discovery: trace existing pipeline.py, scan_coordinator.py, bulk_worker.py, "
        "lifecycle_scanner.py to confirm assumptions about cancel signals and lifecycle hooks. "
        "Output is notes, not code. Cheapest tier on both sides; Haiku is good enough for "
        "summarising existing module behaviour against the plan's assumptions.",
    ),
    (
        "Phase 1 — Registry + DB foundation (Tasks 1–10)",
        "2026-04-28-active-operations-registry.md",
        "Opus",
        "Opus",
        "Load-bearing concurrency primitive: new core/active_ops.py (in-memory dict + write-"
        "through to a new active_operations SQLite table), lifespan hooks, scheduler "
        "integration, singleton lifecycle. Every later phase depends on this being correct — "
        "race conditions or write-through gaps cascade across all six worker subsystems. Spend "
        "tokens here; it is genuinely the highest-risk slice of the whole plan.",
    ),
    (
        "Phase 2 — HTTP API (Tasks 11–13)",
        "2026-04-28-active-operations-registry.md",
        "Sonnet",
        "Sonnet",
        "Single GET /api/active-ops endpoint feeding three frontend surfaces. Standard FastAPI "
        "pattern with a strict response schema. Risk is contract drift between this payload and "
        "Phase 4's three consumers — Sonnet reviewer is sufficient because the payload is small "
        "and reviewable in one screen.",
    ),
    (
        "Phase 3 — Worker retrofits (Tasks 14–23)",
        "2026-04-28-active-operations-registry.md",
        "Opus",
        "Sonnet",
        "Touches six worker modules (pipeline, scan_coordinator, trash, analysis, lifecycle_"
        "scanner, bulk_worker) to register/update/finish operations and bridge cancel signals "
        "to each subsystem's native mechanism. The structural traps — double-register, missed "
        "cleanup on exception paths, cancel hook never firing — need Opus to catch on the "
        "implementer side. Reviewer drops to Sonnet to control cost; the implementer does the "
        "heavy thinking.",
    ),
    (
        "Phase 4 — Frontend (Tasks 24–34)",
        "2026-04-28-active-operations-registry.md",
        "Sonnet",
        "Haiku",
        "Three presentational surfaces (sticky banner, per-page inline widget, Status hub) all "
        "fed by the /api/active-ops payload from Phase 2. Once that contract is stable the work "
        "is mechanical DOM construction + polling. Haiku reviewer is fine — visual diff against "
        "mockups is exactly what cheap models do well.",
    ),
    (
        "Phase 5 — Cleanup + documentation (Tasks 35–46)",
        "2026-04-28-active-operations-registry.md",
        "Sonnet",
        "Sonnet",
        "Removing dead per-subsystem progress code that the registry now subsumes, plus "
        "CLAUDE.md / version-history.md / whats-new.md updates. Deletions are irreversible — "
        "judgement about what's truly subsumed vs. what still has unique callers needs Sonnet, "
        "not Haiku. Sonnet reviewer catches the cases where the implementer was over-eager.",
    ),
]


def write_sheet(ws, rows):
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    model_fills = {
        "Haiku":  PatternFill("solid", fgColor="C6EFCE"),
        "Sonnet": PatternFill("solid", fgColor="FFEB9C"),
        "Opus":   PatternFill("solid", fgColor="FFC7CE"),
    }
    wrap = Alignment(wrap_text=True, vertical="top")

    for col, h in enumerate(HEADERS, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center")

    for r_idx, row in enumerate(rows, start=2):
        for c_idx, val in enumerate(row, start=1):
            c = ws.cell(row=r_idx, column=c_idx, value=val)
            c.alignment = wrap
            if c_idx in (3, 4) and val in model_fills:
                c.fill = model_fills[val]
                c.font = Font(bold=True)
                c.alignment = Alignment(horizontal="center", vertical="center")

    widths = {1: 44, 2: 48, 3: 16, 4: 16, 5: 90}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22
    for r in range(2, 2 + len(rows)):
        ws.row_dimensions[r].height = 100
    ws.freeze_panes = "A2"


def write_legend(ws):
    ws["A1"] = "Model legend & cost guidance"
    ws["A1"].font = Font(bold=True, size=14)
    rows = [
        ("Model", "Use for", "Approx cost vs Opus"),
        ("Haiku",  "Pattern-driven scaffolding, presentational vanilla-JS components, doc edits, read-only discovery, visual diff review.", "≈ 1/15"),
        ("Sonnet", "Most feature work: FastAPI endpoints, vanilla-JS with state, multi-system interactions, judgement-call cleanup.",       "≈ 1/5"),
        ("Opus",   "Concurrency primitives, schema/migration design, auth surface, cancel-propagation across subsystems.",                 "1×"),
        ("", "", ""),
        ("Heuristic", "Default both implementer and reviewer to Sonnet. Justify every upgrade to Opus (irreversibility, security, concurrency) and every downgrade to Haiku (mechanical, well-spec'd, low blast radius).", ""),
    ]
    for r, row in enumerate(rows, start=3):
        for c, val in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if r == 3:
                cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 100
    ws.column_dimensions["C"].width = 22
    for r in range(4, 4 + len(rows) - 1):
        ws.row_dimensions[r].height = 50


def main():
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "UX Overhaul"
    write_sheet(ws1, UX_OVERHAUL)

    ws2 = wb.create_sheet("System Unifier")
    write_sheet(ws2, SYSTEM_UNIFIER)

    ws3 = wb.create_sheet("Legend")
    write_legend(ws3)

    wb.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
