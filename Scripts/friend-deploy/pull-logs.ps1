<#
.SYNOPSIS
    MarkFlow Log Extractor (Windows)
    Pulls log files from Docker containers and runs initial triage.

.EXAMPLE
    .\pull-logs.ps1                              # defaults
    .\pull-logs.ps1 -Tail 5000                   # more docker log lines
    .\pull-logs.ps1 -OutputDir C:\my-logs         # custom output location
    .\pull-logs.ps1 -Analyze                      # extended analysis
    .\pull-logs.ps1 -SkipArchive                  # skip archived logs
    .\pull-logs.ps1 -DebugOnly                    # only pull debug log
#>

param(
    [int]$Tail = 2000,
    [string]$OutputDir,
    [string]$RepoDir,
    [switch]$SkipArchive,
    [switch]$DebugOnly,
    [switch]$Analyze
)

$ErrorActionPreference = "Stop"

# ==============================================================
#  Locate repo
# ==============================================================
if (-not $RepoDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
    $candidate = (Resolve-Path (Join-Path $scriptDir "..\..") -ErrorAction SilentlyContinue).Path
    if ($candidate -and (Test-Path (Join-Path $candidate "docker-compose.yml"))) {
        $RepoDir = $candidate
    }
    elseif (Test-Path ".\docker-compose.yml") {
        $RepoDir = (Get-Location).Path
    }
    else {
        Write-Host "  [ERROR] Cannot find docker-compose.yml." -ForegroundColor Red
        Write-Host "  Run from the repo directory or pass -RepoDir"
        exit 1
    }
}

