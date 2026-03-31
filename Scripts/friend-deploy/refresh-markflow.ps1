<#
.SYNOPSIS
    MarkFlow Quick Refresh - pulls latest code and rebuilds without wiping data.

.DESCRIPTION
    Unlike setup-markflow.ps1, this keeps your database, Meilisearch index,
    and converted output intact. It only:
    1. Force-pulls latest code from GitHub
    2. Re-detects GPU hardware
    3. Rebuilds the Docker images with the new code
    4. Restarts the containers
    5. Starts the hashcat host worker for non-NVIDIA GPUs

.EXAMPLE
    .\refresh-markflow.ps1                  # auto-detects everything
    .\refresh-markflow.ps1 -NoBuild         # just restart, skip rebuild
    .\refresh-markflow.ps1 -RepoDir "C:\my\path"
#>

param(
    [string]$RepoDir,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

# ===========================================================================
#  Locate the repository
# ===========================================================================
if (-not $RepoDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
    $candidate = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
    if (Test-Path (Join-Path $candidate "docker-compose.yml")) {
        $RepoDir = $candidate
    }
    else {
        Write-Host ""
        $RepoDir = Read-Host "  Enter the full path to the Doc-Conversion-2026 folder"
        if (-not (Test-Path (Join-Path $RepoDir "docker-compose.yml"))) {
            Write-Host "  [ERROR] docker-compose.yml not found at: $RepoDir" -ForegroundColor Red
            exit 1
        }
    }
}

# Verify .env exists (setup must have been run first)
$envFile = Join-Path $RepoDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Host ""
    Write-Host "  [ERROR] .env not found at: $envFile" -ForegroundColor Red
    Write-Host "  Run setup-markflow.ps1 first to configure your environment." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Quick Refresh"                  -ForegroundColor Cyan
Write-Host "  Repo: $RepoDir"                          -ForegroundColor DarkGray
Write-Host "==========================================" -ForegroundColor Cyan

# ===========================================================================
#  Admin check
# ===========================================================================
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  [!] Not running as Administrator" -ForegroundColor Yellow
    Write-Host "      Some features (hashcat auto-install) require elevation." -ForegroundColor Yellow
    Write-Host ""
    $choice = Read-Host "  Continue anyway? (Y/N)"
    if ($choice -notmatch "^[Yy]") {
        Write-Host "  Exiting." -ForegroundColor DarkGray
        exit 0
    }
}

# ===========================================================================
#  GPU Auto-Detection
# ===========================================================================
Write-Host ""
Write-Host "[GPU] Detecting host GPU hardware..." -ForegroundColor Yellow

$gpuVendor = "none"
$gpuName = ""
$gpuVramMb = 0
$useNvidiaOverlay = $false
$hashcatPath = $null
$hashcatVersion = $null
$hashcatBackend = $null

# -- NVIDIA via nvidia-smi --
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

