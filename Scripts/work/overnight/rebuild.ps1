<#
.SYNOPSIS
    Overnight unattended rebuild of MarkFlow with CUDA Whisper (v0.22.17+).

.DESCRIPTION
    Self-healing phased rebuild pipeline. Pulls the latest vector branch,
    rebuilds the Docker base image, rebuilds the app image, starts the
    stack detached, and runs extended smoke tests. On verification
    failure after the up -d commit point, attempts a blue/green rollback
    to the last-known-good image pair.

    Design spec:
      docs/superpowers/specs/2026-04-08-overnight-rebuild-self-healing-design.md

    Phased pipeline:
      Phase 0    Preflight       - prerequisites, record HEAD commit,
                                   auto-detect expected GPU state
      Phase 1    Source sync     - git fetch/checkout/pull         [retry 3x]
      Phase 1.5  Anchor last-good - capture current :latest image IDs,
                                    tag as :last-good, write sidecar
                                    (runs BEFORE build - see spec §11)
      Phase 2    Image build     - docker build base + app         [retry 2x]
      Phase 3    Start           - docker-compose up -d             [race override]
      Phase 4    Verify          - containers + health + GPU + MCP  [3x x 5s]
      Phase 5    Success         - compact final-state block

    Exit codes:
      0  Clean success, new build verified
      1  Pre-commit failure (phases 0-2); old build still running, untouched
      2  Rollback succeeded; old build running; new build needs investigation
      3  Rollback attempted but rolled-back stack also broken; stack DOWN
      4  Rollback refused because compose/Dockerfile diverged since last-good
         commit; new build stopped, stack DOWN

    Safe to leave running overnight: every failure path runs
    Write-Diagnostics (docker-compose ps + logs + /api/health + GPU state
    + disk + git state + app log) so the morning review does not require
    running a single follow-up command.

.PARAMETER SkipGpuCheck
    Skip the NVIDIA Container Toolkit smoke test. Use only if GPU
    passthrough was verified earlier today.

.PARAMETER SkipPull
    Skip git fetch/checkout/pull. Use when the desired commit is already
    checked out.

.PARAMETER SkipBase
    Skip the base image rebuild. Use when only Python code changed and
    Dockerfile.base is unchanged.

.PARAMETER Branch
    Git branch to pull. Defaults to 'vector'.

.PARAMETER RepoDir
    Override the repo root. By default resolves via script location.

.PARAMETER DryRun
    Run preflight and GPU detection for real, but log-and-skip every
    git/docker command. Used to validate phase transitions and control
    flow without side effects. Always exits 0.

.EXAMPLE
    .\rebuild.ps1
    Full overnight rebuild with rollback safety net.

.EXAMPLE
    .\rebuild.ps1 -DryRun
    Validate phase structure without touching git or docker.

.EXAMPLE
    .\rebuild.ps1 -SkipPull -SkipBase
    Fast iteration: only rebuild app layer on top of existing base.

.NOTES
    ASCII only. PowerShell 5.1 reads BOM-less UTF-8 as Windows-1252 and
    corrupts non-ASCII characters (em dashes, box-drawing, etc.).
    See docs/gotchas.md - "Overnight Rebuild & PowerShell Native-Command
    Handling" for the PS 5.1 native-command pitfalls this script works
    around.
#>

[CmdletBinding()]
param(
    [switch]$SkipGpuCheck,
    [switch]$SkipPull,
    [switch]$SkipBase,
    [switch]$DryRun,
    [string]$Branch = "vector",
    [string]$RepoDir = ""
)

$ErrorActionPreference = "Stop"

# -----------------------------------------------------------------------------
# Resolve paths
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
$SidecarFile = Join-Path $ScriptDir "last-good.json"

# Compose project name is the repo directory name; images auto-named as
# <project>-<service>. Both the container names seen by Test-StackHealthy
# and these image names rely on that convention.
$MarkflowImageName = "doc-conversion-2026-markflow"
$McpImageName      = "doc-conversion-2026-markflow-mcp"

# -----------------------------------------------------------------------------
# Phase state (script scope so catch/finally/helpers can see it)
# -----------------------------------------------------------------------------
$script:CurrentPhase      = "pre-start"
$script:PreCommit         = $true      # flips to $false after Phase 3 up -d
$script:RollbackAvailable = $false     # set true by Phase 1.5 on successful retag
$script:PrevHeadCommit    = $null
$script:PrevMarkflowId    = $null
$script:PrevMcpId         = $null
$script:ExpectGpu         = "none"     # "container" | "none"
$script:ExitCode          = 0

# -----------------------------------------------------------------------------
# Display helpers
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

function Write-PhaseHeader {
    param([string]$Number, [string]$Name)
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] === Phase $Number : $Name ===" -ForegroundColor Magenta
    $script:CurrentPhase = "$Number $Name"
}

