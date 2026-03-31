# Getting Started with Claude Code + MarkFlow

This guide gets you from zero to a working Claude Code setup with MarkFlow deployed.
Follow it top to bottom -- each step builds on the last.

---

## Part 1: Get Claude Code Installed

### What is Claude Code?

Claude Code is Anthropic's CLI tool that gives Claude full access to your terminal,
filesystem, and development tools. You talk to it in plain English and it reads files,
writes code, runs commands, and manages your projects. Think of it as a senior dev
sitting in your terminal.

### Account Requirement

You need a **paid Anthropic account**. Free accounts don't have Claude Code access.

| Plan | Cost | Notes |
|------|------|-------|
| **Claude Pro** | $20/month | Good starting point |
| **Claude Max** | $200/month | Higher usage limits |

Sign up or upgrade at: https://claude.ai/pricing

### Install Claude Code

Open **PowerShell** and run:

```powershell
irm https://claude.ai/install.ps1 | iex
```

That's it. No Node.js, no npm, no WSL. It runs natively on Windows.

**Alternative install via winget:**
```powershell
winget install Anthropic.ClaudeCode
```

### Verify the Install

```powershell
claude --version
```

You should see a version number. If you get an error about `claude` not being found,
close and reopen PowerShell so your PATH refreshes.

### Prerequisites Check

You need **Git for Windows** installed. Claude Code requires it.

```powershell
git --version
```

If that doesn't work, install Git:
```powershell
winget install Git.Git
```
Then restart PowerShell.

---

## Part 2: First Launch & Authentication

### Start Claude Code

Open PowerShell and type:

```powershell
claude
```

### Authenticate

On first launch, Claude Code opens your browser for login:

1. A browser tab opens automatically to Anthropic's login page
2. If the browser doesn't open, press `c` to copy the login URL and paste it manually
3. Log in with your Claude Pro/Max account
4. Once authenticated, the browser confirms success
5. Back in your terminal, Claude Code is ready

You only do this once. Your credentials are stored locally and persist across sessions.

### Quick Test

Once authenticated, type something to make sure it works:

```
hello, what model are you?
```

Claude should respond. Type `/exit` to leave when you're done testing.

---

## Part 3: Install Docker Desktop

MarkFlow runs in Docker, so you need Docker Desktop installed and running.

1. Download from: https://www.docker.com/products/docker-desktop/
2. Install it (defaults are fine)
3. Launch Docker Desktop
4. Wait for it to finish starting (the whale icon in your system tray stops animating)

Verify Docker works:
```powershell
docker --version
docker compose version
```

Both should return version numbers.

---

## Part 4: Clone MarkFlow & Deploy

### Clone the Repository

```powershell
cd C:\Users\$env:USERNAME\Projects
git clone https://github.com/theace26/Doc-Conversion-2026.git
cd Doc-Conversion-2026
```

If the `Projects` folder doesn't exist, create it first:
```powershell
mkdir C:\Users\$env:USERNAME\Projects
```

### Run the Setup Script

Open PowerShell **as Administrator** (right-click > Run as Administrator):

```powershell
cd C:\Users\$env:USERNAME\Projects\Doc-Conversion-2026\Scripts\friend-deploy
.\setup-markflow.ps1
```

**What happens:**

1. Two folder-picker windows pop up:
   - **First:** Pick the folder with documents you want to convert (your "source" -- MarkFlow only reads from this, never writes)
   - **Second:** Pick where you want converted output saved (any local folder with free space)
