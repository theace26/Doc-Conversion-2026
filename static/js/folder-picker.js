/**
 * FolderPicker — modal directory browser widget for MarkFlow.
 *
 * Usage:
 *   const picker = new FolderPicker({
 *     title: "Select Folder",
 *     initialPath: "/host",
 *     mode: "source",           // "source" | "output" | "any"
 *     onSelect: (path) => { ... },
 *     onCancel: () => { ... },
 *   });
 *   picker.open();
 */
class FolderPicker {
  constructor(options = {}) {
    this.title = options.title || 'Select a Folder';
    this.initialPath = options.initialPath || '/host';
    this.mode = options.mode || 'any';
    this.onSelect = options.onSelect || (() => {});
    this.onCancel = options.onCancel || (() => {});
    this.selectedPath = null;
    this.currentPath = null;
    this.currentData = null;
    this.dialog = null;
    this._build();
  }

  // ── Build DOM ──────────────────────────────────────────────────────────

  _build() {
    this.dialog = document.createElement('dialog');
    this.dialog.className = 'fp-dialog';
    this.dialog.innerHTML = `
      <div class="fp-header">
        <span class="fp-title">${this._esc(this.title)}</span>
        <button class="fp-close" aria-label="Close">&times;</button>
      </div>
      <div class="fp-body">
        <div class="fp-drives" id="fp-drives"></div>
        <div class="fp-content">
          <div class="fp-breadcrumb" id="fp-breadcrumb"></div>
          <div class="fp-entries" id="fp-entries"></div>
        </div>
      </div>
      <div class="fp-footer">
        <div class="fp-selected" id="fp-selected">No folder selected</div>
        <div class="fp-actions">
          <button class="btn btn-ghost" id="fp-cancel">Cancel</button>
          <button class="btn btn-primary" id="fp-select" disabled>Select</button>
        </div>
      </div>
    `;

    // Inject scoped styles (once)
    if (!document.getElementById('fp-styles')) {
      const style = document.createElement('style');
      style.id = 'fp-styles';
      style.textContent = FolderPicker._CSS;
      document.head.appendChild(style);
    }

    // Event listeners
    this.dialog.querySelector('.fp-close').addEventListener('click', () => this.close());
    this.dialog.querySelector('#fp-cancel').addEventListener('click', () => this.close());
    this.dialog.querySelector('#fp-select').addEventListener('click', () => this._confirm());
    this.dialog.addEventListener('cancel', (e) => {
      e.preventDefault();
      this.close();
    });

    // Keyboard navigation
    this.dialog.addEventListener('keydown', (e) => this._onKeyDown(e));

    document.body.appendChild(this.dialog);
  }

  // ── Public API ─────────────────────────────────────────────────────────

  open() {
    this.selectedPath = null;
    this._updateSelectBtn();

    // If mode is "output", start at the output repo
    let startPath = this.initialPath;
    if (this.mode === 'output' && (!startPath || startPath === '/host')) {
      startPath = '/mnt/output-repo';
    }

    this.dialog.showModal();
    this._navigate(startPath);
  }

  close() {
    this.onCancel();
    this.dialog.close();
    this.dialog.remove();
  }

  // ── Navigation ─────────────────────────────────────────────────────────

  async _navigate(path) {
    this.currentPath = path;
    this.selectedPath = null;
    this._updateSelectBtn();
    this._showLoading();

    try {
      const params = new URLSearchParams({ path });
      const resp = await fetch(`/api/browse?${params}`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        this._showError(err.detail || 'Could not read this folder.');
        return;
      }
      this.currentData = await resp.json();
      this._render();
    } catch (e) {
      this._showError('Network error: ' + e.message);
    }
  }

  // ── Rendering ──────────────────────────────────────────────────────────

  _render() {
    const data = this.currentData;
    this._renderDrives(data.drives || []);
    this._renderBreadcrumb(data.path, data.parent);
    this._renderEntries(data.entries || [], data.path);
  }