# -- Timestamp and output dir --
$timestamp = Get-Date -Format "yyyy-MM-dd-HHmm"
if (-not $OutputDir) {
    $OutputDir = Join-Path (Get-Location).Path "markflow-logs-$timestamp"
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

# -- Find the container --
Push-Location $RepoDir

$allContainers = docker compose ps --format '{{.Name}}' 2>$null
$Container = $allContainers | Where-Object { $_ -match 'markflow-1$|markflow$' -and $_ -notmatch 'mcp' } | Select-Object -First 1

if (-not $Container) {
    Write-Host "" 
    Write-Host "  [ERROR] MarkFlow container not found. Is it running?" -ForegroundColor Red
    Write-Host "  Check with: docker compose ps"
    Write-Host ""
    Write-Host "  Attempting to capture docker compose logs anyway..." -ForegroundColor Yellow
    docker compose logs --tail $Tail --timestamps 2>&1 | Out-File (Join-Path $OutputDir "docker-stdout.log") -Encoding utf8
    Write-Host "  [OK] docker-stdout.log saved" -ForegroundColor Green
    Write-Host "  Files saved to: $OutputDir"
    Pop-Location
    exit 1
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Log Extraction" -ForegroundColor Cyan
Write-Host "  Container: $Container" -ForegroundColor DarkGray
Write-Host "  Output:    $OutputDir\" -ForegroundColor DarkGray
Write-Host "==========================================" -ForegroundColor Cyan

# ==============================================================
#  1. Copy app logs from container
# ==============================================================
Write-Host ""
Write-Host "[1/4] Copying app logs..." -ForegroundColor Yellow

function Copy-ContainerLog {
    param([string]$SrcPath, [string]$DestName)
    try {
        $check = docker exec $Container test -f $SrcPath 2>$null
        if ($LASTEXITCODE -eq 0) {
            docker cp "${Container}:${SrcPath}" (Join-Path $OutputDir $DestName)
            $size = (Get-Item (Join-Path $OutputDir $DestName)).Length
            $sizeMb = [math]::Round($size / 1MB, 1)
            Write-Host "  [OK] $DestName ($sizeMb MB)" -ForegroundColor Green
        }
        else {
            Write-Host "  [--] $DestName not found (skipped)" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Host "  [--] $DestName not found (skipped)" -ForegroundColor DarkGray
    }
}

if ($DebugOnly) {
    Copy-ContainerLog "/app/logs/markflow-debug.log" "markflow-debug.log"
}
else {
    Copy-ContainerLog "/app/logs/markflow.log" "markflow.log"
    Copy-ContainerLog "/app/logs/markflow-debug.log" "markflow-debug.log"

    # Rotated logs
    for ($i = 1; $i -le 5; $i++) {
        Copy-ContainerLog "/app/logs/markflow.log.$i" "markflow.log.$i"
    }
}

# Archive directory
if (-not $SkipArchive) {
    try {
        $archiveCheck = docker exec $Container test -d "/app/logs/archive" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $archiveFiles = docker exec $Container ls /app/logs/archive/ 2>$null
            if ($archiveFiles) {
                $archiveDir = Join-Path $OutputDir "archive"
                New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
                docker cp "${Container}:/app/logs/archive/." "$archiveDir/"
                $archiveCount = (Get-ChildItem $archiveDir -File).Count
                $archiveSize = [math]::Round((Get-ChildItem $archiveDir -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
                Write-Host "  [OK] archive/ ($archiveCount files, $archiveSize MB)" -ForegroundColor Green
            }
            else {
                Write-Host "  [--] Archive directory is empty" -ForegroundColor DarkGray
            }
        }
        else {
            Write-Host "  [--] No archive directory found" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Host "  [--] No archive directory found" -ForegroundColor DarkGray
    }
}

# ==============================================================
#  2. Capture docker compose logs
# ==============================================================
Write-Host ""
Write-Host "[2/4] Capturing Docker stdout..." -ForegroundColor Yellow

docker compose logs --tail $Tail --timestamps markflow 2>&1 | Out-File (Join-Path $OutputDir "docker-stdout.log") -Encoding utf8
Write-Host "  [OK] docker-stdout.log ($Tail lines)" -ForegroundColor Green

docker compose logs --tail 500 --timestamps markflow-mcp 2>&1 | Out-File (Join-Path $OutputDir "docker-mcp.log") -Encoding utf8
Write-Host "  [OK] docker-mcp.log (500 lines)" -ForegroundColor Green

docker compose logs --tail 500 --timestamps meilisearch 2>&1 | Out-File (Join-Path $OutputDir "docker-meilisearch.log") -Encoding utf8
Write-Host "  [OK] docker-meilisearch.log (500 lines)" -ForegroundColor Green

# ==============================================================
#  3. Triage
# ==============================================================
Write-Host ""
Write-Host "[3/4] Running triage..." -ForegroundColor Yellow

$logFile = Join-Path $OutputDir "markflow.log"
$triageFile = Join-Path $OutputDir "triage.txt"

$triageLines = @(
    "MarkFlow Log Triage -- $(Get-Date)"
    "Container: $Container"
    "Extracted: $timestamp"
    "=========================================="
    ""
)

if (Test-Path $logFile) {
    $errorCount = (Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue | Measure-Object).Count
    $warnCount  = (Select-String -Path $logFile -Pattern '"level": "warning"' -ErrorAction SilentlyContinue | Measure-Object).Count
    $lockCount  = (Select-String -Path $logFile -Pattern "database is locked" -ErrorAction SilentlyContinue | Measure-Object).Count

    $triageLines += @(
        "=== Counts ==="
        "Errors:         $errorCount"
        "Warnings:       $warnCount"
        "DB lock errors: $lockCount"
        ""
    )

    Write-Host "  Errors:   $errorCount"
    Write-Host "  Warnings: $warnCount"
    Write-Host "  DB locks: $lockCount"

    # Last 20 errors
    $triageLines += "=== Last 20 Errors ==="
    $lastErrors = Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue |
        Select-Object -Last 20 | ForEach-Object { $_.Line }
    if ($lastErrors) { $triageLines += $lastErrors }
    $triageLines += ""

    # Last 10 warnings
    $triageLines += "=== Last 10 Warnings ==="
    $lastWarnings = Select-String -Path $logFile -Pattern '"level": "warning"' -ErrorAction SilentlyContinue |
        Select-Object -Last 10 | ForEach-Object { $_.Line }
    if ($lastWarnings) { $triageLines += $lastWarnings }
    $triageLines += ""

    # -- Extended analysis --
    if ($Analyze) {
        Write-Host ""
        Write-Host "  Running extended analysis..." -ForegroundColor Yellow

        # Top error events
        $triageLines += "=== Top Error Events ==="
        $errorEvents = Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue |
            ForEach-Object {
                if ($_.Line -match '"event":\s*"([^"]*)"') { $Matches[1] }
            } | Group-Object | Sort-Object Count -Descending | Select-Object -First 15
        foreach ($ev in $errorEvents) {
            $triageLines += "  $($ev.Count) $($ev.Name)"
        }
        $triageLines += ""

        # Conversion failures
        $convFails = (Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue |
            Where-Object { $_.Line -match '"event":\s*"(conversion_failed|ingest_error|handler_error)"' } |
            Measure-Object).Count
        $triageLines += "=== Conversion Failures ==="
        $triageLines += "Conversion-related errors: $convFails"
        $triageLines += ""

        # Container disk usage
        $triageLines += "=== Log Directory Size ==="
        try {
            $diskUsage = docker exec $Container du -sh /app/logs/ 2>$null
            $triageLines += $diskUsage
            $archiveDisk = docker exec $Container du -sh /app/logs/archive/ 2>$null
            if ($archiveDisk) { $triageLines += $archiveDisk }
        }
        catch {
            $triageLines += "  (container not accessible)"
        }
        $triageLines += ""

        # MCP crash-loop check
        $mcpLog = Join-Path $OutputDir "docker-mcp.log"
        if (Test-Path $mcpLog) {
            $mcpStarts = (Select-String -Path $mcpLog -Pattern "Application startup complete|Uvicorn running" -ErrorAction SilentlyContinue | Measure-Object).Count
            $triageLines += "=== MCP Health ==="
            $triageLines += "MCP startup events: $mcpStarts (>3 may indicate crash-loop)"
            $triageLines += ""
        }

        Write-Host "  [OK] Extended analysis complete" -ForegroundColor Green
    }
}
else {
    $triageLines += "  [--] No markflow.log found (debug-only mode or container issue)"
    Write-Host "  [--] No markflow.log found" -ForegroundColor DarkGray
}

# Write triage file (BOM-free)
[IO.File]::WriteAllText($triageFile, ($triageLines -join "`n"))

# ==============================================================
#  4. Summary
# ==============================================================
Write-Host ""
Write-Host "[4/4] Done!" -ForegroundColor Yellow
Write-Host ""

$totalSize = [math]::Round((Get-ChildItem $OutputDir -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Files saved to: $OutputDir\" -ForegroundColor Green
Write-Host "  Total size:     $totalSize MB"
Write-Host "  Triage:         $OutputDir\triage.txt"
Write-Host ""
Write-Host "  Tip: Upload markflow.log to Claude.ai for full analysis."
Write-Host "       For large files, filter first:"
Write-Host "         Select-String -Path markflow.log -Pattern '`\"level`\": `\"error`\"' | Out-File errors-only.log"
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan

Pop-Location