# -----------------------------------------------------------------------------
# Invoke-Logged
#   Kept verbatim from v0.22.16 follow-up (commit 54d6808). Any edits here
#   risk reintroducing the NativeCommandError decoration regression - leave
#   it alone unless you are absolutely sure.
#
#   Why this exists:
#     PS 5.1 Start-Transcript does NOT capture stdout/stderr from native
#     executables (docker, git, curl, nvidia-smi) because they bypass the
#     PS host and write directly to the console device. Without this
#     helper, transcripts contain section headers with empty bodies.
#
#   Gotcha:
#     With EAP=Continue, PS 5.1 auto-displays native stderr wrapped as
#     NativeCommandError records to the host BEFORE a '2>&1 | ForEach'
#     pipeline can stringify them. SilentlyContinue + variable capture
#     is the only reliable suppression. See docs/gotchas.md "Overnight
#     Rebuild & PowerShell Native-Command Handling".
# -----------------------------------------------------------------------------
function Invoke-Logged {
    param(
        [Parameter(Mandatory)][string]$What,
        [Parameter(Mandatory)][scriptblock]$Command,
        [switch]$AllowNonZero
    )
    if ($script:DryRun) {
        Write-Step "$What  (DRY RUN: skipped)"
        $global:LASTEXITCODE = 0
        return
    }
    Write-Step $What
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $captured = $null
    try {
        $captured = & $Command 2>&1
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    foreach ($item in @($captured)) {
        if ($null -eq $item) { continue }
        if ($item -is [System.Management.Automation.ErrorRecord]) {
            Write-Host $item.Exception.Message
        } else {
            Write-Host ([string]$item)
        }
    }
    if ($LASTEXITCODE -ne 0 -and -not $AllowNonZero) {
        Write-Host ""
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] FAILED: $What (exit $LASTEXITCODE)" -ForegroundColor Red
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

# -----------------------------------------------------------------------------
# Invoke-Retryable
#   Wraps Invoke-Logged with bounded retry + linear backoff, for steps
#   whose failures are typically transient infrastructure flakes (network,
#   docker daemon race, apt/pip mirror hiccup).
#
#   Logs "RETRY-OK: <label> succeeded on attempt N" when the command
#   succeeded only after retrying, so the morning review can grep
#   RETRY-OK to see what flaked overnight. If every attempt fails, the
#   last attempt's exception propagates.
#
#   Applied to (per spec section 4):
#     git fetch origin            3 attempts
#     git pull --ff-only ...      3 attempts
#     docker build base           2 attempts
#     docker-compose build        2 attempts
#
#   NOT applied to:
#     git checkout        (local; no network)
#     docker-compose up -d (already has race override via Test-StackHealthy)
#     GPU toolkit smoke   (missing toolkit is not transient; masking wastes minutes)
#     Phase 4 health check (already has internal 3x5s retry)
# -----------------------------------------------------------------------------
function Invoke-Retryable {
    param(
        [Parameter(Mandatory)][string]$What,
        [Parameter(Mandatory)][scriptblock]$Command,
        [int]$MaxAttempts = 3,
        [int]$BackoffSeconds = 5
    )
    $backoff = $BackoffSeconds
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            if ($attempt -eq 1) {
                Invoke-Logged -What $What -Command $Command
            } else {
                Invoke-Logged -What "$What  (attempt $attempt / $MaxAttempts)" -Command $Command
            }
            if ($attempt -gt 1) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] RETRY-OK: $What succeeded on attempt $attempt" -ForegroundColor Green
            }
            return
        } catch {
            if ($attempt -eq $MaxAttempts) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] RETRY-EXHAUSTED: $What failed on all $MaxAttempts attempts" -ForegroundColor Red
                throw
            }
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] RETRY: $What failed on attempt $attempt; sleeping ${backoff}s before retry" -ForegroundColor DarkYellow
            Start-Sleep -Seconds $backoff
            $backoff = $backoff * 2
        }
    }
}

# -----------------------------------------------------------------------------
# Get-ImageId
#   Returns the sha256 image ID for a tagged image, or $null if the image
#   does not exist. Used by Phase 1.5 Capture. Silent on failure - missing
#   image is a normal case on a fresh install.
# -----------------------------------------------------------------------------
function Get-ImageId {
    param([Parameter(Mandatory)][string]$Tag)
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $id = $null
    try {
        $id = & docker image inspect --format '{{.Id}}' $Tag 2>$null
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace([string]$id)) {
        return $null
    }
    return ([string]$id).Trim()
}

# -----------------------------------------------------------------------------
# Test-StackHealthy
#   Kept verbatim from v0.22.16 follow-up. Container + /api/health probe
#   used by (a) Phase 3 race override after docker-compose up -d non-zero
#   exit, and (b) Phase 4 baseline verification before GPU/MCP checks.
#
#   Keep this CONSERVATIVE. A false positive marks an actually-broken
#   stack as "success" and we find out the hard way.
# -----------------------------------------------------------------------------
function Test-StackHealthy {
    # SilentlyContinue is load-bearing: docker-compose writes a symlink
    # warning to stderr on every invocation, which PS 5.1 wraps as a
    # NativeCommandError ErrorRecord. With EAP=Continue (or Stop via
    # $ErrorActionPreference), PS auto-displays the record to the host
    # with full CategoryInfo / FullyQualifiedErrorId decoration BEFORE
    # the '2>$null' stream redirection can discard it. SilentlyContinue
    # suppresses the auto-display so the redirection actually works.
    # Same root cause and fix as Invoke-Logged; see docs/gotchas.md
    # "Overnight Rebuild & PowerShell Native-Command Handling" and the
    # v0.22.16 follow-up commit 54d6808. Caught on the 2026-04-08
    # 15:15:12 staged live run, which decorated every compose ps call
    # with 8-line error spam in the transcript.
    $ErrorActionPreference = "SilentlyContinue"
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        # docker-compose ps --format json emits NDJSON (one JSON object per
        # line). Parse each line individually with ConvertFrom-Json rather
        # than regex, because the Publishers field contains nested {...}
        # objects that break negated-class regexes. See docs/gotchas.md
        # "Overnight Rebuild" section. docker-compose stderr goes to $null
        # so the symlink warning does not pollute the NDJSON stream.
        $psLines = & docker-compose ps --format json 2>$null
        $markflowUp = $false
        $mcpUp = $false
        foreach ($line in @($psLines)) {
            $lineStr = [string]$line
            if ([string]::IsNullOrWhiteSpace($lineStr)) { continue }
            if ($lineStr -notmatch '^\s*\{') { continue }
            try {
                $obj = $lineStr | ConvertFrom-Json -ErrorAction Stop
            } catch {
                continue
            }
            if ($obj.Name -eq 'doc-conversion-2026-markflow-1'     -and $obj.State -eq 'running') { $markflowUp = $true }
            if ($obj.Name -eq 'doc-conversion-2026-markflow-mcp-1' -and $obj.State -eq 'running') { $mcpUp = $true }
        }

        if ($markflowUp -and $mcpUp) {
            $healthJson = curl.exe -sf --max-time 5 http://localhost:8000/api/health 2>$null
            if ($LASTEXITCODE -eq 0 -and $healthJson) {
                # Scoped regex '[^{}]*' (not '[^}]*') confines each match
                # to the immediate subobject so an inner '{}' cannot
                # swallow the 'ok' flag lookahead.
                $statusOk = $healthJson -match '"status"\s*:\s*"ok"'
                $dbOk     = $healthJson -match '"database"\s*:\s*\{[^{}]*"ok"\s*:\s*true'
                $meiliOk  = $healthJson -match '"meilisearch"\s*:\s*\{[^{}]*"ok"\s*:\s*true'
                if ($statusOk -and $dbOk -and $meiliOk) {
                    Write-Host "    Test-StackHealthy: markflow+mcp Up, status/db/meili all ok (attempt $attempt)" -ForegroundColor Green
                    return $true
                }
                Write-Host "    Test-StackHealthy: health JSON missing required ok flags (attempt $attempt)" -ForegroundColor DarkYellow
            } else {
                Write-Host "    Test-StackHealthy: /api/health unreachable (attempt $attempt)" -ForegroundColor DarkYellow
            }
        } else {
            Write-Host ("    Test-StackHealthy: containers not both running yet " +
                        "(markflow=$markflowUp, mcp=$mcpUp, attempt $attempt)") -ForegroundColor DarkYellow
        }

        if ($attempt -lt 3) { Start-Sleep -Seconds 5 }
    }

    Write-Host "    Test-StackHealthy: policy failed after 3 attempts" -ForegroundColor Red
    return $false
}

