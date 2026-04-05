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
#  4. Set up NAS mounts (SMB or NFS)
# ----------------------------------------------------------
echo ""
echo "[4/6] Configuring NAS mounts..."

# --- Protocol selection helper ---
generate_fstab_entry() {
    local proto_choice="$1" server="$2" share="$3" mount_point="$4" rw_flag="$5" krb="$6"
    local systemd_opts="_netdev,x-systemd.automount,x-systemd.mount-timeout=30"

    case "$proto_choice" in
        2) echo "${server}:${share}  ${mount_point}  nfs  ${rw_flag},hard,intr,${systemd_opts}  0  0" ;;
        3)
            local opts="${rw_flag},hard,intr,${systemd_opts}"
            [ "$krb" = "true" ] && opts="${opts},sec=krb5"
            echo "${server}:${share}  ${mount_point}  nfs4  ${opts}  0  0"
            ;;
        *) echo "//${server}/${share}  ${mount_point}  cifs  credentials=${CREDS_FILE},${rw_flag},iocharset=utf8,uid=1000,gid=1000,noperm,${systemd_opts}  0  0" ;;
    esac
}

echo ""
echo "Select mount protocol for SOURCE share:"
echo "  1) SMB/CIFS (Windows/Samba shares)"
echo "  2) NFSv3 (Linux NFS exports)"
echo "  3) NFSv4 (Linux NFS v4 exports)"
read -p "Choice [1]: " SRC_PROTO_CHOICE
SRC_PROTO_CHOICE="${SRC_PROTO_CHOICE:-1}"

echo ""
echo "Select mount protocol for OUTPUT share:"
echo "  1) SMB/CIFS (Windows/Samba shares)"
echo "  2) NFSv3 (Linux NFS exports)"
echo "  3) NFSv4 (Linux NFS v4 exports)"
read -p "Choice [1]: " OUT_PROTO_CHOICE
OUT_PROTO_CHOICE="${OUT_PROTO_CHOICE:-1}"

# Install NFS packages if needed
if [ "$SRC_PROTO_CHOICE" != "1" ] || [ "$OUT_PROTO_CHOICE" != "1" ]; then
    echo "  Installing NFS client packages..."
    sudo apt-get install -y nfs-common
fi

# --- Source share ---
echo ""
echo "--- Source share (read-only) ---"
read -p "Server IP/hostname [192.168.1.17]: " SRC_SERVER
SRC_SERVER="${SRC_SERVER:-192.168.1.17}"

if [ "$SRC_PROTO_CHOICE" = "1" ]; then
    read -p "SMB share name [storage_folder]: " SRC_SHARE
    SRC_SHARE="${SRC_SHARE:-storage_folder}"
else
    read -p "NFS export path [/volume1/storage]: " SRC_SHARE
    SRC_SHARE="${SRC_SHARE:-/volume1/storage}"
fi

SRC_KRB="false"
if [ "$SRC_PROTO_CHOICE" = "3" ]; then
    read -p "Enable Kerberos for source? [y/N]: " KRB_ENABLE
    if [ "$KRB_ENABLE" = "y" ] || [ "$KRB_ENABLE" = "Y" ]; then
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y krb5-user
        SRC_KRB="true"
    fi
fi

# --- Output share ---
echo ""
echo "--- Output share (read-write) ---"
read -p "Server IP/hostname [${SRC_SERVER}]: " OUT_SERVER
OUT_SERVER="${OUT_SERVER:-$SRC_SERVER}"

if [ "$OUT_PROTO_CHOICE" = "1" ]; then
    read -p "SMB share name [markflow]: " OUT_SHARE
    OUT_SHARE="${OUT_SHARE:-markflow}"
else
    read -p "NFS export path [/volume1/markflow]: " OUT_SHARE
    OUT_SHARE="${OUT_SHARE:-/volume1/markflow}"
fi

