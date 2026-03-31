# MarkFlow Deployment Guide

This guide walks you through deploying MarkFlow on your machine from scratch.
You'll have a fully working document conversion system in about 30-40 minutes
(most of that is the one-time Docker base image build).

Covers both **Windows** and **macOS** deployment.

---

## Prerequisites

### Windows

| Requirement | How to get it | Verify with |
|-------------|---------------|-------------|
| **Docker Desktop** | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | `docker --version` |
| **Git** | [git-scm.com](https://git-scm.com/download/win) or `winget install Git.Git` | `git --version` |
| **PowerShell 5.1+** | Comes with Windows 11 | `$PSVersionTable.PSVersion` |

### macOS

| Requirement | How to get it | Verify with |
|-------------|---------------|-------------|
| **Docker Desktop** | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | `docker --version` |
| **Git** | `xcode-select --install` (includes Git) | `git --version` |
| **Bash 3.2+** | Comes with macOS | `bash --version` |

### Optional (for GPU-accelerated password cracking)

| Platform | Requirement | How to get it |
|----------|-------------|---------------|
| **Windows** | hashcat | `winget install hashcat.hashcat` |
| **Windows** | NVIDIA GPU drivers | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) |
| **Windows** | NVIDIA Container Toolkit | [docs.nvidia.com](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (GPU passthrough into Docker) |
| **macOS** | hashcat | `brew install hashcat` |

**Note on macOS GPU:** NVIDIA container passthrough is not available on macOS. Apple
Silicon and AMD GPUs use the host worker path (hashcat runs natively on the Mac, not
inside Docker). Apple Silicon Macs use Metal via hashcat for GPU acceleration.

Docker Desktop must be **running** before you execute any scripts.

---

## Step 1: Clone the Repository

### Windows (PowerShell)

```powershell
cd C:\Users\$env:USERNAME\Projects
git clone https://github.com/theace26/Doc-Conversion-2026.git
cd Doc-Conversion-2026
```

### macOS (Terminal)

```bash
cd ~/Projects
git clone https://github.com/theace26/Doc-Conversion-2026.git
cd Doc-Conversion-2026
```

If the `Projects` folder doesn't exist, create it first (`mkdir ~/Projects`).

---

## Step 2: Prepare Your Directories

MarkFlow needs two directories on your machine:

1. **Source Directory** (read-only) -- The folder containing documents you want to convert.
   This can be any folder: a network share, a local archive, a test folder with a few files.

2. **Output Directory** -- Where MarkFlow writes converted Markdown files during bulk jobs.
   This should be on a local drive with decent space (SSD preferred for performance).

You'll pick these interactively when running the setup script.

---

## Step 3: Run the Setup Script

The setup script is your one-stop first-time deployment. It:
- Prompts you to browse/pick your source and output directories
- Auto-detects your GPU hardware
- Installs hashcat if missing (optional, for password cracking)
- Writes the `.env` configuration file
- Builds the Docker base image (slow first time -- only once)
- Builds the app image and starts all services

### Windows

**Run as Administrator** (right-click PowerShell > "Run as Administrator"):

```powershell
cd C:\Users\$env:USERNAME\Projects\Doc-Conversion-2026\Scripts\friend-deploy
.\setup-markflow.ps1
```

### macOS

```bash
cd ~/Projects/Doc-Conversion-2026/Scripts/friend-deploy
chmod +x setup-markflow.sh
./setup-markflow.sh
```

Both scripts open native folder-picker dialogs for your source and output directories.
Follow the prompts.

When it finishes, you'll see:

```
==========================================
  Setup Complete!
==========================================

  MarkFlow UI:  http://localhost:8000
  Meilisearch:  http://localhost:7700
  MCP Server:   http://localhost:8001
==========================================
```

Open **http://localhost:8000** in your browser to verify.

---

## Step 4: Test It Out

### Quick single-file test
1. Go to http://localhost:8000
2. Drop a .docx, .pdf, or .pptx file onto the upload zone
3. Click **Convert** -- you'll get a Markdown file back

### Bulk conversion test
1. Go to http://localhost:8000/bulk.html
2. Your source directory is pre-configured -- click **Start Scan**
3. After scanning, click **Start Conversion**
4. Watch real-time progress with per-worker status

### Search test
1. After converting some files, go to http://localhost:8000/search.html
2. Type a keyword -- Meilisearch indexes everything automatically

### Health check

```bash
curl http://localhost:8000/api/health
```

---

## Day-to-Day Operations

After the initial setup, you only need two scripts:

### Refresh (pull latest code, rebuild, restart -- keeps your data)

**Windows:**
```powershell
.\refresh-markflow.ps1
```

**macOS:**
```bash
./refresh-markflow.sh
```

This pulls the latest code from GitHub, rebuilds the Docker image (fast -- only the
code + pip layer), and restarts all containers. Your database, search index, and
converted files are preserved.

### Full Reset (tear down everything, start fresh)

Re-run the setup script if you want to start completely fresh (new directories, clean
database). It will prompt for directories again.

---

## What's Running

MarkFlow deploys three Docker containers:

| Service | Port | Purpose |
|---------|------|---------|
| **markflow** | 8000 | Main app (FastAPI + web UI) |
| **markflow-mcp** | 8001 | MCP server (Claude.ai integration) |
| **meilisearch** | 7700 | Full-text search engine |

Plus optionally a **hashcat host worker** process (runs natively, not in Docker)
for GPU password cracking. On macOS, this is the only GPU path -- NVIDIA container
passthrough is not available.

### Useful Docker commands
```bash
docker compose ps                    # see running containers
docker compose logs -f markflow      # watch app logs
docker compose down                  # stop everything
docker compose up -d                 # start everything
```

---

## macOS-Specific Notes

### Apple Silicon (M1/M2/M3/M4)

MarkFlow's Docker image is built for linux/amd64 by default. Docker Desktop on Apple
Silicon uses Rosetta 2 emulation transparently -- no configuration needed. Performance
is good for document conversion workloads.

If you experience issues, you can force the platform in docker-compose.yml:
```yaml
services:
  markflow:
    platform: linux/amd64
```

### GPU Acceleration on macOS

macOS does not support NVIDIA container passthrough. GPU password cracking uses the
host worker pattern:

- **Apple Silicon:** hashcat uses Metal backend natively
- **AMD (older Macs):** hashcat uses OpenCL backend
- **Intel integrated:** Limited GPU benefit; CPU cracking is usually faster

The setup script auto-detects your GPU and configures the host worker accordingly.

### Docker Resource Allocation

Docker Desktop on macOS has conservative default memory limits. For large bulk
conversions, increase the allocation:

1. Open Docker Desktop > Settings > Resources
2. Set Memory to at least **4 GB** (8 GB recommended for large repos)
3. Set CPU to at least **4 cores**
4. Click Apply & Restart

### File Sharing

Docker Desktop on macOS may prompt for file sharing permissions when mounting your
source and output directories. Allow access when prompted. You can also pre-configure
this in Docker Desktop > Settings > Resources > File sharing.

### Network Share Access (SMB)

To mount a network share as your source directory on macOS:

1. In Finder, press Cmd+K
2. Enter `smb://server-ip/share-name`
3. The share mounts at `/Volumes/share-name`
4. Use `/Volumes/share-name` as your source directory in the setup script

Note: macOS SMB mounts can disconnect during sleep. For reliable bulk conversions,
prevent sleep (`caffeinate -s`) or use a wired connection.

---

## Troubleshooting

### General

| Problem | Solution |
|---------|----------|
| "Docker is not running" | Start Docker Desktop and wait for it to finish loading |
| Build takes forever | Base image build (~25-40 min HDD, ~5-15 min SSD) only happens once |
| "Port 8000 already in use" | Stop whatever's using it, or change the port in docker-compose.yml |
| Source directory shows 0 files | Check the path in `.env` -- it must point to the actual files |
| GPU not detected | Make sure drivers are installed; restart terminal after installing hashcat |

### Windows-Specific

| Problem | Solution |
|---------|----------|
| Setup script doesn't open folder picker | Use PowerShell (not CMD). The picker needs .NET's System.Windows.Forms |
| hashcat auto-install fails | Install manually: `winget install hashcat.hashcat`, restart PowerShell |
| "Port already in use" | `netstat -ano \| findstr :8000` to find the process |

### macOS-Specific

| Problem | Solution |
|---------|----------|
| "permission denied" on script | Run `chmod +x setup-markflow.sh` first |
| Folder picker doesn't appear | Make sure Terminal has accessibility permissions (System Settings > Privacy) |
| Slow Docker performance | Increase Docker Desktop memory/CPU allocation (see macOS notes above) |
| Network share disconnects | Use `caffeinate -s` to prevent sleep during bulk conversions |
| "no matching manifest for linux/arm64" | Add `platform: linux/amd64` to docker-compose.yml services |
| hashcat Metal not detected | Update macOS and hashcat (`brew upgrade hashcat`) |
| `osascript` permission error | Grant Terminal "Automation" permission in System Settings > Privacy > Automation |

---

## File Layout After Setup

```
Doc-Conversion-2026/
  .env                    # Your machine-specific config (gitignored)
  docker-compose.yml      # Container definitions
  Dockerfile              # App image (fast rebuild)
  Dockerfile.base         # Base image (slow, built once)
  Scripts/
    friend-deploy/
      setup-markflow.ps1    # Windows setup
      setup-markflow.sh     # macOS setup
      refresh-markflow.ps1  # Windows refresh
      refresh-markflow.sh   # macOS refresh
      build-base.ps1        # Windows base image builder
      build-base.sh         # macOS base image builder
      DEPLOY-GUIDE.md       # This file
      CLAUDE-INSTRUCTIONS.md # For Claude Code to generate custom scripts
```

---

## Using Claude Code with MarkFlow

MarkFlow exposes an MCP server on port 8001. To connect Claude Code (or Claude.ai) to it:

1. The MCP server starts automatically with MarkFlow
2. Connect your MCP client to `http://localhost:8001/sse`
3. Available tools: search_documents, read_document, convert_document, and 7 more

See the README.md in the repo root for the full MCP tool list.

---

## Generating Custom Scripts with Claude Code

If you want Claude Code to generate scripts tailored to your specific machine
(different OS, custom paths, VM deployment, etc.), use the instruction file:

```
Scripts/friend-deploy/CLAUDE-INSTRUCTIONS.md
```

Open a Claude Code session in the repo directory and tell it:

> Read Scripts/friend-deploy/CLAUDE-INSTRUCTIONS.md and generate deployment
> scripts for my machine.

Claude Code will ask you the relevant questions and produce scripts customized
to your environment.
