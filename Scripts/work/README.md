# Scripts/work — MarkFlow Operational Scripts

PowerShell scripts for building, deploying, and maintaining MarkFlow on the work machine (Windows + Docker Desktop + WSL2).

---

## Quick Reference

| What you want to do | Script | Time |
|---------------------|--------|------|
| Rebuild after Dockerfile.base changed | `build-base.ps1` then `refresh-markflow.ps1` | ~30 min |
| Rebuild after code/requirements change | `refresh-markflow.ps1` | ~5-15 min |
| Just restart (no rebuild) | `refresh-markflow.ps1 -NoBuild` | ~30 sec |
| Nuke everything and start fresh | `reset-markflow.ps1` | ~35 min |
| Switch git branch | `switch-2vector.ps1` | ~1 min |
| Pull container logs | `pull-logs.ps1` | ~10 sec |
| Overnight unattended rebuild | `overnight\rebuild.ps1` | ~2 hours |

---

## Script Details

### build-base.ps1

Builds the MarkFlow base Docker image (`markflow-base:latest`) containing all system-level apt packages (LibreOffice, Tesseract, ffmpeg, hashcat, mdbtools, torch, whisper, etc.).

**When to run:**
- First time setup on a new machine
- After `Dockerfile.base` changes (new system package added)
- After `docker system prune -a` (wiped all images)

**When NOT needed:**
- Python code changes (use `refresh-markflow.ps1`)
- `requirements.txt` changes (use `refresh-markflow.ps1`)
- `.env` or `docker-compose.yml` changes

**Usage:**
```powershell
.\build-base.ps1              # normal build (~25 min on HDD, ~5 min on SSD)
.\build-base.ps1 -NoCache     # force full rebuild, no Docker layer cache
```

**Parameters:**
- `-RepoDir` — repo root (default: `C:\Users\Xerxes\Projects\Doc-Conversion-2026`)
- `-NoCache` — skip Docker build cache

---

### refresh-markflow.ps1

Quick refresh: pulls latest code from GitHub, rebuilds the app Docker image (NOT the base), and restarts containers. Preserves all data (database, Meilisearch index, converted files, whisper models).

**What it does:**
1. Force-pulls latest code from GitHub
2. Auto-detects GPU hardware (NVIDIA/AMD/Intel/none)
3. Rebuilds Docker images with new code
4. Restarts containers (with GPU passthrough if NVIDIA detected)
5. Starts hashcat host worker if applicable

**Usage:**
```powershell
.\refresh-markflow.ps1              # full rebuild + restart
.\refresh-markflow.ps1 -NoBuild     # just restart, skip rebuild
```

**Parameters:**
- `-RepoDir` — repo root
- `-NoBuild` — skip `docker-compose build`, just restart
- `-GPU` — legacy flag, ignored (GPU auto-detected now)

---

### reset-markflow.ps1

**DESTRUCTIVE.** Tears down everything (containers, volumes, images), force-pulls from GitHub, rebuilds from scratch. Use only when you want a completely clean slate.

**What it destroys:**
- All containers and images
- SQLite database (all conversion history, preferences, user data)
- Meilisearch index (all search data)
- Qdrant vector index
- Whisper model cache
- Converted output files

**What it does:**
1. Tears down all containers, volumes, and images
2. Force-pulls latest code (hard reset to origin/main)
3. Auto-detects GPU hardware
4. Ensures `.env` is configured with work machine paths
5. Rebuilds and starts all services from scratch

**Usage:**
```powershell
.\reset-markflow.ps1
.\reset-markflow.ps1 -SourceDir "C:\MyDocs" -OutputDir "D:\Output"
.\reset-markflow.ps1 -SkipPrune     # skip docker system prune
```

**Parameters:**
- `-RepoDir` — repo root
- `-SourceDir` — source documents path (default: `C:/Users/Xerxes/T86_Work/k_drv_test`)
- `-OutputDir` — bulk output path (default: `D:/Doc-Conv_Test`)
- `-DriveC`, `-DriveD` — host drive mounts
- `-SkipPrune` — skip `docker system prune` step

---

### switch-2vector.ps1

Interactive branch switcher. Fetches all remote branches, displays a numbered menu, and checks out the selected branch with a clean pull. Optionally rebuilds and restarts Docker.

**Usage:**
```powershell
.\switch-2vector.ps1                # interactive menu
.\switch-2vector.ps1 -Build         # switch + rebuild + restart
.\switch-2vector.ps1 -NoBuild       # switch + restart only (no rebuild)
```

---

### pull-logs.ps1

Copies logs from the Docker container to a local directory with timestamps. Useful for sharing logs or debugging offline.

**Output location:** `D:\!!! TEMP\logs\`

**Usage:**
```powershell
.\pull-logs.ps1              # full logs
.\pull-logs.ps1 -Tail 5000  # last 5000 lines only
```

---

### Utility Python Scripts

| Script | Purpose |
|--------|---------|
| `gen_review_doc.py` | Generate a code review document |
| `generate_audit_doc.py` | Generate audit documentation |
| `generate_full_audit.py` | Generate comprehensive audit report |

These are one-off utility scripts, not part of the regular operational workflow.
