/**
 * MarkFlow — DB backup/restore shared UI module.
 *
 * Exposes:
 *   window.openBackupModal()
 *   window.openRestoreModal()
 *
 * Modals are built via DOM APIs (no innerHTML with user data) and injected on
 * first use. API endpoints return 409 when bulk jobs are active — surfaced as a
 * friendly warning.
 */
(function () {
  'use strict';

  let modalsInjected = false;
  let selectedFile = null;
  // Per-modal Esc handlers + opener references so focus can be restored on close.
  const modalState = {
    backup: { escHandler: null, opener: null },
    restore: { escHandler: null, opener: null },
  };

  // Accepted restore file extensions. Keep in sync with the file input's
  // `accept` attribute (which is only a picker hint — drag-drop bypasses it).
  const DB_EXT_RE = /\.(db|sqlite|sqlite3)$/i;

  // ── Helpers ────────────────────────────────────────────────────────────────
  function fmtBytes(n) {
    if (n == null) return '';
    if (n < 1024) return `${n} B`;
    if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1073741824) return `${(n / 1048576).toFixed(1)} MB`;
    return `${(n / 1073741824).toFixed(2)} GB`;
  }

  function fmtLocalTime(iso) {
    if (!iso) return '';
    try {
      const d = (typeof parseUTC === 'function') ? parseUTC(iso) : new Date(iso);
      if (!d || isNaN(d.getTime())) return String(iso);
      return d.toLocaleString();
    } catch {
      return String(iso);
    }
  }

  function toast(msg, type) {
    if (typeof showToast === 'function') showToast(msg, type || 'success');
    else alert(msg);
  }

  function banner(msg) {
    if (typeof showError === 'function') showError(msg);
    else alert(msg);
  }

  function extractErrorMessage(err, fallback) {
    if (!err) return fallback || 'Unknown error';
    if (err.status === 409) {
      return err.data && err.data.detail
        ? `Blocked: ${err.data.detail}`
        : 'Blocked: bulk jobs are active. Pause/cancel them and try again.';
    }
    return err.message || fallback || 'Unknown error';
  }

  function el(tag, opts) {
    const e = document.createElement(tag);
    if (!opts) return e;
    if (opts.className) e.className = opts.className;
    if (opts.id) e.id = opts.id;
    if (opts.text != null) e.textContent = opts.text;
    if (opts.style) Object.assign(e.style, opts.style);
    if (opts.attrs) {
      for (const k in opts.attrs) e.setAttribute(k, opts.attrs[k]);
    }
    if (opts.children) opts.children.forEach(c => c && e.appendChild(c));
    return e;
  }

  // ── Styles (static, no user data) ──────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById('dbbk-styles')) return;
    const css = `
      .dbbk-section { margin-bottom: 1rem; }
      .dbbk-section h4 { margin: 0 0 0.35rem 0; font-size: 0.95rem; }
      .dbbk-section p.hint { font-size: 0.85rem; color: var(--text-muted); margin: 0 0 0.6rem 0; }
      .dbbk-tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 0.75rem; gap: 0.25rem; }
      .dbbk-tab {
        padding: 0.5rem 0.9rem; cursor: pointer; background: none; border: none;
        border-bottom: 2px solid transparent; color: var(--text-muted); font-weight: 500;
      }
      .dbbk-tab.active { color: var(--text); border-bottom-color: var(--accent, #2563eb); }
      .dbbk-panel { display: none; }
      .dbbk-panel.active { display: block; }
      .dbbk-drop {
        border: 2px dashed var(--border); border-radius: var(--radius);
        padding: 1.25rem; text-align: center; color: var(--text-muted);
        cursor: pointer; transition: background 0.15s, border-color 0.15s;
      }
      .dbbk-drop:hover, .dbbk-drop.dragover {
        border-color: var(--accent, #2563eb);
        background: rgba(37,99,235,0.05);
      }
      .dbbk-file-info {
        margin-top: 0.6rem; font-size: 0.85rem; color: var(--text);
        background: var(--surface-alt, rgba(0,0,0,0.04)); padding: 0.4rem 0.6rem;
        border-radius: var(--radius-sm); display: none;
      }
      .dbbk-file-info.shown { display: block; }
      .dbbk-list { max-height: 280px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius); }
      .dbbk-list table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
      .dbbk-list th, .dbbk-list td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); }
      .dbbk-list th { background: var(--surface-alt, rgba(0,0,0,0.04)); position: sticky; top: 0; font-weight: 600; }
      .dbbk-list tr:last-child td { border-bottom: none; }
      .dbbk-warn {
        background: rgba(217,119,6,0.12); color: var(--warn, #92400e);
        border: 1px solid rgba(217,119,6,0.3); border-radius: var(--radius-sm);
        padding: 0.5rem 0.75rem; font-size: 0.85rem; margin-bottom: 0.75rem;
      }
      .dbbk-success-banner {
        background: rgba(22,163,74,0.12); color: var(--ok, #166534);
        border: 1px solid rgba(22,163,74,0.3); border-radius: var(--radius-sm);
        padding: 0.6rem 0.75rem; font-size: 0.9rem; margin: 1rem 0;
      }
      .dbbk-dialog { max-width: 620px; }
      .dbbk-btn-row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    `;
    const style = document.createElement('style');
    style.id = 'dbbk-styles';
    style.appendChild(document.createTextNode(css));
    document.head.appendChild(style);
  }

  // ── Modal builders (DOM only) ──────────────────────────────────────────────
  function buildBackupModal() {
    const dialog = el('div', { className: 'dialog dbbk-dialog' });

    dialog.appendChild(el('h3', { id: 'dbbk-backup-title', text: 'Backup Database' }));
    dialog.appendChild(el('p', {
      text: 'Create a full SQLite backup of the MarkFlow database. Bulk jobs must not be active.',
    }));

    // Download section
    const sec1 = el('div', { className: 'dbbk-section' });
    sec1.appendChild(el('h4', { text: 'Download to browser' }));
    sec1.appendChild(el('p', { className: 'hint', text: "Streams a .db file directly to your browser's download folder." }));
    const dlBtn = el('button', { className: 'btn btn-primary btn-sm', id: 'dbbk-btn-download', text: 'Download backup' });
    sec1.appendChild(dlBtn);
    dialog.appendChild(sec1);

    // Save on server section
    const sec2 = el('div', { className: 'dbbk-section' });
    sec2.appendChild(el('h4', { text: 'Save on server' }));
    sec2.appendChild(el('p', { className: 'hint', text: "Writes a timestamped backup to the server's backup directory." }));
    const saveBtn = el('button', { className: 'btn btn-secondary btn-sm', id: 'dbbk-btn-save', text: 'Save on server' });
    sec2.appendChild(saveBtn);
    dialog.appendChild(sec2);

    const btnGroup = el('div', {
      className: 'btn-group',
      style: { justifyContent: 'flex-end', marginTop: '1rem' },
    });
    const closeBtn = el('button', { className: 'btn btn-ghost btn-sm', id: 'dbbk-btn-close-backup', text: 'Close' });
    btnGroup.appendChild(closeBtn);
    dialog.appendChild(btnGroup);

    const backdrop = el('div', {
      className: 'dialog-backdrop',
      id: 'dbbk-backup-backdrop',
      attrs: { role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'dbbk-backup-title' },
    });
    backdrop.appendChild(dialog);
    return backdrop;
  }

  function buildRestoreModal() {
    const dialog = el('div', { className: 'dialog dbbk-dialog' });
    dialog.appendChild(el('h3', { id: 'dbbk-restore-title', text: 'Restore Database' }));

    const warn = el('div', { className: 'dbbk-warn' });
    const strong = el('strong', { text: 'Warning:' });
    warn.appendChild(strong);
    warn.appendChild(document.createTextNode(
      ' restoring replaces the live database. This is irreversible. Bulk jobs must not be active.'
    ));
    dialog.appendChild(warn);

    // Tabs
    const tabs = el('div', { className: 'dbbk-tabs', attrs: { role: 'tablist' } });
    const tabUpload = el('button', {
      className: 'dbbk-tab active', text: 'Upload file',
      attrs: { type: 'button', 'data-tab': 'upload', role: 'tab' },
    });
    const tabServer = el('button', {
      className: 'dbbk-tab', text: 'Server backups',
      attrs: { type: 'button', 'data-tab': 'server', role: 'tab' },
    });
    tabs.appendChild(tabUpload);
    tabs.appendChild(tabServer);
    dialog.appendChild(tabs);

    // Upload panel
    const uploadPanel = el('div', { className: 'dbbk-panel active', attrs: { 'data-panel': 'upload' } });
    const drop = el('div', { className: 'dbbk-drop', id: 'dbbk-drop', text: 'Drop a .db file here, or click to choose.' });
    const fileInput = el('input', {
      id: 'dbbk-file-input',
      attrs: { type: 'file', accept: '.db,.sqlite,.sqlite3' },
      style: { display: 'none' },
    });
    drop.appendChild(fileInput);
    uploadPanel.appendChild(drop);
    uploadPanel.appendChild(el('div', { className: 'dbbk-file-info', id: 'dbbk-file-info' }));

    const upBtnGroup = el('div', {
      className: 'btn-group',
      style: { marginTop: '0.75rem', justifyContent: 'flex-end' },
    });
    const upBtn = el('button', {
      className: 'btn btn-danger btn-sm',
      id: 'dbbk-btn-upload-restore',
      text: 'Restore from file',
    });
    upBtn.disabled = true;
    upBtnGroup.appendChild(upBtn);
    uploadPanel.appendChild(upBtnGroup);
    dialog.appendChild(uploadPanel);

    // Server panel
    const serverPanel = el('div', { className: 'dbbk-panel', attrs: { 'data-panel': 'server' } });
    const listEl = el('div', { className: 'dbbk-list', id: 'dbbk-list' });
    const loading = el('div', {
      style: { padding: '1rem', textAlign: 'center', color: 'var(--text-muted)' },
      text: 'Loading...',
    });
    listEl.appendChild(loading);
    serverPanel.appendChild(listEl);
    dialog.appendChild(serverPanel);

    // Close
    const btnGroup = el('div', {
      className: 'btn-group',
      style: { justifyContent: 'flex-end', marginTop: '1rem' },
    });
    const closeBtn = el('button', { className: 'btn btn-ghost btn-sm', id: 'dbbk-btn-close-restore', text: 'Close' });
    btnGroup.appendChild(closeBtn);
    dialog.appendChild(btnGroup);

    const backdrop = el('div', {
      className: 'dialog-backdrop',
      id: 'dbbk-restore-backdrop',
      attrs: { role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'dbbk-restore-title' },
    });
    backdrop.appendChild(dialog);
    return backdrop;
  }

  function injectModals() {
    if (modalsInjected) return;
    modalsInjected = true;
    injectStyles();
    document.body.appendChild(buildBackupModal());
    document.body.appendChild(buildRestoreModal());
    wireBackupModal();
    wireRestoreModal();
  }

  // ── Backup modal wiring ────────────────────────────────────────────────────
  function wireBackupModal() {
    const backdrop = document.getElementById('dbbk-backup-backdrop');
    document.getElementById('dbbk-btn-close-backup').addEventListener('click', () => closeModal(backdrop));
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(backdrop); });

    document.getElementById('dbbk-btn-download').addEventListener('click', async () => {
      const btn = document.getElementById('dbbk-btn-download');
      btn.disabled = true;
      const oldText = btn.textContent;
      btn.textContent = 'Preparing...';
      try {
        // Raw fetch (need the blob body, not JSON). Match API.post's options so
        // same-origin cookies / auth travel identically — see `API.post` in app.js.
        const response = await fetch('/api/db/backup?download=true', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({}),
        });
        if (!response.ok) {
          let detail = `HTTP ${response.status}`;
          try {
            const data = await response.json();
            if (data && data.detail) detail = data.detail;
          } catch {}
          if (response.status === 409) banner(`Backup blocked: ${detail}`);
          else banner(`Backup failed: ${detail}`);
          return;
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        a.download = `markflow-backup-${ts}.db`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast('Backup download started', 'success');
      } catch (err) {
        banner(`Backup failed: ${err.message || err}`);
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });

    document.getElementById('dbbk-btn-save').addEventListener('click', async () => {
      const btn = document.getElementById('dbbk-btn-save');
      btn.disabled = true;
      const oldText = btn.textContent;
      btn.textContent = 'Saving...';
      try {
        const result = await API.post('/api/db/backup', {});
        const where = result && result.path ? ` (${result.path})` : '';
        toast(`Backup saved on server${where}`, 'success');
      } catch (err) {
        banner(extractErrorMessage(err, 'Backup failed'));
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });
  }

  // ── Restore modal wiring ───────────────────────────────────────────────────
  function wireRestoreModal() {
    const backdrop = document.getElementById('dbbk-restore-backdrop');
    document.getElementById('dbbk-btn-close-restore').addEventListener('click', () => closeModal(backdrop));
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(backdrop); });

    backdrop.querySelectorAll('.dbbk-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        backdrop.querySelectorAll('.dbbk-tab').forEach(t => t.classList.remove('active'));
        backdrop.querySelectorAll('.dbbk-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.getAttribute('data-tab');
        backdrop.querySelector(`.dbbk-panel[data-panel="${target}"]`).classList.add('active');
        if (target === 'server') loadServerBackups();
      });
    });

    const dropZone = document.getElementById('dbbk-drop');
    const fileInput = document.getElementById('dbbk-file-input');

    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length) setSelectedFile(e.target.files[0]);
    });
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files && e.dataTransfer.files.length) setSelectedFile(e.dataTransfer.files[0]);
    });

    document.getElementById('dbbk-btn-upload-restore').addEventListener('click', async () => {
      if (!selectedFile) return;
      const ok = confirm(
        `Restore database from "${selectedFile.name}"?\n\n` +
        `This will REPLACE the current database. This action is IRREVERSIBLE.\n` +
        `Ensure no bulk jobs are running.`
      );
      if (!ok) return;
      const btn = document.getElementById('dbbk-btn-upload-restore');
      btn.disabled = true;
      const oldText = btn.textContent;
      btn.textContent = 'Restoring...';
      try {
        const fd = new FormData();
        fd.append('file', selectedFile);
        await API.upload('/api/db/restore', fd);
        showPostRestoreBanner();
        closeModal(document.getElementById('dbbk-restore-backdrop'));
        toast('Restore complete. Please refresh the page.', 'success');
      } catch (err) {
        banner(extractErrorMessage(err, 'Restore failed'));
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });
  }

  function setSelectedFile(file) {
    if (!file) return;
    // The file input's `accept=".db,.sqlite,.sqlite3"` is only a picker hint —
    // drag-and-drop bypasses it. Validate extension explicitly here so both
    // paths (change + drop) enforce the same whitelist.
    if (!DB_EXT_RE.test(file.name)) {
      banner('Please select a .db, .sqlite, or .sqlite3 file.');
      const fi = document.getElementById('dbbk-file-input');
      if (fi) fi.value = '';
      return;
    }
    selectedFile = file;
    const info = document.getElementById('dbbk-file-info');
    info.textContent = '';
    const strong = document.createElement('strong');
    strong.textContent = file.name;
    info.appendChild(strong);
    info.appendChild(document.createTextNode(` — ${fmtBytes(file.size)}`));
    info.classList.add('shown');
    document.getElementById('dbbk-btn-upload-restore').disabled = false;
  }

  async function loadServerBackups() {
    const listEl = document.getElementById('dbbk-list');
    listEl.textContent = '';
    const loading = el('div', {
      style: { padding: '1rem', textAlign: 'center', color: 'var(--text-muted)' },
      text: 'Loading...',
    });
    listEl.appendChild(loading);

    try {
      const data = await API.get('/api/db/backups');
      const backups = (data && data.backups) || [];
      listEl.textContent = '';
      if (backups.length === 0) {
        listEl.appendChild(el('div', {
          style: { padding: '1rem', textAlign: 'center', color: 'var(--text-muted)' },
          text: 'No server backups found.',
        }));
        return;
      }
      const table = document.createElement('table');
      const thead = document.createElement('thead');
      const hdr = document.createElement('tr');
      ['Filename', 'Size', 'Modified', ''].forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        hdr.appendChild(th);
      });
      thead.appendChild(hdr);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      backups.forEach(b => {
        const tr = document.createElement('tr');

        const tdName = document.createElement('td');
        tdName.textContent = b.filename || '';
        tdName.title = b.path || '';
        tr.appendChild(tdName);

        const tdSize = document.createElement('td');
        tdSize.textContent = fmtBytes(b.size_bytes);
        tr.appendChild(tdSize);

        const tdDate = document.createElement('td');
        tdDate.textContent = fmtLocalTime(b.modified_at);
        tr.appendChild(tdDate);

        const tdBtn = document.createElement('td');
        tdBtn.style.textAlign = 'right';
        const btn = document.createElement('button');
        btn.className = 'btn btn-danger btn-sm';
        btn.textContent = 'Restore';
        btn.addEventListener('click', () => restoreFromServer(b, btn));
        tdBtn.appendChild(btn);
        tr.appendChild(tdBtn);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      listEl.appendChild(table);
    } catch (err) {
      listEl.textContent = '';
      const errDiv = document.createElement('div');
      errDiv.style.padding = '1rem';
      errDiv.style.color = 'var(--error, #b91c1c)';
      errDiv.textContent = `Failed to load: ${err.message || err}`;
      listEl.appendChild(errDiv);
    }
  }

  async function restoreFromServer(backup, btn) {
    const ok = confirm(
      `Restore database from "${backup.filename}"?\n\n` +
      `This will REPLACE the current database. This action is IRREVERSIBLE.\n` +
      `Ensure no bulk jobs are running.`
    );
    if (!ok) return;
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = 'Restoring...';
    try {
      const fd = new FormData();
      fd.append('backup_path', backup.path);
      await API.upload('/api/db/restore', fd);
      showPostRestoreBanner();
      closeModal(document.getElementById('dbbk-restore-backdrop'));
      toast('Restore complete. Please refresh the page.', 'success');
    } catch (err) {
      banner(extractErrorMessage(err, 'Restore failed'));
    } finally {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }

  function showPostRestoreBanner() {
    const host = document.querySelector('.page-content') || document.body;
    const prev = document.getElementById('dbbk-post-restore-banner');
    if (prev) prev.remove();

    const div = document.createElement('div');
    div.id = 'dbbk-post-restore-banner';
    div.className = 'dbbk-success-banner';
    div.textContent =
      'Database restore complete. The connection pool was reinitialized, but cached UI state may be stale. ' +
      'Please refresh this page to reload from the restored database.';

    const refreshBtn = document.createElement('button');
    refreshBtn.className = 'btn btn-primary btn-sm';
    refreshBtn.style.marginLeft = '0.75rem';
    refreshBtn.textContent = 'Refresh now';
    refreshBtn.addEventListener('click', () => window.location.reload());
    div.appendChild(refreshBtn);

    host.insertBefore(div, host.firstChild);
  }

  // ── Modal open/close ───────────────────────────────────────────────────────
  // `key` is 'backup' or 'restore' — used to track opener + Esc handler per modal.
  function openModal(backdrop, key) {
    backdrop.classList.add('open');
    const state = modalState[key];
    if (state) {
      // Stash the element that opened us so we can restore focus on close.
      state.opener = document.activeElement;
      // One Esc handler per modal; removed on close.
      state.escHandler = (e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          closeModal(backdrop, key);
        }
      };
      document.addEventListener('keydown', state.escHandler);
    }
    // Move focus into the dialog. The close button is the safest initial
    // focus target (it's always present and its action is non-destructive).
    const closeId = key === 'backup' ? 'dbbk-btn-close-backup' : 'dbbk-btn-close-restore';
    const focusTarget = document.getElementById(closeId) || backdrop.querySelector('.dialog');
    if (focusTarget && typeof focusTarget.focus === 'function') {
      // Defer so the browser applies .open styles before focusing.
      setTimeout(() => focusTarget.focus(), 0);
    }
  }

  function closeModal(backdrop, key) {
    backdrop.classList.remove('open');
    // Resolve key from the backdrop id if the caller didn't pass it (older
    // call sites just pass the backdrop element).
    if (!key) {
      key = backdrop.id === 'dbbk-backup-backdrop' ? 'backup'
          : backdrop.id === 'dbbk-restore-backdrop' ? 'restore'
          : null;
    }
    const state = key ? modalState[key] : null;
    if (state) {
      if (state.escHandler) {
        document.removeEventListener('keydown', state.escHandler);
        state.escHandler = null;
      }
      // Restore focus to the element that opened the modal.
      if (state.opener && typeof state.opener.focus === 'function') {
        try { state.opener.focus(); } catch {}
      }
      state.opener = null;
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.openBackupModal = function () {
    injectModals();
    openModal(document.getElementById('dbbk-backup-backdrop'), 'backup');
  };

  window.openRestoreModal = function () {
    injectModals();
    selectedFile = null;
    const info = document.getElementById('dbbk-file-info');
    if (info) { info.textContent = ''; info.classList.remove('shown'); }
    const btn = document.getElementById('dbbk-btn-upload-restore');
    if (btn) btn.disabled = true;
    const fi = document.getElementById('dbbk-file-input');
    if (fi) fi.value = '';
    const backdrop = document.getElementById('dbbk-restore-backdrop');
    backdrop.querySelectorAll('.dbbk-tab').forEach(t => {
      t.classList.toggle('active', t.getAttribute('data-tab') === 'upload');
    });
    backdrop.querySelectorAll('.dbbk-panel').forEach(p => {
      p.classList.toggle('active', p.getAttribute('data-panel') === 'upload');
    });
    openModal(backdrop, 'restore');
  };
})();
