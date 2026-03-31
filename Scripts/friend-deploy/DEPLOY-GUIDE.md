# MarkFlow Deployment Guide

This guide walks you through deploying MarkFlow on your Windows machine from scratch.
You'll have a fully working document conversion system in about 30-40 minutes (most of
that is the one-time Docker base image build).

---

## Prerequisites

Install these before starting:

| Requirement | How to get it | Verify with |
|-------------|---------------|-------------|
| **Docker Desktop** | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | `docker --version` |
| **Git** | [git-scm.com](https://git-scm.com/download/win) or `winget install Git.Git` | `git --version` |
| **PowerShell 5.1+** | Comes with Windows 11 | `$PSVersionTable.PSVersion` |

**Optional (for GPU-accelerated password cracking):**

| Requirement | How to get it |
|-------------|---------------|
| **hashcat** | `winget install hashcat.hashcat` (the setup script will try to install this automatically) |
| **NVIDIA GPU drivers** | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) |
| **NVIDIA Container Toolkit** | [docs.nvidia.com/datacenter/cloud-native](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (only if you want GPU passthrough into Docker) |

Docker Desktop must be **running** before you execute any scripts.

---

## Step 1: Clone the Repository

Open PowerShell and run:

```powershell
cd C:\Users\$env:USERNAME\Projects
git clone https://github.com/theace26/Doc-Conversion-2026.git
cd Doc-Conversion-2026
```

If you want to clone to a different location, that's fine -- just remember the path.

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
- Builds the Docker base image (slow, ~25-40 min on HDD, ~5 min on SSD -- only once)
- Builds the app image and starts all services

**Run as Administrator** (right-click PowerShell > "Run as Administrator"):

```powershell
cd C:\Users\$env:USERNAME\Projects\Doc-Conversion-2026\Scripts\friend-deploy
.\setup-markflow.ps1
```

The script will open folder-picker dialogs for your source and output directories.
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
```powershell
curl http://localhost:8000/api/health
```

---

## Day-to-Day Operations

After the initial setup, you only need two scripts:

### Refresh (pull latest code, rebuild, restart -- keeps your data)
```powershell
.\refresh-markflow.ps1
```

This is what you run when there's a new version. It:
- Pulls the latest code from GitHub
- Rebuilds the Docker image (fast -- only code + pip layer)
- Restarts all containers
- Preserves your database, search index, and converted files

### Full Reset (tear down everything, start fresh)
```powershell
.\setup-markflow.ps1
```

Re-run the setup script if you want to start completely fresh (new directories, clean database).
It will prompt for directories again.

---

## What's Running

MarkFlow deploys three Docker containers:

| Service | Port | Purpose |
|---------|------|---------|
| **markflow** | 8000 | Main app (FastAPI + web UI) |
| **markflow-mcp** | 8001 | MCP server (Claude.ai integration) |
| **meilisearch** | 7700 | Full-text search engine |

Plus optionally a **hashcat host worker** process (runs natively, not in Docker) for GPU password cracking.

### Useful Docker commands
```powershell
docker compose ps                    # see running containers
docker compose logs -f markflow      # watch app logs
docker compose down                  # stop everything
docker compose up -d                 # start everything
```

---

## Troubleshooting

### "Docker is not running"
Start Docker Desktop and wait for it to finish loading before running scripts.

### Build takes forever
The base image build (~25-40 min on HDD) only happens once. After that, code rebuilds
take 3-5 minutes. If your drive is slow, consider cloning the repo to an SSD.

### "Port 8000 already in use"
Something else is using that port. Either stop it or edit `docker-compose.yml` to change
the port mapping (e.g., `"9000:8000"` to use port 9000 instead).

### GPU not detected
- Make sure your GPU drivers are installed
- For NVIDIA: `nvidia-smi` should work in PowerShell
- hashcat must be installed for GPU cracking: `winget install hashcat.hashcat`
- Restart PowerShell after installing hashcat so PATH updates

### Source directory shows 0 files
The source directory is mounted read-only. Make sure it actually contains files.
Check the path in `.env` -- forward slashes required (`C:/Users/...` not `C:\Users\...`).

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
      setup-markflow.ps1    # First-time setup (you ran this)
      refresh-markflow.ps1  # Pull + rebuild + restart
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
