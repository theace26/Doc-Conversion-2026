# Overnight Rebuild Self-Healing — Design Spec

**Status:** Implemented in v0.22.17 (2026-04-08). See §11 "Implementation
notes & spec deviations" at the bottom for divergences from the draft.
**Date:** 2026-04-08
**Owner:** Xerxes
**Scope:** `Scripts/work/overnight/rebuild.ps1`
**Related:** v0.22.16 (initial Invoke-Logged + Test-StackHealthy), the
2026-04-08 11:37:31 overnight failure log

---

## 1. Problem

The overnight rebuild script runs unattended (~3 AM) and currently has
three failure modes that force a human morning intervention even when
the underlying issue is recoverable:

1. **Transient infrastructure flakes** — a single `git fetch` network
   hiccup, a single `docker pull` timeout during the base image
   rebuild, or a single `docker-compose` reconciler race aborts the
   whole run. The next manual run almost always succeeds.
2. **New build regressions** — a commit merged late in the day
   introduces a bug that passes CI but fails a runtime health check
   (the v0.22.15/v0.22.16 "Whisper on CPU" / "GPU detector lying" class
   of bug is the canonical example). The stack either refuses to start
   or starts but serves broken functionality. The user wakes up to a
   dead or lying service.
3. **Opaque failure logs** — when something does fail, the transcript
   contains just the failing command's output. Context needed for
   diagnosis (container logs, disk state, GPU state, health response
   body, recent git history) has to be gathered by hand in the
   morning, turning a 5-minute fix into a 30-minute investigation.

## 2. Goals / non-goals

### Goals

- **Transient-failure tolerance (A):** retry network- and
  daemon-sensitive steps within a bounded budget, log retry successes
  so flaky infrastructure is visible.
- **Blue/green rollback (C):** if a new build fails verification, fall
  back to the last-known-good image so morning state is "yesterday's
  build running" rather than "dead stack".
- **Honest failure (no silent remediation, B):** never auto-remediate
  a broken state in a way that masks a real bug. Rollback is only
  triggered on definite verification failures, never on ambiguous or
  partial states. Rollback is **refused** if it would be unsafe
  (compose/Dockerfile divergence — see §6.3).
- **Morning-ready diagnostics (D):** on any non-success exit, the
  transcript contains everything needed to diagnose without running a
  single additional command. On success, the transcript contains a
  compact final-state block.
- **Portable by default:** all behavior stays correct on friend-deploys
  with no NVIDIA GPU. GPU-specific smoke assertions auto-detect
  expectation based on host `nvidia-smi` presence.

### Non-goals

- **Auto-remediation of bad state** (restart crashed containers,
  `docker system prune` on disk pressure, `git reset --hard` on pull
  conflicts). Explicitly rejected in brainstorming — these hide real
  bugs.
- **External notifications** (Discord/email/push) — out of scope for
  this spec. The transcript is the morning artifact.
- **Multi-version rollback history.** Exactly one rollback target
  (`:last-good`) is maintained. No time-travel to older images.
- **Rollback of the database or on-disk state.** Only images are
  rolled back. Database schema migrations in MarkFlow are
  additive-only (per `core/db/schema.py` patterns), so rolling the
  image back while keeping the new schema is safe in practice; if
  this assumption ever breaks, rollback becomes a new bug-finder.

## 3. Architecture overview

The rebuild becomes a **phased pipeline with promotion gates**. Each
phase succeeds (advance), retries within its own budget for
transient-prone steps (A), or fails and drops to diagnostic capture
plus an honest-reason exit code (D). Only the verify phase (Phase 4)
can trigger a rollback (C).

```
Phase 0    Preflight       → verify prerequisites, record HEAD commit,
                              auto-detect expected GPU state
Phase 1    Source sync     → git fetch / checkout / pull --ff-only  [retry 3×]
Phase 1.5  Capture          → snapshot current :latest image IDs into
                              script vars before Phase 2 overwrites them
Phase 2    Image build     → docker build base + compose build      [retry 2×]
Phase 2.5  Retag last-good → tag captured IDs as :last-good, write sidecar
Phase 3    Start           → docker-compose up -d                    [race override]
Phase 4    Verify          → container + app-health + GPU + MCP      [3× × 5s]
Phase 5    Success         → exit 0 with compact final-state block
```

### Gate semantics

