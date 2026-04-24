# Storage

The **Storage** page is where you configure every location MarkFlow reads from or writes to:

- **Quick Access** — one-click tiles for common locations (home folder, drive letters, external drives)
- **Sources** — folders MarkFlow scans for files to convert
- **Output Directory** — where converted Markdown and sidecars are written
- **Network Shares** — mount SMB/CIFS or NFS shares at `/mnt/shares/<name>`
- **Folder Exclusions** — path prefixes to skip during scanning

Open it from the sidebar or visit `/storage.html` directly.

---

## First-time setup

The first time you log in as a MANAGER or ADMIN, a short wizard walks you through:

1. **Pick a source folder** — where your documents live
2. **Pick an output folder** — where converted Markdown should go
3. **(Optional) Add a network share** — skip if everything is local

You can re-open the wizard anytime by clicking **Setup Wizard** in the page header.

---

## Changing the source or output directory

Use the **Sources** section to add or remove source folders. Each source is validated when you add it — MarkFlow checks that it exists, is readable, and has at least one file (you'll get a warning but not an error if the folder is empty). After clicking **Add**, a green **✓** pill appears below the form showing the path MarkFlow actually sees plus the item count, so you can confirm at a glance that the folder is the right one and is accessible.

Use the **Output Directory** section to set where converted files go. Output is validated for:

- Existence and readability
- Writability (the MarkFlow process needs write permission)
- At least 1 GB of free disk space (warning only; not a hard failure)

After clicking **Save**, a green **✓** pill appears below the path input showing the path MarkFlow sees, "Writable", and a free-space summary. On page load, the currently-saved output path is re-validated and shown the same way — if a share was unmounted or permissions changed, you'll see a red **✗** with the specific reason.

**Changing the output directory requires a restart** to fully take effect. MarkFlow posts an amber banner at the top of every page reminding you. Click **Remind me later** to hide it for 1 hour, or restart the container (`docker-compose restart markflow`) to clear it immediately.

---

## Adding a network share

Click **Add Share** in the Network Shares section and fill in:

- **Name** — alphanumeric + dashes + underscores; becomes the folder under `/mnt/shares/`
- **Protocol** — `smb` (SMB/CIFS), `nfsv3`, or `nfsv4`
- **Server** — IP or hostname
- **Share path** — the share name on the server (SMB) or export path (NFS)
- **Username / password** — SMB only; NFS uses host-level trust

Credentials are encrypted at rest (Fernet + PBKDF2) in `/etc/markflow/credentials.enc`. Only ADMIN users can read clear-text passwords back.

### Discovering shares automatically

- **Scan my network** — probe a CIDR subnet (e.g. `192.168.1.0/24`) for SMB servers. Caps at 256 hosts to protect large networks.
- **Probe server** — given a server IP, list its SMB shares (via `smbclient -L`) or NFS exports (via `showmount -e`).

Discovery is always user-initiated — MarkFlow never auto-scans.

---

## Troubleshooting

### "Restart required" banner won't go away

The banner appears whenever the output directory changes after startup. Restart the container:

```bash
docker-compose restart markflow
```

### A network share shows a red status dot

The mount-health probe runs every 5 minutes and tries a `listdir` on each share. If the probe fails, you'll see a red dot with the error in the tooltip. Common causes:

- Share server is down or unreachable — check network / VPN
- Credentials rotated on the server — re-enter via **Edit**
- SMB signing mismatch — try `nfsv3` or ensure your server supports modern SMB

### "write denied — outside output dir" errors in logs

MarkFlow refuses to write anywhere outside the configured output directory. If you see this error:

- Check that **Output Directory** is set in the Storage page
- Check that the configured path still exists and is writable
- If you rotated the `SECRET_KEY` env var, the credential store can no longer decrypt saved passwords — re-enter them via **Edit Share** and restart

### Mount worked before, broke after upgrade

Check `docker-compose logs markflow | grep storage_remount` on startup. If you see `credential_store_load_failed`, the encrypted credential file can't be read with the current `SECRET_KEY`. Either restore the previous key or re-enter each share's password.

---

## Security notes

MarkFlow's container uses a **broad host mount** (`/host/rw`) so you can point Output anywhere on the host. The **only** restriction on this mount is the application-level write guard. If you're running in a shared environment, keep `SECRET_KEY` secret — leaking it compromises every saved network-share credential.
