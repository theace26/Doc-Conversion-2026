<#
.SYNOPSIS
    Overnight unattended rebuild of MarkFlow with CUDA Whisper (v0.22.15+).

.DESCRIPTION
    Pulls the latest vector branch, rebuilds the Docker base image with
    CUDA 12.1 torch, rebuilds the app image on top, and starts the stack
    detached. Designed to run unattended overnight.

    Halts on the first failure with a clear error code. Writes a
    timestamped transcript to Scripts/work/overnight/logs/.

    Safe steps to leave running overnight:
      1. Script halts on any failure (ErrorActionPreference = Stop)
      2. Final 'docker-compose up -d' is detached, so you can close the
         terminal after the script exits
      3. A health check runs at the end and is captured in the log, so
         the morning review is a one-liner

.PARAMETER SkipGpuCheck
    Skip the NVIDIA Container Toolkit smoke test. Use only if you have
    already verified GPU passthrough today.

.PARAMETER SkipPull
    Skip the git fetch/checkout/pull steps. Use when you already have
    the desired commit checked out and just want to rebuild Docker.

.PARAMETER SkipBase
    Skip the base image rebuild. Use when you only changed Python code
    and Dockerfile.base is unchanged. Saves 5 to 25 minutes.

.PARAMETER Branch
    Git branch to pull. Defaults to 'vector'.

.PARAMETER RepoDir
    Override the repo root. By default the script resolves its own
    location and walks up three levels, which works as long as the
    script stays at Scripts/work/overnight/rebuild.ps1.

.EXAMPLE
    .\rebuild.ps1
    Full overnight rebuild: GPU check + git pull + base + app + up.

.EXAMPLE
    .\rebuild.ps1 -SkipGpuCheck
    Skip the GPU smoke test (you verified it earlier today).

.EXAMPLE
    .\rebuild.ps1 -SkipPull -SkipBase
    Fast iteration: rebuild only the app layer on top of the existing
    base image, no git pull.

.NOTES
    Version conventions: ASCII only, no em dashes (PowerShell 5.1 reads
    BOM-less UTF-8 as Windows-1252 and corrupts non-ASCII characters).
    Logs under Scripts/work/overnight/logs/ are gitignored automatically
    by the repo root 'logs/' rule.
#>

[CmdletBinding()]
param(
    [switch]$SkipGpuCheck,
    [switch]$SkipPull,
    [switch]$SkipBase,
    [string]$Branch = "vector",
    [string]$RepoDir = ""
)

$ErrorActionPreference = "Stop"

# -----------------------------------------------------------------------------
# Resolve paths (script-relative by default, -RepoDir override available)
# -----------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrEmpty($RepoDir)) {
    $RepoDir = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
}
$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "rebuild-$Stamp.log"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Label)
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] >>> $Label" -ForegroundColor Yellow
}

function Assert-ExitCode {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] FAILED: $What (exit $LASTEXITCODE)" -ForegroundColor Red
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$transcriptActive = $false

try {
    Start-Transcript -Path $LogFile | Out-Null
    $transcriptActive = $true
} catch {
    Write-Host "Warning: could not start transcript ($($_.Exception.Message)). Continuing without a log file." -ForegroundColor DarkYellow
}

