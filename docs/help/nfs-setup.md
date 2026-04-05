# Setting Up NFS Mounts in MarkFlow

MarkFlow supports three network mount protocols: **SMB/CIFS** (default),
**NFSv3**, and **NFSv4** (with optional Kerberos). This guide walks you
through switching from SMB to NFS.

---

## Prerequisites

1. Your NAS/server has NFS exports enabled
2. The MarkFlow VM's IP is in the NFS export allow-list
3. The export paths are accessible (test with `showmount -e <NAS_IP>`)

## Method 1: Settings UI (running system)

1. Open **Settings** at `http://<VM_IP>:8000/settings.html`
2. Scroll down to **Storage Connections**
3. For each mount (Source and Output):
   - Select **NFSv3** or **NFSv4** as the protocol
   - Enter the NAS server IP (e.g., `192.168.1.17`)
   - Enter the NFS export path (e.g., `/volume1/storage`)
   - For NFSv4 with Kerberos: check "Enable Kerberos", enter realm and keytab path
4. Click **Test Connection** to verify
5. Click **Apply & Remount** to switch live

> **Note:** You cannot remount while a bulk scan is running. Stop the scan
> first from the Admin page.

## Method 2: Setup Script (fresh install)

During initial VM provisioning, `setup-markflow.sh` now prompts:

```
Select mount protocol for SOURCE share:
  1) SMB/CIFS (Windows/Samba shares)
  2) NFSv3 (Linux NFS exports)
  3) NFSv4 (Linux NFS v4 exports)
Choice [1]:
```

Select `2` or `3`, then provide the server IP and export path when prompted.

## Method 3: Manual (command line)

### Step 1: Install NFS client tools

```bash
sudo apt-get install -y nfs-common
```

### Step 2: Verify the NFS export is visible

```bash
showmount -e 192.168.1.17
```

You should see your export paths listed. If not, check the NFS server
configuration (export list, IP allow-list).

### Step 3: Test mount manually

```bash
# NFSv3
sudo mount -t nfs -o ro,hard,intr 192.168.1.17:/volume1/storage /mnt/source-share

# NFSv4
sudo mount -t nfs4 -o ro,hard,intr 192.168.1.17:/volume1/storage /mnt/source-share

# NFSv4 with Kerberos
sudo mount -t nfs4 -o ro,hard,intr,sec=krb5 192.168.1.17:/volume1/storage /mnt/source-share
```

### Step 4: Verify files are accessible

```bash
ls /mnt/source-share
```

### Step 5: Make it permanent (fstab)

Edit `/etc/fstab` and replace the existing CIFS line with:

```
# NFSv3 example
192.168.1.17:/volume1/storage  /mnt/source-share  nfs  ro,hard,intr,_netdev,x-systemd.automount,x-systemd.mount-timeout=30  0  0

# NFSv4 example
192.168.1.17:/volume1/storage  /mnt/source-share  nfs4  ro,hard,intr,_netdev,x-systemd.automount,x-systemd.mount-timeout=30  0  0
```

Then apply:

```bash
sudo mount -a
```

### Step 6: Restart MarkFlow

```bash
~/refresh-markflow.sh
```

---

## NFS vs SMB: When to Use Which

| Factor | NFS | SMB/CIFS |
|--------|-----|----------|
| Linux NAS (TrueNAS, bare metal) | Preferred | Works |
| Windows NAS / Active Directory | Not available | Required |
| Synology / QNAP | Both supported | Both supported |
| Performance on Linux | Better (kernel-native) | Good (higher overhead) |
| Authentication | Host IP (v3) or Kerberos (v4) | Username/password |

## Troubleshooting

**"mount: wrong fs type, bad option, bad superblock"**
- Install NFS tools: `sudo apt-get install -y nfs-common`

**"mount.nfs: access denied by server"**
- Your VM's IP is not in the NFS export allow-list on the server
- Check with: `showmount -e <NAS_IP>`

**"mount.nfs: Connection timed out"**
- Firewall blocking NFS ports (TCP 2049 for NFSv4, TCP/UDP 111+2049 for NFSv3)
- NFS server not running

**Kerberos: "mount.nfs4: No such file or directory"**
- `krb5-user` not installed: `sudo apt-get install -y krb5-user`
- Keytab file missing or wrong path
- Kerberos realm not configured in `/etc/krb5.conf`

**Files visible but permission denied inside container**
- NFS UID/GID mismatch: the container runs as root (UID 0), but the NFS
  export may squash root. Set `no_root_squash` on the export, or map UIDs.
