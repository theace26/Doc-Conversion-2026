<#
.SYNOPSIS
    MarkFlow Docker Reset & Rebuild Script (PowerShell / Windows Work Machine)
    Tears down everything, force-pulls latest from GitHub, rebuilds from scratch.

.DESCRIPTION
    This script:
    1. Tears down all containers, volumes, and images
    2. Force-pulls the latest code from GitHub (hard reset to origin/main)
    3. Auto-detects GPU hardware on the host
    4. Ensures .env is configured with work machine paths
    5. Rebuilds and starts all services (with NVIDIA passthrough if applicable)
    6. Starts the hashcat host worker for non-NVIDIA GPUs (if hashcat installed)

    GPU detection is fully automatic. The -GPU flag is accepted for backwards
    compatibility but is no longer required.

.EXAMPLE
    .\reset-markflow.ps1
    .\reset-markflow.ps1 -SourceDir "C:\MyDocs" -OutputDir "D:\Output"
    .\reset-markflow.ps1 -SkipPrune
    .\reset-markflow.ps1 -GPU                  # (legacy, same as no flag)
#>

param(
    [string]$RepoDir = "C:\Users\Xerxes\Projects\Doc-Conversion-2026",
    [string]$SourceDir = "C:/Users/Xerxes/T86_Work/k_drv_test",
    [string]$OutputDir = "D:/Doc-Conv_Test",
    [string]$DriveC = "C:/",
    [string]$DriveD = "D:/",
    [switch]$SkipPrune,
    [switch]$GPU   # Accepted for backwards compat, no longer needed
)

$ErrorActionPreference = "Stop"

# ----------------------------------------------------------
#  Admin check -- winget and some GPU tools need elevation
# ----------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  [!] Not running as Administrator" -ForegroundColor Yellow
    Write-Host "      Some features (hashcat auto-install, GPU toolkit) require elevation." -ForegroundColor Yellow
    Write-Host ""
    $choice = Read-Host "  Continue anyway? (Y/N)"
    if ($choice -notmatch "^[Yy]") {
        Write-Host "  Exiting. Re-run as Administrator for full functionality." -ForegroundColor DarkGray
        exit 0
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Docker Reset & Rebuild"        -ForegroundColor Cyan
Write-Host "  Machine: Work (Windows)"                -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# ----------------------------------------------------------
#  GPU Auto-Detection
# ----------------------------------------------------------
Write-Host ""
Write-Host "[GPU] Detecting host GPU hardware..." -ForegroundColor Yellow

$gpuVendor = "none"
$gpuName = ""
$gpuVramMb = 0
$useNvidiaOverlay = $false
$hashcatPath = $null
$hashcatVersion = $null
$hashcatBackend = $null

# -- Check for NVIDIA via nvidia-smi --
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    try {
        $nvidiaOut = & nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $nvidiaOut) {
            $parts = $nvidiaOut.Trim() -split ",\s*"
            if ($parts.Count -ge 3) {
                $gpuVendor = "nvidia"
                $gpuName = $parts[0].Trim()
                $gpuVramMb = [int][double]$parts[1].Trim()
                $gpuFile = Join-Path $RepoDir "docker-compose.gpu.yml"
                if (Test-Path $gpuFile) {
                    $useNvidiaOverlay = $true
                }
                Write-Host "  [OK] NVIDIA GPU: $gpuName ($gpuVramMb MB)" -ForegroundColor Green
            }
        }
    }
    catch { }
}

# -- Fallback: Check for Intel/AMD via WMI --
if ($gpuVendor -eq "none") {
    try {
        $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                Select-Object Name, AdapterRAM
        foreach ($g in $gpus) {
            $name = if ($g.Name) { $g.Name.ToLower() } else { "" }
            if ($name -match "nvidia") {
                # NVIDIA found via WMI but nvidia-smi missing -- no container passthrough
                $gpuVendor = "nvidia"
                $gpuName = $g.Name
                if ($g.AdapterRAM) { $gpuVramMb = [int]($g.AdapterRAM / 1MB) }
                Write-Host "  [OK] NVIDIA GPU: $gpuName (nvidia-smi not found -- host worker path)" -ForegroundColor Green
                break
            }
            elseif ($name -match "amd|radeon") {
                $gpuVendor = "amd"
                $gpuName = $g.Name
                if ($g.AdapterRAM) { $gpuVramMb = [int]($g.AdapterRAM / 1MB) }
                Write-Host "  [OK] AMD GPU: $gpuName ($gpuVramMb MB)" -ForegroundColor Green
                break
            }
            elseif ($name -match "intel" -and $name -match "arc|iris|xe|uhd|hd graphics") {
                $gpuVendor = "intel"
                $gpuName = $g.Name
                if ($g.AdapterRAM) { $gpuVramMb = [int]($g.AdapterRAM / 1MB) }
                Write-Host "  [OK] Intel GPU: $gpuName ($gpuVramMb MB)" -ForegroundColor Green
                break
            }
        }
    }
    catch { }
}