# -----------------------------------------------------------------------------
# Test-GpuExpectation
#   Parses /api/health for components.gpu.execution_path and
#   components.whisper.cuda. The actual response structure nests every
#   component under "components": { ... }, and the whisper cuda flag is
#   literally named "cuda" (not "cuda_available") - the CLAUDE.md
#   v0.22.16 note about "cuda_available=true in the logs" refers to
#   structlog events, NOT the health JSON field. Validated against
#   live payload on 2026-04-08.
#
#   $expectGpu == "container":
#     gpu.execution_path must NOT be "container_cpu" or "none"
#     whisper.cuda must be true
#     Catches v0.22.15 (Whisper silently on CPU) and v0.22.16 (GPU
#     detector lying on WSL2) regression classes.
#
#   $expectGpu == "none":
#     Skip. Returns $true. Keeps the script portable to friend-deploys
#     on CPU-only hosts.
#
#   Regex notes:
#     - The '"gpu":' pattern does NOT collide with '"container_gpu":'
#       because the latter has '_gpu"' not '"gpu"'.
#     - The gpu subobject lists 'execution_path' BEFORE any nested
#       subobjects (container_gpu/host_worker), so '[^{}]*?' lazy walk
#       from the opening '{' to 'execution_path' never crosses an
#       inner brace. Validated against the live response shape.
# -----------------------------------------------------------------------------
function Test-GpuExpectation {
    param([Parameter(Mandatory)][string]$Expect)

    if ($Expect -eq "none") {
        Write-Host "    Test-GpuExpectation: expectGpu=none, skipping" -ForegroundColor DarkGray
        return $true
    }

    $ErrorActionPreference = "Continue"
    $healthJson = curl.exe -sf --max-time 5 http://localhost:8000/api/health 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $healthJson) {
        Write-Host "    Test-GpuExpectation: /api/health unreachable" -ForegroundColor Red
        return $false
    }

    $epMatch = [regex]::Match($healthJson, '"gpu"\s*:\s*\{[^{}]*?"execution_path"\s*:\s*"([^"]+)"')
    if (-not $epMatch.Success) {
        Write-Host "    Test-GpuExpectation: gpu.execution_path not found in /api/health response" -ForegroundColor Red
        return $false
    }
    $executionPath = $epMatch.Groups[1].Value

    # whisper.cuda (NOT cuda_available)
    $cudaMatch = [regex]::Match($healthJson, '"whisper"\s*:\s*\{[^{}]*?"cuda"\s*:\s*(true|false)')
    if (-not $cudaMatch.Success) {
        Write-Host "    Test-GpuExpectation: whisper.cuda not found in /api/health response" -ForegroundColor Red
        return $false
    }
    $cudaAvailable = ($cudaMatch.Groups[1].Value -eq "true")

    if ($executionPath -in @("container_cpu", "none")) {
        Write-Host "    Test-GpuExpectation: execution_path='$executionPath' on a GPU-expected host (v0.22.16 regression class)" -ForegroundColor Red
        return $false
    }
    if (-not $cudaAvailable) {
        Write-Host "    Test-GpuExpectation: whisper.cuda=false on a GPU-expected host (v0.22.15 regression class)" -ForegroundColor Red
        return $false
    }

    Write-Host "    Test-GpuExpectation: execution_path='$executionPath', whisper.cuda=true" -ForegroundColor Green
    return $true
}

# -----------------------------------------------------------------------------
# Test-McpHealth
#   Hits the MCP server's /health endpoint on port 8001. Catches the case
#   where docker-compose ps reports markflow-mcp as running but the MCP
#   server process inside has crashed or failed to bind. The port 8001
#   /health endpoint is a Starlette route manually registered in the MCP
#   server (FastMCP.run does not accept host/port - see CLAUDE.md MCP
#   gotcha).
# -----------------------------------------------------------------------------
function Test-McpHealth {
    $ErrorActionPreference = "Continue"
    $body = curl.exe -sf --max-time 5 http://localhost:8001/health 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace([string]$body)) {
        Write-Host "    Test-McpHealth: MCP /health on port 8001 unreachable or empty body" -ForegroundColor Red
        return $false
    }
    Write-Host "    Test-McpHealth: MCP /health responded (body length $($body.Length))" -ForegroundColor Green
    return $true
}