  _renderDrives(drives) {
    const el = this.dialog.querySelector('#fp-drives');
    el.replaceChildren();

    const makeLabel = (text, marginTop = false) => {
      const lbl = document.createElement('div');
      lbl.className = 'fp-drive-label';
      if (marginTop) lbl.style.marginTop = '0.75rem';
      lbl.textContent = text;
      return lbl;
    };

    const makeDriveBtn = ({ label, path, mounted }) => {
      const btn = document.createElement('button');
      btn.className = 'fp-drive-btn ' + (mounted ? 'fp-drive-mounted' : 'fp-drive-unmounted');
      btn.dataset.path = path;
      btn.dataset.mounted = String(mounted);
      btn.title = mounted ? 'Click to browse' : 'Not mounted';

      const icon = document.createElement('span');
      icon.className = 'fp-drive-icon';
      icon.textContent = '\u{1F4BE}';
      btn.appendChild(icon);
      btn.appendChild(document.createTextNode(' ' + label));

      btn.addEventListener('click', () => {
        if (!mounted) {
          this._showUnmountedHelp(label);
          return;
        }
        this._navigate(path);
      });
      return btn;
    };

    el.appendChild(makeLabel('Drives'));
    drives.forEach(d => {
      el.appendChild(makeDriveBtn({ label: d.name, path: d.path, mounted: !!d.mounted }));
    });

    // Show the Output Repo shortcut for modes that write output
    if (this.mode === 'any' || this.mode === 'output') {
      el.appendChild(makeLabel('Output', true));
      el.appendChild(makeDriveBtn({ label: 'Output Repo', path: '/mnt/output-repo', mounted: true }));
    }
  }

  _renderBreadcrumb(path, parent) {
    const el = this.dialog.querySelector('#fp-breadcrumb');
    let html = '';
    if (parent) {
      html += `<button class="fp-back-btn" id="fp-back">&larr; Back</button>`;
    }
    html += `<span class="fp-current-path">${this._esc(path)}</span>`;
    el.innerHTML = html;

    if (parent) {
      el.querySelector('#fp-back').addEventListener('click', () => this._navigate(parent));
    }
  }

  _renderEntries(entries, currentPath) {
    const el = this.dialog.querySelector('#fp-entries');
    let html = '';

    // "Select this folder" row
    html += `<div class="fp-entry fp-entry-select-current" data-path="${this._esc(currentPath)}">
      <span class="fp-entry-icon">&#128194;</span>
      <span class="fp-entry-name">Select current folder</span>
      <span class="fp-entry-count"></span>
    </div>`;

    if (entries.length === 0) {
      html += '<div class="fp-empty">This folder is empty.</div>';
    }

    entries.forEach(entry => {
      if (entry.type !== 'directory') return;
      const countText = entry.item_count != null ? `${entry.item_count} items` : '';
      const readableClass = entry.readable ? '' : 'fp-entry-unreadable';
      html += `<div class="fp-entry ${readableClass}" data-path="${this._esc(entry.path)}" data-readable="${entry.readable}">
        <span class="fp-entry-icon">&#128193;</span>
        <span class="fp-entry-name">${this._esc(entry.name)}</span>
        <span class="fp-entry-count">${countText}</span>
      </div>`;
    });

    el.innerHTML = html;

    // Click handlers
    el.querySelectorAll('.fp-entry').forEach(row => {
      row.addEventListener('click', () => this._selectEntry(row));
      row.addEventListener('dblclick', () => {
        const path = row.dataset.path;
        if (row.classList.contains('fp-entry-select-current')) {
          this.selectedPath = path;
          this._confirm();
          return;
        }
        if (row.dataset.readable !== 'false') {
          this._navigate(path);
        }
      });
    });
  }

  _selectEntry(row) {
    // Deselect previous
    this.dialog.querySelectorAll('.fp-entry.fp-entry-active').forEach(el => {
      el.classList.remove('fp-entry-active');
    });
    row.classList.add('fp-entry-active');
    this.selectedPath = row.dataset.path;
    this._updateSelectBtn();
  }

  _showLoading() {
    const el = this.dialog.querySelector('#fp-entries');
    el.innerHTML = '<div class="fp-loading"><div class="fp-spinner"></div> Loading...</div>';
  }

  _showError(detail) {
    const el = this.dialog.querySelector('#fp-entries');
    let msg = 'Could not read this folder.';
    if (typeof detail === 'object') {
      msg = detail.message || detail.error || msg;
    } else if (typeof detail === 'string') {
      msg = detail;
    }
    const parent = this.currentData?.parent;
    el.innerHTML = `
      <div class="fp-error">
        <p>${this._esc(msg)}</p>
        ${parent ? '<button class="btn btn-ghost btn-sm fp-error-back">&larr; Back</button>' : ''}
      </div>
    `;
    const backBtn = el.querySelector('.fp-error-back');
    if (backBtn && parent) {
      backBtn.addEventListener('click', () => this._navigate(parent));
    }
  }

