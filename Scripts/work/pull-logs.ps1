<#
.SYNOPSIS
    MarkFlow Log Extraction Script (PowerShell)
    Copies logs from the Docker container to your home directory
    with timestamps, then prints scp commands for downloading.

.USAGE
    .\pull-logs.ps1
    .\pull-logs.ps1 -Tail 5000    (last N lines only)
#>

param(
    [int]$Tail = 0
)

$ErrorActionPreference = "Stop"

$Container  = "markflow-markflow-1"
$Timestamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$MainLog    = "markflow-${Timestamp}.log"
$DebugLog   = "markflow-debug-${Timestamp}.log"
$VmIp       = "192.168.1.208"
$VmUser     = "xerxes"
$HomeDir    = $env:USERPROFILE

Write-Host "=========================================="
Write-Host "  MarkFlow Log Extraction"
Write-Host "  Timestamp: $Timestamp"
Write-Host "=========================================="

# ----------------------------------------------------------
#  1. Verify container is running
# ----------------------------------------------------------
$running = docker ps --format '{{.Names}}' 2>$null | Where-Object { $_ -eq $Container }

if (-not $running) {
    Write-Host ""
    Write-Host "  WARNING: Container '$Container' is not running." -ForegroundColor Yellow
    Write-Host "  Available containers:"
    docker ps -a --format "  {{.Names}}  ({{.Status}})"
    exit 1
}

# ----------------------------------------------------------
#  2. Copy logs from container
# ----------------------------------------------------------
Write-Host ""
Write-Host "[1/3] Copying logs from container..."

$mainCopied = $false
$debugCopied = $false

try {
    docker cp "${Container}:/app/logs/markflow.log" (Join-Path $HomeDir $MainLog) 2>$null
    Write-Host "  [OK] Main log copied" -ForegroundColor Green
    $mainCopied = $true
} catch {
    Write-Host "  [!] Main log not found in container" -ForegroundColor Yellow
}

try {
    docker cp "${Container}:/app/logs/markflow-debug.log" (Join-Path $HomeDir $DebugLog) 2>$null
    Write-Host "  [OK] Debug log copied" -ForegroundColor Green
    $debugCopied = $true
} catch {
    Write-Host "  [!] Debug log not found in container" -ForegroundColor Yellow
}

# docker cp doesn't throw on missing files in all cases, check if files actually exist
if (-not (Test-Path (Join-Path $HomeDir $MainLog))) {
    if ($mainCopied) {
        Write-Host "  [!] Main log not found in container" -ForegroundColor Yellow
        $mainCopied = $false
    }
}
if (-not (Test-Path (Join-Path $HomeDir $DebugLog))) {
    if ($debugCopied) {
        Write-Host "  [!] Debug log not found in container" -ForegroundColor Yellow
        $debugCopied = $false
    }
}

# ----------------------------------------------------------
#  3. Tail if requested (for large logs)
# ----------------------------------------------------------
if ($Tail -gt 0) {
    Write-Host ""
    Write-Host "[2/3] Trimming to last $Tail lines..."

    if ($mainCopied) {
        $fullMainPath = Join-Path $HomeDir $MainLog
        $MainLog = "markflow-tail-${Timestamp}.log"
        $tailMainPath = Join-Path $HomeDir $MainLog
        Get-Content $fullMainPath -Tail $Tail | Set-Content $tailMainPath -Encoding UTF8
        Remove-Item $fullMainPath
        Write-Host "  [OK] Main log trimmed -> $MainLog" -ForegroundColor Green
    }

    if ($debugCopied) {
        $fullDebugPath = Join-Path $HomeDir $DebugLog
        $DebugLog = "markflow-debug-tail-${Timestamp}.log"
        $tailDebugPath = Join-Path $HomeDir $DebugLog
        Get-Content $fullDebugPath -Tail $Tail | Set-Content $tailDebugPath -Encoding UTF8
        Remove-Item $fullDebugPath
        Write-Host "  [OK] Debug log trimmed -> $DebugLog" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "[2/3] No -Tail flag, keeping full logs"
}

# ----------------------------------------------------------
#  4. Report sizes and print scp commands
# ----------------------------------------------------------
Write-Host ""
Write-Host "[3/3] Log files ready:"
Write-Host ""

$mainPath = Join-Path $HomeDir $MainLog
$debugPath = Join-Path $HomeDir $DebugLog

if (Test-Path $mainPath) {
    $mainSize = (Get-Item $mainPath).Length
    $mainSizeFmt = if ($mainSize -ge 1MB) { "{0:N1} MB" -f ($mainSize / 1MB) }
                   elseif ($mainSize -ge 1KB) { "{0:N1} KB" -f ($mainSize / 1KB) }
                   else { "$mainSize B" }
    Write-Host "  $MainLog  ($mainSizeFmt)"
} else {
    Write-Host "  Main log - not available" -ForegroundColor Red
}

if (Test-Path $debugPath) {
    $debugSize = (Get-Item $debugPath).Length
    $debugSizeFmt = if ($debugSize -ge 1MB) { "{0:N1} MB" -f ($debugSize / 1MB) }
                    elseif ($debugSize -ge 1KB) { "{0:N1} KB" -f ($debugSize / 1KB) }
                    else { "$debugSize B" }
    Write-Host "  $DebugLog  ($debugSizeFmt)"
} else {
    Write-Host "  Debug log - not available" -ForegroundColor Red
}

Write-Host ""
Write-Host "=========================================="
Write-Host "  Log files saved to: $HomeDir"
Write-Host "=========================================="
Write-Host ""

if ((Test-Path $mainPath) -or (Test-Path $debugPath)) {
    Write-Host "  To download from the VM instead, use:"
    Write-Host ""
    if (Test-Path $mainPath) {
        Write-Host "  scp ${VmUser}@${VmIp}:~/${MainLog} $env:USERPROFILE\Downloads\"
    }
    if (Test-Path $debugPath) {
        Write-Host "  scp ${VmUser}@${VmIp}:~/${DebugLog} $env:USERPROFILE\Downloads\"
    }
    Write-Host ""
    Write-Host "  After downloading, clean up with:"
    Write-Host "  Remove-Item $(Join-Path $HomeDir $MainLog), $(Join-Path $HomeDir $DebugLog)"
}

Write-Host "=========================================="
