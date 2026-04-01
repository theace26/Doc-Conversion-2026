# Claude Code: Generate MarkFlow Deployment Scripts

## Purpose

This document instructs Claude Code to generate **machine-specific deployment scripts**
for a new MarkFlow user. The user already has the repo cloned. Claude Code should ask
the necessary questions, then produce customized scripts for their platform.

---

## What to generate

Three scripts in a user-chosen directory (default: a `my-scripts/` folder alongside
the repo, NOT inside the repo -- so `git pull` doesn't overwrite them).

**For Windows users:** PowerShell scripts (`.ps1`)
**For macOS users:** Bash scripts (`.sh`)

If the platform is unknown, ask the user first.

### 1. `setup-markflow.ps1` / `setup-markflow.sh`
First-time setup script. Must:
- Open a native folder-picker dialog for **Source Directory** (the folder of documents to convert)
- Open a native folder-picker dialog for **Output Directory** (where converted files go)
- Validate both paths exist (create output dir if needed, warn if source is empty)
- Auto-detect CPU threads and RAM, prompt user to confirm or override
- Calculate optimal `BULK_WORKER_COUNT` (~67% of threads, min 2, max 12)
- Calculate Meilisearch memory based on RAM (32GB+=1g, 16GB+=512m, 8GB+=256m, <8GB=128m)
- Generate a cryptographic Meilisearch master key (API key for search auth)
- Auto-detect the repo location (default: parent of the script, or ask the user)
- Auto-detect GPU hardware (platform-specific -- see GPU Detection below)
- Install hashcat if missing (winget on Windows, brew on macOS, or skip with a message)
- Write `worker_capabilities.json` to `hashcat-queue/`
- Write `.env` with the user's chosen paths, tuned workers, Meili key, and memory limits
- Check if `markflow-base:latest` Docker image exists; build it if not
- Build the app image and start all services (`docker compose up -d --build`)
- Include NVIDIA GPU overlay (`docker-compose.gpu.yml`) automatically if NVIDIA detected (Windows only)
- Start the hashcat host worker for non-NVIDIA GPUs (or all GPUs on macOS)
- Print service URLs, GPU status, and tuned hardware values when done

**Folder picker implementation:**

| Platform | Method |
|----------|--------|
| **Windows** | `System.Windows.Forms.FolderBrowserDialog` with descriptive title, starting at user's home. Cancel = abort with message. |
| **macOS** | `osascript -e 'choose folder with prompt "..." default location ...'` via AppleScript. Cancel = abort with message. |

### 2. `refresh-markflow.ps1` / `refresh-markflow.sh`
Quick update script (preserves data). Must:
- Auto-detect the repo location
- Force-pull latest code from GitHub (`git fetch origin && git reset --hard origin/main`)
- Re-detect GPU hardware and update `worker_capabilities.json`
- Rebuild Docker images with new code (`docker compose build`)
- Restart containers (`docker compose up -d`)
- Start hashcat host worker if applicable
- Support a skip-build flag (`-NoBuild` on Windows, `--no-build` on macOS)
- Print service URLs and GPU status when done

### 3. `build-base.ps1` / `build-base.sh`
Base image builder (run once). Must:
- Build `markflow-base:latest` from `Dockerfile.base`
- Show timing (start a stopwatch/timer, print elapsed time)
- Support a no-cache flag (`-NoCache` on Windows, `--no-cache` on macOS)
- Print next-step instructions when done

---

## Questions to ask the user

Before generating scripts, ask:

1. **What platform?** Windows or macOS. This determines script language and GPU detection method.

2. **Where is the repo cloned?** (e.g., `C:\Users\John\Projects\Doc-Conversion-2026` or
   `~/Projects/Doc-Conversion-2026`). Use this as the default repo path in all scripts.

3. **Where should the scripts live?** Recommend a folder OUTSIDE the repo so `git pull`
   won't touch them. Default suggestion:
   - Windows: `C:\Users\<username>\markflow-scripts\`
   - macOS: `~/markflow-scripts/`

4. **Drive mounts (Windows only):** The drive browser mounts C: and D: into the container.
   Ask if they have a D: drive or other drives they want browsable. On macOS, drives are
   not letter-based -- skip this question.

5. **Any custom port needs?** Default is 8000/8001/7700. If they have conflicts, adjust.

Note: CPU cores, RAM, and Meilisearch config are **not** asked upfront -- the setup script
auto-detects them at runtime and prompts the user to confirm or override. This keeps the
Claude Code questionnaire short while still tuning for the hardware.

---

## GPU Detection by Platform

### Windows

```
NVIDIA detection:
  1. nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits
  2. Fallback: Get-CimInstance Win32_VideoController

AMD/Intel detection:
  Get-CimInstance Win32_VideoController | match "amd|radeon" or "intel" + "arc|iris|xe|uhd"

NVIDIA overlay:
  If NVIDIA detected AND nvidia-smi works AND docker-compose.gpu.yml exists,
  include -f docker-compose.gpu.yml in compose args.
  Non-NVIDIA GPUs use the host worker path.
```

### macOS

```
GPU detection:
  system_profiler SPDisplaysDataType | grep "Chipset Model|VRAM"

Apple Silicon:
  gpu_vendor = "apple"
  Unified memory reported via: sysctl -n hw.memsize
  hashcat backend = "Metal"

AMD (older Intel Macs):
  gpu_vendor = "amd"
  hashcat backend = "OpenCL" or "Metal" (newer hashcat versions)

Intel integrated:
  gpu_vendor = "intel"
  Limited GPU benefit

NVIDIA overlay:
  NEVER used on macOS. NVIDIA container passthrough is not available.
  All GPU cracking goes through the host worker path.
```

### hashcat Installation

| Platform | Auto-install command | Backend probe |
|----------|---------------------|---------------|
| Windows | `winget install hashcat.hashcat` | `hashcat -I` (requires cd to hashcat dir) |
| macOS | `brew install hashcat` | `hashcat -I` (Metal/OpenCL auto-detected) |

---

## Template patterns to follow

Reference the existing scripts in `Scripts/friend-deploy/` for:
- Windows: `setup-markflow.ps1`, `refresh-markflow.ps1`, `build-base.ps1`
- macOS: `setup-markflow.sh`, `refresh-markflow.sh`, `build-base.sh`

Key patterns from these scripts:
- GPU detection logic (platform-specific)
- hashcat auto-install and backend probing
- `worker_capabilities.json` format
- Docker compose argument construction
- Colored output styling
- Error handling
- Folder picker implementation

Key principles for generated scripts:
- **No hardcoded paths** -- everything derived from user input or auto-detected
- **Folder picker dialogs** in setup script instead of parameter defaults
- **Repo path auto-detected** or prompted
- Scripts live **outside the repo** so they survive `git pull`

---

## .env template

The setup script should write this `.env` file to the repo root:

```
# MarkFlow Environment Configuration
# Auto-generated by setup-markflow on {date}
# Hardware: {cpu_threads} threads, {ram_gb}GB RAM

# Host paths - mounted into Docker containers
SOURCE_DIR={user_source_dir}
OUTPUT_DIR={user_output_dir}

# Drive mounts (Windows only -- omit on macOS)
# DRIVE_C=C:/
# DRIVE_D=D:/

# Meilisearch (full-text search engine)
MEILI_MASTER_KEY={auto_generated_hex_key}
MEILI_MEMORY_LIMIT={1g|512m|256m|128m}
MEILI_MAX_INDEXING_MEMORY={bytes_matching_memory_limit}

# Bulk conversion (tuned for {cpu_threads} threads)
BULK_WORKER_COUNT={calculated_workers}

# App
SECRET_KEY=dev-secret-change-in-prod
DEFAULT_LOG_LEVEL=normal
DEV_BYPASS_AUTH=true
```

**Hardware tuning rules:**
- `BULK_WORKER_COUNT` = floor(cpu_threads * 2/3), clamped to 2-12
- `MEILI_MEMORY_LIMIT`: 32GB+ RAM = 1g, 16GB+ = 512m, 8GB+ = 256m, <8GB = 128m
- `MEILI_MAX_INDEXING_MEMORY`: same as MEILI_MEMORY_LIMIT but in bytes
- `MEILI_MASTER_KEY`: 64-char hex string from cryptographic random (openssl rand -hex 32)

**Windows paths** must use **forward slashes** (`C:/Users/John/Documents` not
`C:\Users\John\Documents`). macOS paths are already forward-slash native.

---

## Important gotchas for script generation

### Both Platforms
- **Docker must be running**: Check with `docker info` before proceeding.
- **Base image is slow**: First build takes 5-40 min depending on disk speed. Warn the user.
- **hashcat -I output**: hashcat writes diagnostic info to stderr. Suppress or handle it.
- **NVIDIA overlay**: Only include `-f docker-compose.gpu.yml` if NVIDIA is detected AND
  nvidia-smi works AND the gpu overlay file exists AND the platform is Windows. Never on macOS.

### Windows-Specific
- **PowerShell BOM**: Use `[IO.File]::WriteAllText()` for writing `.env` and JSON files.
  `Set-Content -Encoding UTF8` writes a BOM on Windows PowerShell 5.x which breaks
  Python's `json.loads()`.
- **hashcat -I requires cwd**: Must `Set-Location` to hashcat's install directory before
  running `hashcat -I`, or it fails with `./OpenCL/: No such file or directory`.
- **PowerShell native stderr**: hashcat writes to stderr. Wrap calls with
  `$ErrorActionPreference = 'SilentlyContinue'` to prevent exceptions.
- **Docker path format**: All paths in `.env` must use forward slashes. Convert with
  `$path.Replace('\', '/')`.
- **Admin elevation**: hashcat install and some GPU tools need Administrator. Check at
  script start and warn (don't block).

### macOS-Specific
- **Script permissions**: Generated `.sh` files need `chmod +x` before first run. Include
  this in the instructions to the user.
- **AppleScript folder picker**: Requires Terminal to have Automation permissions in
  System Settings > Privacy & Security > Automation. The first run may prompt the user.
- **Apple Silicon Docker**: Docker Desktop uses Rosetta 2 transparently. If the base image
  has platform issues, add `platform: linux/amd64` to docker-compose.yml services.
- **No drive letters**: macOS doesn't have C:/D: drives. Skip the drive-mount section
  entirely. The source and output directories are the only mounts needed.
- **Homebrew path**: On Apple Silicon, Homebrew installs to `/opt/homebrew/bin`. On Intel
  Macs, it's `/usr/local/bin`. The `brew` command handles this, but `hashcat` may not be
  on PATH immediately after install. Suggest `eval "$(brew shellenv)"` or terminal restart.
- **No WMI**: `Get-CimInstance` doesn't exist on macOS. Use `system_profiler` for hardware
  detection and `sysctl` for memory info.
- **File writes**: Use `cat > file << EOF ... EOF` (heredoc) for writing multi-line files.
  No BOM issues on macOS.
- **Background processes**: Use `nohup command &>/dev/null &` for the hashcat host worker.
  On Windows, use `Start-Process -WindowStyle Hidden`.
