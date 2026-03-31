#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  MarkFlow VM Setup Script
#  Run this inside a fresh Ubuntu 24.04 VM on Proxmox
#
#  Usage:  chmod +x ~/setup-markflow.sh && ~/setup-markflow.sh
# ============================================================

echo "=========================================="
echo "  MarkFlow VM Setup"
echo "=========================================="

# ----------------------------------------------------------
#  1. System updates and base packages
# ----------------------------------------------------------
echo ""
echo "[1/6] Updating system and installing base packages..."
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    git \
    cifs-utils \
    qemu-guest-agent \
    htop \
    jq

# Enable guest agent so Proxmox can see IP and manage shutdowns
sudo systemctl enable --now qemu-guest-agent || echo "  ⚠️  Guest agent failed to start (non-fatal, continuing)"

# ----------------------------------------------------------
#  2. Install Docker (official method)
# ----------------------------------------------------------
echo ""
echo "[2/6] Installing Docker..."

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add current user to docker group (takes effect on next login)
sudo usermod -aG docker "$USER"

echo "  ✅ Docker installed"

# ----------------------------------------------------------
#  3. Create directory structure and mount points
# ----------------------------------------------------------
echo ""
echo "[3/6] Creating directories and mount points..."

sudo mkdir -p /mnt/source-share
sudo mkdir -p /mnt/markflow-output
sudo mkdir -p /opt/markflow-output

echo "  ✅ Directories created"

# ----------------------------------------------------------
#  4. Set up SMB/CIFS mounts for NAS
# ----------------------------------------------------------
echo ""
echo "[4/6] Configuring NAS mounts..."

# Create credentials file
CREDS_FILE="/etc/markflow-smb-credentials"
if [ ! -f "$CREDS_FILE" ]; then
    sudo tee "$CREDS_FILE" > /dev/null << 'CREDS'
username=markflow
password=computer
CREDS
    sudo chmod 600 "$CREDS_FILE"
    echo "  ✅ Credentials file created at $CREDS_FILE"
else
    echo "  Credentials file already exists — skipping"
fi

# Add fstab entries for NAS shares
FSTAB_SOURCE="//192.168.1.17/storage_folder  /mnt/source-share    cifs  credentials=$CREDS_FILE,ro,iocharset=utf8,uid=1000,gid=1000,noperm  0  0"
FSTAB_OUTPUT="//192.168.1.17/markflow         /mnt/markflow-output cifs  credentials=$CREDS_FILE,rw,iocharset=utf8,uid=1000,gid=1000,noperm  0  0"

if ! grep -q "source-share" /etc/fstab; then
    echo "$FSTAB_SOURCE" | sudo tee -a /etc/fstab > /dev/null
    echo "$FSTAB_OUTPUT" | sudo tee -a /etc/fstab > /dev/null
    echo "  ✅ fstab entries added"
else
    echo "  fstab entries already exist — skipping"
fi

# Try mounting
sudo mount -a && echo "  ✅ Mounts successful" || echo "  ⚠️  mount -a failed — check credentials and NAS availability"

# ----------------------------------------------------------
#  5. Clone the MarkFlow repository
# ----------------------------------------------------------
echo ""
echo "[5/6] Cloning MarkFlow repository..."

REPO_DIR="/opt/markflow"

if [ ! -d "$REPO_DIR" ]; then
    sudo git clone https://github.com/theace26/Doc-Conversion-2026.git "$REPO_DIR"
    sudo chown -R "$USER":"$USER" "$REPO_DIR"
else
    echo "  Repo already exists at $REPO_DIR — pulling latest..."
    cd "$REPO_DIR"
    git pull
fi

# ----------------------------------------------------------
#  6. Create .env file from template
# ----------------------------------------------------------
echo ""
echo "[6/6] Creating environment configuration..."

ENV_FILE="$REPO_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'ENV_CONTENT'
# MarkFlow Environment Configuration
# Proxmox VM test environment

# Paths — these map into the Docker containers
SOURCE_DIR=/mnt/source-share
OUTPUT_DIR=/opt/markflow-output

# Meilisearch
MEILI_MASTER_KEY=markflow-test-key-change-in-production

# MinIO (S3-compatible object storage)
MINIO_ROOT_USER=markflow
MINIO_ROOT_PASSWORD=markflow-test-password

# MarkFlow app
SECRET_KEY=change-me-in-production-use-openssl-rand-hex-32
LOG_LEVEL=INFO
ENV_CONTENT
    echo "  ✅ Created $ENV_FILE"
else
    echo "  .env already exists — skipping"
fi

# ----------------------------------------------------------
#  Done!
# ----------------------------------------------------------
echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "  NEXT STEPS:"
echo ""
echo "  1. LOG OUT AND BACK IN (so docker group takes effect):"
echo "     exit"
echo "     ssh $USER@$(hostname -I | awk '{print $1}')"
echo ""
echo "  2. Build the base image (slow, only needed once ~25 min HDD / ~5 min SSD):"
echo "     cd /opt/markflow"
echo "     docker build -f Dockerfile.base -t markflow-base:latest ."
echo ""
echo "  3. First run (full reset + rebuild):"
echo "     ~/reset-markflow.sh"
echo ""
echo "  4. Later updates (quick refresh, keeps data):"
echo "     ~/refresh-markflow.sh"
echo ""
echo "  5. Check it's running:"
echo "     docker compose ps"
echo "     curl http://localhost:8000/api/health"
echo ""
echo "  MarkFlow UI:  http://$(hostname -I | awk '{print $1}'):8000"
echo "  Meilisearch:  http://$(hostname -I | awk '{print $1}'):7700"
echo "  MCP Server:   http://$(hostname -I | awk '{print $1}'):8001"
echo "=========================================="
