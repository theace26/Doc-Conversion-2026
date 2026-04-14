# Scripts/work/overnight — Unattended Rebuild Pipeline

Self-healing overnight rebuild of MarkFlow with full verification and automatic rollback on failure.

---

## rebuild.ps1

The main overnight rebuild script. Designed to run unattended (e.g., scheduled task, before bed). Safe to leave running — every failure path writes full diagnostics so the morning review doesn't require running follow-up commands.

### What It Does (6 Phases)

| Phase | Name | Action |
|-------|------|--------|
| 0 | Preflight | Check prerequisites, detect GPU (nvidia-smi), record HEAD commit |
| 1 | Source sync | `git fetch/checkout/pull` (retry 3x) |
| 1.5 | Anchor last-good | Tag current `:latest` images as `:last-good`, write sidecar JSON |
| 2 | Image build | Rebuild base image + app image (retry 2x each) |
| 3 | Start | `docker-compose up -d` + 20s lifespan pause |
| 4 | Verify | Container health + `/api/health` + GPU check + MCP health |
| 5 | Success | Log final state |

If Phase 4 verification fails, the script automatically rolls back to the `:last-good` images and re-verifies.

### Exit Codes

| Code | Meaning | Stack State |
|------|---------|-------------|
| 0 | Clean success — new build verified | New build running |
| 1 | Pre-commit failure (phases 0-2) | Old build still running, untouched |
| 2 | Rollback succeeded | Old (last-good) build running |
| 3 | Rollback attempted but failed | Stack DOWN — needs manual intervention |
| 4 | Rollback refused (Dockerfile/compose diverged) | Stack DOWN — compose mismatch |

### Usage

```powershell
# Full rebuild (pulls from git + rebuilds base + app)
.\rebuild.ps1

# Skip git pull (code is already current)
.\rebuild.ps1 -SkipPull

# Skip base image rebuild (only code changed)
.\rebuild.ps1 -SkipBase

# Skip both
.\rebuild.ps1 -SkipPull -SkipBase

# Dry run (validates phases without executing docker/git commands)
.\rebuild.ps1 -DryRun

# Different branch
.\rebuild.ps1 -Branch main
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Branch` | `main` | Git branch to pull |
| `-SkipPull` | false | Skip git fetch/checkout/pull |
| `-SkipBase` | false | Skip base image rebuild |
| `-SkipGpuCheck` | false | Skip NVIDIA Container Toolkit smoke test |
| `-RepoDir` | (auto from script location) | Override repo root |
| `-DryRun` | false | Log-and-skip all git/docker commands |

### Output Files

| File | Purpose |
|------|---------|
| `logs/rebuild-YYYYMMDD-HHMMSS.log` | Full transcript of the rebuild run |
| `last-good.json` | Sidecar recording the last-good image IDs, commit hash, and timestamp |

### Morning Review

Check the latest log file:
```powershell
Get-Content (Get-ChildItem .\logs\rebuild-*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
```

Or just check the exit code and final block:
```powershell
# Look for "REBUILD OK" or "REBUILD FAILED" near the end
Get-Content (Get-ChildItem .\logs\rebuild-*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1) | Select-Object -Last 20
```