try {
    Write-Header "MarkFlow Overnight Rebuild"
    Write-Host "  Started:      $(Get-Date)"
    Write-Host "  Repo:         $RepoDir"
    Write-Host "  Branch:       $Branch"
    Write-Host "  Log file:     $LogFile"
    Write-Host "  SkipGpuCheck: $SkipGpuCheck"
    Write-Host "  SkipPull:     $SkipPull"
    Write-Host "  SkipBase:     $SkipBase"

    if (-not (Test-Path $RepoDir)) {
        throw "Repo directory does not exist: $RepoDir"
    }
    Push-Location $RepoDir

    # -------------------------------------------------------------------------
    # Step 1: GPU toolkit smoke test
    # -------------------------------------------------------------------------
    if (-not $SkipGpuCheck) {
        Write-Step "GPU toolkit smoke test (NVIDIA Container Toolkit)"
        Write-Host "  If this fails, the toolkit is not installed in WSL2 and"
        Write-Host "  everything downstream will fall back to CPU. See"
        Write-Host "  docs/help/gpu-setup.md."
        docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
        Assert-ExitCode "GPU smoke test"
    } else {
        Write-Step "GPU toolkit smoke test SKIPPED (-SkipGpuCheck)"
    }

    # -------------------------------------------------------------------------
    # Step 2: Git pull (fast-forward only, refuses to merge)
    # -------------------------------------------------------------------------
    if (-not $SkipPull) {
        Write-Step "git fetch origin"
        git fetch origin
        Assert-ExitCode "git fetch"

        Write-Step "git checkout $Branch"
        git checkout $Branch
        Assert-ExitCode "git checkout $Branch"

        Write-Step "git pull --ff-only origin $Branch"
        git pull --ff-only origin $Branch
        Assert-ExitCode "git pull --ff-only"

        Write-Step "HEAD after pull"
        git log -1 --oneline
    } else {
        Write-Step "git pull SKIPPED (-SkipPull)"
    }

    # -------------------------------------------------------------------------
    # Step 3: Rebuild base image (the slow step)
    # -------------------------------------------------------------------------
    if (-not $SkipBase) {
        Write-Step "Rebuild base image markflow-base:latest (5 to 25 min)"
        Write-Host "  The CUDA 12.1 torch wheel is ~2.5 GB; first build will"
        Write-Host "  download it. Cached after that."
        docker build -f Dockerfile.base -t markflow-base:latest .
        Assert-ExitCode "docker build base"
    } else {
        Write-Step "Base image rebuild SKIPPED (-SkipBase)"
    }

    # -------------------------------------------------------------------------
    # Step 4: Rebuild app image on top of base
    # -------------------------------------------------------------------------
    Write-Step "Rebuild app image (docker-compose build)"
    docker-compose build
    Assert-ExitCode "docker-compose build"

    # -------------------------------------------------------------------------
    # Step 5: Start the stack detached
    # -------------------------------------------------------------------------
    Write-Step "Start stack detached (docker-compose up -d)"
    docker-compose up -d
    Assert-ExitCode "docker-compose up -d"

    # -------------------------------------------------------------------------
    # Step 6: Wait for lifespan + verify health
    # -------------------------------------------------------------------------
    Write-Step "Waiting 20 seconds for FastAPI lifespan startup"
    Start-Sleep -Seconds 20

    Write-Step "Container status"
    docker-compose ps

    Write-Step "Health check (curl /api/health)"
    Write-Host "  Look for whisper.cuda_available = true and whisper.gpu_name"
    Write-Host ""
    curl.exe -s http://localhost:8000/api/health
    Write-Host ""

    # -------------------------------------------------------------------------
    # Success
    # -------------------------------------------------------------------------
    $stopwatch.Stop()
    $elapsed = $stopwatch.Elapsed.ToString("hh\:mm\:ss")
    Write-Header "REBUILD COMPLETED ($elapsed)"
    Write-Host "  Finished: $(Get-Date)" -ForegroundColor Green
    Write-Host "  Log:      $LogFile" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Morning checklist:"
    Write-Host "    1. Confirm 'cuda_available: true' in the health output above."
    Write-Host "    2. Confirm 'gpu_name' lists your NVIDIA card."
    Write-Host "    3. Retry the failing MP3 convert and watch for"
    Write-Host "       'whisper_device_auto' events with device=cuda in logs."
    Write-Host ""
    Write-Host "  To tail live logs:"
    Write-Host "    docker-compose logs -f markflow"
    Write-Host ""
    exit 0

} catch {
    $stopwatch.Stop()
    $elapsed = $stopwatch.Elapsed.ToString("hh\:mm\:ss")
    Write-Header "REBUILD FAILED ($elapsed)"
    Write-Host "  Error:    $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Failed:   $(Get-Date)" -ForegroundColor Red
    Write-Host "  Log:      $LogFile" -ForegroundColor Red
    Write-Host ""
    Write-Host "  The stack may be in a partial state. Check with:"
    Write-Host "    docker-compose ps"
    Write-Host "    docker-compose logs --tail=100 markflow"
    Write-Host ""
    exit 1
} finally {
    if ($transcriptActive) {
        try { Stop-Transcript | Out-Null } catch {}
    }
    try { Pop-Location } catch {}
}
