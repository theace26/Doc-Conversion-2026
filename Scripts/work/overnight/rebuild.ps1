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

function Invoke-Logged {
    <#
    Run a native command scriptblock, force its stdout and stderr through the
    PowerShell host so Start-Transcript captures the output, then check
    $LASTEXITCODE and throw on non-zero (unless -AllowNonZero is given).

    Why this exists:
      PS 5.1 Start-Transcript does NOT capture stdout/stderr from native
      executables (docker, git, curl, nvidia-smi, etc.) because they bypass
      the PS host and write directly to the console device. Piping through
      'Out-String -Stream | Write-Host' forces each line through the host,
      which the transcript then records. Without this, overnight rebuild logs
      contain only the section headers with empty bodies and are useless for
      morning forensics on a 3am failure.

    Gotcha (docs/gotchas.md ~line 852):
      '2>&1' wraps native stderr lines as RemoteException records in PS 5.1.
      'Out-String -Stream' stringifies them before Write-Host, so the log
      shows the actual command output instead of "RemoteException: <line>".

    Parameters:
      -What          Human label for the step header and error message.
      -Command       ScriptBlock wrapping the native invocation.
      -AllowNonZero  Don't throw on non-zero exit; let the caller inspect
                     $LASTEXITCODE and decide (used by the docker-compose
                     up -d race-override path).
    #>
    param(
        [Parameter(Mandatory)][string]$What,
        [Parameter(Mandatory)][scriptblock]$Command,
        [switch]$AllowNonZero
    )
    Write-Step $What
    # Temporarily relax $ErrorActionPreference. With 'Stop' active, native
    # commands that write a harmless warning to stderr (e.g. docker-compose's
    # "project has been loaded without an explicit name from a symlink")
    # get promoted to a terminating PS error by '2>&1' and blow up the whole
    # pipeline before $LASTEXITCODE can even be checked. We authoritatively
    # use the process exit code instead.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # Stringify ErrorRecord objects before Write-Host so native stderr
        # warnings render as their plain text instead of the full PS error
        # decoration (CategoryInfo, FullyQualifiedErrorId, etc.) that would
        # otherwise dominate the log. See docs/gotchas.md ~line 852.
        & $Command 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                Write-Host $_.Exception.Message
            } else {
                Write-Host "$_"
            }
        }
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($LASTEXITCODE -ne 0 -and -not $AllowNonZero) {
        Write-Host ""
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] FAILED: $What (exit $LASTEXITCODE)" -ForegroundColor Red
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