# -----------------------------------------------------------------------------
# Write-Diagnostics
#   13-item diagnostic dump, emitted to the transcript on any non-success
#   exit. Budget ~20s total. Every command wrapped in Invoke-Logged
#   -AllowNonZero so a failing diagnostic command does not abort the
#   capture.
# -----------------------------------------------------------------------------
function Write-Diagnostics {
    param([Parameter(Mandatory)][string]$Reason)
    if ($script:DryRun) {
        Write-Host ""
        Write-Host "======= DIAGNOSTICS (DRY RUN: would capture, reason: $Reason) =======" -ForegroundColor DarkGray
        return
    }
    Write-Host ""
    Write-Host "======= DIAGNOSTICS (reason: $Reason) =======" -ForegroundColor Red
    Invoke-Logged "diag 1/13: docker-compose ps"                      { docker-compose ps } -AllowNonZero
    Invoke-Logged "diag 2/13: docker-compose logs markflow (tail 100)" { docker-compose logs --tail=100 --timestamps markflow } -AllowNonZero
    Invoke-Logged "diag 3/13: docker-compose logs markflow-mcp (tail 100)" { docker-compose logs --tail=100 --timestamps markflow-mcp } -AllowNonZero
    Invoke-Logged "diag 4/13: docker-compose logs meilisearch (tail 20)" { docker-compose logs --tail=20 meilisearch } -AllowNonZero
    Invoke-Logged "diag 5/13: docker-compose logs qdrant (tail 20)"     { docker-compose logs --tail=20 qdrant } -AllowNonZero
    Invoke-Logged "diag 6/13: curl /api/health (verbose)"               { curl.exe -sv --max-time 5 http://localhost:8000/api/health } -AllowNonZero
    Invoke-Logged "diag 7/13: curl MCP /health (verbose)"               { curl.exe -sv --max-time 5 http://localhost:8001/health } -AllowNonZero
    Invoke-Logged "diag 8/13: host GPU state (nvidia-smi.exe)"          { nvidia-smi.exe } -AllowNonZero
    Invoke-Logged "diag 9/13: host disk free (wsl df -h /)"             { wsl.exe -e df -h / } -AllowNonZero
    Invoke-Logged "diag 10/13: git log -5 --oneline"                    { git log -5 --oneline } -AllowNonZero
    Invoke-Logged "diag 11/13: git status --short"                      { git status --short } -AllowNonZero
    Invoke-Logged "diag 12/13: last-good.json sidecar"                  {
        if (Test-Path $SidecarFile) { Get-Content $SidecarFile -Raw } else { Write-Output "(no last-good.json; no rollback target)" }
    } -AllowNonZero
    $appLog = Join-Path $RepoDir "logs\app.log"
    Invoke-Logged "diag 13/13: logs/app.log (tail 100)" {
        if (Test-Path $appLog) { Get-Content $appLog -Tail 100 } else { Write-Output "(no logs/app.log found at $appLog)" }
    } -AllowNonZero
    Write-Host "======= END DIAGNOSTICS =======" -ForegroundColor Red
}

# -----------------------------------------------------------------------------
# Write-FinalState
#   Compact success block. Only docker-compose ps + /api/health body.
#   Emitted on exit 0 so every morning's transcript has the baseline
#   "what does the stack look like now" without follow-up commands.
# -----------------------------------------------------------------------------
function Write-FinalState {
    if ($script:DryRun) {
        Write-Host ""
        Write-Host "======= FINAL STATE (DRY RUN: would emit) =======" -ForegroundColor DarkGray
        return
    }
    Write-Host ""
    Write-Host "======= FINAL STATE =======" -ForegroundColor Green
    Invoke-Logged "final 1/2: docker-compose ps"        { docker-compose ps } -AllowNonZero
    Invoke-Logged "final 2/2: curl /api/health (pretty)" { curl.exe -s http://localhost:8000/api/health } -AllowNonZero
    Write-Host "======= END =======" -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Invoke-RetagImage
#   Helper for Phase 1.5. Tags $PrevId as $TargetTag. Retries once on
#   failure. Returns $true on success, $false after both attempts fail.
#
#   Important: this MUST run BEFORE Phase 2's build, because
#   docker-compose build garbage-collects the previous :latest image
#   the moment the new build tags :latest. Without a :last-good tag
#   holding a reference, the old image's sha becomes immediately
#   unreachable and rollback becomes impossible. This is a spec §11
#   deviation from the original draft, which assumed "build N is
#   still resident on the host but reachable only by sha ID" - that
#   assumption was wrong on modern BuildKit and broke the first live
#   staged run (2026-04-08 15:03:46 rebuild log).
#
#   Stderr is captured and Write-Host'd on failure so the morning
#   log shows the actual docker error (previously was Out-Null'd).
# -----------------------------------------------------------------------------
function Invoke-RetagImage {
    param(
        [Parameter(Mandatory)][string]$PrevId,
        [Parameter(Mandatory)][string]$TargetTag
    )
    for ($i = 1; $i -le 2; $i++) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $tagOutput = & docker tag $PrevId $TargetTag 2>&1
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($code -eq 0) { return $true }
        Write-Host "    Retag $TargetTag attempt $i failed (exit $code)" -ForegroundColor DarkYellow
        foreach ($line in @($tagOutput)) {
            if ($null -eq $line) { continue }
            if ($line -is [System.Management.Automation.ErrorRecord]) {
                Write-Host "      $($line.Exception.Message)" -ForegroundColor DarkYellow
            } else {
                Write-Host "      $([string]$line)" -ForegroundColor DarkYellow
            }
        }
        if ($i -lt 2) {
            Write-Host "    Retrying in 2s" -ForegroundColor DarkYellow
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

# -----------------------------------------------------------------------------
# Invoke-Rollback
#   Blue/green rollback. Called when Phase 3 (after race override also
#   fails) or Phase 4 verification fails. Returns an exit code:
#
#     2  Rollback succeeded; rolled-back stack is healthy
#     3  Rollback attempted but image/tag/recreate/verify failed
#     4  Rollback refused because compose/Dockerfile diverged
#
#   Steps per spec section 5.4:
#     1. Compose/Dockerfile divergence check
#     2. Sidecar validation (both image IDs still exist)
#     3. Retag :last-good -> :latest (markflow + mcp)
#     4. docker-compose up -d --force-recreate markflow markflow-mcp
#     5. Re-verify: Test-StackHealthy + Test-GpuExpectation + Test-McpHealth
# -----------------------------------------------------------------------------
function Invoke-Rollback {
    Write-Header "ROLLBACK INITIATED"
    if (-not $script:RollbackAvailable) {
        Write-Host "  Rollback UNAVAILABLE - no last-good target captured this cycle." -ForegroundColor Red
        return 3
    }
    if (-not (Test-Path $SidecarFile)) {
        Write-Host "  Rollback UNAVAILABLE - last-good.json sidecar missing at $SidecarFile" -ForegroundColor Red
        return 3
    }

    $sidecar = $null
    try {
        $sidecar = Get-Content $SidecarFile -Raw | ConvertFrom-Json
    } catch {
        Write-Host "  Rollback UNAVAILABLE - last-good.json is corrupt: $($_.Exception.Message)" -ForegroundColor Red
        return 3
    }

    Write-Host "  Sidecar: commit=$($sidecar.commit) tagged_at=$($sidecar.tagged_at)"
    Write-Host "           markflow_image_id=$($sidecar.markflow_image_id)"
    Write-Host "           mcp_image_id=$($sidecar.mcp_image_id)"

    # Step 1: compose/Dockerfile divergence
    Write-Step "Rollback step 1: compose/Dockerfile divergence check"
    $diffOutput = $null
    try {
        $diffOutput = & git diff --name-only "$($sidecar.commit)" HEAD -- docker-compose.yml Dockerfile Dockerfile.base 2>&1
    } catch {
        Write-Host "  git diff failed: $($_.Exception.Message)" -ForegroundColor Red
        return 3
    }
    $changed = @($diffOutput | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) -and ([string]$_) -notmatch '^\s*fatal:' })
    if ($changed.Count -gt 0) {
        Write-Host "  ROLLBACK REFUSED: compose/Dockerfile changed since last-good commit $($sidecar.commit):" -ForegroundColor Red
        foreach ($f in $changed) { Write-Host "    $f" -ForegroundColor Red }
        Write-Host "  A compose-old-image mismatch could silently half-work. Investigate manually." -ForegroundColor Red
        return 4
    }
    Write-Host "    Divergence check: clean" -ForegroundColor Green

    # Step 2: sidecar validation - both image IDs still exist
    Write-Step "Rollback step 2: verify last-good image IDs still exist"
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $markflowPresent = $null
    $mcpPresent = $null
    try {
        $markflowPresent = & docker image inspect --format '{{.Id}}' $sidecar.markflow_image_id 2>$null
        $markflowExit = $LASTEXITCODE
        $mcpPresent = & docker image inspect --format '{{.Id}}' $sidecar.mcp_image_id 2>$null
        $mcpExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($markflowExit -ne 0 -or [string]::IsNullOrWhiteSpace([string]$markflowPresent)) {
        Write-Host "  Rollback FAILED: markflow last-good image $($sidecar.markflow_image_id) no longer exists (image prune?)" -ForegroundColor Red
        return 3
    }
    if ($mcpExit -ne 0 -or [string]::IsNullOrWhiteSpace([string]$mcpPresent)) {
        Write-Host "  Rollback FAILED: markflow-mcp last-good image $($sidecar.mcp_image_id) no longer exists (image prune?)" -ForegroundColor Red
        return 3
    }
    Write-Host "    Both last-good image IDs present" -ForegroundColor Green

    # Step 3: retag :last-good -> :latest
    try {
        Invoke-Logged "Rollback step 3a: docker tag ${MarkflowImageName}:last-good ${MarkflowImageName}:latest" {
            docker tag "${MarkflowImageName}:last-good" "${MarkflowImageName}:latest"
        }
        Invoke-Logged "Rollback step 3b: docker tag ${McpImageName}:last-good ${McpImageName}:latest" {
            docker tag "${McpImageName}:last-good" "${McpImageName}:latest"
        }
    } catch {
        Write-Host "  Rollback FAILED: retag step: $($_.Exception.Message)" -ForegroundColor Red
        return 3
    }

    # Step 4: recreate
    try {
        Invoke-Logged "Rollback step 4: docker-compose up -d --force-recreate markflow markflow-mcp" {
            docker-compose up -d --force-recreate markflow markflow-mcp
        } -AllowNonZero
    } catch {
        Write-Host "  Rollback FAILED: recreate step: $($_.Exception.Message)" -ForegroundColor Red
        return 3
    }
    # Lifespan pause before ANY health probes on the rolled-back stack,
    # including the race-override check. The non-zero-exit race-override
    # and the strict re-verification both assume lifespan has completed;
    # wait once, then run both. Without this, a compose non-zero exit
    # on --force-recreate races the /api/health probe and triggers a
    # false rollback-failed (exit 3) on a healthy rolled-back stack.
    Write-Step "Rollback step 4.5: waiting 20s for rolled-back lifespan startup"
    Start-Sleep -Seconds 20

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  docker-compose up -d --force-recreate exited $LASTEXITCODE; probing stack anyway..." -ForegroundColor DarkYellow
        if (-not (Test-StackHealthy)) {
            Write-Host "  Rollback FAILED: recreate non-zero and post-recreate stack unhealthy" -ForegroundColor Red
            return 3
        }
    }

    # Step 5: re-verify (same as Phase 4)
    Write-Step "Rollback step 5: re-verifying rolled-back stack"
    $healthy = Test-StackHealthy
    if (-not $healthy) {
        Write-Host "  Rollback FAILED: rolled-back stack unhealthy on baseline check" -ForegroundColor Red
        return 3
    }
    $gpuOk = Test-GpuExpectation -Expect $script:ExpectGpu
    if (-not $gpuOk) {
        Write-Host "  Rollback FAILED: rolled-back stack failed GPU expectation ($($script:ExpectGpu))" -ForegroundColor Red
        return 3
    }
    $mcpOk = Test-McpHealth
    if (-not $mcpOk) {
        Write-Host "  Rollback FAILED: rolled-back stack failed MCP /health" -ForegroundColor Red
        return 3
    }

    Write-Host ""
    Write-Host "  ROLLBACK SUCCEEDED - old build is running healthy." -ForegroundColor Green
    Write-Host "  The new build needs human investigation. See diagnostics below." -ForegroundColor Yellow
    return 2
}

# =============================================================================
# Main
# =============================================================================
$script:DryRun = $DryRun.IsPresent
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$transcriptActive = $false

try {
    Start-Transcript -Path $LogFile | Out-Null
    $transcriptActive = $true
} catch {
    Write-Host "Warning: could not start transcript ($($_.Exception.Message)). Continuing without a log file." -ForegroundColor DarkYellow
}

try {
    Write-Header "MarkFlow Overnight Rebuild (self-healing)"
    Write-Host "  Started:      $(Get-Date)"
    Write-Host "  Repo:         $RepoDir"
    Write-Host "  Branch:       $Branch"
    Write-Host "  Log file:     $LogFile"
    Write-Host "  Sidecar:      $SidecarFile"
    Write-Host "  SkipGpuCheck: $SkipGpuCheck"
    Write-Host "  SkipPull:     $SkipPull"
    Write-Host "  SkipBase:     $SkipBase"
    Write-Host "  DryRun:       $($script:DryRun)"

    if (-not (Test-Path $RepoDir)) {
        throw "Repo directory does not exist: $RepoDir"
    }
    Push-Location $RepoDir

    # -------------------------------------------------------------------------
    # Phase 0: Preflight
    # -------------------------------------------------------------------------
    Write-PhaseHeader "0" "Preflight"

    # GPU toolkit smoke (retained from pre-self-healing; not retried - a
    # missing toolkit is not a transient failure)
    if (-not $SkipGpuCheck) {
        Write-Host "  GPU toolkit smoke test: if this fails, the NVIDIA Container"
        Write-Host "  Toolkit is not installed/exposed in WSL2 and Whisper will"
        Write-Host "  fall back to CPU. See docs/help/gpu-setup.md."
        Invoke-Logged "GPU toolkit smoke test (nvidia-smi in container)" {
            docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
        }
    } else {
        Write-Step "GPU toolkit smoke test SKIPPED (-SkipGpuCheck)"
    }

    # Record HEAD commit BEFORE Phase 1's pull. This is the commit that
    # produced the current :latest image, which Phase 2.5 will tag as
    # :last-good. Used later by the compose-divergence check.
    $prevEAP2 = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $headRaw = $null
    if (-not $script:DryRun) {
        $headRaw = & git rev-parse HEAD 2>$null
    }
    $ErrorActionPreference = $prevEAP2
    if (-not $script:DryRun -and $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$headRaw)) {
        $script:PrevHeadCommit = ([string]$headRaw).Trim()
        Write-Host "    prevHeadCommit (commit of current :latest): $($script:PrevHeadCommit)"
    } else {
        $script:PrevHeadCommit = $null
        Write-Host "    prevHeadCommit: unavailable" -ForegroundColor DarkYellow
    }

    # Auto-detect expected GPU state via Windows-native nvidia-smi.exe.
    # Determines whether Phase 4's Test-GpuExpectation asserts or skips.
    # Keeps the script portable to friend-deploys on CPU-only hosts.
    #
    # Probe choice: the Windows NVIDIA driver installs nvidia-smi.exe at
    # C:\Windows\System32\nvidia-smi.exe, which is the authoritative
    # "does this host have an NVIDIA GPU" check. The design spec
    # originally called for 'wsl.exe -e nvidia-smi' but that's wrong on
    # this configuration: the default WSL2 distro does not have
    # nvidia-smi installed (Docker Desktop's GPU passthrough uses a
    # separate path via the NVIDIA Container Toolkit), so the WSL probe
    # returns a WSL-level exec error on an otherwise GPU-capable host.
    # Dry run still probes - cheap, no side effects.
    $prevEAP3 = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $gpuProbe = & nvidia-smi.exe 2>$null
    $gpuProbeExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP3
    if ($gpuProbeExit -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$gpuProbe)) {
        $script:ExpectGpu = "container"
        Write-Host "    Host GPU detected via nvidia-smi.exe -> expectGpu=container" -ForegroundColor Green
    } else {
        $script:ExpectGpu = "none"
        Write-Host "    No host GPU via nvidia-smi.exe -> expectGpu=none (portable mode)" -ForegroundColor DarkGray
    }

    # -------------------------------------------------------------------------
    # Phase 1: Source sync (retryable)
    # -------------------------------------------------------------------------
    Write-PhaseHeader "1" "Source sync"
    if (-not $SkipPull) {
        Invoke-Retryable "git fetch origin"                { git fetch origin } -MaxAttempts 3
        # git checkout is local; not retried.
        Invoke-Logged    "git checkout $Branch"            { git checkout $Branch }
        Invoke-Retryable "git pull --ff-only origin $Branch" { git pull --ff-only origin $Branch } -MaxAttempts 3
        Invoke-Logged    "HEAD after pull"                 { git log -1 --oneline } -AllowNonZero
    } else {
        Write-Step "git pull SKIPPED (-SkipPull)"
    }

    # -------------------------------------------------------------------------
    # Phase 1.5: Anchor last-good (tag current :latest BEFORE the build)
    #
    # Why this runs BEFORE Phase 2 (spec §11 deviation from the draft):
    # modern BuildKit garbage-collects the previous :latest image the moment
    # docker-compose build tags :latest with the new build. If we try to
    # retag the old sha AFTER the build (as the draft spec assumed), the
    # image is already gone. Tagging it as :last-good BEFORE the build
    # gives the image store a second reference, keeping it resident.
    #
    # The sidecar is also written here so tag and sidecar are atomic:
    # if either side of the pair can't be retagged, we throw before any
    # build happens and the old build keeps serving (exit 1, pre-commit).
    # -------------------------------------------------------------------------
    Write-PhaseHeader "1.5" "Anchor last-good (pre-build retag + sidecar)"
    if ($script:DryRun) {
        Write-Host "    DRY RUN: would capture IDs, retag as :last-good, write sidecar"
    } else {
        $script:PrevMarkflowId = Get-ImageId -Tag "${MarkflowImageName}:latest"
        $script:PrevMcpId      = Get-ImageId -Tag "${McpImageName}:latest"
        if ($null -eq $script:PrevMarkflowId -or $null -eq $script:PrevMcpId) {
            Write-Host "    No previous :latest image(s) found - fresh install or first run." -ForegroundColor DarkYellow
            Write-Host "      markflow: $(if ($script:PrevMarkflowId) { $script:PrevMarkflowId } else { '(missing)' })"
            Write-Host "      mcp:      $(if ($script:PrevMcpId) { $script:PrevMcpId } else { '(missing)' })"
            Write-Host "    Rollback will be UNAVAILABLE for this cycle. Next cycle will capture this build." -ForegroundColor DarkYellow
            $script:RollbackAvailable = $false
        } else {
            Write-Host "    Captured markflow: $($script:PrevMarkflowId)"
            Write-Host "    Captured mcp:      $($script:PrevMcpId)"

            $markflowTagged = Invoke-RetagImage -PrevId $script:PrevMarkflowId -TargetTag "${MarkflowImageName}:last-good"
            if (-not $markflowTagged) {
                throw "Phase 1.5: failed to retag markflow :last-good after retry. Aborting before Phase 2 build (no safety net = no risky action)."
            }
            $mcpTagged = Invoke-RetagImage -PrevId $script:PrevMcpId -TargetTag "${McpImageName}:last-good"
            if (-not $mcpTagged) {
                # Atomicity: markflow tag succeeded but mcp failed. Abort as
                # exit 1 rather than proceed - image pair would be out of sync.
                throw "Phase 1.5: failed to retag markflow-mcp :last-good after retry (markflow retag already succeeded but pair out of sync). Aborting."
            }
            Write-Host "    Both images retagged as :last-good" -ForegroundColor Green

            # Write sidecar
            $sidecarObj = [ordered]@{
                commit             = $script:PrevHeadCommit
                tagged_at          = (Get-Date).ToString("o")
                markflow_image_id  = $script:PrevMarkflowId
                mcp_image_id       = $script:PrevMcpId
                host_expects_gpu   = ($script:ExpectGpu -eq "container")
            }
            try {
                $sidecarObj | ConvertTo-Json -Depth 4 | Out-File -FilePath $SidecarFile -Encoding ASCII -Force
                Write-Host "    Wrote sidecar: $SidecarFile" -ForegroundColor Green
            } catch {
                throw "Phase 1.5: failed to write sidecar $SidecarFile : $($_.Exception.Message)"
            }
            $script:RollbackAvailable = $true
        }
    }

    # -------------------------------------------------------------------------
    # Phase 2: Image build (retryable)
    # -------------------------------------------------------------------------
    Write-PhaseHeader "2" "Image build"
    if (-not $SkipBase) {
        Write-Host "  Base image rebuild: CUDA 12.1 torch wheel is ~2.5 GB."
        Write-Host "  First build downloads it; cached after that."
        Invoke-Retryable "Rebuild base image markflow-base:latest (5 to 25 min)" {
            docker build -f Dockerfile.base -t markflow-base:latest .
        } -MaxAttempts 2 -BackoffSeconds 10
    } else {
        Write-Step "Base image rebuild SKIPPED (-SkipBase)"
    }
    Invoke-Retryable "Rebuild app image (docker-compose build)" {
        docker-compose build
    } -MaxAttempts 2 -BackoffSeconds 10

    # -------------------------------------------------------------------------
    # Phase 3: Start (commit point - after this the old stack is gone)
    # -------------------------------------------------------------------------
    Write-PhaseHeader "3" "Start"
    $script:PreCommit = $false  # from here on, a failure may need rollback
    Invoke-Logged "Start stack detached (docker-compose up -d)" {
        docker-compose up -d
    } -AllowNonZero
    $composeUpExit = $LASTEXITCODE

    # Lifespan pause applies to BOTH the clean-exit and race-override
    # branches. Test-StackHealthy's 3x5s=15s retry budget is not enough
    # for a cold container start, which typically takes ~20s for
    # FastAPI lifespan startup. Without this pause the race-override
    # path reports /api/health unreachable on a perfectly fine new
    # build and triggers a rollback unnecessarily - caught on the
    # 2026-04-08 15:15:12 staged live run, which rolled back a
    # functionally-identical build just because the health probe hit
    # the container before it finished booting.
    Write-Step "Waiting 20 seconds for FastAPI lifespan startup"
    if (-not $script:DryRun) { Start-Sleep -Seconds 20 }

    if ($composeUpExit -ne 0) {
        Write-Host ""
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] docker-compose up -d exited $composeUpExit" -ForegroundColor DarkYellow
        Write-Host "  Checking whether the stack came up anyway (post-start race override)..." -ForegroundColor DarkYellow
        if ($script:DryRun -or (Test-StackHealthy)) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Stack is healthy; overriding exit $composeUpExit as success." -ForegroundColor Green
        } else {
            throw "PHASE3_FAIL: docker-compose up -d failed with exit code $composeUpExit and health verification did not pass"
        }
    }

    # -------------------------------------------------------------------------
    # Phase 4: Verify (containers + health + GPU + MCP)
    # -------------------------------------------------------------------------
    Write-PhaseHeader "4" "Verify"
    # No additional lifespan wait - Phase 3 already waited 20s after up -d.

    Invoke-Logged "Container status" { docker-compose ps } -AllowNonZero

    if (-not $script:DryRun) {
        $baselineOk = Test-StackHealthy
        if (-not $baselineOk) {
            throw "PHASE4_FAIL: Test-StackHealthy (containers + /api/health + db + meili)"
        }
        $gpuOk = Test-GpuExpectation -Expect $script:ExpectGpu
        if (-not $gpuOk) {
            throw "PHASE4_FAIL: Test-GpuExpectation (expectGpu=$($script:ExpectGpu))"
        }
        $mcpOk = Test-McpHealth
        if (-not $mcpOk) {
            throw "PHASE4_FAIL: Test-McpHealth (MCP /health on port 8001)"
        }
        Write-Host ""
        Write-Host "  Phase 4 verification: ALL CHECKS PASSED" -ForegroundColor Green
    } else {
        Write-Host "    DRY RUN: would run Test-StackHealthy + Test-GpuExpectation + Test-McpHealth"
    }

    # -------------------------------------------------------------------------
    # Phase 5: Success
    # -------------------------------------------------------------------------
    Write-PhaseHeader "5" "Success"
    Write-FinalState

    $stopwatch.Stop()
    $elapsed = $stopwatch.Elapsed.ToString("hh\:mm\:ss")
    Write-Header "REBUILD COMPLETED ($elapsed)"
    Write-Host "  Finished: $(Get-Date)" -ForegroundColor Green
    Write-Host "  Log:      $LogFile" -ForegroundColor Green
    Write-Host ""
    if ($script:DryRun) {
        Write-Host "  DRY RUN complete - no side effects." -ForegroundColor DarkGray
    } else {
        Write-Host "  Morning checklist:"
        Write-Host "    1. grep RETRY-OK in the log to see what flaked overnight."
        Write-Host "    2. Confirm execution_path='container' and whisper.cuda=true in the FINAL STATE block."
        Write-Host "    3. To tail live logs: docker-compose logs -f markflow"
    }
    Write-Host ""
    $script:ExitCode = 0
    exit 0

} catch {
    $stopwatch.Stop()
    $elapsed = $stopwatch.Elapsed.ToString("hh\:mm\:ss")
    $errMsg = $_.Exception.Message

    Write-Header "REBUILD FAILED ($elapsed)"
    Write-Host "  Phase:    $($script:CurrentPhase)" -ForegroundColor Red
    Write-Host "  Error:    $errMsg" -ForegroundColor Red
    Write-Host "  Failed:   $(Get-Date)" -ForegroundColor Red
    Write-Host "  Log:      $LogFile" -ForegroundColor Red

    if ($script:PreCommit) {
        # Phases 0-2.5: the running stack was never touched. No rollback
        # possible or needed; exit 1 and the old build continues to serve.
        Write-Host ""
        Write-Host "  Pre-commit failure - old build is still running (untouched)." -ForegroundColor DarkYellow
        Write-Diagnostics -Reason "pre-commit failure in phase $($script:CurrentPhase): $errMsg"
        $script:ExitCode = 1
    } else {
        # Phases 3-4: new stack is (or should be) running. Attempt rollback.
        Write-Host ""
        Write-Host "  Post-commit failure - attempting rollback to last-good build." -ForegroundColor DarkYellow
        $rollbackExit = 3
        try {
            $rollbackExit = Invoke-Rollback
        } catch {
            Write-Host "  Rollback helper threw unexpectedly: $($_.Exception.Message)" -ForegroundColor Red
            $rollbackExit = 3
        }
        $reason = switch ($rollbackExit) {
            2 { "rollback succeeded ($errMsg); new build needs investigation" }
            3 { "rollback failed ($errMsg)" }
            4 { "rollback refused - compose/Dockerfile divergence ($errMsg)" }
            default { "unknown rollback outcome $rollbackExit ($errMsg)" }
        }
        Write-Diagnostics -Reason $reason
        $script:ExitCode = $rollbackExit
    }

    Write-Host ""
    Write-Host "  Exit code: $($script:ExitCode)" -ForegroundColor Red
    Write-Host "    0  clean success"
    Write-Host "    1  pre-commit failure - phases 0-2 (old build still running)"
    Write-Host "    2  rollback succeeded (old build running, new build needs investigation)"
    Write-Host "    3  rollback attempted but failed (stack DOWN)"
    Write-Host "    4  rollback refused (compose/Dockerfile divergence; stack DOWN)"
    Write-Host ""
    exit $script:ExitCode

} finally {
    if ($transcriptActive) {
        try { Stop-Transcript | Out-Null } catch {}
    }
    try { Pop-Location } catch {}
}