  _showUnmountedHelp(driveName) {
    const letter = driveName.replace(':', '').trim().toUpperCase();
    const el = this.dialog.querySelector('#fp-entries');
    el.innerHTML = `
      <div class="fp-unmounted-help">
        <p><strong>Drive ${letter}: is not mounted.</strong></p>
        <p>To mount it, add this line to your <code>docker-compose.yml</code>:</p>
        <pre>- ${letter}:/:/host/${letter.toLowerCase()}:ro</pre>
        <p>Then restart:</p>
        <pre>docker-compose down && docker-compose up -d</pre>
      </div>
    `;
    this.dialog.querySelector('#fp-breadcrumb').innerHTML =
      `<span class="fp-current-path">Drive ${letter}: (not mounted)</span>`;
  }

  _updateSelectBtn() {
    const btn = this.dialog.querySelector('#fp-select');
    const label = this.dialog.querySelector('#fp-selected');
    if (this.selectedPath) {
      btn.disabled = false;
      label.textContent = 'Selected: ' + this.selectedPath;
    } else {
      btn.disabled = true;
      label.textContent = 'No folder selected';
    }
  }

  _confirm() {
    if (!this.selectedPath) return;
    const path = this.selectedPath;
    this.dialog.close();
    this.dialog.remove();
    this.onSelect(path);
  }

  // ── Keyboard ───────────────────────────────────────────────────────────

