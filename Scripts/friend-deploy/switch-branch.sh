#!/usr/bin/env bash
#
# MarkFlow Branch Switcher (Friend Deploy)
#
# Fetches all branches from origin, presents an interactive menu,
# and checks out the selected branch with a clean pull.
#
# Usage:
#   ./switch-branch.sh                  # auto-detects repo
#   ./switch-branch.sh --repo /path     # custom repo location
#   ./switch-branch.sh --no-build       # switch + restart without rebuild
#   ./switch-branch.sh --build          # switch + rebuild + restart

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
DO_BUILD=""

# ── Parse args ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)      REPO_DIR="$2"; shift 2 ;;
        --no-build)  DO_BUILD="no"; shift ;;
        --build)     DO_BUILD="yes"; shift ;;
        *)           echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "=========================================="
echo "  MarkFlow Branch Switcher"
echo "  Machine: Friend Deploy"
echo "=========================================="

cd "$REPO_DIR"

# ── 1. Fetch latest ────────────────────────────────────────────
echo ""
echo "[1/3] Fetching branches from origin..."
git fetch --all --prune
echo "  [OK] Remote refs updated"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git log -1 --format="%h %s")
echo ""
echo "  Current branch: $CURRENT_BRANCH"
echo "  Latest commit:  $CURRENT_COMMIT"

# ── 2. Build branch list ──────────────────────────────────────
echo ""
echo "[2/3] Available branches:"
echo ""

BRANCHES=()
while IFS= read -r branch; do
    [[ "$branch" == *"HEAD"* ]] && continue
    branch="${branch#"${branch%%[![:space:]]*}"}"
    branch="${branch#remotes/origin/}"
    branch="${branch#\* }"
    BRANCHES+=("$branch")
done < <(git branch -a --no-color 2>/dev/null)

BRANCHES=($(printf '%s\n' "${BRANCHES[@]}" | sort -u))

if [[ ${#BRANCHES[@]} -eq 0 ]]; then
    echo "  No branches found!"
    exit 1
fi

for i in "${!BRANCHES[@]}"; do
    NUM=$((i + 1))
    BRANCH="${BRANCHES[$i]}"
    if [[ "$BRANCH" == "$CURRENT_BRANCH" ]]; then
        printf "  %3d) %s  <- current\n" "$NUM" "$BRANCH"
    else
        printf "  %3d) %s\n" "$NUM" "$BRANCH"
    fi
done

echo ""
echo "  Enter branch number, branch name, or 'q' to quit"
echo ""
read -rp "  Select branch: " SELECTION

if [[ "$SELECTION" == "q" || "$SELECTION" == "Q" || -z "$SELECTION" ]]; then
    echo "  Cancelled."
    exit 0
fi

TARGET_BRANCH=""
if [[ "$SELECTION" =~ ^[0-9]+$ ]]; then
    IDX=$((SELECTION - 1))
    if [[ $IDX -ge 0 && $IDX -lt ${#BRANCHES[@]} ]]; then
        TARGET_BRANCH="${BRANCHES[$IDX]}"
    else
        echo "  Invalid selection: $SELECTION"
        exit 1
    fi
else
    for b in "${BRANCHES[@]}"; do
        if [[ "$b" == "$SELECTION" ]]; then
            TARGET_BRANCH="$b"
            break
        fi
    done
    if [[ -z "$TARGET_BRANCH" ]]; then
        echo "  Branch not found: $SELECTION"
        exit 1
    fi
fi

# ── 3. Switch to branch ──────────────────────────────────────
echo ""
echo "[3/3] Switching to branch: $TARGET_BRANCH"

if [[ "$TARGET_BRANCH" == "$CURRENT_BRANCH" ]]; then
    echo "  Already on $TARGET_BRANCH — pulling latest..."
    git pull origin "$TARGET_BRANCH"
else
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "  [!] You have uncommitted changes."
        echo ""
        git status --short
        echo ""
        read -rp "  Stash changes and continue? (Y/n): " STASH_CHOICE
        if [[ "$STASH_CHOICE" =~ ^[Nn] ]]; then
            echo "  Cancelled. Commit or stash your changes first."
            exit 0
        fi
        git stash push -m "auto-stash before switching to $TARGET_BRANCH"
        echo "  [OK] Changes stashed"
    fi

    if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH" 2>/dev/null; then
        git checkout "$TARGET_BRANCH"
    else
        git checkout -b "$TARGET_BRANCH" "origin/$TARGET_BRANCH"
    fi

    git pull origin "$TARGET_BRANCH"
fi

NEW_COMMIT=$(git log -1 --format="%h %s")
echo "  [OK] Now on: $TARGET_BRANCH"
echo "  [OK] Latest: $NEW_COMMIT"

# ── Optional: Rebuild + restart ───────────────────────────────
COMPOSE_ARGS=("-f" "$REPO_DIR/docker-compose.yml")

if [[ -z "$DO_BUILD" ]]; then
    echo ""
    echo "  Would you like to rebuild and restart Docker containers?"
    echo "    1) Yes — rebuild + restart"
    echo "    2) Restart only (no rebuild)"
    echo "    3) No — just switch branch"
    echo ""
    read -rp "  Choice [3]: " BUILD_CHOICE
    case "${BUILD_CHOICE:-3}" in
        1) DO_BUILD="yes" ;;
        2) DO_BUILD="no" ;;
        *) DO_BUILD="skip" ;;
    esac
fi

if [[ "$DO_BUILD" == "yes" ]]; then
    echo ""
    echo "  Rebuilding Docker images..."

    BASE_EXISTS=$(docker images markflow-base:latest --format "{{.ID}}" 2>/dev/null || true)
    if [[ -z "$BASE_EXISTS" ]]; then
        echo "  [!] Base image missing — building it first..."
        docker build -f Dockerfile.base -t markflow-base:latest .
    fi

    docker compose "${COMPOSE_ARGS[@]}" build
    echo "  [OK] Build complete"
    echo "  Restarting containers..."
    docker compose "${COMPOSE_ARGS[@]}" up -d
    echo "  [OK] Containers restarted"
elif [[ "$DO_BUILD" == "no" ]]; then
    echo ""
    echo "  Restarting containers (no rebuild)..."
    docker compose "${COMPOSE_ARGS[@]}" up -d
    echo "  [OK] Containers restarted"
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  Branch Switch Complete!"
echo "=========================================="
echo ""
echo "  Branch:  $TARGET_BRANCH"
echo "  Commit:  $NEW_COMMIT"
if [[ "$DO_BUILD" != "skip" ]]; then
    echo "  MarkFlow UI:  http://localhost:8000"
fi
echo "=========================================="
