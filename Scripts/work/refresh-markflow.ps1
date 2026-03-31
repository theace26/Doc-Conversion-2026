<#
.SYNOPSIS
    MarkFlow Quick Refresh - pulls latest code and rebuilds without wiping volumes.

.DESCRIPTION
    Unlike reset-markflow.ps1, this keeps your database, Meilisearch index,
    and converted output intact. It only:
    1. Force-pulls latest code from GitHub
    2. Rebuilds the Docker images with the new code
    3. Restarts the containers

.EXAMPLE
    .\refresh-markflow.ps1                  # normal refresh (CPU only)
    .\refresh-markflow.ps1 -GPU             # refresh with GPU passthrough
    .\refresh-markflow.ps1 -NoBuild         # just restart, skip rebuild
    .\refresh-markflow.ps1 -GPU -NoBuild    # GPU, restart only
#>

param(
    [string]$RepoDir = "C:\Users\Xerxes\Projects\Doc-Conversion-2026",
    [switch]$NoBuild,
    [switch]$GPU
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Quick Refresh"                  -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# ----------------------------------------------------------
#  Build compose args (base + optional GPU override)
# ----------------------------------------------------------
$composeArgs = @("-f", (Join-Path $RepoDir "docker-compose.yml"))

if ($GPU) {
    $gpuFile = Join-Path $RepoDir "docker-compose.gpu.yml"
    if (Test-Path $gpuFile) {
        $composeArgs += @("-f", $gpuFile)
        Write-Host "  [GPU] Including GPU compose override" -ForegroundColor Magenta
    } else {
        Write-Host "  [WARN] docker-compose.gpu.yml not found — falling back to CPU only" -ForegroundColor Red
    }
}

# ----------------------------------------------------------
#  1. Force-pull latest code from GitHub
# ----------------------------------------------------------
Write-Host ""
Write-Host "[1/3] Pulling latest code from GitHub..." -ForegroundColor Yellow

git -C $RepoDir fetch origin
git -C $RepoDir reset --hard origin/main

$commitHash = git -C $RepoDir log -1 --format="%h %s"
Write-Host "  [OK] Now at: $commitHash" -ForegroundColor Green

# ----------------------------------------------------------
#  2. Rebuild images (or skip with -NoBuild)
# ----------------------------------------------------------
Write-Host ""

if ($NoBuild) {
    Write-Host "[2/3] Skipping rebuild (-NoBuild flag)" -ForegroundColor DarkGray
} else {
    Write-Host "[2/3] Rebuilding Docker images..." -ForegroundColor Yellow
    docker compose @composeArgs build
    Write-Host "  [OK] Build complete" -ForegroundColor Green
}

# ----------------------------------------------------------
#  3. Restart containers with new images
# ----------------------------------------------------------
Write-Host ""
Write-Host "[3/3] Restarting containers..." -ForegroundColor Yellow

docker compose @composeArgs up -d

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Refresh Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

docker compose @composeArgs ps

Write-Host ""
Write-Host "  MarkFlow UI:  http://localhost:8000"
Write-Host "  Meilisearch:  http://localhost:7700"
Write-Host "  MCP Server:   http://localhost:8001"
if ($GPU) {
    Write-Host "  GPU Mode:     ENABLED" -ForegroundColor Magenta
}
Write-Host "==========================================" -ForegroundColor Cyan