  _onKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
      return;
    }

    if (e.key === 'Backspace' && !e.target.matches('input, textarea')) {
      e.preventDefault();
      const parent = this.currentData?.parent;
      if (parent) this._navigate(parent);
      return;
    }

    if (e.key === 'Enter') {
      const active = this.dialog.querySelector('.fp-entry.fp-entry-active');
      if (active) {
        if (active.classList.contains('fp-entry-select-current')) {
          this.selectedPath = active.dataset.path;
          this._confirm();
        } else if (active.dataset.readable !== 'false') {
          this._navigate(active.dataset.path);
        }
      }
      return;
    }

    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const entries = Array.from(this.dialog.querySelectorAll('.fp-entry'));
      if (entries.length === 0) return;
      const current = entries.findIndex(el => el.classList.contains('fp-entry-active'));
      let next;
      if (e.key === 'ArrowDown') {
        next = current < 0 ? 0 : Math.min(current + 1, entries.length - 1);
      } else {
        next = current < 0 ? entries.length - 1 : Math.max(current - 1, 0);
      }
      this._selectEntry(entries[next]);
      entries[next].scrollIntoView({ block: 'nearest' });
    }
  }

  // ── Utilities ──────────────────────────────────────────────────────────

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  // ── Scoped CSS ─────────────────────────────────────────────────────────

  static _CSS = `
    .fp-dialog {
      border: none;
      border-radius: var(--radius, 8px);
      box-shadow: var(--shadow-lg, 0 4px 12px rgba(0,0,0,.15));
      padding: 0;
      width: min(680px, 95vw);
      max-height: min(520px, 90vh);
      display: flex;
      flex-direction: column;
      background: var(--surface, #fff);
      color: var(--text, #1a1d2e);
      font-family: var(--font-sans, system-ui, sans-serif);
    }
    .fp-dialog::backdrop {
      background: rgba(0, 0, 0, 0.45);
    }

    /* Header */
    .fp-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border, #dfe1e8);
    }
    .fp-title {
      font-weight: 600;
      font-size: 1rem;
    }
    .fp-close {
      background: none;
      border: none;
      font-size: 1.4rem;
      cursor: pointer;
      color: var(--text-muted, #6b7084);
      line-height: 1;
      padding: 0 0.25rem;
    }
    .fp-close:hover { color: var(--text, #1a1d2e); }

    /* Body: two-panel layout */
    .fp-body {
      display: flex;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }

    /* Drive panel */
    .fp-drives {
      width: 140px;
      min-width: 140px;
      border-right: 1px solid var(--border, #dfe1e8);
      padding: 0.5rem;
      overflow-y: auto;
    }
    .fp-drive-label {
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      color: var(--text-muted, #6b7084);
      padding: 0.25rem 0.5rem;
      letter-spacing: 0.03em;
    }
    .fp-drive-btn {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      width: 100%;
      padding: 0.4rem 0.5rem;
      border: none;
      border-radius: var(--radius-sm, 4px);
      background: none;
      cursor: pointer;
      font-size: 0.85rem;
      font-family: inherit;
      color: var(--text, #1a1d2e);
      text-align: left;
    }
    .fp-drive-btn:hover { background: var(--surface-alt, #f0f1f5); }
    .fp-drive-unmounted {
      opacity: 0.45;
      cursor: help;
    }
    .fp-drive-icon { font-size: 1rem; }

    /* Content panel */
    .fp-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
      overflow: hidden;
    }
    .fp-breadcrumb {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 0.75rem;
      border-bottom: 1px solid var(--border, #dfe1e8);
      font-size: 0.82rem;
    }
    .fp-back-btn {
      background: none;
      border: 1px solid var(--border, #dfe1e8);
      border-radius: var(--radius-sm, 4px);
      padding: 0.2rem 0.5rem;
      cursor: pointer;
      font-size: 0.8rem;
      font-family: inherit;
      color: var(--text, #1a1d2e);
    }
    .fp-back-btn:hover { background: var(--surface-alt, #f0f1f5); }
    .fp-current-path {
      font-family: var(--font-mono, monospace);
      font-size: 0.82rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    /* Entries */
    .fp-entries {
      flex: 1;
      overflow-y: auto;
      padding: 0.25rem 0;
    }
    .fp-entry {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.4rem 0.75rem;
      cursor: pointer;
      font-size: 0.88rem;
    }
    .fp-entry:hover { background: var(--surface-alt, #f0f1f5); }
    .fp-entry.fp-entry-active {
      background: var(--accent, #4f5bd5);
      color: var(--text-on-accent, #fff);
    }
    .fp-entry.fp-entry-active .fp-entry-count {
      color: var(--text-on-accent, #fff);
      opacity: 0.8;
    }
    .fp-entry-unreadable { opacity: 0.5; cursor: not-allowed; }
    .fp-entry-icon { font-size: 1rem; flex-shrink: 0; }
    .fp-entry-name {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .fp-entry-count {
      font-size: 0.75rem;
      color: var(--text-muted, #6b7084);
      white-space: nowrap;
    }
    .fp-entry-select-current {
      border-bottom: 1px solid var(--border, #dfe1e8);
      font-style: italic;
      font-size: 0.84rem;
    }

    /* States */
    .fp-loading, .fp-empty, .fp-error, .fp-unmounted-help {
      padding: 1.5rem;
      text-align: center;
      color: var(--text-muted, #6b7084);
      font-size: 0.9rem;
    }
    .fp-error p, .fp-unmounted-help p { margin-bottom: 0.5rem; }
    .fp-unmounted-help pre {
      background: var(--surface-alt, #f0f1f5);
      padding: 0.5rem 0.75rem;
      border-radius: var(--radius-sm, 4px);
      font-family: var(--font-mono, monospace);
      font-size: 0.82rem;
      text-align: left;
      display: inline-block;
      margin: 0.5rem 0;
    }
    .fp-unmounted-help code {
      font-family: var(--font-mono, monospace);
      background: var(--surface-alt, #f0f1f5);
      padding: 0.1rem 0.3rem;
      border-radius: 2px;
      font-size: 0.85rem;
    }

    .fp-spinner {
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid var(--border, #dfe1e8);
      border-top-color: var(--accent, #4f5bd5);
      border-radius: 50%;
      animation: fp-spin 0.6s linear infinite;
      vertical-align: middle;
      margin-right: 0.5rem;
    }
    @keyframes fp-spin { to { transform: rotate(360deg); } }

    /* Footer */
    .fp-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.6rem 1rem;
      border-top: 1px solid var(--border, #dfe1e8);
      gap: 1rem;
    }
    .fp-selected {
      font-family: var(--font-mono, monospace);
      font-size: 0.8rem;
      color: var(--text-muted, #6b7084);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }
    .fp-actions {
      display: flex;
      gap: 0.5rem;
      flex-shrink: 0;
    }
  `;
}
