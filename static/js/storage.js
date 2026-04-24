/**
 * storage.js — Universal Storage Manager UI (v0.29.0)
 *
 * Powers /storage.html: host info / quick-access / sources / output /
 * shares / discovery / exclusions / cloud prefetch / first-run wizard.
 *
 * v0.29.0 polish:
 * - Add-Share and Discovery prompt() chains replaced with proper modals
 * - Host-OS override dropdown in the page header
 * - Folder-picker integration for source/output path inputs
 * - Cloud Prefetch section migrated from Settings page
 *
 * Conventions:
 * - All DOM construction uses createElement + textContent. Never innerHTML
 *   on fetched data (per CLAUDE.md XSS-safety rule).
 * - All API calls are gated MANAGER+ — auth cookie is sent automatically.
 * - parseUTC() from app.js for any timestamps from the backend.
 */
(function () {
  'use strict';

  // ── DOM helpers ───────────────────────────────────────────────────────────

  function $(id) { return document.getElementById(id); }

  function clearChildren(el) {
    while (el && el.firstChild) el.removeChild(el.firstChild);
  }

  function el(tag, opts, children) {
    const node = document.createElement(tag);
    if (opts) {
      if (opts.text != null) node.textContent = String(opts.text);
      if (opts.cls) node.className = opts.cls;
      if (opts.id) node.id = opts.id;
      if (opts.title) node.title = opts.title;
      if (opts.onClick) node.addEventListener('click', opts.onClick);
      if (opts.attrs) {
        for (const k in opts.attrs) node.setAttribute(k, opts.attrs[k]);
      }
      if (opts.style) {
        for (const k in opts.style) node.style[k] = opts.style[k];
      }
    }
    if (children) {
      for (const c of children) {
        if (c == null) continue;
        node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
      }
    }
    return node;
  }

  function makeRow(cells) {
    const tr = el('tr');
    for (const c of cells) {
      const td = el('td');
      if (c instanceof Node) td.appendChild(c);
      else td.textContent = c == null ? '' : String(c);
      tr.appendChild(td);
    }
    return tr;
  }

  function prettyOS(code) {
    return ({
      windows: 'Windows',
      wsl: 'Windows (WSL)',
      macos: 'macOS',
      linux: 'Linux',
      unknown: 'Unknown'
    })[code] || code;
  }

  // ── Generic fetch with error surface ─────────────────────────────────────

  async function api(path, opts) {
    const res = await fetch(path, opts || {});
    if (!res.ok) {
      let detail = '';
      try { detail = JSON.stringify(await res.json()); } catch { /* ignore */ }
      const err = new Error(`${path} → ${res.status} ${res.statusText} ${detail}`);
      err.status = res.status;
      err.detail = detail;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  function showError(msg) {
    const banner = $('error-banner');
    if (!banner) return;
    banner.textContent = msg;
    banner.hidden = false;
    setTimeout(() => { banner.hidden = true; }, 8000);
  }

  function flash(elem, text, ms) {
    if (!elem) return;
    elem.textContent = text;
    if (ms) setTimeout(() => { if (elem.textContent === text) elem.textContent = ''; }, ms);
  }

  // ── Host info / Quick Access ─────────────────────────────────────────────

  async function loadHostInfo() {
    const badge = $('host-os-badge');
    try {
      const info = await api('/api/storage/host-info');
      badge.textContent = `Detected: ${prettyOS(info.os)}`;
      renderQuickAccess(info.quick_access || []);
      // Sync override dropdown with persisted value — we need to read the pref
      try {
        const prefs = await api('/api/preferences');
        const override = (prefs.preferences && prefs.preferences.host_os_override) || '';
        $('host-os-override').value = override;
      } catch { /* pref read is non-critical */ }
    } catch (e) {
      badge.textContent = 'OS unknown';
      console.warn('host-info failed', e);
    }
  }

  function renderQuickAccess(entries) {
    const grid = $('quick-access-grid');
    clearChildren(grid);
    if (!entries.length) {
      grid.appendChild(el('p', { text: 'No quick-access entries detected.', cls: 'text-muted' }));
      return;
    }
    for (const q of entries) {
      const tile = el('div', { cls: 'quick-access-tile' });
      tile.appendChild(el('strong', { text: q.name }));
      tile.appendChild(el('div', { text: q.path, cls: 'text-sm text-muted' }));
      const useBtn = el('button', {
        text: 'Use as source',
        cls: 'btn btn-sm',
        onClick: async () => addSource(q.path, q.name)
      });
      tile.appendChild(useBtn);
      grid.appendChild(tile);
    }
  }

  async function saveHostOsOverride() {
    const value = $('host-os-override').value;
    try {
      await api('/api/preferences/host_os_override', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value })
      });
      // Re-load host info so Quick Access reflects the override
      loadHostInfo();
    } catch (e) {
      showError(`Failed to save OS override: ${e.message}`);
    }
  }

  // ── Folder picker integration (A4) ───────────────────────────────────────

  function openFolderPicker(title, mode, inputId) {
    if (typeof FolderPicker === 'undefined') {
      showError('Folder picker unavailable — type the path manually.');
      return;
    }
    const input = $(inputId);
    const initial = (input && input.value.trim()) || (mode === 'output' ? '/host/rw' : '/host/root');
    const picker = new FolderPicker({
      title, mode, initialPath: initial,
      onSelect: (path) => { if (input) input.value = path; }
    });
    picker.open();
  }

  // ── Sources ──────────────────────────────────────────────────────────────

  async function loadSources() {
    try {
      const { sources } = await api('/api/storage/sources');
      const tbody = $('sources-tbody');
      clearChildren(tbody);
      if (!sources.length) {
        tbody.appendChild(makeRow(['', 'No sources configured.', '']));
        return;
      }
      for (const s of sources) {
        const rmBtn = el('button', {
          text: 'Remove', cls: 'btn btn-sm btn-danger',
          onClick: () => removeSource(s.id)
        });
        tbody.appendChild(makeRow([s.label, s.path, rmBtn]));
      }
    } catch (e) {
      showError(`Failed to load sources: ${e.message}`);
    }
  }

  async function addSource(path, label) {
    if (!path) {
      const inp = $('source-path-input');
      path = inp ? inp.value.trim() : '';
      label = ($('source-label-input') ? $('source-label-input').value.trim() : '') || '';
    }
    if (!path) { showError('Source path is required.'); return; }
    try {
      await api('/api/storage/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, label: label || '' })
      });
      if ($('source-path-input')) $('source-path-input').value = '';
      if ($('source-label-input')) $('source-label-input').value = '';
      await renderVerificationAt($('source-add-verify'), path, 'source');
      loadSources();
    } catch (e) {
      await renderVerificationAt($('source-add-verify'), path, 'source', extractErrors(e));
    }
  }

  async function removeSource(id) {
    try {
      await api(`/api/storage/sources/${encodeURIComponent(id)}`, { method: 'DELETE' });
      loadSources();
    } catch (e) {
      showError(e.message);
    }
  }

  // ── Path verification (shared by Output + Sources) ───────────────────────

  function formatBytes(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    const units = ['KB', 'MB', 'GB', 'TB'];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return v.toFixed(v < 10 ? 1 : 0) + ' ' + units[i];
  }

  function extractErrors(err) {
    try {
      const parsed = typeof err.detail === 'string' ? JSON.parse(err.detail) : null;
      const d = parsed && parsed.detail ? parsed.detail : parsed;
      if (d && Array.isArray(d.errors) && d.errors.length) return d.errors;
      if (d && Array.isArray(d.warnings) && d.warnings.length) return d.warnings;
    } catch { /* fall through */ }
    return [err.message || 'Unknown error.'];
  }

  async function renderVerificationAt(container, path, role, forcedErrors) {
    if (!container) return;
    clearChildren(container);

    // If caller knows validation already failed (e.g. save returned 400),
    // render immediately without a second round-trip.
    let result;
    if (forcedErrors) {
      result = { ok: false, errors: forcedErrors, warnings: [], stats: {} };
    } else {
      try {
        result = await api('/api/storage/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, role }),
        });
      } catch (e) {
        result = { ok: false, errors: [e.message || 'Validation failed.'], warnings: [], stats: {} };
      }
    }

    const ok = !!result.ok;
    const iconCls = 'sv-icon ' + (ok ? 'sv-ok' : 'sv-bad');
    const icon = el('span', { cls: iconCls, text: ok ? '✓' : '✗', attrs: { 'aria-hidden': 'true' } });
    const pathCode = el('code', { cls: 'sv-path', text: path });

    const details = [];
    if (ok) {
      details.push(role === 'output' ? 'Writable' : 'Readable');
      if (result.stats && result.stats.item_count != null) {
        details.push(result.stats.item_count + ' item' + (result.stats.item_count === 1 ? '' : 's'));
      }
      if (result.stats && result.stats.free_space_bytes != null) {
        details.push(formatBytes(result.stats.free_space_bytes) + ' free');
      }
    } else {
      details.push((result.errors && result.errors.join(' · ')) || 'Unavailable');
    }

    const line1 = el('div', { cls: 'sv-line' }, [icon, document.createTextNode(' '), pathCode]);
    const line2 = el('div', { cls: 'sv-sub' + (ok ? ' sv-ok-sub' : ' sv-bad-sub'), text: details.join(' · ') });
    container.appendChild(line1);
    container.appendChild(line2);

    if (ok && result.warnings && result.warnings.length) {
      container.appendChild(el('div', { cls: 'sv-warn', text: '⚠ ' + result.warnings.join(' · ') }));
    }
  }

  // ── Output ───────────────────────────────────────────────────────────────

  async function loadOutput() {
    try {
      const { path } = await api('/api/storage/output');
      $('output-path-input').value = path || '';
      const verifyEl = $('output-verify');
      clearChildren(verifyEl);
      if (path) {
        await renderVerificationAt(verifyEl, path, 'output');
      } else {
        verifyEl.appendChild(el('p', {
          cls: 'text-sm text-muted',
          text: 'No output directory configured. MarkFlow will refuse to write until one is set.',
        }));
      }
    } catch (e) {
      showError(`Failed to load output: ${e.message}`);
    }
  }

  async function setOutput() {
    const path = $('output-path-input').value.trim();
    if (!path) { showError('Output path is required.'); return; }
    try {
      await api('/api/storage/output', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      await renderVerificationAt($('output-verify'), path, 'output');
    } catch (e) {
      await renderVerificationAt($('output-verify'), path, 'output', extractErrors(e));
    }
  }

  // ── Exclusions ───────────────────────────────────────────────────────────

  async function loadExclusions() {
    try {
      const { exclusions } = await api('/api/storage/exclusions');
      const tbody = $('exclusions-tbody');
      clearChildren(tbody);
      if (!exclusions.length) {
        tbody.appendChild(makeRow(['No exclusions configured.', '']));
        return;
      }
      for (const x of exclusions) {
        const rmBtn = el('button', {
          text: 'Remove', cls: 'btn btn-sm btn-danger',
          onClick: () => removeExclusion(x.id)
        });
        tbody.appendChild(makeRow([x.path_prefix, rmBtn]));
      }
    } catch (e) {
      showError(`Failed to load exclusions: ${e.message}`);
    }
  }

  async function addExclusion() {
    const prefix = $('exclusion-input').value.trim();
    if (!prefix) { showError('Path prefix is required.'); return; }
    try {
      await api('/api/storage/exclusions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path_prefix: prefix })
      });
      $('exclusion-input').value = '';
      loadExclusions();
    } catch (e) {
      showError(e.message);
    }
  }

  async function removeExclusion(id) {
    try {
      await api(`/api/storage/exclusions/${encodeURIComponent(id)}`, { method: 'DELETE' });
      loadExclusions();
    } catch (e) {
      showError(e.message);
    }
  }

  // ── Network shares ───────────────────────────────────────────────────────

  function statusDot(status) {
    const dot = el('span', { cls: 'mount-status-dot' });
    if (status && status.ok === true) {
      dot.classList.add('ok');
      dot.title = 'Mounted';
    } else if (status && status.ok === false) {
      dot.classList.add('err');
      dot.title = status.error || 'Unreachable';
    } else {
      dot.classList.add('unknown');
      dot.title = 'No probe yet';
    }
    return dot;
  }

  async function loadShares() {
    try {
      const { shares } = await api('/api/storage/shares');
      const tbody = $('shares-tbody');
      clearChildren(tbody);
      if (!shares.length) {
        tbody.appendChild(makeRow(['', '', 'No shares configured.', '', '']));
        return;
      }
      for (const s of shares) {
        const rmBtn = el('button', {
          text: 'Remove', cls: 'btn btn-sm btn-danger',
          onClick: () => removeShare(s.name)
        });
        const testBtn = el('button', {
          text: 'Test', cls: 'btn btn-sm',
          onClick: () => testShare(s.name)
        });
        const actions = el('div', { style: { display: 'flex', gap: '0.25rem' } }, [testBtn, rmBtn]);
        tbody.appendChild(makeRow([s.name, s.protocol, s.server, statusDot(s.status), actions]));
      }
    } catch (e) {
      showError(`Failed to load shares: ${e.message}`);
    }
  }

  async function removeShare(name) {
    if (!confirm(`Remove share "${name}"? Saved credentials will be deleted.`)) return;
    try {
      await api(`/api/storage/shares/${encodeURIComponent(name)}`, { method: 'DELETE' });
      loadShares();
    } catch (e) {
      showError(e.message);
    }
  }

  async function testShare(name) {
    try {
      const r = await api(`/api/storage/shares/${encodeURIComponent(name)}/test`, { method: 'POST' });
      alert(r.ok ? `OK — ${r.item_count} entries visible.` : `Failed: ${r.error}`);
    } catch (e) {
      showError(e.message);
    }
  }

  // ── Add-Share modal (A1) ─────────────────────────────────────────────────

  function openAddShareModal(prefill) {
    $('add-share-name').value = (prefill && prefill.name) || '';
    const proto = (prefill && prefill.protocol) || 'smb';
    for (const r of document.querySelectorAll('input[name="add-share-protocol"]')) {
      r.checked = (r.value === proto);
    }
    $('add-share-server').value = (prefill && prefill.server) || '';
    $('add-share-sharepath').value = (prefill && prefill.share_path) || '';
    $('add-share-username').value = '';
    $('add-share-password').value = '';
    $('add-share-readonly').checked = true;
    $('add-share-error').hidden = true;
    toggleAddShareSmbFields();
    $('add-share-modal').hidden = false;
    $('add-share-name').focus();
  }

  function closeAddShareModal() { $('add-share-modal').hidden = true; }

  function toggleAddShareSmbFields() {
    const proto = document.querySelector('input[name="add-share-protocol"]:checked').value;
    $('add-share-smb-fields').style.display = (proto === 'smb') ? '' : 'none';
  }

  async function submitAddShare() {
    const errBox = $('add-share-error');
    errBox.hidden = true;
    const name = $('add-share-name').value.trim();
    const proto = document.querySelector('input[name="add-share-protocol"]:checked').value;
    const server = $('add-share-server').value.trim();
    const sharePath = $('add-share-sharepath').value.trim();
    const username = $('add-share-username').value;
    const password = $('add-share-password').value;
    const readOnly = $('add-share-readonly').checked;

    // Client-side validation
    if (!/^[A-Za-z0-9_-]+$/.test(name)) {
      errBox.textContent = 'Name must be alphanumeric (dashes and underscores allowed).';
      errBox.hidden = false; return;
    }
    if (!server) { errBox.textContent = 'Server is required.'; errBox.hidden = false; return; }
    if (!sharePath) { errBox.textContent = 'Share path is required.'; errBox.hidden = false; return; }
    if (proto === 'smb' && !username) {
      errBox.textContent = 'SMB requires a username.'; errBox.hidden = false; return;
    }

    const submitBtn = $('add-share-submit');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Adding…';

    try {
      await api('/api/storage/shares', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name, protocol: proto, server, share: sharePath,
          username, password,
          options: { read_only: readOnly }
        })
      });
      closeAddShareModal();
      loadShares();
    } catch (e) {
      errBox.textContent = e.detail || e.message;
      errBox.hidden = false;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalText;
    }
  }

  // ── Discovery modal (A2) ─────────────────────────────────────────────────

  function openDiscoverModal() {
    // Reset tabs to subnet, clear output
    switchDiscoverTab('subnet');
    clearChildren($('discover-output'));
    $('discover-modal').hidden = false;
  }

  function closeDiscoverModal() { $('discover-modal').hidden = true; }

  function switchDiscoverTab(tab) {
    for (const btn of document.querySelectorAll('#discover-modal .tab-btn')) {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    }
    for (const p of document.querySelectorAll('#discover-modal .tab-panel')) {
      p.hidden = (p.dataset.tab !== tab);
    }
  }

  async function doDiscoverSubnet() {
    const subnet = $('discover-subnet').value.trim();
    if (!subnet) return;
    const out = $('discover-output');
    clearChildren(out);
    out.appendChild(el('p', { text: 'Scanning…', cls: 'text-muted' }));
    try {
      const { servers } = await api('/api/storage/shares/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'subnet', subnet })
      });
      renderDiscoverResults(servers, (s) => ({
        label: `${s.hostname} (${s.ip})`,
        prefill: { server: s.ip, protocol: 'smb' }
      }));
    } catch (e) {
      clearChildren(out);
      out.appendChild(el('p', { text: e.message, style: { color: '#f87171' } }));
    }
  }

  async function doDiscoverServer() {
    const server = $('discover-server').value.trim();
    if (!server) return;
    const protocol = document.querySelector('input[name="discover-protocol"]:checked').value;
    const out = $('discover-output');
    clearChildren(out);
    out.appendChild(el('p', { text: 'Probing…', cls: 'text-muted' }));
    try {
      const { shares } = await api('/api/storage/shares/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'server', server, protocol })
      });
      const smbProto = protocol === 'smb' ? 'smb' : 'nfsv3';
      renderDiscoverResults(shares, (s) => ({
        label: `${s.name || s.path}${s.comment ? ' — ' + s.comment : ''}`,
        prefill: {
          server,
          protocol: smbProto,
          share_path: s.name || s.path,
          name: (s.name || (s.path || '').split('/').pop() || '').replace(/[^A-Za-z0-9_-]/g, '') || 'share'
        }
      }));
    } catch (e) {
      clearChildren(out);
      out.appendChild(el('p', { text: e.message, style: { color: '#f87171' } }));
    }
  }

  function renderDiscoverResults(items, toEntry) {
    const out = $('discover-output');
    clearChildren(out);
    if (!items || !items.length) {
      out.appendChild(el('p', { text: 'No results.', cls: 'text-muted' }));
      return;
    }
    const ul = el('ul', { style: { listStyle: 'none', padding: '0', margin: '0' } });
    for (const it of items) {
      const entry = toEntry(it);
      const li = el('li', { style: { padding: '0.25rem 0' } });
      const btn = el('button', {
        text: entry.label,
        cls: 'btn btn-ghost btn-sm',
        style: { textAlign: 'left', width: '100%' },
        onClick: () => {
          closeDiscoverModal();
          openAddShareModal(entry.prefill);
        }
      });
      li.appendChild(btn);
      ul.appendChild(li);
    }
    out.appendChild(ul);
  }

  // ── Cloud Prefetch (B) ────────────────────────────────────────────────────

  const PREFETCH_KEYS = [
    'cloud_prefetch_enabled',
    'cloud_prefetch_concurrency',
    'cloud_prefetch_rate_limit',
    'cloud_prefetch_timeout_seconds',
    'cloud_prefetch_min_size_bytes',
    'cloud_prefetch_probe_all',
  ];

  async function loadPrefetch() {
    try {
      const { preferences } = await api('/api/preferences');
      for (const k of PREFETCH_KEYS) {
        const input = document.querySelector(`[data-pref="${k}"]`);
        if (!input) continue;
        const v = preferences[k] ?? '';
        if (input.type === 'checkbox') {
          input.checked = String(v).toLowerCase() === 'true';
        } else {
          input.value = v;
        }
      }
    } catch (e) {
      showError(`Failed to load prefetch prefs: ${e.message}`);
    }
  }

  async function savePrefetch() {
    const status = $('prefetch-save-status');
    flash(status, 'Saving…');
    try {
      for (const k of PREFETCH_KEYS) {
        const input = document.querySelector(`[data-pref="${k}"]`);
        if (!input) continue;
        const value = (input.type === 'checkbox') ? String(input.checked) : String(input.value);
        await api(`/api/preferences/${encodeURIComponent(k)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value })
        });
      }
      flash(status, 'Saved ✓', 3000);
    } catch (e) {
      flash(status, `Error: ${e.message}`, 6000);
    }
  }

  // ── First-run wizard ─────────────────────────────────────────────────────

  let _wizardStep = 1;
  const WIZARD_LAST = 5;

  function showStep(n) {
    _wizardStep = n;
    for (const s of document.querySelectorAll('.wizard-step')) {
      s.hidden = Number(s.dataset.step) !== n;
    }
    $('wizard-back').hidden = (n === 1);
    $('wizard-continue').textContent = (n === WIZARD_LAST) ? 'Start using MarkFlow' : 'Continue';
  }

  async function maybeAutoOpenWizard() {
    try {
      const r = await api('/api/storage/wizard-status');
      if (r.show) openWizard();
    } catch { /* non-critical */ }
  }

  function openWizard() {
    showStep(1);
    $('wizard-modal').hidden = false;
  }

  function closeWizard() {
    $('wizard-modal').hidden = true;
  }

  async function wizardSkip() {
    try {
      await api('/api/storage/wizard-dismiss', { method: 'POST' });
    } catch { /* non-critical */ }
    closeWizard();
  }

  async function wizardContinue() {
    if (_wizardStep === 2) {
      const path = $('wizard-source-path').value.trim();
      const fb = $('wizard-source-feedback');
      if (!path) { fb.textContent = 'Pick a folder to continue.'; return; }
      try {
        const v = await api('/api/storage/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, role: 'source' })
        });
        if (!v.ok) { fb.textContent = (v.errors || []).join(' '); return; }
        await addSource(path, '');
      } catch (e) { fb.textContent = e.message; return; }
    }
    if (_wizardStep === 3) {
      const path = $('wizard-output-path').value.trim();
      const fb = $('wizard-output-feedback');
      if (!path) { fb.textContent = 'Pick a folder to continue.'; return; }
      try {
        const v = await api('/api/storage/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, role: 'output' })
        });
        if (!v.ok) { fb.textContent = (v.errors || []).join(' '); return; }
        await api('/api/storage/output', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path })
        });
        loadOutput();
      } catch (e) { fb.textContent = e.message; return; }
    }
    if (_wizardStep === WIZARD_LAST) {
      closeWizard();
      return;
    }
    showStep(_wizardStep + 1);
  }

  // ── Init ─────────────────────────────────────────────────────────────────

  function init() {
    // Sources / output / exclusions
    $('btn-add-source').addEventListener('click', () => addSource());
    $('btn-save-output').addEventListener('click', setOutput);
    $('btn-add-exclusion').addEventListener('click', addExclusion);

    // Folder-picker buttons (A4)
    $('btn-browse-source').addEventListener('click',
      () => openFolderPicker('Select source folder', 'source', 'source-path-input'));
    $('btn-browse-output').addEventListener('click',
      () => openFolderPicker('Select output folder', 'output', 'output-path-input'));

    // Shares modals (A1)
    $('btn-add-share').addEventListener('click', () => openAddShareModal());
    $('add-share-cancel').addEventListener('click', closeAddShareModal);
    $('add-share-submit').addEventListener('click', submitAddShare);
    for (const r of document.querySelectorAll('input[name="add-share-protocol"]')) {
      r.addEventListener('change', toggleAddShareSmbFields);
    }

    // Discovery modal (A2)
    $('btn-discover-subnet').addEventListener('click', openDiscoverModal);
    $('btn-discover-server').addEventListener('click', () => {
      openDiscoverModal();
      switchDiscoverTab('server');
    });
    $('discover-close').addEventListener('click', closeDiscoverModal);
    for (const b of document.querySelectorAll('#discover-modal .tab-btn')) {
      b.addEventListener('click', () => switchDiscoverTab(b.dataset.tab));
    }
    $('discover-subnet-go').addEventListener('click', doDiscoverSubnet);
    $('discover-server-go').addEventListener('click', doDiscoverServer);

    // Host-OS override (A3)
    $('host-os-override').addEventListener('change', saveHostOsOverride);

    // Cloud Prefetch (B)
    $('btn-save-prefetch').addEventListener('click', savePrefetch);

    // Wizard
    $('btn-run-wizard').addEventListener('click', openWizard);
    $('wizard-skip').addEventListener('click', wizardSkip);
    $('wizard-back').addEventListener('click', () => { if (_wizardStep > 1) showStep(_wizardStep - 1); });
    $('wizard-continue').addEventListener('click', wizardContinue);

    loadHostInfo();
    loadSources();
    loadOutput();
    loadExclusions();
    loadShares();
    loadPrefetch();
    maybeAutoOpenWizard();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
