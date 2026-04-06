<#
.SYNOPSIS
    MarkFlow Branch Switcher — fetches all branches and lets you pick one.

.DESCRIPTION
    Fetches all branches from origin, displays an interactive numbered menu,
    and checks out the selected branch with a clean pull. Optionally rebuilds
    and restarts Docker containers.

.EXAMPLE
    .\switch-branch.ps1                       # interactive menu
    .\switch-branch.ps1 -Build                # switch + rebuild + restart
    .\switch-branch.ps1 -NoBuild              # switch + restart only
    .\switch-branch.ps1 -RepoDir "D:\repos\markflow"
#>

param(
    [string]$RepoDir = "C:\Users\Xerxes\Projects\Doc-Conversion-2026",
    [switch]$Build,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MarkFlow Branch Switcher"                -ForegroundColor Cyan
Write-Host "  Machine: Work (Windows)"                 -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

Set-Location $RepoDir

# ──────────────────────────────────────────────────────────────
#  1. Fetch latest
# ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[1/3] Fetching branches from origin..." -ForegroundColor Yellow
git fetch --all --prune
Write-Host "  [OK] Remote refs updated" -ForegroundColor Green

# Show current branch
$currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
$currentCommit = (git log -1 --format="%h %s").Trim()
Write-Host ""
Write-Host "  Current branch: $currentBranch" -ForegroundColor Magenta
Write-Host "  Latest commit:  $currentCommit" -ForegroundColor DarkGray

# ──────────────────────────────────────────────────────────────
#  2. Build branch list
# ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/3] Available branches:" -ForegroundColor Yellow
Write-Host ""

$rawBranches = git branch -a --no-color 2>&1 | ForEach-Object { $_.Trim() }

$branches = @()
foreach ($line in $rawBranches) {
    if ($line -match "HEAD") { continue }
    $name = $line -replace "^\*\s+", "" -replace "^remotes/origin/", ""
    if ($name -and $branches -notcontains $name) {
        $branches += $name
    }
}
$branches = $branches | Sort-Object

if ($branches.Count -eq 0) {
    Write-Host "  No branches found!" -ForegroundColor Red
    exit 1
}

for ($i = 0; $i -lt $branches.Count; $i++) {
    $num = $i + 1
    $branch = $branches[$i]
    if ($branch -eq $currentBranch) {
        Write-Host ("  {0,3}) {1}  <- current" -f $num, $branch) -ForegroundColor Green
    }
    else {
        Write-Host ("  {0,3}) {1}" -f $num, $branch)
    }
}

Write-Host ""
Write-Host "  Enter branch number, branch name, or 'q' to quit" -ForegroundColor DarkGray
Write-Host ""
$selection = Read-Host "  Select branch"

if (-not $selection -or $selection -eq "q" -or $selection -eq "Q") {
    Write-Host "  Cancelled." -ForegroundColor DarkGray
    exit 0
}

# Resolve selection
$targetBranch = $null
if ($selection -match "^\d+$") {
    $idx = [int]$selection - 1
    if ($idx -ge 0 -and $idx -lt $branches.Count) {
        $targetBranch = $branches[$idx]
    }
    else {
        Write-Host "  Invalid selection: $selection" -ForegroundColor Red
        exit 1
    }
}
else {
    if ($branches -contains $selection) {
        $targetBranch = $selection
    }
    else {
        Write-Host "  Branch not found: $selection" -ForegroundColor Red
        exit 1
    }
}

# ──────────────────────────────────────────────────────────────
#  3. Switch to branch
# ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/3] Switching to branch: $targetBranch" -ForegroundColor Yellow

if ($targetBranch -eq $currentBranch) {
    Write-Host "  Already on $targetBranch — pulling latest..." -ForegroundColor DarkGray
    git pull origin $targetBranch
}
else {
    # Check for uncommitted changes
    $statusOut = git status --porcelain 2>&1
    if ($statusOut) {
        Write-Host "  [!] You have uncommitted changes." -ForegroundColor Yellow
        Write-Host ""
        git status --short
        Write-Host ""
        $stashChoice = Read-Host "  Stash changes and continue? (Y/n)"
        if ($stashChoice -match "^[Nn]") {
            Write-Host "  Cancelled. Commit or stash your changes first." -ForegroundColor DarkGray
            exit 0
        }
        git stash push -m "auto-stash before switching to $targetBranch"
        Write-Host "  [OK] Changes stashed" -ForegroundColor Green
    }

    # Checkout (create tracking branch if needed)
    $localExists = git show-ref --verify "refs/heads/$targetBranch" 2>&1
    if ($LASTEXITCODE -eq 0) {
        git checkout $targetBranch
    }
    else {
        git checkout -b $targetBranch "origin/$targetBranch"
    }

    git pull origin $targetBranch
}

$newCommit = (git log -1 --format="%h %s").Trim()
Write-Host "  [OK] Now on: $targetBranch" -ForegroundColor Green
Write-Host "  [OK] Latest: $newCommit" -ForegroundColor Green

# ──────────────────────────────────────────────────────────────
#  Optional: Rebuild + restart
# ──────────────────────────────────────────────────────────────
$composeArgs = @("-f", (Join-Path $RepoDir "docker-compose.yml"))

$gpuFile = Join-Path $RepoDir "docker-compose.gpu.yml"
if ((Test-Path $gpuFile) -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    $composeArgs += @("-f", $gpuFile)
}

$doBuild = "skip"
if ($Build) { $doBuild = "yes" }
elseif ($NoBuild) { $doBuild = "no" }
else {
    Write-Host ""
    Write-Host "  Would you like to rebuild and restart Docker containers?" -ForegroundColor Cyan
    Write-Host "    1) Yes - rebuild + restart"
    Write-Host "    2) Restart only (no rebuild)"
    Write-Host "    3) No - just switch branch"
    Write-Host ""
    $buildChoice = Read-Host "  Choice [3]"
    switch ($buildChoice) {
        "1" { $doBuild = "yes" }
        "2" { $doBuild = "no" }
        default { $doBuild = "skip" }
    }
}

if ($doBuild -eq "yes") {
    Write-Host ""
    Write-Host "  Rebuilding Docker images..." -ForegroundColor Yellow
    docker compose @composeArgs build
    Write-Host "  [OK] Build complete" -ForegroundColor Green
    Write-Host "  Restarting containers..." -ForegroundColor Yellow
    docker compose @composeArgs up -d
    Write-Host "  [OK] Containers restarted" -ForegroundColor Green
}
elseif ($doBuild -eq "no") {
    Write-Host ""
    Write-Host "  Restarting containers (no rebuild)..." -ForegroundColor Yellow
    docker compose @composeArgs up -d
    Write-Host "  [OK] Containers restarted" -ForegroundColor Green
}

# ──────────────────────────────────────────────────────────────
#  Done
# ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Branch Switch Complete!"                 -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Branch:  $targetBranch"
Write-Host "  Commit:  $newCommit"
if ($doBuild -ne "skip") {
    Write-Host "  MarkFlow UI:  http://localhost:8000"
}
Write-Host "==========================================" -ForegroundColor Cyan