if ($gpuVendor -eq "none") {
    Write-Host "  [--] No supported GPU detected" -ForegroundColor DarkGray
}

# -- Check for hashcat on host (auto-install if missing) --
$hashcatCmd = Get-Command hashcat -ErrorAction SilentlyContinue
if (-not $hashcatCmd) {
    Write-Host "  [--] hashcat not found -- attempting auto-install via winget..." -ForegroundColor Yellow
    try {
        & winget install hashcat.hashcat --accept-source-agreements --accept-package-agreements 2>$null
        # Refresh PATH so we can find hashcat in this session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $hashcatCmd = Get-Command hashcat -ErrorAction SilentlyContinue
        if ($hashcatCmd) {
            Write-Host "  [OK] hashcat installed successfully" -ForegroundColor Green
        }
        else {
            Write-Host "  [WARN] winget install completed but hashcat not on PATH" -ForegroundColor Yellow
            Write-Host "         You may need to restart your terminal or add hashcat to PATH manually" -ForegroundColor Yellow
            Write-Host "         Download: https://hashcat.net/hashcat/" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Host "  [WARN] Auto-install failed -- install hashcat manually" -ForegroundColor Yellow
        Write-Host "         winget install hashcat.hashcat" -ForegroundColor DarkGray
        Write-Host "         Or download: https://hashcat.net/hashcat/" -ForegroundColor DarkGray
    }
}

if ($hashcatCmd) {
    $hashcatPath = $hashcatCmd.Source
    try {
        $hashcatVersion = (& hashcat --version 2>$null).Trim()
        Write-Host "  [OK] hashcat: $hashcatVersion" -ForegroundColor Green
    }
    catch {
        $hashcatVersion = "unknown"
    }
    # Probe backend
    try {
        $backendOut = & hashcat -I 2>&1 | Out-String
        $backendLower = $backendOut.ToLower()
        if ($backendLower -match "cuda")      { $hashcatBackend = "CUDA" }
        elseif ($backendLower -match "rocm")  { $hashcatBackend = "ROCm" }
        elseif ($backendLower -match "opencl" -and $backendLower -match "gpu") { $hashcatBackend = "OpenCL" }
        elseif ($backendLower -match "opencl") { $hashcatBackend = "OpenCL-CPU" }
        if ($hashcatBackend) {
            Write-Host "  [OK] hashcat backend: $hashcatBackend" -ForegroundColor Green
        }
    }
    catch { }
}
else {
    Write-Host "  [--] hashcat unavailable (GPU cracking disabled)" -ForegroundColor DarkGray
}

# -- Write worker_capabilities.json for the container to read --
$queueDir = Join-Path $RepoDir "hashcat-queue"
if (-not (Test-Path $queueDir)) {
    New-Item -ItemType Directory -Path $queueDir -Force | Out-Null
}

$capabilities = @{
    available        = ($gpuVendor -ne "none")
    gpu_vendor       = $gpuVendor
    gpu_name         = $gpuName
    gpu_vram_mb      = $gpuVramMb
    hashcat_backend  = $hashcatBackend
    hashcat_version  = $hashcatVersion
    host_os          = "Windows"
    host_machine     = $env:PROCESSOR_ARCHITECTURE
    timestamp        = (Get-Date -Format "o")
} | ConvertTo-Json -Depth 2

Set-Content -Path (Join-Path $queueDir "worker_capabilities.json") -Value $capabilities -Encoding UTF8
Write-Host "  [OK] worker_capabilities.json written" -ForegroundColor Green

# -- Summary --
if ($useNvidiaOverlay) {
    Write-Host "  [GPU] NVIDIA container passthrough: ENABLED" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none" -and $hashcatPath) {
    Write-Host "  [GPU] Host worker path: $gpuVendor ($hashcatBackend)" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none") {
    Write-Host "  [GPU] GPU found but hashcat not installed -- install hashcat for GPU cracking" -ForegroundColor Yellow
}

# ----------------------------------------------------------
#  Build compose args (auto-include NVIDIA overlay if detected)
# ----------------------------------------------------------
$composeArgs = @("-f", (Join-Path $RepoDir "docker-compose.yml"))

if ($useNvidiaOverlay) {
    $composeArgs += @("-f", (Join-Path $RepoDir "docker-compose.gpu.yml"))
}

# ----------------------------------------------------------
#  1. Tear down everything
# ----------------------------------------------------------
Write-Host ""
Write-Host "[1/5] Tearing down containers, volumes, and images..." -ForegroundColor Yellow

Push-Location $RepoDir
try {
    docker compose @composeArgs down -v 2>$null
}
catch {
    Write-Host "  No existing containers to tear down" -ForegroundColor DarkGray
}

if (-not $SkipPrune) {
    Write-Host "  Pruning unused images and build cache (preserving markflow-base)..."
    docker system prune -f --volumes
    # Remove markflow app images but NOT the base image
    docker images "markflow-*" --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -ne "markflow-base:latest" } | ForEach-Object {
        docker rmi $_ 2>$null
    }
}

