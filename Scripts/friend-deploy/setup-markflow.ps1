<#
.SYNOPSIS
    MarkFlow First-Time Setup & Full Reset Script
    Interactive folder picker, GPU detection, Docker build, and service startup.

.DESCRIPTION
    This script:
    1. Opens folder-picker dialogs for your Source and Output directories
    2. Auto-detects GPU hardware (NVIDIA, AMD, Intel)
    3. Installs hashcat if missing (optional, for GPU password cracking)
    4. Writes .env configuration for Docker
    5. Builds the base Docker image if not already built (~25-40 min first time)
    6. Builds the app image and starts all MarkFlow services
    7. Starts the hashcat host worker for non-NVIDIA GPUs

.EXAMPLE
    .\setup-markflow.ps1                           # interactive folder picker
    .\setup-markflow.ps1 -SkipPrune                # keep old Docker artifacts
    .\setup-markflow.ps1 -RepoDir "C:\my\path"     # custom repo location
#>

param(
    [string]$RepoDir,
    [switch]$SkipPrune
)

$ErrorActionPreference = "Stop"

# ===========================================================================
#  Locate the repository
# ===========================================================================
if (-not $RepoDir) {
    # Default: assume the repo is two levels up from this script
    # (Scripts/friend-deploy/setup-markflow.ps1 -> repo root)
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
    $candidate = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
    if (Test-Path (Join-Path $candidate "docker-compose.yml")) {
        $RepoDir = $candidate
    }
    else {
        Write-Host ""
        Write-Host "  Could not auto-detect the MarkFlow repo location." -ForegroundColor Yellow
        $RepoDir = Read-Host "  Enter the full path to the Doc-Conversion-2026 folder"
        if (-not (Test-Path (Join-Path $RepoDir "docker-compose.yml"))) {
            Write-Host "  [ERROR] docker-compose.yml not found at: $RepoDir" -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Setup"                          -ForegroundColor Cyan
Write-Host "  Repo: $RepoDir"                          -ForegroundColor DarkGray
Write-Host "==========================================" -ForegroundColor Cyan

# ===========================================================================
#  Admin check
# ===========================================================================
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

# ===========================================================================
#  Folder Picker Helper
# ===========================================================================
function Select-FolderDialog {
    param(
        [string]$Title,
        [string]$InitialDir = [Environment]::GetFolderPath("MyDocuments")
    )
    Add-Type -AssemblyName System.Windows.Forms

    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Title
    $dialog.ShowNewFolderButton = $true

    # Set initial directory via SelectedPath
    if (Test-Path $InitialDir) {
        $dialog.SelectedPath = $InitialDir
    }

    # Show dialog on top of other windows
    $topForm = New-Object System.Windows.Forms.Form
    $topForm.TopMost = $true
    $result = $dialog.ShowDialog($topForm)
    $topForm.Dispose()

    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return $dialog.SelectedPath
    }
    return $null
}

# ===========================================================================
#  1. Pick Source Directory
# ===========================================================================
Write-Host ""
Write-Host "[1/6] Select your SOURCE directory" -ForegroundColor Yellow
Write-Host "  This is the folder containing documents you want to convert." -ForegroundColor DarkGray
Write-Host "  (It will be mounted read-only -- MarkFlow never modifies your originals)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  A folder picker dialog will open..." -ForegroundColor DarkGray

$SourceDir = Select-FolderDialog -Title "Select your SOURCE directory - the folder of documents to convert" -InitialDir ([Environment]::GetFolderPath("MyDocuments"))

if (-not $SourceDir) {
    Write-Host "  [ERROR] No source directory selected. Setup cancelled." -ForegroundColor Red
    exit 1
}

# Convert to forward slashes for Docker
$SourceDirDocker = $SourceDir.Replace('\', '/')

if (Test-Path $SourceDir) {
    $fileCount = (Get-ChildItem $SourceDir -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1000 | Measure-Object).Count
    if ($fileCount -eq 0) {
        Write-Host "  [WARN] Source directory is empty: $SourceDir" -ForegroundColor Yellow
        Write-Host "         Add some documents to it before running a bulk conversion." -ForegroundColor Yellow
    }
    elseif ($fileCount -ge 1000) {
        Write-Host "  [OK] Source dir: $SourceDir (1000+ files)" -ForegroundColor Green
    }
    else {
        Write-Host "  [OK] Source dir: $SourceDir ($fileCount files)" -ForegroundColor Green
    }
}
else {
    Write-Host "  [WARN] Source directory does not exist: $SourceDir" -ForegroundColor Yellow
    Write-Host "         Create it and add documents before running a bulk conversion." -ForegroundColor Yellow
}

# ===========================================================================
#  2. Pick Output Directory
# ===========================================================================
Write-Host ""
Write-Host "[2/6] Select your OUTPUT directory" -ForegroundColor Yellow
Write-Host "  This is where MarkFlow writes converted Markdown files during bulk jobs." -ForegroundColor DarkGray
Write-Host "  Recommend: a local SSD folder with at least a few GB free." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  A folder picker dialog will open..." -ForegroundColor DarkGray

$OutputDir = Select-FolderDialog -Title "Select your OUTPUT directory - where converted files will be saved" -InitialDir ([Environment]::GetFolderPath("MyDocuments"))

if (-not $OutputDir) {
    Write-Host "  [ERROR] No output directory selected. Setup cancelled." -ForegroundColor Red
    exit 1
}

$OutputDirDocker = $OutputDir.Replace('\', '/')

if (-not (Test-Path $OutputDir)) {
    Write-Host "  [--] Output directory does not exist -- creating it..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}
Write-Host "  [OK] Output dir: $OutputDir" -ForegroundColor Green

# ===========================================================================
#  Detect available drive letters for the directory browser
# ===========================================================================
Write-Host ""
Write-Host "[3/6] Detecting drives and GPU..." -ForegroundColor Yellow

$driveLetters = @()
$driveEnvLines = @()
$driveComposeVolumes = @()

foreach ($letter in @("c", "d", "e", "f")) {
    $drivePath = "${letter}:/"
    if (Test-Path "${letter}:\") {
        $driveLetters += $letter
        $driveEnvLines += "DRIVE_$($letter.ToUpper())=$drivePath"
        Write-Host "  [OK] Drive ${letter}: found" -ForegroundColor Green
    }
}

$mountedDrives = ($driveLetters -join ",")
Write-Host "  Browsable drives: $mountedDrives"

# ===========================================================================
#  GPU Auto-Detection
# ===========================================================================
Write-Host ""
Write-Host "  Detecting GPU hardware..." -ForegroundColor DarkGray

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
    Write-Host "  [--] No supported GPU detected (password cracking will use CPU)" -ForegroundColor DarkGray
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
            Write-Host "  [WARN] hashcat not on PATH after install -- restart terminal later" -ForegroundColor Yellow
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
Write-Host "  [OK] worker_capabilities.json written" -ForegroundColor Green

# -- GPU summary --
if ($useNvidiaOverlay) {
    Write-Host "  [GPU] NVIDIA container passthrough: ENABLED" -ForegroundColor Magenta
}
elseif ($gpuVendor -ne "none" -and $hashcatPath) {
    Write-Host "  [GPU] Host worker path: $gpuVendor ($hashcatBackend)" -ForegroundColor Magenta
}

# ===========================================================================
#  Write .env
# ===========================================================================
Write-Host ""
Write-Host "[4/6] Writing .env configuration..." -ForegroundColor Yellow

$envFile = Join-Path $RepoDir ".env"

$envLines = @(
    "# MarkFlow Environment Configuration"
    "# Auto-generated by setup-markflow.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    ""
    "# Host paths - mounted into Docker containers"
    "SOURCE_DIR=$SourceDirDocker"
    "OUTPUT_DIR=$OutputDirDocker"
)
foreach ($dl in $driveEnvLines) {
    $envLines += $dl
}
$envLines += @(
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

[IO.File]::WriteAllText($envFile, $envContent)
Write-Host "  [OK] .env written" -ForegroundColor Green
Write-Host "    SOURCE_DIR = $SourceDirDocker"
Write-Host "    OUTPUT_DIR = $OutputDirDocker"
Write-Host "    Drives     = $mountedDrives"

# ===========================================================================
#  Tear down existing containers (if any)
# ===========================================================================
$composeArgs = @("-f", (Join-Path $RepoDir "docker-compose.yml"))
if ($useNvidiaOverlay) {
    $composeArgs += @("-f", (Join-Path $RepoDir "docker-compose.gpu.yml"))
}

Write-Host ""
Write-Host "[5/6] Preparing Docker environment..." -ForegroundColor Yellow

Push-Location $RepoDir

try {
    docker compose @composeArgs down -v 2>$null
}
catch {
    Write-Host "  No existing containers to tear down" -ForegroundColor DarkGray
}

if (-not $SkipPrune) {
    Write-Host "  Pruning unused Docker artifacts (preserving base image)..."
    docker system prune -f --volumes 2>$null
    docker images "markflow-*" --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -ne "markflow-base:latest" } | ForEach-Object {
        docker rmi $_ 2>$null
    }
}

# -- Build base image if missing --
$baseExists = docker images markflow-base:latest --format "{{.ID}}" 2>$null
if (-not $baseExists) {
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Yellow
    Write-Host "  Building markflow-base:latest (first time)" -ForegroundColor Yellow
    Write-Host "  This is the slow step -- 25-40 min on HDD, ~5 min on SSD." -ForegroundColor Yellow
    Write-Host "  It only needs to happen ONCE. Go grab a coffee." -ForegroundColor Yellow
    Write-Host "  ============================================" -ForegroundColor Yellow
    Write-Host ""

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    docker build -f (Join-Path $RepoDir "Dockerfile.base") -t markflow-base:latest $RepoDir
    $stopwatch.Stop()
    $elapsed = $stopwatch.Elapsed.ToString("mm\:ss")

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] Base image build failed. Check the output above." -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Write-Host "  [OK] Base image built in $elapsed" -ForegroundColor Green
}
else {
    $baseInfo = docker images markflow-base:latest --format "{{.CreatedSince}} ({{.Size}})" 2>$null
    Write-Host "  [OK] Base image already exists: $baseInfo" -ForegroundColor Green
}

# ===========================================================================
#  Build and start
# ===========================================================================
Write-Host ""
Write-Host "[6/6] Building and starting MarkFlow..." -ForegroundColor Yellow

docker compose @composeArgs up -d --build

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
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

docker compose @composeArgs ps

Write-Host ""
Write-Host "  MarkFlow UI:  http://localhost:8000" -ForegroundColor White
Write-Host "  Meilisearch:  http://localhost:7700" -ForegroundColor White
Write-Host "  MCP Server:   http://localhost:8001" -ForegroundColor White
Write-Host "  API Docs:     http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
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
Write-Host ""
Write-Host "  Source: $SourceDir"
Write-Host "  Output: $OutputDir"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Open http://localhost:8000 in your browser"
Write-Host "    2. Drop a file to test single-file conversion"
Write-Host "    3. Go to /bulk.html to run a bulk scan + conversion"
Write-Host "    4. Use .\refresh-markflow.ps1 to pull updates later"
Write-Host "==========================================" -ForegroundColor Cyan

Pop-Location
