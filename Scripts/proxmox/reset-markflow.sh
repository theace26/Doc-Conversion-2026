#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  MarkFlow Docker Reset & Patch Script
#  Tears down everything, pulls latest, patches docker-compose
#  for the Proxmox VM environment, rebuilds from scratch.
#
#  Usage:  chmod +x ~/reset-markflow.sh && ~/reset-markflow.sh
# ============================================================

REPO_DIR="/opt/markflow"
COMPOSE_FILE="$REPO_DIR/docker-compose.yml"

echo "=========================================="
echo "  MarkFlow Docker Reset & Rebuild"
echo "=========================================="

# ----------------------------------------------------------
#  1. Tear down everything
# ----------------------------------------------------------
echo ""
echo "[1/5] Tearing down containers, volumes, and images..."
cd "$REPO_DIR"

docker compose down -v 2>/dev/null || true
docker system prune -f --volumes
# Remove app images but preserve the base image
docker images "markflow-*" --format "{{.Repository}}:{{.Tag}}" \
    | grep -v "markflow-base:latest" \
    | xargs -r docker rmi 2>/dev/null || true

# Build base image if missing
if ! docker images markflow-base:latest -q | grep -q .; then
    echo ""
    echo "  [!] markflow-base:latest not found -- building it now..."
    echo "  (This is the slow step -- only needed once)"
    docker build -f "$REPO_DIR/Dockerfile.base" -t markflow-base:latest "$REPO_DIR"
fi

# ----------------------------------------------------------
#  2. Pull latest code
# ----------------------------------------------------------
echo ""
echo "[2/5] Pulling latest code from GitHub..."

# Discard any local docker-compose changes (we'll re-patch)
git checkout -- docker-compose.yml 2>/dev/null || true
git pull

# ----------------------------------------------------------
#  3. Patch docker-compose.yml for Linux/NAS mounts
# ----------------------------------------------------------
echo ""
echo "[3/5] Patching docker-compose.yml for Proxmox VM..."

# Replace Windows source mount with NAS source mount
sed -i 's|C:/Users/Xerxes/T86_Work/k_drv_test:/mnt/source:ro|/mnt/source-share:/mnt/source:ro|' "$COMPOSE_FILE"

# Replace Windows output mount with NAS output mount
sed -i 's|D:/Doc-Conv_Test:/mnt/output-repo|/mnt/markflow-output:/mnt/output-repo|g' "$COMPOSE_FILE"

# Remove Windows drive browser mounts (C:/ and D:/)
sed -i '/C:\/:/d' "$COMPOSE_FILE"
sed -i '/D:\/:/d' "$COMPOSE_FILE"

# Remove old MOUNTED_DRIVES line
sed -i '/MOUNTED_DRIVES/d' "$COMPOSE_FILE"

# Add NAS drive browser mounts after the hashcat-queue line
sed -i '/hashcat-queue/a\      - /mnt/source-share:/host/source:ro                   # Drive browser — NAS source docs\n      - /mnt/markflow-output:/host/output:ro               # Drive browser — NAS converted output' "$COMPOSE_FILE"

# Add MOUNTED_DRIVES env var after SECRET_KEY
sed -i '/SECRET_KEY.*dev-secret/a\      - MOUNTED_DRIVES=source,output' "$COMPOSE_FILE"

# Set developer logging by default on test VM
if ! grep -q 'DEFAULT_LOG_LEVEL' "$COMPOSE_FILE"; then
    sed -i '/MOUNTED_DRIVES/a\      DEFAULT_LOG_LEVEL: developer' "$COMPOSE_FILE"
fi

echo "  ✅ docker-compose.yml patched"

# ----------------------------------------------------------
#  4. Verify the patch
# ----------------------------------------------------------
echo ""
echo "[4/5] Verifying patch — mount lines:"
grep -n "mnt\|host\|MOUNTED\|DEFAULT_LOG" "$COMPOSE_FILE" || true

# Check for any remaining Windows paths
if grep -q "C:/" "$COMPOSE_FILE" || grep -q "D:/" "$COMPOSE_FILE"; then
    echo "  ⚠️  WARNING: Windows paths still found in docker-compose.yml!"
    grep -n "C:/" "$COMPOSE_FILE" 2>/dev/null || true
    grep -n "D:/" "$COMPOSE_FILE" 2>/dev/null || true
else
    echo "  ✅ No Windows paths remaining"
fi

# ----------------------------------------------------------
#  5. Rebuild and start
# ----------------------------------------------------------
echo ""
echo "[5/5] Building and starting MarkFlow..."
docker compose up -d --build

echo ""
echo "=========================================="
echo "  Reset Complete!"
echo "=========================================="
echo ""
docker compose ps
echo ""
echo "  MarkFlow UI:  http://192.168.1.208:8000"
echo "  Meilisearch:  http://192.168.1.208:7700"
echo "  MCP Server:   http://192.168.1.208:8001"
echo "=========================================="