# Verify base image exists
$baseExists = docker images markflow-base:latest --format "{{.ID}}" 2>$null
if (-not $baseExists) {
    Write-Host ""
    Write-Host "  [!] markflow-base:latest not found -- building it now..." -ForegroundColor Yellow
    Write-Host "  (This is the slow step -- only needed once)"  -ForegroundColor DarkGray
    docker build -f (Join-Path $RepoDir "Dockerfile.base") -t markflow-base:latest $RepoDir
}

# ----------------------------------------------------------
#  2. Force-pull latest code from GitHub
# ----------------------------------------------------------
Write-Host ""
Write-Host "[2/5] Force-pulling latest code from GitHub..." -ForegroundColor Yellow

git -C $RepoDir fetch origin
git -C $RepoDir reset --hard origin/main
git -C $RepoDir pull origin main

$commitHash = git -C $RepoDir log -1 --format="%h %s"
Write-Host "  [OK] Now at: $commitHash" -ForegroundColor Green

# ----------------------------------------------------------
#  3. Ensure .env is configured for this work machine
# ----------------------------------------------------------
Write-Host ""
Write-Host "[3/5] Configuring .env for work machine..." -ForegroundColor Yellow

$envFile = Join-Path $RepoDir ".env"

$envLines = @(
    "# MarkFlow Environment Configuration"
    "# Work machine (Windows) - auto-generated by reset-markflow.ps1"
    ""
    "# Host paths - mounted into Docker containers"
    "SOURCE_DIR=$SourceDir"
    "OUTPUT_DIR=$OutputDir"
    "DRIVE_C=$DriveC"
    "DRIVE_D=$DriveD"
    ""
    "# Meilisearch"
    "MEILI_MASTER_KEY="
    ""
    "# Bulk conversion"
    "BULK_WORKER_COUNT=4"
    ""
    "# App"
    "SECRET_KEY=dev-secret-change-in-prod"
    "DEFAULT_LOG_LEVEL=normal"
    "DEV_BYPASS_AUTH=true"
)
$envContent = $envLines -join "`n"

Set-Content -Path $envFile -Value $envContent -Encoding UTF8 -NoNewline
Write-Host "  [OK] .env written" -ForegroundColor Green
Write-Host "    SOURCE_DIR = $SourceDir"
Write-Host "    OUTPUT_DIR = $OutputDir"

# ----------------------------------------------------------
#  4. Verify paths exist
# ----------------------------------------------------------
Write-Host ""
Write-Host "[4/5] Verifying paths..." -ForegroundColor Yellow

if (Test-Path $SourceDir) {
    $sourceCount = (Get-ChildItem $SourceDir -File -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Host "  [OK] Source dir exists ($sourceCount files)" -ForegroundColor Green
}
else {
    Write-Host "  [!] Source dir not found: $SourceDir" -ForegroundColor Red
}

if (Test-Path $OutputDir) {
    Write-Host "  [OK] Output dir exists" -ForegroundColor Green
}
else {
    Write-Host "  [!] Output dir not found: $OutputDir - creating it..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    Write-Host "  [OK] Output dir created" -ForegroundColor Green
}

# ----------------------------------------------------------
#  5. Rebuild and start
# ----------------------------------------------------------
Write-Host ""
Write-Host "[5/5] Building and starting MarkFlow..." -ForegroundColor Yellow

docker compose @composeArgs up -d --build

# ----------------------------------------------------------
#  Auto-start hashcat host worker (non-NVIDIA or no toolkit)
# ----------------------------------------------------------
if ($hashcatPath -and $gpuVendor -ne "none" -and -not $useNvidiaOverlay) {
    $workerScript = Join-Path $RepoDir "tools\markflow-hashcat-worker.py"
    if (Test-Path $workerScript) {
        Write-Host ""
        Write-Host "[GPU] Starting hashcat host worker in background..." -ForegroundColor Magenta
        Start-Process -FilePath "python" -ArgumentList "`"$workerScript`"", "--queue-dir", "`"$queueDir`"" `
                      -WindowStyle Hidden -PassThru | Out-Null
        Write-Host "  [OK] Host worker started (PID will be in hashcat-queue\worker.lock)" -ForegroundColor Green
    }
}

# ----------------------------------------------------------
#  Done
# ----------------------------------------------------------
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Reset Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

docker compose @composeArgs ps

Write-Host ""
Write-Host "  MarkFlow UI:  http://localhost:8000"
Write-Host "  Meilisearch:  http://localhost:7700"
Write-Host "  MCP Server:   http://localhost:8001"
if ($useNvidiaOverlay) {
    Write-Host "  GPU Mode:     NVIDIA container passthrough" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none" -and $hashcatPath) {
    Write-Host "  GPU Mode:     $gpuName (host worker)" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none") {
    Write-Host "  GPU Mode:     $gpuName (hashcat not installed)" -ForegroundColor Yellow
}
else {
    Write-Host "  GPU Mode:     None detected" -ForegroundColor DarkGray
}
Write-Host "==========================================" -ForegroundColor Cyan

Pop-Location
