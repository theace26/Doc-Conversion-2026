<#
.SYNOPSIS
    Build the MarkFlow base Docker image (system dependencies only).

.DESCRIPTION
    This builds the heavy base layer containing all apt packages
    (LibreOffice, Tesseract, ffmpeg, hashcat, etc.). Run this once,
    then daily rebuilds only need pip install + code copy.

    Rebuild the base when:
    - First time setup on a new machine
    - Dockerfile.base changes (new system package added)
    - You ran docker system prune -a (wiped all images)

    You do NOT need to rebuild the base when:
    - Python code changes
    - requirements.txt changes
    - .env or docker-compose.yml changes

.EXAMPLE
    .\build-base.ps1              # build the base image
    .\build-base.ps1 -NoCache     # force full rebuild (no Docker cache)
#>

param(
    [string]$RepoDir = "C:\Users\Xerxes\Projects\Doc-Conversion-2026",
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Base Image Builder"             -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Check if base image already exists
$existing = docker images markflow-base:latest --format "{{.ID}} ({{.CreatedSince}}, {{.Size}})" 2>$null
if ($existing) {
    Write-Host ""
    Write-Host "  Existing base image: $existing" -ForegroundColor DarkGray
    Write-Host "  This will be replaced." -ForegroundColor DarkGray
}

# Build
Write-Host ""
Write-Host "Building markflow-base:latest ..." -ForegroundColor Yellow
Write-Host "  (This takes 25-40 min on HDD, ~5 min on SSD/NVMe)" -ForegroundColor DarkGray
Write-Host ""

$buildArgs = @("build", "-f", "Dockerfile.base", "-t", "markflow-base:latest")
if ($NoCache) {
    $buildArgs += "--no-cache"
}
$buildArgs += "."

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Push-Location $RepoDir
docker @buildArgs
$exitCode = $LASTEXITCODE
Pop-Location

$stopwatch.Stop()
$elapsed = $stopwatch.Elapsed.ToString("mm\:ss")

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "  Base image built successfully! ($elapsed)" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""

    # Show image info
    $size = docker images markflow-base:latest --format "{{.Size}}"
    Write-Host "  Image: markflow-base:latest ($size)"
    Write-Host ""
    Write-Host "  Next steps:"
    Write-Host "    .\refresh-markflow.ps1    # quick rebuild (code + pip only)"
    Write-Host "    .\reset-markflow.ps1      # full reset (keeps base image)"
    Write-Host "==========================================" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "  Build FAILED (exit code $exitCode, $elapsed elapsed)" -ForegroundColor Red
    Write-Host "  Check the output above for errors." -ForegroundColor Red
    exit $exitCode
}