2. The script auto-detects your GPU
3. It writes the Docker configuration
4. It builds the Docker base image (**this takes 25-40 minutes the first time** -- it's downloading LibreOffice, Tesseract OCR, ffmpeg, Whisper, and a bunch of other tools into the container)
5. It starts all three services

When it finishes you'll see:

```
==========================================
  Setup Complete!
==========================================

  MarkFlow UI:  http://localhost:8000
  Meilisearch:  http://localhost:7700
  MCP Server:   http://localhost:8001
==========================================
```

Open http://localhost:8000 in your browser. You should see the MarkFlow UI.

---

## Part 5: Using Claude Code with MarkFlow

Now the fun part. Claude Code can work directly with the MarkFlow codebase
and connect to MarkFlow's MCP server to search and manage documents.

### Start a Claude Code Session in the Project

```powershell
cd C:\Users\$env:USERNAME\Projects\Doc-Conversion-2026
claude
```

Claude Code automatically reads the project's `CLAUDE.md` file and understands
the entire codebase -- architecture, file locations, gotchas, everything.

### Things You Can Ask Claude Code

**About the codebase:**
```
what does the bulk conversion pipeline do?
show me how OCR confidence scoring works
explain the password recovery cascade
```

**To make changes:**
```
add a new format handler for .xyz files
fix the bug where [describe the issue]
```

**To run operations:**
```
run the tests
check the Docker container logs
show me the health check output
```

### Connect the MCP Server (Optional)

MarkFlow has an MCP server that lets Claude Code search your converted documents,
trigger conversions, and browse your file catalog directly.

Create a `.mcp.json` file in the repo root:

```json
{
  "mcpServers": {
    "markflow": {
      "type": "http",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

Or use the CLI:
```powershell
claude mcp add markflow --type http --url http://localhost:8001/sse
```

Now Claude Code has access to 10 MarkFlow tools:
- `search_documents` -- full-text search across all converted documents
- `read_document` -- retrieve a specific document
- `convert_document` -- trigger a conversion
- `search_transcripts` -- search audio/video transcripts
- And 6 more

Try it:
```
search my converted documents for "quarterly report"
```

---

## Part 6: Day-to-Day Usage

### Pulling Updates

When there's new code (I'll let you know), run:

```powershell
cd C:\Users\$env:USERNAME\Projects\Doc-Conversion-2026\Scripts\friend-deploy
.\refresh-markflow.ps1
```

This pulls the latest code, rebuilds the app (fast -- only code layer, not the base image),
and restarts everything. Your database, search index, and converted files are preserved.

### Starting / Stopping MarkFlow

```powershell
cd C:\Users\$env:USERNAME\Projects\Doc-Conversion-2026

# Stop everything
docker compose down

# Start everything
docker compose up -d

# Watch logs
docker compose logs -f markflow

# Check status
docker compose ps
```

### Useful MarkFlow Pages

| URL | What it does |
|-----|-------------|
| http://localhost:8000 | Main UI -- drag-and-drop file conversion |
| http://localhost:8000/bulk.html | Bulk scan + convert an entire directory |
| http://localhost:8000/search.html | Full-text search across all documents |
| http://localhost:8000/history.html | Conversion history with redownload |
| http://localhost:8000/settings.html | All preferences (OCR, workers, logging, etc.) |
| http://localhost:8000/status.html | Active jobs with progress and controls |
| http://localhost:8000/resources.html | CPU, memory, disk, activity monitoring |
| http://localhost:8000/help.html | Built-in help wiki (19 articles) |
| http://localhost:8000/docs | Interactive API documentation |
| http://localhost:8000/api/health | System health check (JSON) |

---

## Part 7: Claude Code Tips & Shortcuts

### Essential Slash Commands

Type these inside a Claude Code session:

| Command | What it does |
|---------|-------------|
| `/help` | Show all available commands |
| `/exit` | Quit the session |
| `/cost` | Show token usage for this session |
| `/clear` | Clear conversation history |
| `/config` | Open settings |
| `/memory` | View Claude Code's memory about you and the project |
| `/init` | Generate a CLAUDE.md for a project |

### Running Shell Commands from Claude Code

If Claude suggests you run something yourself (like an interactive login),
type `!` followed by the command:

```
! docker compose logs -f markflow
```

The `!` prefix runs it in your terminal directly.

### Resuming Previous Conversations

```powershell
claude -c    # continue most recent conversation
claude -r    # pick from previous conversations
```

### Multiple Platforms

Claude Code also has:
- **VS Code extension** -- install from the marketplace (`anthropic.claude-code`)
- **Desktop app** -- download from https://claude.ai/download
- **Web version** -- https://claude.ai/code (runs in browser, good for long tasks)

All share the same configuration and MCP servers.

---

## Troubleshooting

### "claude: command not found"
Close and reopen PowerShell. If still broken:
```powershell
# Check if it's installed
Get-Command claude -ErrorAction SilentlyContinue
```
If not found, reinstall: `irm https://claude.ai/install.ps1 | iex`

### "Claude Code on Windows requires git-bash"
Install Git for Windows: `winget install Git.Git`, then restart PowerShell.

### Docker build fails
- Make sure Docker Desktop is running (check the system tray icon)
- Make sure you have disk space (the base image is ~3-4 GB)
- Try: `docker system prune -f` to free space, then run the setup script again

### "Port 8000 already in use"
Something else is using that port. Find out what:
```powershell
netstat -ano | findstr :8000
```
Either stop that process or edit `docker-compose.yml` to change the port.

### Setup script doesn't open folder picker
Make sure you're running PowerShell (not CMD). The folder picker uses .NET's
`System.Windows.Forms` which requires PowerShell.

### MCP server not connecting
1. Make sure MarkFlow is running: `docker compose ps`
2. Check that port 8001 is accessible: `curl http://localhost:8001/sse`
3. Verify `.mcp.json` is in the repo root (not in a subfolder)

---

## Quick Reference Card

```
INSTALL:        irm https://claude.ai/install.ps1 | iex
START SESSION:  cd Doc-Conversion-2026 && claude
DEPLOY:         Scripts\friend-deploy\setup-markflow.ps1
UPDATE:         Scripts\friend-deploy\refresh-markflow.ps1
MARKFLOW UI:    http://localhost:8000
MCP SERVER:     http://localhost:8001/sse
API DOCS:       http://localhost:8000/docs
```
