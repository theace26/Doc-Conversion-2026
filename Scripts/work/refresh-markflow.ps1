<#
.SYNOPSIS
    MarkFlow Quick Refresh - pulls latest code and rebuilds without wiping volumes.

.DESCRIPTION
    Unlike reset-markflow.ps1, this keeps your database, Meilisearch index,
    and converted output intact. It only:
    1. Force-pulls latest code from GitHub
    2. Auto-detects GPU hardware on the host
    3. Rebuilds the Docker images with the new code
    4. Restarts the containers (with NVIDIA passthrough if applicable)
    5. Starts the hashcat host worker for non-NVIDIA GPUs (if hashcat installed)

    GPU detection is fully automatic. The -GPU flag is accepted for backwards
    compatibility but is no longer required.

.EXAMPLE
    .\refresh-markflow.ps1                  # auto-detects GPU
    .\refresh-markflow.ps1 -NoBuild         # just restart, skip rebuild
    .\refresh-markflow.ps1 -GPU             # (legacy, same as no flag)
#>

param(
    [string]$RepoDir = "C:\Users\Xerxes\Projects\Doc-Conversion-2026",
    [switch]$NoBuild,
    [switch]$GPU   # Accepted for backwards compat, no longer needed
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Quick Refresh"                  -ForegroundColor Cyan
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
}
else {
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
Write-Host "  Refresh Complete!" -ForegroundColor Green
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
