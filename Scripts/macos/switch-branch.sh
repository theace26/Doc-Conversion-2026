#!/usr/bin/env bash
# --------------------------------------------------------------
# MarkFlow Branch Switcher (macOS - personal machine)
#
# Fetches all branches from origin, presents an interactive menu,
# and checks out the selected branch with a clean pull.
#
# Usage:
#   ./switch-branch.sh                    # auto-detects repo
#   ./switch-branch.sh --repo /my/path    # custom repo location
#   ./switch-branch.sh --no-build         # switch + restart without rebuild
#   ./switch-branch.sh --build            # switch + rebuild + restart
# --------------------------------------------------------------

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

# -- Defaults --
REPO_DIR=""
DO_BUILD=""

# -- Parse arguments --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)      REPO_DIR="$2"; shift 2 ;;
        --no-build)  DO_BUILD="no"; shift ;;
        --build)     DO_BUILD="yes"; shift ;;
        *)           echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

# ==============================================================
#  Locate the repository
# ==============================================================
if [[ -z "$REPO_DIR" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CANDIDATE="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd)"
    if [[ -f "$CANDIDATE/docker-compose.yml" ]]; then
        REPO_DIR="$CANDIDATE"
    else
        read -rp "  Enter the full path to the Doc-Conversion-2026 folder: " REPO_DIR
        if [[ ! -f "$REPO_DIR/docker-compose.yml" ]]; then
            echo -e "${RED}  [ERROR] docker-compose.yml not found at: $REPO_DIR${NC}"
            exit 1
        fi
    fi
fi

cd "$REPO_DIR"

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MarkFlow Branch Switcher${NC}"
echo -e "${CYAN}  Machine: macOS (personal)${NC}"
echo -e "${GRAY}  Repo: $REPO_DIR${NC}"
echo -e "${CYAN}==========================================${NC}"

# ==============================================================
#  Fetch latest from origin
# ==============================================================
echo ""
echo -e "${YELLOW}[1/3] Fetching branches from origin...${NC}"
git fetch --all --prune
echo -e "${GREEN}  [OK] Remote refs updated${NC}"

# ==============================================================
#  Show current branch
# ==============================================================
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git log -1 --format="%h %s")
echo ""
echo -e "${MAGENTA}  Current branch: ${BOLD}$CURRENT_BRANCH${NC}"
echo -e "${GRAY}  Latest commit:  $CURRENT_COMMIT${NC}"

# ==============================================================
#  Build branch list (local + remote, deduplicated)
# ==============================================================
echo ""
echo -e "${YELLOW}[2/3] Available branches:${NC}"
echo ""

# Collect all branch names, strip remotes/origin/ prefix, deduplicate, sort
BRANCHES=()
while IFS= read -r branch; do
    # Skip HEAD pointer
    [[ "$branch" == *"HEAD"* ]] && continue
    # Strip leading whitespace and remote prefix
    branch="${branch#"${branch%%[![:space:]]*}"}"
    branch="${branch#remotes/origin/}"
    branch="${branch#\* }"
    BRANCHES+=("$branch")
done < <(git branch -a --no-color 2>/dev/null)

# Deduplicate and sort
BRANCHES=($(printf '%s\n' "${BRANCHES[@]}" | sort -u))

if [[ ${#BRANCHES[@]} -eq 0 ]]; then
    echo -e "${RED}  No branches found!${NC}"
    exit 1
fi

# Display numbered list with current branch highlighted
for i in "${!BRANCHES[@]}"; do
    NUM=$((i + 1))
    BRANCH="${BRANCHES[$i]}"
    if [[ "$BRANCH" == "$CURRENT_BRANCH" ]]; then
        printf "  ${GREEN}${BOLD}%3d) %s  <- current${NC}\n" "$NUM" "$BRANCH"
    else
        printf "  %3d) %s\n" "$NUM" "$BRANCH"
    fi
done

echo ""
echo -e "${GRAY}  Enter branch number, branch name, or 'q' to quit${NC}"
echo ""
read -rp "  Select branch: " SELECTION

# Handle quit
if [[ "$SELECTION" == "q" || "$SELECTION" == "Q" || -z "$SELECTION" ]]; then
    echo -e "${GRAY}  Cancelled.${NC}"
    exit 0
fi

# Resolve selection to branch name
TARGET_BRANCH=""
if [[ "$SELECTION" =~ ^[0-9]+$ ]]; then
    # Numeric selection
    IDX=$((SELECTION - 1))
    if [[ $IDX -ge 0 && $IDX -lt ${#BRANCHES[@]} ]]; then
        TARGET_BRANCH="${BRANCHES[$IDX]}"
    else
        echo -e "${RED}  Invalid selection: $SELECTION${NC}"
        exit 1
    fi
else
    # Name selection -- check if it matches a known branch
    for b in "${BRANCHES[@]}"; do
        if [[ "$b" == "$SELECTION" ]]; then
            TARGET_BRANCH="$b"
            break
        fi
    done
    if [[ -z "$TARGET_BRANCH" ]]; then
        echo -e "${RED}  Branch not found: $SELECTION${NC}"
        exit 1
    fi
fi

# ==============================================================
#  Switch to selected branch
# ==============================================================
echo ""
echo -e "${YELLOW}[3/3] Switching to branch: ${BOLD}$TARGET_BRANCH${NC}"

if [[ "$TARGET_BRANCH" == "$CURRENT_BRANCH" ]]; then
    echo -e "${GRAY}  Already on $TARGET_BRANCH -- checking for updates...${NC}"
    # Local-only branches (never pushed, or remote was pruned) have no upstream
    # to pull from. Skip cleanly instead of erroring out.
    if git rev-parse --verify --quiet "refs/remotes/origin/$TARGET_BRANCH" >/dev/null; then
        git pull origin "$TARGET_BRANCH"
    else
        echo -e "${GRAY}  (local-only branch; skipping pull)${NC}"
    fi
else
    # Check for uncommitted changes
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo -e "${YELLOW}  [!] You have uncommitted changes.${NC}"
        echo ""
        git status --short
        echo ""
        read -rp "  Stash changes and continue? (Y/n): " STASH_CHOICE
        if [[ "$STASH_CHOICE" =~ ^[Nn] ]]; then
            echo -e "${GRAY}  Cancelled. Commit or stash your changes first.${NC}"
            exit 0
        fi
        git stash push -m "auto-stash before switching to $TARGET_BRANCH"
        echo -e "${GREEN}  [OK] Changes stashed${NC}"
    fi

    # Checkout (create tracking branch if it only exists on remote)
    if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH" 2>/dev/null; then
        git checkout "$TARGET_BRANCH"
    else
        git checkout -b "$TARGET_BRANCH" "origin/$TARGET_BRANCH"
    fi

    # Skip pull for local-only branches (never pushed, or remote was pruned).
    if git rev-parse --verify --quiet "refs/remotes/origin/$TARGET_BRANCH" >/dev/null; then
        git pull origin "$TARGET_BRANCH"
    else
        echo -e "${GRAY}  (local-only branch; skipping pull)${NC}"
    fi
fi

NEW_COMMIT=$(git log -1 --format="%h %s")
echo -e "${GREEN}  [OK] Now on: $TARGET_BRANCH${NC}"
echo -e "${GREEN}  [OK] Latest: $NEW_COMMIT${NC}"

# ==============================================================
#  Optional: Rebuild + restart containers
# ==============================================================
if [[ -z "$DO_BUILD" ]]; then
    echo ""
    echo -e "${CYAN}  Would you like to rebuild and restart Docker containers?${NC}"
    echo "    1) Yes -- rebuild + restart"
    echo "    2) Restart only (no rebuild)"
    echo "    3) No -- just switch branch"
    echo ""
    read -rp "  Choice [3]: " BUILD_CHOICE
    case "${BUILD_CHOICE:-3}" in
        1) DO_BUILD="yes" ;;
        2) DO_BUILD="no" ;;
        *) DO_BUILD="skip" ;;
    esac
fi

# docker-compose.override.yml is gitignored (per-machine by Docker
# convention). On macOS / Apple Silicon we seed it from the sample so
# docker-compose auto-merges it and the NVIDIA GPU deploy block gets
# zeroed out — otherwise `up` fails on hosts without nvidia-container-toolkit.
if [[ ! -f docker-compose.override.yml && -f docker-compose.apple-silicon.yml ]]; then
    echo -e "${YELLOW}  Seeding docker-compose.override.yml from docker-compose.apple-silicon.yml (Apple Silicon / no-GPU)${NC}"
    cp docker-compose.apple-silicon.yml docker-compose.override.yml
fi
# Leave COMPOSE_ARGS empty so the override auto-merges.
COMPOSE_ARGS=()

if [[ "$DO_BUILD" == "yes" ]]; then
    echo ""
    echo -e "${YELLOW}  Rebuilding Docker images...${NC}"

    BASE_EXISTS=$(docker images markflow-base:latest --format "{{.ID}}" 2>/dev/null || true)
    if [[ -z "$BASE_EXISTS" ]]; then
        echo -e "${YELLOW}  [!] Base image missing -- building it first...${NC}"
        docker build -f Dockerfile.base -t markflow-base:latest .
    fi

    docker compose "${COMPOSE_ARGS[@]}" build
    echo -e "${GREEN}  [OK] Build complete${NC}"
    echo -e "${YELLOW}  Restarting containers...${NC}"
    docker compose "${COMPOSE_ARGS[@]}" up -d
    echo -e "${GREEN}  [OK] Containers restarted${NC}"
elif [[ "$DO_BUILD" == "no" ]]; then
    echo ""
    echo -e "${YELLOW}  Restarting containers (no rebuild)...${NC}"
    docker compose "${COMPOSE_ARGS[@]}" up -d
    echo -e "${GREEN}  [OK] Containers restarted${NC}"
fi

# ==============================================================
#  Done
# ==============================================================
echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${GREEN}  Branch Switch Complete!${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""
echo -e "  Branch:  ${BOLD}$TARGET_BRANCH${NC}"
echo -e "  Commit:  $NEW_COMMIT"
if [[ "$DO_BUILD" != "skip" ]]; then
    echo "  MarkFlow UI:  http://localhost:8000"
fi
echo -e "${CYAN}==========================================${NC}"