# -- Fallback: AMD/Intel via WMI --
if ($gpuVendor -eq "none") {
    try {
        $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                Select-Object Name, AdapterRAM
        foreach ($g in $gpus) {
            $name = if ($g.Name) { $g.Name.ToLower() } else { "" }
            if ($name -match "nvidia") {
                $gpuVendor = "nvidia"
                $gpuName = $g.Name
                if ($g.AdapterRAM) { $gpuVramMb = [int]($g.AdapterRAM / 1MB) }
                Write-Host "  [OK] NVIDIA GPU: $gpuName (nvidia-smi not found -- host worker)" -ForegroundColor Green
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

# -- hashcat --
$hashcatCmd = Get-Command hashcat -ErrorAction SilentlyContinue
if (-not $hashcatCmd) {
    Write-Host "  [--] hashcat not found -- attempting auto-install via winget..." -ForegroundColor Yellow
    try {
        & winget install hashcat.hashcat --accept-source-agreements --accept-package-agreements 2>$null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $hashcatCmd = Get-Command hashcat -ErrorAction SilentlyContinue
        if ($hashcatCmd) {
            Write-Host "  [OK] hashcat installed" -ForegroundColor Green
        }
        else {
            Write-Host "  [WARN] hashcat not on PATH -- restart terminal" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "  [WARN] Auto-install failed -- install manually: winget install hashcat.hashcat" -ForegroundColor Yellow
    }
}

if ($hashcatCmd) {
    $hashcatPath = $hashcatCmd.Source
    try {
        $hashcatVersion = (& hashcat --version 2>$null).Trim()
        Write-Host "  [OK] hashcat: $hashcatVersion" -ForegroundColor Green
    }
    catch { $hashcatVersion = "unknown" }

    try {
        $hashcatDir = Split-Path $hashcatPath -Parent
        $savedDir = Get-Location
        Set-Location $hashcatDir
        $ErrorActionPreference = 'SilentlyContinue'
        $backendOut = & hashcat -I 2>&1 | Out-String
        $ErrorActionPreference = 'Stop'
        Set-Location $savedDir
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

# -- Write worker_capabilities.json --
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

[IO.File]::WriteAllText((Join-Path $queueDir "worker_capabilities.json"), $capabilities)
Write-Host "  [OK] worker_capabilities.json updated" -ForegroundColor Green

# -- GPU summary --
if ($useNvidiaOverlay) {
    Write-Host "  [GPU] NVIDIA container passthrough: ENABLED" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none" -and $hashcatPath) {
    Write-Host "  [GPU] Host worker path: $gpuVendor ($hashcatBackend)" -ForegroundColor Magenta
}

# ===========================================================================
#  Compose args
# ===========================================================================
$composeArgs = @("-f", (Join-Path $RepoDir "docker-compose.yml"))
if ($useNvidiaOverlay) {
    $composeArgs += @("-f", (Join-Path $RepoDir "docker-compose.gpu.yml"))
}

# ===========================================================================
#  1. Pull latest code
# ===========================================================================
Write-Host ""
Write-Host "[1/3] Pulling latest code from GitHub..." -ForegroundColor Yellow

git -C $RepoDir fetch origin
git -C $RepoDir reset --hard origin/main

$commitHash = git -C $RepoDir log -1 --format="%h %s"
Write-Host "  [OK] Now at: $commitHash" -ForegroundColor Green

# ===========================================================================
#  2. Rebuild images
# ===========================================================================
Write-Host ""

if ($NoBuild) {
    Write-Host "[2/3] Skipping rebuild (-NoBuild flag)" -ForegroundColor DarkGray
}
else {
    Write-Host "[2/3] Rebuilding Docker images..." -ForegroundColor Yellow

    # Check base image
    $baseExists = docker images markflow-base:latest --format "{{.ID}}" 2>$null
    if (-not $baseExists) {
        Write-Host "  [!] Base image missing -- building it first..." -ForegroundColor Yellow
        Write-Host "  (This takes 25-40 min on HDD, ~5 min on SSD)" -ForegroundColor DarkGray
        docker build -f (Join-Path $RepoDir "Dockerfile.base") -t markflow-base:latest $RepoDir
    }

    Push-Location $RepoDir
    docker compose @composeArgs build
    Pop-Location
    Write-Host "  [OK] Build complete" -ForegroundColor Green
}

# ===========================================================================
#  3. Restart containers
# ===========================================================================
Write-Host ""
Write-Host "[3/3] Restarting containers..." -ForegroundColor Yellow

Push-Location $RepoDir
docker compose @composeArgs up -d
Pop-Location

# ===========================================================================
#  Start hashcat host worker (non-NVIDIA GPUs)
# ===========================================================================
if ($hashcatPath -and $gpuVendor -ne "none" -and -not $useNvidiaOverlay) {
    $workerScript = Join-Path $RepoDir "tools\markflow-hashcat-worker.py"
    if (Test-Path $workerScript) {
        Write-Host ""
        Write-Host "[GPU] Starting hashcat host worker in background..." -ForegroundColor Magenta
        Start-Process -FilePath "python" -ArgumentList "`"$workerScript`"", "--queue-dir", "`"$queueDir`"" `
                      -WindowStyle Hidden -PassThru | Out-Null
        Write-Host "  [OK] Host worker started" -ForegroundColor Green
    }
}

# ===========================================================================
#  Done
# ===========================================================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Refresh Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $RepoDir
docker compose @composeArgs ps
Pop-Location

Write-Host ""
Write-Host "  MarkFlow UI:  http://localhost:8000"
Write-Host "  Meilisearch:  http://localhost:7700"
Write-Host "  MCP Server:   http://localhost:8001"
if ($useNvidiaOverlay) {
    Write-Host "  GPU Mode:     NVIDIA container passthrough" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none" -and $hashcatPath) {
    Write-Host "  GPU Mode:     $gpuName (host worker, $hashcatBackend)" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none") {
    Write-Host "  GPU Mode:     $gpuName (hashcat not installed)" -ForegroundColor Yellow
}
else {
    Write-Host "  GPU Mode:     None detected" -ForegroundColor DarkGray
}
Write-Host "==========================================" -ForegroundColor Cyan