OUT_KRB="false"
if [ "$OUT_PROTO_CHOICE" = "3" ]; then
    read -p "Enable Kerberos for output? [y/N]: " KRB_ENABLE
    if [ "$KRB_ENABLE" = "y" ] || [ "$KRB_ENABLE" = "Y" ]; then
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y krb5-user
        OUT_KRB="true"
    fi
fi

# SMB credentials file (only needed if either share uses SMB)
CREDS_FILE="/etc/markflow-smb-credentials"
if [ "$SRC_PROTO_CHOICE" = "1" ] || [ "$OUT_PROTO_CHOICE" = "1" ]; then
    if [ ! -f "$CREDS_FILE" ]; then
        read -p "SMB username [markflow]: " SMB_USER
        SMB_USER="${SMB_USER:-markflow}"
        read -sp "SMB password: " SMB_PASS
        echo ""
        SMB_PASS="${SMB_PASS:-computer}"
        sudo tee "$CREDS_FILE" > /dev/null << CREDS
username=${SMB_USER}
password=${SMB_PASS}
CREDS
        sudo chmod 600 "$CREDS_FILE"
        echo "  ✅ Credentials file created at $CREDS_FILE"
    else
        echo "  Credentials file already exists — skipping"
    fi
fi

# Generate and write fstab entries
FSTAB_SOURCE=$(generate_fstab_entry "$SRC_PROTO_CHOICE" "$SRC_SERVER" "$SRC_SHARE" "/mnt/source-share" "ro" "$SRC_KRB")
FSTAB_OUTPUT=$(generate_fstab_entry "$OUT_PROTO_CHOICE" "$OUT_SERVER" "$OUT_SHARE" "/mnt/markflow-output" "rw" "$OUT_KRB")

if ! grep -q "source-share" /etc/fstab; then
    echo "$FSTAB_SOURCE" | sudo tee -a /etc/fstab > /dev/null
    echo "$FSTAB_OUTPUT" | sudo tee -a /etc/fstab > /dev/null
    echo "  ✅ fstab entries added"
else
    echo "  fstab entries already exist — skipping"
fi

# Save mount config JSON for the Settings UI
PROTO_NAMES=("" "smb" "nfsv3" "nfsv4")
sudo mkdir -p /etc/markflow
sudo tee /etc/markflow/mounts.json > /dev/null << MOUNTJSON
{
  "source": {
    "protocol": "${PROTO_NAMES[$SRC_PROTO_CHOICE]}",
    "server": "${SRC_SERVER}",
    "share_path": "${SRC_SHARE}",
    "mount_point": "/mnt/source-share",
    "read_only": true,
    "nfs_kerberos": ${SRC_KRB}
  },
  "output": {
    "protocol": "${PROTO_NAMES[$OUT_PROTO_CHOICE]}",
    "server": "${OUT_SERVER}",
    "share_path": "${OUT_SHARE}",
    "mount_point": "/mnt/markflow-output",
    "read_only": false,
    "nfs_kerberos": ${OUT_KRB}
  }
}
MOUNTJSON
echo "  ✅ Mount config saved to /etc/markflow/mounts.json"

# Try mounting
sudo mount -a && echo "  ✅ Mounts successful" || echo "  ⚠️  mount -a failed — check credentials/exports and NAS availability"

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
# Proxmox VM (5 cores / 28GB RAM)

# Paths — these map into the Docker containers
SOURCE_DIR=/mnt/source-share
OUTPUT_DIR=/opt/markflow-output

# Meilisearch
MEILI_MASTER_KEY=f7b85048ef044c5e64c7e0dec03deebaef4c78e3327aaca89e9814ae4cb3d8c4

# Bulk conversion — 4 workers (reserve 1 core for OS + Meilisearch)
BULK_WORKER_COUNT=4

# MarkFlow app
SECRET_KEY=change-me-in-production-use-openssl-rand-hex-32
DEFAULT_LOG_LEVEL=normal
DEV_BYPASS_AUTH=true
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