# -----------------------------------------------------------------------------
# Test-StackHealthy
#
# Purpose:
#   Called after 'docker-compose up -d' returns a non-zero exit code, to decide
#   whether the stack is actually up despite the error. Compose can exit 1 when
#   its post-start container cleanup loses a race with the Docker Desktop
#   reconciler (e.g. 'No such container: <old id>' while the new replacement
#   container is Up and serving traffic). In that case we want to treat the
#   rebuild as successful instead of waking someone up.
#
# Inputs:
#   None. This function shells out to 'docker-compose ps' and curl against
#   http://localhost:8000/api/health.
#
# Returns:
#   $true  -> stack is healthy enough to override the compose exit code
#   $false -> stack is genuinely broken; let the failure propagate
#
# Design notes:
#   - Keep this CONSERVATIVE. A false positive here means an actually-broken
#     stack gets marked "success" and we find out in the morning the hard way.
#     When in doubt, return $false.
#   - Do NOT swallow stderr from the tools you call; the transcript log is
#     the morning forensics trail.
#   - Must tolerate temporary startup delays: health endpoint may not respond
#     instantly even when containers are Up. Caller has already slept 20s
#     before reaching this function in the success path, but on the failure
#     path we arrive immediately. Budget a short retry loop (~10-15s total)
#     rather than a single shot.
# -----------------------------------------------------------------------------
function Test-StackHealthy {
    # Relax EAP locally: docker-compose writes a warning to stderr on every
    # invocation ("project has been loaded without an explicit name from a
    # symlink") and with EAP=Stop the '2>&1' below turns that into a
    # terminating error that kills this function before it can check
    # anything. We rely on $LASTEXITCODE and the content of the response,
    # not on PS error records.
    $ErrorActionPreference = "Continue"

    # Policy (v0.22.16):
    #   1. Container coverage: both 'markflow' and 'markflow-mcp' must be Up.
    #      meilisearch/qdrant are external images that survive rebuilds and
    #      are not in the rebuild blast radius, so we don't re-check them.
    #   2. Health depth: top-level status == 'ok' AND database.ok AND
    #      meilisearch.ok (the app's two critical runtime deps). We
    #      deliberately skip whisper.cuda so this script stays portable to
    #      friend-deploys on CPU-only hosts.
    #   3. Retry budget: 3 attempts, 5 seconds apart (~10-15s total). Enough
    #      to ride out lifespan startup when we arrive on the failure path
    #      without waiting, not enough to hide a genuinely dead stack.
    #
    # Any deviation -> return $false and let the caller throw.

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $psJson = docker-compose ps --format json 2>&1 | Out-String
        $markflowUp = $psJson -match '"Name"\s*:\s*"[^"]*markflow-1"[^}]*"State"\s*:\s*"running"'
        $mcpUp      = $psJson -match '"Name"\s*:\s*"[^"]*markflow-mcp-1"[^}]*"State"\s*:\s*"running"'

        if ($markflowUp -and $mcpUp) {
            $healthJson = curl.exe -sf --max-time 5 http://localhost:8000/api/health 2>$null
            if ($LASTEXITCODE -eq 0 -and $healthJson) {
                # Minimal JSON probing without ConvertFrom-Json (PS 5.1's parser
                # is picky with deeply nested structures and we only need three
                # booleans). Regex against the flat string is enough.
                $statusOk = $healthJson -match '"status"\s*:\s*"ok"'
                $dbOk     = $healthJson -match '"database"\s*:\s*\{[^}]*"ok"\s*:\s*true'
                $meiliOk  = $healthJson -match '"meilisearch"\s*:\s*\{[^}]*"ok"\s*:\s*true'
                if ($statusOk -and $dbOk -and $meiliOk) {
                    Write-Host "    Test-StackHealthy: markflow+mcp Up, status/db/meili all ok (attempt $attempt)" -ForegroundColor Green
                    return $true
                }
                Write-Host "    Test-StackHealthy: health JSON missing required ok flags (attempt $attempt)" -ForegroundColor DarkYellow
            } else {
                Write-Host "    Test-StackHealthy: /api/health unreachable (attempt $attempt)" -ForegroundColor DarkYellow
            }
        } else {
            Write-Host "    Test-StackHealthy: containers not both Up yet (attempt $attempt)" -ForegroundColor DarkYellow
        }

        if ($attempt -lt 3) { Start-Sleep -Seconds 5 }
    }

    Write-Host "    Test-StackHealthy: policy failed after 3 attempts; real failure" -ForegroundColor Red
    return $false
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
        Write-Host ""
        Write-Host "  GPU toolkit smoke test: if this fails, the toolkit is not"
        Write-Host "  installed in WSL2 and everything downstream will fall back"
        Write-Host "  to CPU. See docs/help/gpu-setup.md."
        Invoke-Logged "GPU toolkit smoke test (nvidia-smi in container)" {
            docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
        }
    } else {
        Write-Step "GPU toolkit smoke test SKIPPED (-SkipGpuCheck)"
    }

    # -------------------------------------------------------------------------
    # Step 2: Git pull (fast-forward only, refuses to merge)
    # -------------------------------------------------------------------------
    if (-not $SkipPull) {
        Invoke-Logged "git fetch origin" { git fetch origin }
        Invoke-Logged "git checkout $Branch" { git checkout $Branch }
        Invoke-Logged "git pull --ff-only origin $Branch" { git pull --ff-only origin $Branch }
        # git log is purely informational; tolerate failure so we never halt
        # a successful rebuild over a missing commit formatter or similar.
        Invoke-Logged "HEAD after pull" { git log -1 --oneline } -AllowNonZero
    } else {
        Write-Step "git pull SKIPPED (-SkipPull)"
    }

    # -------------------------------------------------------------------------
    # Step 3: Rebuild base image (the slow step)
    # -------------------------------------------------------------------------
    if (-not $SkipBase) {
        Write-Host ""
        Write-Host "  Base image rebuild: the CUDA 12.1 torch wheel is ~2.5 GB;"
        Write-Host "  first build will download it. Cached after that."
        Invoke-Logged "Rebuild base image markflow-base:latest (5 to 25 min)" {
            docker build -f Dockerfile.base -t markflow-base:latest .
        }
    } else {
        Write-Step "Base image rebuild SKIPPED (-SkipBase)"
    }

    # -------------------------------------------------------------------------
    # Step 4: Rebuild app image on top of base
    # -------------------------------------------------------------------------
    Invoke-Logged "Rebuild app image (docker-compose build)" { docker-compose build }

    # -------------------------------------------------------------------------
    # Step 5: Start the stack detached
    # -------------------------------------------------------------------------
    Invoke-Logged "Start stack detached (docker-compose up -d)" {
        docker-compose up -d
    } -AllowNonZero
    $composeUpExit = $LASTEXITCODE
    if ($composeUpExit -ne 0) {
        Write-Host ""
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] docker-compose up -d exited $composeUpExit" -ForegroundColor DarkYellow
        Write-Host "  Checking whether the stack came up anyway (post-start race override)..." -ForegroundColor DarkYellow
        if (Test-StackHealthy) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Stack is healthy; overriding exit $composeUpExit as success." -ForegroundColor Green
        } else {
            throw "docker-compose up -d failed with exit code $composeUpExit (and health verification did not pass)"
        }
    }

    # -------------------------------------------------------------------------
    # Step 6: Wait for lifespan + verify health
    # -------------------------------------------------------------------------
    Write-Step "Waiting 20 seconds for FastAPI lifespan startup"
    Start-Sleep -Seconds 20

    Invoke-Logged "Container status" { docker-compose ps } -AllowNonZero

    Write-Host ""
    Write-Host "  Health check: look for whisper.cuda = true,"
    Write-Host "  gpu.execution_path = 'container', and gpu.effective_gpu"
    Write-Host "  naming your NVIDIA card (v0.22.16+)."
    Invoke-Logged "Health check (curl /api/health)" {
        curl.exe -s http://localhost:8000/api/health
    } -AllowNonZero
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
