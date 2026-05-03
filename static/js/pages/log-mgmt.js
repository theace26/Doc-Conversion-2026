/* MFLogMgmt -- new-UX Log Management page component.
 *
 * Feature parity with /log-management.html:
 *   - File table with checkboxes (name/stream/status/size/modified/action)
 *   - Action bar: Download All, Download Selected, Compress Now, Refresh,
 *     Open Live Viewer
 *   - Settings card: compression format, retention days, rotation size, 7z cap
 *
 * Endpoints:
 *   GET  /api/logs                       -- file inventory
 *   GET  /api/logs/settings              -- compression/retention settings
 *   PUT  /api/logs/settings              -- update settings
 *   POST /api/logs/compress-now          -- trigger compression
 *   POST /api/logs/apply-retention-now   -- trigger retention
 *   GET  /api/logs/download/{name}       -- download single file
 *   POST /api/logs/download-bundle       -- download as zip (names: [] = all)
 *
 * Admin-only (boot script guards). Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var _cssInjected = false;
  function injectCss() {
    if (_cssInjected) return;
    _cssInjected = true;
    var style = document.createElement('style');
    style.textContent = [
      '.mf-lm { max-width:1100px; margin:0 auto; padding:1.5rem 1rem 3rem; }',
      '.mf-lm__head { margin-bottom:0.25rem; }',
      '.mf-lm__head h1 { margin:0 0 0.35rem; font-size:1.65rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-lm__head p { margin:0; font-size:0.88rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-lm__topbar { display:flex; flex-wrap:wrap; align-items:center; gap:0.65rem; padding:0.85rem 1rem; background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); margin:1rem 0; }',
      '.mf-lm__stats { display:flex; flex-wrap:wrap; gap:0.65rem; font-size:0.85rem; color:var(--mf-color-text-muted,#8892a4); margin-left:auto; }',
      '.mf-lm__stats strong { color:var(--mf-color-text,#e2e8f0); margin-left:0.25em; }',
      '.mf-lm__card { border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); background:var(--mf-surface,#16213e); padding:1.1rem 1.2rem; margin-bottom:1rem; }',
      '.mf-lm__card h2 { margin:0 0 0.35rem; font-size:1rem; font-weight:600; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-lm__card-hint { color:var(--mf-color-text-muted,#8892a4); font-size:0.84rem; margin:0 0 0.85rem; }',
      '.mf-lm__table { width:100%; border-collapse:collapse; font-size:0.88rem; }',
      '.mf-lm__table th { padding:0.5rem 0.7rem; text-align:left; border-bottom:1px solid var(--mf-border,#2a2a4a); font-size:0.74rem; color:var(--mf-color-text-muted,#8892a4); text-transform:uppercase; letter-spacing:0.03em; font-weight:600; }',
      '.mf-lm__table td { padding:0.5rem 0.7rem; border-bottom:1px solid var(--mf-border,#2a2a4a); vertical-align:middle; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-lm__table td.name { font-family:ui-monospace,monospace; font-size:0.84rem; }',
      '.mf-lm__table td.size, .mf-lm__table td.modified { color:var(--mf-color-text-muted,#8892a4); white-space:nowrap; }',
      '.mf-lm__pill { display:inline-block; padding:0.1em 0.6em; border-radius:999px; font-size:0.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.03em; }',
      '.mf-lm__pill--active { background:rgba(34,197,94,.18); color:#86efac; }',
      '.mf-lm__pill--rotated { background:rgba(217,119,6,.18); color:#fbbf24; }',
      '.mf-lm__pill--compressed { background:rgba(59,130,246,.18); color:#93c5fd; }',
      '.mf-lm__pill--other { background:rgba(156,163,175,.18); color:#d1d5db; }',
      '.mf-lm__settings-grid { display:grid; grid-template-columns:auto 1fr; gap:0.5rem 1rem; max-width:520px; }',
      '.mf-lm__settings-grid label { align-self:center; color:var(--mf-color-text-muted,#8892a4); font-size:0.88rem; }',
      '.mf-lm__settings-grid input, .mf-lm__settings-grid select { padding:0.35rem 0.55rem; background:var(--mf-surface-soft,#1a1a2e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.88rem; }',
      '.mf-lm__actions { display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }',
      '.mf-lm__cap-warn { font-size:0.78rem; padding:0.2rem 0; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-lm__cap-warn--warn { color:#fbbf24; }',
      '.mf-lm__cap-warn--error { color:#f87171; }',
      '.mf-lm__save-note { font-size:0.82rem; color:var(--mf-color-success,#22c55e); opacity:0; transition:opacity .2s; align-self:center; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }
  function clearEl(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function fmtBytes(n) {
    if (n == null) return '-';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
    return (n / 1073741824).toFixed(2) + ' GB';
  }

  function fmtDateTime(iso) {
    if (!iso) return '-';
    try { var d = new Date(iso); return isNaN(d.getTime()) ? String(iso) : d.toLocaleString(); }
    catch (e) { return String(iso); }
  }

  function showToast(msg) {
    var t = document.createElement('div');
    t.className = 'mf-toast mf-toast--info';
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 250);
    }, 2400);
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFLogMgmt.mount: slot is required');
    injectCss();
    clearEl(slot);
    opts = opts || {};

    var files = opts.files || [];
    var totalSizeBytes = opts.totalSizeBytes || 0;
    var settings = opts.settings || {};

    var wrap = el('div', 'mf-lm');

    var head = el('div', 'mf-lm__head');
    var h1 = el('h1'); h1.textContent = 'Log Management';
    var desc = el('p'); desc.textContent = 'Inventory, download, and inspect log files. Rotated files are auto-compressed every 6 hours.';
    head.appendChild(h1); head.appendChild(desc);
    wrap.appendChild(head);

    var topbar = el('div', 'mf-lm__topbar');
    var liveBtn = el('a', 'mf-pill mf-pill--primary mf-pill--sm');
    liveBtn.href = '/log-viewer-new.html'; liveBtn.textContent = 'Open Live Viewer';

    var dlAllBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    dlAllBtn.type = 'button'; dlAllBtn.textContent = 'Download All';

    var dlSelBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    dlSelBtn.type = 'button'; dlSelBtn.textContent = 'Download Selected (0)'; dlSelBtn.disabled = true;

    var compressBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    compressBtn.type = 'button'; compressBtn.textContent = 'Compress Rotated Now';

    var refreshBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    refreshBtn.type = 'button'; refreshBtn.textContent = 'Refresh';

    var statsEl = el('div', 'mf-lm__stats');
    [liveBtn, dlAllBtn, dlSelBtn, compressBtn, refreshBtn, statsEl].forEach(function (n) { topbar.appendChild(n); });
    wrap.appendChild(topbar);

    var filesCard = el('div', 'mf-lm__card');
    var filesH2 = el('h2'); filesH2.textContent = 'Log Files';
    var filesHint = el('p', 'mf-lm__card-hint');
    filesHint.textContent = 'Active (currently being written), rotated (awaiting compression), compressed (archived). Click a filename to open in the live viewer.';

    var table = el('table', 'mf-lm__table');
    var thead = el('thead');
    var hrow = el('tr');
    var thCb = el('th'); thCb.style.width = '2rem';
    var selectAllCb = document.createElement('input'); selectAllCb.type = 'checkbox';
    thCb.appendChild(selectAllCb);
    hrow.appendChild(thCb);
    ['File', 'Stream', 'Status', 'Size', 'Modified', 'Action'].forEach(function (txt, i) {
      var th = el('th'); th.textContent = txt;
      if (i === 3) th.style.width = '9rem';
      if (i === 4) th.style.width = '13rem';
      if (i === 5) th.style.width = '8rem';
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);
    var tbody = el('tbody');
    table.appendChild(tbody);
    filesCard.appendChild(filesH2);
    filesCard.appendChild(filesHint);
    filesCard.appendChild(table);
    wrap.appendChild(filesCard);

    var settingsCard = el('details', 'mf-lm__card');
    var summary = el('summary');
    summary.style.cssText = 'cursor:pointer;font-weight:600;color:var(--mf-color-text,#e2e8f0)';
    summary.textContent = 'Settings';
    settingsCard.appendChild(summary);

    var settHint = el('p', 'mf-lm__card-hint'); settHint.style.marginTop = '0.75rem';
    settHint.textContent = 'Compression and retention settings. Changes apply on the next scheduled run unless you click "Compress Rotated Now".';
    settingsCard.appendChild(settHint);

    var grid = el('div', 'mf-lm__settings-grid');
    var fmtLabel = el('label'); fmtLabel.textContent = 'Compression format';
    var fmtSel = el('select'); fmtSel.style.width = 'auto';
    ['gz', 'tar.gz', '7z'].forEach(function (fmt) {
      var opt = el('option'); opt.value = fmt; opt.textContent = fmt;
      if (fmt === (settings.compression_format || 'gz')) opt.selected = true;
      fmtSel.appendChild(opt);
    });

    var retLabel = el('label'); retLabel.textContent = 'Retention (days)';
    var retInp = el('input'); retInp.type = 'number'; retInp.min = '1'; retInp.max = '3650'; retInp.style.width = '8rem';
    retInp.value = String(settings.retention_days || 30);

    var rotLabel = el('label'); rotLabel.textContent = 'Rotation size per log (MB)';
    var rotInp = el('input'); rotInp.type = 'number'; rotInp.min = '10'; rotInp.max = '10240'; rotInp.style.width = '8rem';
    rotInp.value = String(settings.rotation_max_size_mb || 100);

    var sevenZLabel = el('label'); sevenZLabel.textContent = '7z search byte cap (MB)';
    var sevenZWrap = el('div');
    var sevenZInp = el('input'); sevenZInp.type = 'number'; sevenZInp.min = '1'; sevenZInp.max = '4096'; sevenZInp.style.width = '8rem';
    sevenZInp.value = String(settings.seven_z_max_mb || 200);
    var capWarn = el('div', 'mf-lm__cap-warn');
    capWarn.textContent = 'Default 200 MB. Caps how much of a .7z log the search reads.';
    sevenZWrap.appendChild(sevenZInp); sevenZWrap.appendChild(capWarn);

    var emptyCell = el('div');
    var actionsWrap = el('div', 'mf-lm__actions');
    var saveBtn = el('button', 'mf-pill mf-pill--primary mf-pill--sm');
    saveBtn.type = 'button'; saveBtn.textContent = 'Save Settings';
    var applyRetBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    applyRetBtn.type = 'button'; applyRetBtn.textContent = 'Apply Retention Now';
    var savedNote = el('span', 'mf-lm__save-note'); savedNote.textContent = 'Saved';
    actionsWrap.appendChild(saveBtn); actionsWrap.appendChild(applyRetBtn); actionsWrap.appendChild(savedNote);
    [fmtLabel, fmtSel, retLabel, retInp, rotLabel, rotInp, sevenZLabel, sevenZWrap, emptyCell, actionsWrap]
      .forEach(function (n) { grid.appendChild(n); });
    settingsCard.appendChild(grid);
    wrap.appendChild(settingsCard);
    slot.appendChild(wrap);

    function renderFiles(fileList, total) {
      clearEl(tbody); clearEl(statsEl);
      var s1 = el('span'); s1.textContent = 'Files:';
      var s1b = el('strong'); s1b.textContent = String(fileList.length); s1.appendChild(s1b); statsEl.appendChild(s1);
      var s2 = el('span'); s2.textContent = 'Total:';
      var s2b = el('strong'); s2b.textContent = fmtBytes(total); s2.appendChild(s2b); statsEl.appendChild(s2);
      if (fileList.length === 0) {
        var tr0 = el('tr'); var td0 = el('td'); td0.colSpan = 7;
        td0.style.color = 'var(--mf-color-text-muted,#8892a4)'; td0.textContent = 'No log files found.';
        tr0.appendChild(td0); tbody.appendChild(tr0); updateSelection(); return;
      }
      fileList.forEach(function (f) {
        var tr = el('tr');
        var cbTd = el('td');
        var cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'row-cb'; cb.dataset.name = f.name;
        cb.addEventListener('change', updateSelection); cbTd.appendChild(cb); tr.appendChild(cbTd);
        var nameTd = el('td', 'name');
        var a = document.createElement('a');
        a.href = '/log-viewer-new.html?file=' + encodeURIComponent(f.name);
        a.textContent = f.name; nameTd.appendChild(a); tr.appendChild(nameTd);
        var streamTd = el('td'); streamTd.textContent = f.stream || '-'; tr.appendChild(streamTd);
        var statTd = el('td');
        var pill = el('span', 'mf-lm__pill mf-lm__pill--' + (f.status || 'other'));
        pill.textContent = f.status + (f.compression ? ' - ' + f.compression : '');
        statTd.appendChild(pill); tr.appendChild(statTd);
        var sizeTd = el('td', 'size'); sizeTd.textContent = fmtBytes(f.size_bytes); tr.appendChild(sizeTd);
        var modTd = el('td', 'modified'); modTd.textContent = fmtDateTime(f.modified); tr.appendChild(modTd);
        var actTd = el('td');
        var dlA = el('a', 'mf-pill mf-pill--ghost mf-pill--sm');
        dlA.href = '/api/logs/download/' + encodeURIComponent(f.name);
        dlA.setAttribute('download', ''); dlA.textContent = 'Download';
        actTd.appendChild(dlA); tr.appendChild(actTd);
        tbody.appendChild(tr);
      });
      updateSelection();
    }

    function updateSelection() {
      var checked = tbody.querySelectorAll('input.row-cb:checked');
      dlSelBtn.disabled = checked.length === 0;
      dlSelBtn.textContent = 'Download Selected (' + checked.length + ')';
    }

    selectAllCb.addEventListener('change', function () {
      tbody.querySelectorAll('input.row-cb').forEach(function (c) { c.checked = selectAllCb.checked; });
      updateSelection();
    });

    function loadInventory() {
      clearEl(tbody);
      var tr0 = el('tr'); var td0 = el('td'); td0.colSpan = 7;
      td0.style.color = 'var(--mf-color-text-muted,#8892a4)'; td0.textContent = 'Loading…';
      tr0.appendChild(td0); tbody.appendChild(tr0);
      fetch('/api/logs', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) { renderFiles(data.logs || [], data.total_size_bytes || 0); })
        .catch(function (e) {
          clearEl(tbody);
          var tr = el('tr'); var td = el('td'); td.colSpan = 7;
          td.style.color = '#f87171'; td.textContent = 'Failed to load logs: ' + e;
          tr.appendChild(td); tbody.appendChild(tr);
        });
    }

    function downloadBundle(names) {
      fetch('/api/logs/download-bundle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ names: names }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.blob().then(function (blob) {
            var cd = r.headers.get('Content-Disposition') || '';
            var cdParts = cd.split('filename=');
            var fname = cdParts.length > 1 ? cdParts[1].replace(/"/g, '') : 'markflow-logs.zip';
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a'); a.href = url; a.download = fname;
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast('Bundle downloaded');
          });
        })
        .catch(function (e) { showToast('Download failed: ' + e.message); });
    }

    dlAllBtn.addEventListener('click', function () { downloadBundle([]); });
    dlSelBtn.addEventListener('click', function () {
      var names = Array.from(tbody.querySelectorAll('input.row-cb:checked')).map(function (c) { return c.dataset.name; });
      if (names.length) downloadBundle(names);
    });

    compressBtn.addEventListener('click', function () {
      compressBtn.disabled = true;
      fetch('/api/logs/compress-now', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin', body: '{}',
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) {
          showToast('Compressed ' + d.compressed + ' file(s); reclaimed ' + fmtBytes(d.bytes_reclaimed));
          loadInventory();
        })
        .catch(function (e) { showToast('Compress failed: ' + e); })
        .finally(function () { compressBtn.disabled = false; });
    });

    applyRetBtn.addEventListener('click', function () {
      if (!confirm('Apply retention now? Compressed logs older than the configured window will be deleted.')) return;
      applyRetBtn.disabled = true;
      fetch('/api/logs/apply-retention-now', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin', body: '{}',
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) {
          showToast('Deleted ' + d.deleted + ' file(s); reclaimed ' + fmtBytes(d.bytes_reclaimed));
          loadInventory();
        })
        .catch(function (e) { showToast('Retention failed: ' + e); })
        .finally(function () { applyRetBtn.disabled = false; });
    });

    refreshBtn.addEventListener('click', loadInventory);

    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      var body = {
        compression_format: fmtSel.value,
        retention_days: parseInt(retInp.value, 10) || 30,
        rotation_max_size_mb: parseInt(rotInp.value, 10) || 100,
        seven_z_max_mb: parseInt(sevenZInp.value, 10) || 200,
      };
      fetch('/api/logs/settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin', body: JSON.stringify(body),
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function () {
          savedNote.style.opacity = '1';
          setTimeout(function () { savedNote.style.opacity = '0'; }, 2000);
        })
        .catch(function (e) { showToast('Save failed: ' + e); })
        .finally(function () { saveBtn.disabled = false; });
    });

    renderFiles(files, totalSizeBytes);
  }

  global.MFLogMgmt = { mount: mount };
})(window);