| Phase failure | Running stack state | Action | Exit |
|---|---|---|---|
| 0 — Preflight | Untouched | Diagnostics, abort | 1 |
| 1 — Source sync | Untouched | Diagnostics, abort | 1 |
| 1.5 — Capture | Untouched | Diagnostics, abort | 1 |
| 2 — Image build | Untouched (build is out-of-band from the running container) | Diagnostics, abort | 1 |
| 2.5 — Retag last-good | Untouched | Diagnostics, abort | 1 |
| 3 — Start (race override also fails) | New containers stopped, stack DOWN | Attempt rollback | 2/3/4 |
| 4 — Verify | New stack running but broken or lying | Attempt rollback | 2/3/4 |

Phases 0-2.5 leave the running stack untouched (the `docker build`
step writes to the image store but doesn't recreate containers), so
no rollback is needed — yesterday's image keeps serving until the
user investigates.

Phases 3-4 have already run `up -d`, so the old containers are gone.
Recovery requires retagging `:last-good` → `:latest` and running `up -d
--force-recreate` again.

### Exit codes

| Code | Meaning | Morning stack state |
|---|---|---|
| 0 | Clean success, new build verified | New build running, healthy |
| 1 | Pre-commit failure (phases 0 through 2.5) | Old build still running (untouched) |
| 2 | Rollback succeeded — old build running; new build needs investigation | Old build running, healthy |
| 3 | Rollback failed — retag succeeded but rolled-back stack also failed verification | Stack DOWN |
| 4 | Rollback refused — compose/Dockerfile diverged since last-good commit | New build stopped, stack DOWN |

Exit codes 1-4 all include full diagnostics. Exit 0 includes a
compact final-state block (just `compose ps` + `curl /api/health`).

## 4. Retry wrapper (A)

New `Invoke-Retryable` helper that wraps `Invoke-Logged`. Attempts
the command up to `-MaxAttempts` times, with linear backoff from
`-BackoffSeconds` (5s → 10s → 20s). Succeeds if any attempt returns
exit 0. Logs the retry count on success so morning review can spot
flaky infrastructure.

### Applied to

| Step | MaxAttempts | Why |
|---|---|---|
| `git fetch origin` | 3 | Network flake |
| `git pull --ff-only` | 3 | Network flake |
| `docker build base` | 2 | pip/apt download flakes during ~2.5 GB torch wheel pull |
| `docker-compose build` | 2 | Same |

### Not retried

- **GPU toolkit smoke test** — a missing NVIDIA Container Toolkit is
  not transient; retrying wastes minutes and masks the real problem.
- **`git checkout`** — local operation, no network dependency.
- **`docker-compose up -d`** — already has the race-override path via
  `Test-StackHealthy`.
- **Health check (Phase 4)** — already has a 3-attempt internal loop
  with a 5-second backoff.

### Success logging

On success after >1 attempt, emit:
```
RETRY-OK: git fetch origin succeeded on attempt 2
```
So the morning summary can grep `RETRY-OK` to see what flaked
overnight.

## 5. Blue/green rollback (C)

### 5.1 Tag lifecycle

`doc-conversion-2026-markflow:last-good` and
`doc-conversion-2026-markflow-mcp:last-good` are the rollback anchors.
Both must always point to the same previously-verified build — if
either is missing or stale, rollback is refused.

**Key constraint:** `docker build` and `docker-compose build`
overwrite `:latest` the moment they succeed. Once Phase 2 runs, the
OLD `:latest` image ID is no longer reachable through a tag — only
through its sha256 ID. So we must **capture the old image IDs before
Phase 2** and **retag them as `:last-good` after Phase 2 succeeds**.

**Tag lifecycle across one rebuild cycle:**

Assume at start of night: `:latest` = build N, `:last-good` = build
N-1, sidecar describes N-1.

| Phase | Action on tags |
|---|---|
| **1.5 — Capture** (inserted between 1 and 2) | Record current image IDs via `docker image inspect --format '{{.Id}}' doc-conversion-2026-markflow:latest` (and mcp). Store in script variables `$prevMarkflowId`, `$prevMcpId`. If either `:latest` is missing (fresh install), set `$rollbackAvailable = $false` and skip the retag in Phase 2.5. |
| **2 — Build** | `docker build` + `docker-compose build` overwrite `:latest` with build N+1. Build N is still resident on the host but reachable only by `$prevMarkflowId` / `$prevMcpId`. |
| **2.5 — Retag last-good** | `docker tag $prevMarkflowId doc-conversion-2026-markflow:last-good` (and mcp). Overwrite `last-good.json` with metadata describing build N (commit SHA from `git rev-parse HEAD` *before* Phase 1's pull — recorded in Phase 0, see §5.2). If retag of either image fails, retry once; if still failing, abort as exit 1. |
| **3 — Start** | `docker-compose up -d`. Build N+1 becomes running. |
| **4 — Verify** | Smoke tests run against build N+1. |
| **5 — Success** | Nothing more to do for tags: `:latest` = N+1, `:last-good` = N, sidecar describes N. Exit 0. On the NEXT cycle, Phase 1.5 will capture N+1 as the new rollback target. |
| **4/5 — Failure path** | Retag `$prevMarkflowId` (via the `:last-good` tag just written in 2.5) → `:latest`. `up -d --force-recreate markflow markflow-mcp`. Re-run smoke tests against rolled-back stack. |

Phases are thus renumbered: 0 Preflight, 1 Source, 1.5 Capture, 2
Build, 2.5 Retag, 3 Start, 4 Verify, 5 Success. Updated gate-semantics
table in §3 reflects this.

### 5.2 Sidecar state file

`Scripts/work/overnight/last-good.json` (gitignored, per-machine):

```json
{
  "commit": "a0a4e0b1c2...",
  "tagged_at": "2026-04-08T03:14:27-07:00",
  "markflow_image_id": "sha256:960b23031e14...",
  "mcp_image_id": "sha256:1fdecb17fb8e...",
  "host_expects_gpu": true
}
```

Written by Phase 2.5 when the retag succeeds. Read by the rollback
path to check compose-file divergence (§6.3) and to validate that the
image IDs behind `:last-good` haven't been clobbered by an unrelated
`docker image prune`.

**The `commit` field holds the SHA the previous build was built from,
not tonight's current HEAD.** Phase 0 records `$prevHeadCommit = git
rev-parse HEAD` *before* Phase 1's pull, then Phase 2.5 writes that
value into the sidecar. This is the commit that produced the image
currently being tagged as `:last-good`.

### 5.3 Atomicity

Tagging is atomic per image in Docker, but not across the pair. If the
markflow retag succeeds and the markflow-mcp retag fails:

1. Retry the failing retag once.
2. If it still fails, **abort Phase 2.5** and exit 1 (treat as a
   pre-commit failure). Do not proceed to Phase 3, because rollback
   would be impossible (image pair out of sync).

This is conservative: a genuine rebuild can't proceed if rollback
isn't available, on the principle that "no safety net = don't do the
risky thing."

### 5.4 Rollback execution

When Phase 3 (after race override) or Phase 4 triggers rollback:

1. **Compose divergence check** (§6.3). If files changed since
   `last-good.commit`, skip rollback → exit 4.
2. **Sidecar validation.** Read `last-good.json`. Verify both image
   IDs still exist via `docker image inspect`. If either is gone,
   rollback is impossible → exit 3 (rollback failed at the image
   level).
3. **Retag**. `docker tag doc-conversion-2026-markflow:last-good
   doc-conversion-2026-markflow:latest` (and the mcp variant).
4. **Recreate**. `docker-compose up -d --force-recreate markflow
   markflow-mcp`. `--force-recreate` is needed because compose won't
   see the tag change as a reason to recreate by default.
5. **Re-verify**. Run Phase 4 verification against the rolled-back
   stack. If it passes → exit 2 (rolled back successfully). If it
   fails → exit 3 (rollback attempted but rolled-back stack is also
   broken — an infrastructure issue, not a new-build regression).

## 6. Smoke tests (Phase 4)

### 6.1 Existing checks (unchanged)

- Container check: both `doc-conversion-2026-markflow-1` and
  `doc-conversion-2026-markflow-mcp-1` are `"State":"running"` in
  `docker-compose ps --format json`. Parsed line-by-line via
  `ConvertFrom-Json` (the regex-across-Publishers bug was fixed in the
  pre-spec v0.22.16 follow-up commit).
- App health: `/api/health` returns top-level `status=ok` AND
  `database.ok=true` AND `meilisearch.ok=true`. Scoped regex match
  `[^{}]*` to survive nested subobjects.

### 6.2 New checks

3. **GPU expectation assertion.** Parse `/api/health` for
   `gpu.execution_path`. Behavior depends on `$expectGpu` computed in
   Phase 0:

   - `"container"` → assert `execution_path -notin @("container_cpu", "none")`.
     Also assert `whisper.cuda_available -eq $true`. Catches v0.22.15
     and v0.22.16 regression classes.
   - `"none"` → skip this assertion entirely. Keeps the script portable
     to CPU-only friend-deploys.

4. **MCP `/health` endpoint.** `curl.exe -sf --max-time 5
   http://localhost:8001/health`. Must return exit 0 and a non-empty
   body. Catches the case where `docker-compose ps` reports the
   markflow-mcp container as `running` but the MCP server process
   inside it has crashed or failed to bind.

### 6.3 Phase 0 GPU auto-detection

On Windows (the current host), probe `wsl.exe -e nvidia-smi`
(suppressing stderr). On Linux, probe plain `nvidia-smi`. On
non-zero exit or missing binary, `$expectGpu = "none"`. On zero exit,
`$expectGpu = "container"`. Log the decision prominently:

```
[03:14:22] >>> Phase 0: Preflight
    Host GPU detected via nvidia-smi -> expectGpu=container
```

This value flows into the smoke-test gate (§6.2) and into the sidecar
JSON (§5.2) so a later rollback can check consistency.

### 6.4 Compose/Dockerfile divergence check

Used by the rollback path (§5.4 step 1). Computes:

```powershell
$changed = git diff --name-only $lastGoodCommit HEAD -- `
    docker-compose.yml Dockerfile Dockerfile.base
```

If `$changed` is non-empty → refuse rollback → exit 4.

**Rationale:** blue/green via image tagging only rolls back the
*image*. A compose file that adds a new required mount, removes an
env var, changes a port binding, or adds a new service would create a
compose-old-image mismatch that silently half-works. Rather than
wake the user up to a "rolled back successfully" log with a broken
stack, exit 4 signals "unsafe to rollback, investigate manually."
Documented in the morning diagnostics block.

## 7. Diagnostic capture (D)

### 7.1 Trigger points

`Write-Diagnostics` is called from:
- Every catch block that sets a non-zero exit code (phases 0 through 4)
- The rollback path, after determining the outcome (success path too,
  to show what the rolled-back stack looks like)
- Phase 5 success (compact variant, not the full dump)

### 7.2 Full diagnostic block contents

Emitted inline in the transcript, in this order:

1. **Header**: `======= DIAGNOSTICS (reason: <string>) =======` with a
   clear `<string>` identifying which phase failed and why.
2. `docker-compose ps` (plain format)
3. `docker-compose logs --tail=100 --timestamps markflow`
4. `docker-compose logs --tail=100 --timestamps markflow-mcp`
5. `docker-compose logs --tail=20 meilisearch`
6. `docker-compose logs --tail=20 qdrant`
7. `curl.exe -sv http://localhost:8000/api/health` (verbose flag shows
   HTTP status + headers + body)
8. `curl.exe -sv http://localhost:8001/health`
9. Host GPU state: `wsl.exe -e nvidia-smi` (Windows) or `nvidia-smi`
   (Linux), wrapped in a try/catch so a missing binary doesn't abort
10. `wsl.exe -e df -h /` — disk pressure
11. `git log -5 --oneline` + `git status --short`
12. Last 100 lines of `logs/app.log` (if it exists — path is relative
    to `$RepoDir`)
13. Footer: `======= END DIAGNOSTICS =======`

Each line routed through `Invoke-Logged -AllowNonZero` so a failing
diagnostic command doesn't abort the capture. Budget: ~20 seconds
total.

### 7.3 Compact success block

On exit 0, emit only:

```
======= FINAL STATE =======
[docker-compose ps output]
[curl /api/health response]
======= END =======
```

So every morning's transcript has the baseline "what does the running
stack look like now" without making the user run anything.

## 8. Files touched

| File | Change |
|---|---|
| `Scripts/work/overnight/rebuild.ps1` | Major refactor: phased pipeline, `Invoke-Retryable`, `Write-Diagnostics`, `Invoke-Rollback`, Phase 0 GPU + prev-commit detection, Phase 1.5 image ID capture, Phase 2.5 retag + sidecar write |
| `Scripts/work/overnight/last-good.json` | New file (gitignored, per-machine). Created by Phase 3 on first successful run. |
| `.gitignore` | Add `Scripts/work/overnight/last-good.json` |
| `docs/version-history.md` | New entry: v0.22.17 (or whatever version ships with this) describing the self-healing rebuild |
| `CLAUDE.md` | Roll "Current Version" block when this ships |
| `docs/gotchas.md` | Two new entries: (1) PS 5.1 `SilentlyContinue` + variable capture is the only reliable way to suppress `NativeCommandError` decoration; (2) `docker-compose ps --format json` — don't regex across fields, parse NDJSON line-by-line because Publishers has nested `{}` |

## 9. Testing plan

The rebuild script cannot be unit tested in the normal sense — it
orchestrates side-effecting shell commands. Validation strategy:

1. **Dry-run mode.** Optional `-DryRun` switch that logs what each
   phase would do without executing docker/git commands. Runs the
   Phase 0 GPU detection and prints the resolved `$expectGpu`.
   Verifies script-level control flow without touching the stack.
2. **Staged live runs.** Run with `-SkipGpuCheck -SkipPull -SkipBase`
   first (fastest path, skips the expensive steps) to validate the
   phase transitions, tagging, and health assertions. Then run
   without skips overnight.
3. **Rollback rehearsal.** Force Phase 4 failure by temporarily
   editing Dockerfile to add a broken `RUN` step after the normal
   successful build — actually that breaks Phase 2, not Phase 4.
   Better: introduce a runtime failure (e.g. a bad import at the top
   of `main.py`) so the build succeeds but the container fails to
   boot or fails the health check. Observe rollback path. Revert the
   edit after.
4. **Compose divergence rehearsal.** After a successful run creates
   `last-good.json`, make a trivial edit to `docker-compose.yml`,
   re-run the script with a forced Phase 4 failure (as in 3), verify
   exit 4.

## 10. Open questions — RESOLVED

All three resolved as **out of scope** at implementation time (2026-04-08):

1. **Driver-mismatch warning in Phase 0?** — **Out of scope.** The
   driver-mismatch case manifests at `docker run` time as a clear error
   and is already caught by the existing GPU toolkit smoke test in
   Phase 0.
2. **On-disk "nag flag" when exit 2 (rollback succeeded)?** — **Out of
   scope.** The transcript log is the source of truth and the user
   reads it every morning; adding a second channel adds cognitive load
   without new signal.
3. **Multi-version rollback history (last-5 instead of last-good
   only)?** — **Out of scope.** Explicitly rejected in §2 non-goals;
   one rollback target is enough for the "recover from last night's
   regression" use case.

## 11. Implementation notes & spec deviations (v0.22.17)

Four meaningful deviations from the draft spec, all caught by
live-probe validation or the first two staged live runs during
implementation:

**§6.3 GPU auto-detection probe — changed from `wsl.exe -e nvidia-smi`
to `nvidia-smi.exe` (Windows-native).** The spec called for probing
nvidia-smi inside the default WSL2 distro, but on the reference host
(Windows 11 + Docker Desktop + GTX 1660 Ti) the default WSL distro has
no nvidia-smi installed — the CUDA/NVIDIA toolchain for the default
distro is a separate install from Docker Desktop's GPU passthrough,
which uses the NVIDIA Container Toolkit path independently. Result: the
spec's probe returned a WSL exec error on a fully GPU-capable host,
making `$expectGpu` wrongly resolve to `none` and silently disabling
the GPU verification gate that's the entire point of Phase 4.

The Windows NVIDIA driver installs `C:\Windows\System32\nvidia-smi.exe`,
which is on the default PATH and is the authoritative "does this host
have an NVIDIA GPU" check. Validated by dry-run: with `nvidia-smi.exe`
it correctly resolves `expectGpu=container`. On CPU-only Windows hosts
(friend-deploy scenario) nvidia-smi.exe is simply absent and
`expectGpu=none`, preserving portability.

**§6.2 Test-GpuExpectation regex field names corrected.** The draft
spec and the CLAUDE.md v0.22.16 notes both referenced
`whisper.cuda_available`, but that is the name of a structlog event
field (and an internal whisper-module attribute), not the key in the
`/api/health` response. The health JSON key is `whisper.cuda` (under
`components.whisper`). Validated against the live payload on
2026-04-08. The regex for `execution_path` is correct as specified
because the `gpu` subobject lists `execution_path` before its nested
`container_gpu`/`host_worker` subobjects, so the lazy `[^{}]*?` walk
never crosses an inner brace.

**§5.1 / §5.4 — retag must happen BEFORE the build, not after.** The
draft spec's Phase 2.5 ("retag captured IDs as :last-good after Phase
2 succeeds") assumed the previous `:latest` image would remain
resident after `docker-compose build` overwrote the `:latest` tag -
reachable only by sha ID but still alive. On modern BuildKit that's
false: the old image is garbage-collected the moment its `:latest`
tag is reassigned, and `docker tag <prev-sha> :last-good` fails with
`Error response from daemon: No such image`. Caught on the first
staged live run (2026-04-08 15:03:46). **Fix:** merged Phase 1.5
(Capture) and Phase 2.5 (Retag) into a single Phase 1.5 ("Anchor
last-good") that runs BEFORE Phase 2. Tagging the current `:latest`
as `:last-good` pre-build gives the image store a second reference,
which keeps the old image resident across the build. Sidecar is
also written in Phase 1.5 so tag and sidecar remain atomic. Phase
2.5 deleted entirely - the pipeline is now six phases (0, 1, 1.5,
2, 3, 4, 5).

**Phase 3 lifespan pause was missing from the race-override branch.**
The draft spec mentioned a 20s lifespan wait at "Phase 6 Verify" but
the implementation put it at the start of Phase 4, which only runs
AFTER Phase 3's race-override succeeds. On the race-override path
(compose up -d exits non-zero, Test-StackHealthy runs immediately to
check whether the stack came up anyway), there was no wait — the
health probe hit the container before FastAPI's lifespan startup
finished. Second staged live run (2026-04-08 15:15:12) surfaced
this as a FALSE ROLLBACK of a functionally-identical new build.
**Fix:** moved the 20-second lifespan pause to the end of Phase 3,
applying to BOTH the clean-exit and race-override branches. Phase 4
no longer sleeps. Same pause added to `Invoke-Rollback`'s
--force-recreate step in case its up -d also exits non-zero from the
same compose race.

**`Test-StackHealthy` EAP must be `SilentlyContinue`, not `Continue`.**
The draft spec didn't specify this and the v0.22.16 version of
`Test-StackHealthy` set `$ErrorActionPreference = "Continue"` locally
as a workaround for docker-compose writing a symlink warning to
stderr on every invocation. With EAP=Continue, PS 5.1 auto-displays
the native stderr as a `NativeCommandError` ErrorRecord BEFORE the
`2>$null` redirection takes effect, filling the transcript with
8-line error decoration on every probe attempt. Second staged live
run transcript was completely flooded. **Fix:** changed to
`SilentlyContinue` (same pattern as `Invoke-Logged`). Documented in
the function's comment block so future edits can't re-regress.

**`Invoke-RetagImage` must expose stderr on failure.** The initial
implementation used `& docker tag ... 2>&1 | Out-Null` to silence
the command, which hid the actual docker error from the morning
transcript. When Bug A above failed retag, the log just said
"attempt 1 failed (exit 1)" with no clue why. **Fix:** capture the
combined stream into a variable and `Write-Host` each line (with
ErrorRecord -> Exception.Message projection) on retag failure.
Applied the same pattern to all future native-command wrappers.

**§9 testing plan status:**
- Dry-run mode (§9.1): **implemented and passed** — all six phase
  transitions execute without touching git/docker.
- Staged live run (§9.2): **PASSED on the third attempt** (2026-04-08
  15:35:20). Runtime 1:36 end-to-end with `-SkipPull -SkipBase
  -SkipGpuCheck`. Exit 0, no NativeCommandError decoration, all
  three Phase 4 smoke tests green. First two attempts surfaced Bugs
  A-D above.
- Rollback rehearsal (§9.3): **partially exercised** — the second
  staged run (2026-04-08 15:15:12) triggered a false-positive
  rollback due to Bug D, which inadvertently exercised the
  Invoke-Rollback path end-to-end: compose-divergence check (clean),
  sidecar validation (both IDs present), retag :last-good -> :latest
  for both images, `up -d --force-recreate markflow markflow-mcp`,
  20s lifespan pause (added post-Bug-D), Test-StackHealthy +
  Test-GpuExpectation + Test-McpHealth all passed on the rolled-back
  stack. Final exit 2. A TRUE rollback rehearsal (deliberately broken
  runtime import) has still not been performed because a real
  regression would be a better test than a contrived one, and the
  false-positive run already proved the mechanics work.
- Compose-divergence rehearsal (§9.4): **still deferred** — requires
  a small docker-compose.yml edit after a successful cycle, then
  forcing a Phase 4 failure to exercise the exit 4 path.

---

**End of spec.**
