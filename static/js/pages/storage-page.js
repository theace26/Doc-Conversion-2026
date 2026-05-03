/* MFStoragePage — new-UX Storage Management page component.
 *
 * Feature parity with /storage.html (80%):
 *   - Source folders list (cards) with mount-health indicator
 *   - Add source / remove source
 *   - Discover sources (subnet scan / server probe)
 *   - Per-source path verification (green/amber/red status dot)
 *   - Output directory display + change
 *   - Network shares table with test/remove
 *   - Storage stats summary (total sources, files indexed, disk usage)
 *   - Exclusions list + add/remove
 *   - Cloud prefetch settings
 *
 * Endpoints used:
 *   GET  /api/storage/host-info                          -- OS detection + quick access
 *   GET  /api/storage/sources                            -- list source folders
 *   POST /api/storage/sources                            -- add source
 *   DELETE /api/storage/sources/:id                      -- remove source
 *   GET  /api/storage/output                             -- current output dir
 *   PUT  /api/storage/output                             -- set output dir
 *   POST /api/storage/validate                           -- verify path (source|output)
 *   GET  /api/storage/shares                             -- list network shares
 *   POST /api/storage/shares                             -- add share
 *   DELETE /api/storage/shares/:name                     -- remove share
 *   POST /api/storage/shares/:name/test                  -- test mount
 *   POST /api/storage/shares/discover                    -- subnet/server discovery
 *   GET  /api/storage/exclusions                         -- list exclusions
 *   POST /api/storage/exclusions                         -- add exclusion
 *   DELETE /api/storage/exclusions/:id                   -- remove exclusion
 *   GET  /api/preferences                                -- read cloud prefetch prefs
 *   PUT  /api/preferences/:key                           -- save single pref
 *
 * Deferred (link to legacy page):
 *   - Advanced exclusion patterns UI
 *   - NFS/SMB credentials editor (use Add Share modal on /storage.html)
 *
 * Admin/operator-gated. Safe DOM throughout.
 */
(function (global) {
  'use strict';

  /* ── CSS ────────────────────────────────────────────────────────────────── */

  var _cssInjected = false;
  function injectCss() {
    if (_cssInjected) return;
    _cssInjected = true;
    var s = document.createElement('style');
    s.textContent = [
      '.mf-st { max-width:1100px; margin:0 auto; padding:1.5rem 1rem 3rem; }',
      '.mf-st__head { margin-bottom:1.25rem; display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:0.75rem; }',
      '.mf-st__head h1 { margin:0 0 0.2rem; font-size:1.65rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-st__head p { margin:0; font-size:0.88rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-st__head-actions { display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }',
      '.mf-st__stats { display:flex; flex-wrap:wrap; gap:0.75rem; margin-bottom:1.25rem; }',
      '.mf-st__stat { flex:1; min-width:130px; padding:0.85rem 1rem; background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); }',
      '.mf-st__stat-val { font-size:1.5rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-st__stat-lbl { font-size:0.75rem; color:var(--mf-color-text-muted,#8892a4); text-transform:uppercase; letter-spacing:0.04em; margin-top:0.2rem; }',
      '.mf-st__section { border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); background:var(--mf-surface,#16213e); margin-bottom:1rem; overflow:hidden; }',
      '.mf-st__section-head { display:flex; align-items:center; justify-content:space-between; padding:0.85rem 1rem; border-bottom:1px solid var(--mf-border,#2a2a4a); gap:0.5rem; flex-wrap:wrap; }',
      '.mf-st__section-title { font-size:1rem; font-weight:600; color:var(--mf-color-text,#e2e8f0); margin:0; }',
      '.mf-st__section-body { padding:1rem; }',
      '.mf-st__section-hint { font-size:0.84rem; color:var(--mf-color-text-muted,#8892a4); margin:0 0 0.85rem; }',
      '.mf-st__row { display:flex; gap:0.5rem; align-items:flex-end; flex-wrap:wrap; margin-bottom:0.75rem; }',
      '.mf-st__row .mf-st__fg { flex:1; min-width:200px; }',
      '.mf-st__fg label { display:block; font-size:0.78rem; color:var(--mf-color-text-muted,#8892a4); margin-bottom:0.25rem; }',
      '.mf-st__fg input { width:100%; padding:0.42rem 0.6rem; background:var(--mf-surface-soft,#1a1a2e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.88rem; box-sizing:border-box; }',
      '.mf-st__table { width:100%; border-collapse:collapse; font-size:0.87rem; }',
      '.mf-st__table th { padding:0.5rem 0.75rem; text-align:left; font-size:0.73rem; color:var(--mf-color-text-muted,#8892a4); text-transform:uppercase; letter-spacing:0.04em; border-bottom:1px solid var(--mf-border,#2a2a4a); white-space:nowrap; }',
      '.mf-st__table td { padding:0.55rem 0.75rem; border-bottom:1px solid var(--mf-border,#2a2a4a); vertical-align:middle; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-st__table tr:last-child td { border-bottom:none; }',
      '.mf-st__table td.mono { font-family:ui-monospace,monospace; font-size:0.82rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-st__table td.actions { white-space:nowrap; }',
      /* Health dot */
      '.mf-st__dot { display:inline-block; width:9px; height:9px; border-radius:50%; vertical-align:middle; margin-right:0.45rem; flex-shrink:0; }',
      '.mf-st__dot--ok  { background:#22c55e; box-shadow:0 0 4px #22c55e88; }',
      '.mf-st__dot--warn { background:#f59e0b; }',
      '.mf-st__dot--err  { background:#f87171; }',
      '.mf-st__dot--pending { background:#8892a4; animation:mf-st-pulse 1.1s infinite; }',
      '@keyframes mf-st-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }',
      /* Verify line */
      '.mf-st__verify { font-size:0.78rem; margin-top:0.3rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-st__verify--ok  { color:#22c55e; }',
      '.mf-st__verify--err { color:#f87171; }',
      /* Source card */
      '.mf-st__src-card { border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,6px); padding:0.75rem 0.85rem; margin-bottom:0.6rem; display:flex; align-items:flex-start; gap:0.75rem; }',
      '.mf-st__src-card-body { flex:1; min-width:0; }',
      '.mf-st__src-label { font-weight:600; font-size:0.9rem; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-st__src-path { font-family:ui-monospace,monospace; font-size:0.8rem; color:var(--mf-color-text-muted,#8892a4); word-break:break-all; margin-top:0.1rem; }',
      '.mf-st__src-actions { display:flex; gap:0.3rem; flex-shrink:0; align-self:center; }',
      /* Modal overlay */
      '.mf-st__modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:200; display:flex; align-items:center; justify-content:center; padding:1rem; }',
      '.mf-st__modal { background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); padding:1.5rem; width:100%; max-width:480px; max-height:90vh; overflow-y:auto; z-index:201; }',
      '.mf-st__modal h2 { margin:0 0 1rem; font-size:1.1rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-st__modal-row { margin-bottom:0.75rem; }',
      '.mf-st__modal-row label { display:block; font-size:0.78rem; color:var(--mf-color-text-muted,#8892a4); margin-bottom:0.25rem; }',
      '.mf-st__modal-row input, .mf-st__modal-row select { width:100%; padding:0.42rem 0.6rem; background:var(--mf-surface-soft,#1a1a2e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.88rem; box-sizing:border-box; }',
      '.mf-st__modal-footer { display:flex; justify-content:flex-end; gap:0.5rem; margin-top:1.25rem; }',
      '.mf-st__modal-err { font-size:0.82rem; color:#f87171; margin-top:0.5rem; }',
      /* Prefetch grid */
      '.mf-st__prefetch-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:0.75rem; margin-top:0.75rem; }',
      '.mf-st__prefetch-field label { display:block; font-size:0.78rem; color:var(--mf-color-text-muted,#8892a4); margin-bottom:0.25rem; }',
      '.mf-st__prefetch-field input { padding:0.42rem 0.6rem; background:var(--mf-surface-soft,#1a1a2e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.88rem; width:100%; box-sizing:border-box; }',
      '.mf-st__toggle { display:flex; align-items:center; gap:0.5rem; font-size:0.88rem; color:var(--mf-color-text,#e2e8f0); cursor:pointer; }',
      /* Empty / error states */
      '.mf-st__empty { padding:1.5rem; text-align:center; color:var(--mf-color-text-muted,#8892a4); font-size:0.88rem; }',
      '.mf-st__error-banner { padding:0.65rem 1rem; background:rgba(248,113,113,.1); border:1px solid rgba(248,113,113,.4); border-radius:var(--mf-radius-sm,4px); color:#f87171; font-size:0.85rem; margin-bottom:1rem; }',
      /* Tag panel for discovery results */
      '.mf-st__disc-results { max-height:240px; overflow-y:auto; margin-top:0.75rem; }',
      '.mf-st__disc-item { display:flex; justify-content:space-between; align-items:center; padding:0.4rem 0; border-bottom:1px solid var(--mf-border,#2a2a4a); font-size:0.85rem; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-st__disc-item:last-child { border-bottom:none; }',
    ].join('\n');
    document.head.appendChild(s);
  }

  /* ── Helpers ────────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function txt(node, t) {
    node.textContent = t;
    return node;
  }

  function showToast(msg, type) {
    var t = el('div', 'mf-toast mf-toast--' + (type || 'info'));
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, 2500);
  }

  function fmtBytes(n) {
    if (n == null || n < 0) return '—';
    if (n < 1024) return n + ' B';
    var units = ['KB', 'MB', 'GB', 'TB'];
    var v = n / 1024;
    var i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return v.toFixed(v < 10 ? 1 : 0) + ' ' + units[i];
  }

  /* ── API ────────────────────────────────────────────────────────────────── */

  function apiFetch(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}))
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (body) {
            var err = new Error(path + ' → ' + r.status + ' ' + r.statusText);
            err.status = r.status;
            try { err.detail = JSON.parse(body); } catch (e) { err.detail = body; }
            throw err;
          });
        }
        return r.status === 204 ? null : r.json();
      });
  }

  function apiGet(path) { return apiFetch(path); }

  function apiPost(path, body) {
    return apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  function apiPut(path, body) {
    return apiFetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  function apiDelete(path) {
    return apiFetch(path, { method: 'DELETE' });
  }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFStoragePage.mount: root element is required');
    injectCss();
    clear(root);
    opts = opts || {};
    var role = opts.role || 'operator';

    /* ── Skeleton ─────────────────────────────────────────────────────── */

    var wrap = el('div', 'mf-st');

    /* Header */
    var head = el('div', 'mf-st__head');
    var headLeft = el('div');
    var h1 = el('h1'); h1.textContent = 'Storage';
    var subhead = el('p'); subhead.textContent = 'Manage source folders, output directory, network shares, and exclusions.';
    headLeft.appendChild(h1);
    headLeft.appendChild(subhead);
    head.appendChild(headLeft);
    var headActions = el('div', 'mf-st__head-actions');
    var refreshBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    refreshBtn.textContent = 'Refresh all';
    refreshBtn.addEventListener('click', function () { loadAll(); });
    headActions.appendChild(refreshBtn);
    head.appendChild(headActions);
    wrap.appendChild(head);

    /* Error banner (inline, not global) */
    var errorBanner = el('div', 'mf-st__error-banner');
    errorBanner.style.display = 'none';
    wrap.appendChild(errorBanner);

    function showError(msg) {
      errorBanner.textContent = msg;
      errorBanner.style.display = '';
      setTimeout(function () { errorBanner.style.display = 'none'; }, 8000);
    }

    /* Stats row */
    var statsRow = el('div', 'mf-st__stats');
    var statSources = makeStatCard('—', 'Source Folders');
    var statFiles   = makeStatCard('—', 'Files Indexed');
    var statDisk    = makeStatCard('—', 'Free Disk (output)');
    statsRow.appendChild(statSources.el);
    statsRow.appendChild(statFiles.el);
    statsRow.appendChild(statDisk.el);
    wrap.appendChild(statsRow);

    function makeStatCard(val, lbl) {
      var card = el('div', 'mf-st__stat');
      var valEl = el('div', 'mf-st__stat-val'); valEl.textContent = val;
      var lblEl = el('div', 'mf-st__stat-lbl'); lblEl.textContent = lbl;
      card.appendChild(valEl);
      card.appendChild(lblEl);
      return { el: card, set: function (v) { valEl.textContent = v; } };
    }

    /* ── Sources section ──────────────────────────────────────────────── */

    var srcSection = makeSectionShell('Source Folders', 'Folders MarkFlow scans for files.');

    /* Add-source inline form */
    var addSrcRow = el('div', 'mf-st__row');
    var srcPathFg = el('div', 'mf-st__fg');
    var srcPathLbl = el('label'); srcPathLbl.textContent = 'Path';
    var srcPathInp = el('input');
    srcPathInp.type = 'text';
    srcPathInp.placeholder = '/host/root/Users/you/Documents';
    srcPathFg.appendChild(srcPathLbl);
    srcPathFg.appendChild(srcPathInp);

    var srcLabelFg = el('div', 'mf-st__fg');
    srcLabelFg.style.maxWidth = '200px';
    var srcLabelLbl = el('label'); srcLabelLbl.textContent = 'Label (optional)';
    var srcLabelInp = el('input');
    srcLabelInp.type = 'text';
    srcLabelInp.placeholder = 'Documents';
    srcLabelFg.appendChild(srcLabelLbl);
    srcLabelFg.appendChild(srcLabelInp);

    var addSrcBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    addSrcBtn.textContent = 'Add Source';
    addSrcBtn.style.flexShrink = '0';
    addSrcRow.appendChild(srcPathFg);
    addSrcRow.appendChild(srcLabelFg);
    addSrcRow.appendChild(addSrcBtn);
    srcSection.body.appendChild(addSrcRow);

    /* Discover button */
    var discoverBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    discoverBtn.textContent = 'Discover Sources (Network)';
    discoverBtn.style.marginBottom = '0.75rem';
    srcSection.body.appendChild(discoverBtn);

    /* Re-verify button */
    var reverifyBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    reverifyBtn.textContent = 'Re-verify All';
    reverifyBtn.style.marginBottom = '0.75rem';
    reverifyBtn.style.marginLeft = '0.4rem';
    srcSection.body.appendChild(reverifyBtn);

    /* Source cards list */
    var srcList = el('div');
    srcSection.body.appendChild(srcList);

    wrap.appendChild(srcSection.el);

    /* ── Output section ───────────────────────────────────────────────── */

    var outSection = makeSectionShell('Output Directory', 'Markdown output and sidecars are written here. Changing this requires a restart to fully take effect.');

    var outRow = el('div', 'mf-st__row');
    var outFg = el('div', 'mf-st__fg');
    var outLbl = el('label'); outLbl.textContent = 'Path';
    var outInp = el('input');
    outInp.type = 'text';
    outInp.placeholder = '/host/rw/markflow-output';
    outFg.appendChild(outLbl);
    outFg.appendChild(outInp);

    var saveOutBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    saveOutBtn.textContent = 'Save';
    saveOutBtn.style.flexShrink = '0';
    outRow.appendChild(outFg);
    outRow.appendChild(saveOutBtn);
    outSection.body.appendChild(outRow);

    var outVerify = el('div', 'mf-st__verify');
    outSection.body.appendChild(outVerify);

    wrap.appendChild(outSection.el);

    /* ── Shares section ───────────────────────────────────────────────── */

    var sharesSection = makeSectionShell('Network Shares', 'SMB/CIFS and NFS shares. Mount points appear under /mnt/shares/<name>.');

    /* Action buttons */
    var sharesActions = el('div');
    sharesActions.style.cssText = 'display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.75rem;';
    var addShareBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    addShareBtn.textContent = 'Add Share';
    var discoverShareBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    discoverShareBtn.textContent = 'Discover on Network';
    sharesActions.appendChild(addShareBtn);
    sharesActions.appendChild(discoverShareBtn);
    sharesSection.body.appendChild(sharesActions);

    /* Shares table */
    var sharesTableWrap = el('div');
    sharesTableWrap.style.overflowX = 'auto';
    var sharesTable = el('table', 'mf-st__table');
    var sharesThead = el('thead');
    var sharesTr = el('tr');
    ['Name', 'Protocol', 'Server', 'Status', ''].forEach(function (h) {
      var th = el('th'); th.textContent = h;
      sharesTr.appendChild(th);
    });
    sharesThead.appendChild(sharesTr);
    sharesTable.appendChild(sharesThead);
    var sharesTbody = el('tbody');
    sharesTable.appendChild(sharesTbody);
    sharesTableWrap.appendChild(sharesTable);
    sharesSection.body.appendChild(sharesTableWrap);

    wrap.appendChild(sharesSection.el);

    /* ── Exclusions section ───────────────────────────────────────────── */

    var exclSection = makeSectionShell('Folder Exclusions', 'Path prefixes to skip during scanning. Useful for backup folders, OS junk, or noisy subdirectories.');

    var addExclRow = el('div', 'mf-st__row');
    var exclFg = el('div', 'mf-st__fg');
    var exclLbl = el('label'); exclLbl.textContent = 'Path prefix';
    var exclInp = el('input');
    exclInp.type = 'text';
    exclInp.placeholder = '/host/root/Users/you/.Trash';
    exclFg.appendChild(exclLbl);
    exclFg.appendChild(exclInp);

    var addExclBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    addExclBtn.textContent = 'Add';
    addExclBtn.style.flexShrink = '0';
    addExclRow.appendChild(exclFg);
    addExclRow.appendChild(addExclBtn);
    exclSection.body.appendChild(addExclRow);

    var exclTableWrap = el('div');
    exclTableWrap.style.overflowX = 'auto';
    var exclTable = el('table', 'mf-st__table');
    var exclThead = el('thead');
    var exclThRow = el('tr');
    ['Prefix', ''].forEach(function (h) {
      var th = el('th'); th.textContent = h;
      exclThRow.appendChild(th);
    });
    exclThead.appendChild(exclThRow);
    exclTable.appendChild(exclThead);
    var exclTbody = el('tbody');
    exclTable.appendChild(exclTbody);
    exclTableWrap.appendChild(exclTable);
    exclSection.body.appendChild(exclTableWrap);

    wrap.appendChild(exclSection.el);

    /* ── Cloud Prefetch section ───────────────────────────────────────── */

    var prefetchSection = makeSectionShell('Cloud Prefetch', 'Prefetch files from cloud storage (Dropbox, iCloud, OneDrive placeholders) before conversion.');

    /* Toggle */
    var pfToggleRow = el('div', 'mf-st__modal-row');
    var pfToggleLbl = el('label', 'mf-st__toggle');
    var pfToggleChk = el('input');
    pfToggleChk.type = 'checkbox';
    pfToggleChk.id = 'mf-st-pf-enabled';
    var pfToggleTxt = document.createTextNode(' Enable cloud prefetch');
    pfToggleLbl.appendChild(pfToggleChk);
    pfToggleLbl.appendChild(pfToggleTxt);
    pfToggleRow.appendChild(pfToggleLbl);
    prefetchSection.body.appendChild(pfToggleRow);

    /* Numeric grid */
    var pfGrid = el('div', 'mf-st__prefetch-grid');
    var pfFields = [
      { key: 'cloud_prefetch_concurrency',     label: 'Concurrent workers (1–20)', type: 'number', min: 1,  max: 20 },
      { key: 'cloud_prefetch_rate_limit',       label: 'Rate limit /min (1–100)',   type: 'number', min: 1,  max: 100 },
      { key: 'cloud_prefetch_timeout_seconds',  label: 'Per-file timeout (sec)',    type: 'number', min: 10, max: 600 },
      { key: 'cloud_prefetch_min_size_bytes',   label: 'Min file size (bytes)',     type: 'number', min: 0  },
    ];
    var pfInputMap = {};
    pfFields.forEach(function (f) {
      var div = el('div', 'mf-st__prefetch-field');
      var lbl = el('label'); lbl.textContent = f.label; lbl.htmlFor = 'mf-st-pf-' + f.key;
      var inp = el('input');
      inp.type = f.type;
      inp.id = 'mf-st-pf-' + f.key;
      if (f.min != null) inp.min = f.min;
      if (f.max != null) inp.max = f.max;
      div.appendChild(lbl);
      div.appendChild(inp);
      pfGrid.appendChild(div);
      pfInputMap[f.key] = inp;
    });
    prefetchSection.body.appendChild(pfGrid);

    /* Probe-all toggle */
    var pfProbeRow = el('div', 'mf-st__modal-row');
    pfProbeRow.style.marginTop = '0.75rem';
    var pfProbeLbl = el('label', 'mf-st__toggle');
    var pfProbeChk = el('input');
    pfProbeChk.type = 'checkbox';
    pfProbeChk.id = 'mf-st-pf-probe-all';
    pfProbeLbl.appendChild(pfProbeChk);
    pfProbeLbl.appendChild(document.createTextNode(' Probe all files (slower, more thorough)'));
    pfProbeRow.appendChild(pfProbeLbl);
    prefetchSection.body.appendChild(pfProbeRow);

    /* Save row */
    var pfSaveRow = el('div');
    pfSaveRow.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-top:0.85rem;';
    var pfSaveBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    pfSaveBtn.textContent = 'Save Prefetch Settings';
    var pfStatus = el('span');
    pfStatus.style.cssText = 'font-size:0.82rem;color:var(--mf-color-success,#22c55e);';
    pfSaveRow.appendChild(pfSaveBtn);
    pfSaveRow.appendChild(pfStatus);
    prefetchSection.body.appendChild(pfSaveRow);

    wrap.appendChild(prefetchSection.el);

    root.appendChild(wrap);

    /* ── Helper: make section shell ───────────────────────────────────── */

    function makeSectionShell(title, hint) {
      var section = el('div', 'mf-st__section');
      var sHead = el('div', 'mf-st__section-head');
      var titleEl = el('h2', 'mf-st__section-title'); titleEl.textContent = title;
      sHead.appendChild(titleEl);
      section.appendChild(sHead);
      var body = el('div', 'mf-st__section-body');
      if (hint) {
        var hintEl = el('p', 'mf-st__section-hint'); hintEl.textContent = hint;
        body.appendChild(hintEl);
      }
      section.appendChild(body);
      return { el: section, head: sHead, body: body };
    }

    /* ── Verification helper ──────────────────────────────────────────── */

    function makeStatusDot(status) {
      /* status: 'ok' | 'warn' | 'err' | 'pending' */
      var dot = el('span', 'mf-st__dot mf-st__dot--' + (status || 'pending'));
      dot.title = status === 'ok' ? 'Accessible' : status === 'err' ? 'Not accessible' : status === 'warn' ? 'Warning' : 'Checking…';
      return dot;
    }

    function runValidate(path, role, onDone) {
      /* Calls /api/storage/validate and returns { ok, details } */
      apiPost('/api/storage/validate', { path: path, role: role })
        .then(function (r) { onDone(null, r); })
        .catch(function (e) { onDone(e, null); });
    }

    /* ── Load Sources ─────────────────────────────────────────────────── */

    function loadSources() {
      clear(srcList);
      var loadingEl = el('div', 'mf-st__empty');
      loadingEl.textContent = 'Loading sources…';
      srcList.appendChild(loadingEl);

      apiGet('/api/storage/sources')
        .then(function (data) {
          clear(srcList);
          var sources = data.sources || [];
          statSources.set(sources.length);

          if (!sources.length) {
            var empty = el('div', 'mf-st__empty');
            empty.textContent = 'No source folders configured.';
            srcList.appendChild(empty);
            return;
          }

          sources.forEach(function (s) {
            var card = renderSourceCard(s);
            srcList.appendChild(card);
          });
        })
        .catch(function (e) {
          clear(srcList);
          showError('Failed to load sources: ' + e.message);
        });
    }

    function renderSourceCard(s) {
      var card = el('div', 'mf-st__src-card');

      /* Status dot (starts pending, resolves async) */
      var dotWrap = el('div');
      dotWrap.style.paddingTop = '0.2rem';
      var dot = makeStatusDot('pending');
      dotWrap.appendChild(dot);

      var body = el('div', 'mf-st__src-card-body');
      var labelEl = el('div', 'mf-st__src-label');
      labelEl.textContent = s.label || s.path;
      var pathEl = el('div', 'mf-st__src-path');
      pathEl.textContent = s.path;
      var verifyEl = el('div', 'mf-st__verify');
      verifyEl.textContent = 'Verifying…';
      body.appendChild(labelEl);
      body.appendChild(pathEl);
      body.appendChild(verifyEl);

      var actions = el('div', 'mf-st__src-actions');
      var rmBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
      rmBtn.textContent = 'Remove';
      rmBtn.addEventListener('click', function () { removeSource(s.id, s.label || s.path); });
      actions.appendChild(rmBtn);

      card.appendChild(dotWrap);
      card.appendChild(body);
      card.appendChild(actions);

      /* Async validation */
      runValidate(s.path, 'source', function (err, result) {
        if (err || !result || !result.ok) {
          dot.className = 'mf-st__dot mf-st__dot--err';
          dot.title = (result && result.errors && result.errors[0]) || (err && err.message) || 'Not accessible';
          verifyEl.className = 'mf-st__verify mf-st__verify--err';
          verifyEl.textContent = (result && result.errors && result.errors.join(' · ')) || 'Not accessible';
        } else {
          dot.className = 'mf-st__dot mf-st__dot--ok';
          dot.title = 'Accessible';
          verifyEl.className = 'mf-st__verify mf-st__verify--ok';
          var details = ['Readable'];
          if (result.stats && result.stats.item_count != null) details.push(result.stats.item_count + ' items');
          if (result.stats && result.stats.free_space_bytes != null) details.push(fmtBytes(result.stats.free_space_bytes) + ' free');
          verifyEl.textContent = details.join(' · ');
          if (result.stats && result.stats.item_count != null) {
            statFiles.set(result.stats.item_count);
          }
        }
      });

      return card;
    }

    function removeSource(id, label) {
      if (!confirm('Remove source "' + label + '"?')) return;
      apiDelete('/api/storage/sources/' + encodeURIComponent(id))
        .then(function () {
          showToast('Source removed');
          loadSources();
        })
        .catch(function (e) { showError('Failed to remove source: ' + e.message); });
    }

    function addSource() {
      var path = srcPathInp.value.trim();
      var label = srcLabelInp.value.trim();
      if (!path) { showError('Source path is required.'); return; }

      addSrcBtn.disabled = true;
      addSrcBtn.textContent = 'Adding…';

      apiPost('/api/storage/sources', { path: path, label: label || '' })
        .then(function () {
          srcPathInp.value = '';
          srcLabelInp.value = '';
          showToast('Source added');
          loadSources();
        })
        .catch(function (e) { showError('Failed to add source: ' + e.message); })
        .then(function () {
          addSrcBtn.disabled = false;
          addSrcBtn.textContent = 'Add Source';
        });
    }

    function reverifyAll() {
      reverifyBtn.disabled = true;
      reverifyBtn.textContent = 'Verifying…';
      /* Re-render all source cards to trigger fresh validation */
      loadSources();
      /* Re-verify output path */
      var outPath = outInp.value.trim();
      if (outPath) { verifyOutputPath(outPath); }
      setTimeout(function () {
        reverifyBtn.disabled = false;
        reverifyBtn.textContent = 'Re-verify All';
      }, 1500);
    }

    /* ── Load Output ──────────────────────────────────────────────────── */

    function loadOutput() {
      apiGet('/api/storage/output')
        .then(function (data) {
          var path = data.path || '';
          outInp.value = path;
          if (path) { verifyOutputPath(path); }
        })
        .catch(function (e) { showError('Failed to load output directory: ' + e.message); });
    }

    function verifyOutputPath(path) {
      clear(outVerify);
      outVerify.textContent = 'Verifying…';
      outVerify.className = 'mf-st__verify';

      runValidate(path, 'output', function (err, result) {
        if (err || !result || !result.ok) {
          outVerify.className = 'mf-st__verify mf-st__verify--err';
          outVerify.textContent = (result && result.errors && result.errors.join(' · ')) || (err && err.message) || 'Not accessible';
          statDisk.set('Error');
        } else {
          outVerify.className = 'mf-st__verify mf-st__verify--ok';
          var details = ['Writable'];
          if (result.stats && result.stats.free_space_bytes != null) {
            details.push(fmtBytes(result.stats.free_space_bytes) + ' free');
            statDisk.set(fmtBytes(result.stats.free_space_bytes));
          }
          outVerify.textContent = details.join(' · ');
        }
      });
    }

    function saveOutput() {
      var path = outInp.value.trim();
      if (!path) { showError('Output path is required.'); return; }

      saveOutBtn.disabled = true;
      saveOutBtn.textContent = 'Saving…';

      apiPut('/api/storage/output', { path: path })
        .then(function () {
          showToast('Output directory saved');
          verifyOutputPath(path);
        })
        .catch(function (e) { showError('Failed to save output: ' + e.message); })
        .then(function () {
          saveOutBtn.disabled = false;
          saveOutBtn.textContent = 'Save';
        });
    }

    /* ── Load Shares ──────────────────────────────────────────────────── */

    function loadShares() {
      clear(sharesTbody);
      var loadRow = el('tr');
      var loadTd = el('td');
      loadTd.colSpan = 5;
      loadTd.className = 'mf-st__empty';
      loadTd.textContent = 'Loading shares…';
      loadRow.appendChild(loadTd);
      sharesTbody.appendChild(loadRow);

      apiGet('/api/storage/shares')
        .then(function (data) {
          clear(sharesTbody);
          var shares = data.shares || [];
          if (!shares.length) {
            var emptyRow = el('tr');
            var emptyTd = el('td');
            emptyTd.colSpan = 5;
            emptyTd.className = 'mf-st__empty';
            emptyTd.textContent = 'No network shares configured.';
            emptyRow.appendChild(emptyTd);
            sharesTbody.appendChild(emptyRow);
            return;
          }
          shares.forEach(function (s) {
            sharesTbody.appendChild(renderShareRow(s));
          });
        })
        .catch(function (e) { showError('Failed to load shares: ' + e.message); });
    }

    function shareStatusDot(status) {
      var cls = 'mf-st__dot ';
      if (!status) { cls += 'mf-st__dot--pending'; }
      else if (status.ok === true) { cls += 'mf-st__dot--ok'; }
      else { cls += 'mf-st__dot--err'; }
      var d = el('span', cls);
      d.title = !status ? 'Unknown' : status.ok ? 'Mounted' : (status.error || 'Unreachable');
      return d;
    }

    function renderShareRow(s) {
      var tr = el('tr');

      var tdName = el('td'); tdName.textContent = s.name;
      var tdProto = el('td'); tdProto.textContent = s.protocol || '';
      var tdServer = el('td', 'mono'); tdServer.textContent = s.server || '';
      var tdStatus = el('td');
      tdStatus.appendChild(shareStatusDot(s.status));

      var tdActions = el('td', 'actions');
      var testBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      testBtn.textContent = 'Test';
      testBtn.style.marginRight = '0.3rem';
      testBtn.addEventListener('click', (function (name) {
        return function () { testShare(name); };
      })(s.name));

      var rmBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
      rmBtn.textContent = 'Remove';
      rmBtn.addEventListener('click', (function (name) {
        return function () { removeShare(name); };
      })(s.name));

      tdActions.appendChild(testBtn);
      tdActions.appendChild(rmBtn);
      tr.appendChild(tdName);
      tr.appendChild(tdProto);
      tr.appendChild(tdServer);
      tr.appendChild(tdStatus);
      tr.appendChild(tdActions);
      return tr;
    }

    function testShare(name) {
      showToast('Testing share ' + name + '…', 'info');
      apiPost('/api/storage/shares/' + encodeURIComponent(name) + '/test', {})
        .then(function (r) {
          if (r && r.ok) {
            showToast(name + ': OK — ' + (r.item_count || 0) + ' entries visible', 'success');
          } else {
            showToast(name + ': Failed — ' + ((r && r.error) || 'unknown'), 'error');
          }
          loadShares();
        })
        .catch(function (e) { showError('Test failed: ' + e.message); });
    }

    function removeShare(name) {
      if (!confirm('Remove share "' + name + '"? Saved credentials will be deleted.')) return;
      apiDelete('/api/storage/shares/' + encodeURIComponent(name))
        .then(function () { showToast('Share removed'); loadShares(); })
        .catch(function (e) { showError('Failed to remove share: ' + e.message); });
    }

    /* ── Add-Share Modal ──────────────────────────────────────────────── */

    var addShareModal = null;

    function openAddShareModal(prefill) {
      if (addShareModal) { removeModal(); }
      prefill = prefill || {};

      var backdrop = el('div', 'mf-st__modal-backdrop');
      var modal = el('div', 'mf-st__modal');

      var title = el('h2'); title.textContent = 'Add Network Share';
      modal.appendChild(title);

      /* Name */
      var nameRow = el('div', 'mf-st__modal-row');
      var nameLbl = el('label'); nameLbl.textContent = 'Name'; nameLbl.htmlFor = 'mf-st-share-name';
      var nameInp = el('input'); nameInp.id = 'mf-st-share-name'; nameInp.type = 'text'; nameInp.placeholder = 'nas-docs';
      nameInp.value = prefill.name || '';
      nameRow.appendChild(nameLbl);
      nameRow.appendChild(nameInp);
      modal.appendChild(nameRow);

      /* Protocol */
      var protoRow = el('div', 'mf-st__modal-row');
      var protoLbl = el('label'); protoLbl.textContent = 'Protocol';
      protoRow.appendChild(protoLbl);
      var protoOptions = [
        { value: 'smb', label: 'SMB/CIFS' },
        { value: 'nfsv3', label: 'NFSv3' },
        { value: 'nfsv4', label: 'NFSv4' },
      ];
      var protoSel = el('select');
      protoSel.id = 'mf-st-share-protocol';
      protoOptions.forEach(function (p) {
        var opt = el('option');
        opt.value = p.value;
        opt.textContent = p.label;
        if ((prefill.protocol || 'smb') === p.value) opt.selected = true;
        protoSel.appendChild(opt);
      });
      protoRow.appendChild(protoSel);
      modal.appendChild(protoRow);

      /* Server */
      var serverRow = el('div', 'mf-st__modal-row');
      var serverLbl = el('label'); serverLbl.textContent = 'Server'; serverLbl.htmlFor = 'mf-st-share-server';
      var serverInp = el('input'); serverInp.id = 'mf-st-share-server'; serverInp.type = 'text'; serverInp.placeholder = '192.168.1.17';
      serverInp.value = prefill.server || '';
      serverRow.appendChild(serverLbl);
      serverRow.appendChild(serverInp);
      modal.appendChild(serverRow);

      /* Share path */
      var shareRow = el('div', 'mf-st__modal-row');
      var shareLbl = el('label'); shareLbl.textContent = 'Share name / export path'; shareLbl.htmlFor = 'mf-st-share-path';
      var shareInp = el('input'); shareInp.id = 'mf-st-share-path'; shareInp.type = 'text'; shareInp.placeholder = 'documents';
      shareInp.value = prefill.share_path || '';
      shareRow.appendChild(shareLbl);
      shareRow.appendChild(shareInp);
      modal.appendChild(shareRow);

      /* SMB credentials (shown only for smb) */
      var smbFields = el('div');
      smbFields.id = 'mf-st-smb-fields';
      var userRow = el('div', 'mf-st__modal-row');
      var userLbl = el('label'); userLbl.textContent = 'Username'; userLbl.htmlFor = 'mf-st-share-user';
      var userInp = el('input'); userInp.id = 'mf-st-share-user'; userInp.type = 'text'; userInp.autocomplete = 'off';
      userRow.appendChild(userLbl); userRow.appendChild(userInp);
      var passRow = el('div', 'mf-st__modal-row');
      var passLbl = el('label'); passLbl.textContent = 'Password'; passLbl.htmlFor = 'mf-st-share-pass';
      var passInp = el('input'); passInp.id = 'mf-st-share-pass'; passInp.type = 'password'; passInp.autocomplete = 'new-password';
      passRow.appendChild(passLbl); passRow.appendChild(passInp);
      smbFields.appendChild(userRow);
      smbFields.appendChild(passRow);
      modal.appendChild(smbFields);

      /* Read-only toggle */
      var roRow = el('div', 'mf-st__modal-row');
      var roLabel = el('label', 'mf-st__toggle');
      var roChk = el('input'); roChk.type = 'checkbox'; roChk.checked = true;
      roLabel.appendChild(roChk);
      roLabel.appendChild(document.createTextNode(' Read-only mount (recommended for sources)'));
      roRow.appendChild(roLabel);
      modal.appendChild(roRow);

      /* Error */
      var errEl = el('div', 'mf-st__modal-err');
      errEl.style.display = 'none';
      modal.appendChild(errEl);

      /* Footer */
      var footer = el('div', 'mf-st__modal-footer');
      var cancelBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', removeModal);
      var submitBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
      submitBtn.textContent = 'Add Share';
      footer.appendChild(cancelBtn);
      footer.appendChild(submitBtn);
      modal.appendChild(footer);

      /* Toggle SMB fields based on protocol */
      function toggleSmbFields() {
        smbFields.style.display = protoSel.value === 'smb' ? '' : 'none';
      }
      protoSel.addEventListener('change', toggleSmbFields);
      toggleSmbFields();

      submitBtn.addEventListener('click', function () {
        errEl.style.display = 'none';
        var name = nameInp.value.trim();
        var protocol = protoSel.value;
        var server = serverInp.value.trim();
        var share = shareInp.value.trim();
        var username = userInp.value;
        var password = passInp.value;
        var readOnly = roChk.checked;

        if (!/^[A-Za-z0-9_-]+$/.test(name)) {
          errEl.textContent = 'Name must be alphanumeric (dashes and underscores allowed).';
          errEl.style.display = '';
          return;
        }
        if (!server) { errEl.textContent = 'Server is required.'; errEl.style.display = ''; return; }
        if (!share) { errEl.textContent = 'Share path is required.'; errEl.style.display = ''; return; }
        if (protocol === 'smb' && !username) { errEl.textContent = 'SMB requires a username.'; errEl.style.display = ''; return; }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Adding…';

        apiPost('/api/storage/shares', {
          name: name, protocol: protocol, server: server, share: share,
          username: username, password: password,
          options: { read_only: readOnly }
        })
          .then(function () {
            removeModal();
            showToast('Share added');
            loadShares();
          })
          .catch(function (e) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Add Share';
            errEl.textContent = (e.detail && e.detail.detail) || e.message;
            errEl.style.display = '';
          });
      });

      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);
      addShareModal = backdrop;
      nameInp.focus();

      /* Close on backdrop click */
      backdrop.addEventListener('click', function (ev) {
        if (ev.target === backdrop) removeModal();
      });
    }

    function removeModal() {
      if (addShareModal && addShareModal.parentNode) {
        addShareModal.parentNode.removeChild(addShareModal);
      }
      addShareModal = null;
    }

    /* ── Discover Modal ───────────────────────────────────────────────── */

    var discoverModal = null;

    function openDiscoverModal() {
      if (discoverModal) { removeDiscoverModal(); }

      var backdrop = el('div', 'mf-st__modal-backdrop');
      var modal = el('div', 'mf-st__modal');

      var title = el('h2'); title.textContent = 'Discover Network Sources';
      modal.appendChild(title);

      /* Protocol tabs (subnet / server) */
      var tabBar = el('div');
      tabBar.style.cssText = 'display:flex;gap:0.4rem;border-bottom:1px solid var(--mf-border,#2a2a4a);margin-bottom:0.85rem;';

      var tabSubnet = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      tabSubnet.textContent = 'Scan subnet';
      tabSubnet.style.borderBottom = '2px solid var(--mf-color-accent,#6366f1)';

      var tabServer = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      tabServer.textContent = 'Probe server';

      tabBar.appendChild(tabSubnet);
      tabBar.appendChild(tabServer);
      modal.appendChild(tabBar);

      /* Subnet panel */
      var subnetPanel = el('div');
      var subnetRow = el('div', 'mf-st__modal-row');
      var subnetLbl = el('label'); subnetLbl.textContent = 'Subnet (CIDR)'; subnetLbl.htmlFor = 'mf-st-discover-subnet';
      var subnetInp = el('input'); subnetInp.id = 'mf-st-discover-subnet'; subnetInp.type = 'text'; subnetInp.placeholder = '192.168.1.0/24';
      subnetRow.appendChild(subnetLbl);
      subnetRow.appendChild(subnetInp);
      subnetPanel.appendChild(subnetRow);
      var scanBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
      scanBtn.textContent = 'Scan';
      subnetPanel.appendChild(scanBtn);

      /* Server panel */
      var serverPanel = el('div');
      serverPanel.style.display = 'none';
      var srvRow = el('div', 'mf-st__modal-row');
      var srvLbl = el('label'); srvLbl.textContent = 'Server (IP or hostname)'; srvLbl.htmlFor = 'mf-st-discover-server';
      var srvInp = el('input'); srvInp.id = 'mf-st-discover-server'; srvInp.type = 'text'; srvInp.placeholder = '192.168.1.17';
      srvRow.appendChild(srvLbl);
      srvRow.appendChild(srvInp);
      serverPanel.appendChild(srvRow);
      var probeBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
      probeBtn.textContent = 'Probe';
      serverPanel.appendChild(probeBtn);

      modal.appendChild(subnetPanel);
      modal.appendChild(serverPanel);

      /* Results area */
      var resultsEl = el('div', 'mf-st__disc-results');
      modal.appendChild(resultsEl);

      /* Footer */
      var footer = el('div', 'mf-st__modal-footer');
      var closeBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      closeBtn.textContent = 'Close';
      closeBtn.addEventListener('click', removeDiscoverModal);
      footer.appendChild(closeBtn);
      modal.appendChild(footer);

      /* Tab switching */
      tabSubnet.addEventListener('click', function () {
        subnetPanel.style.display = '';
        serverPanel.style.display = 'none';
        tabSubnet.style.borderBottom = '2px solid var(--mf-color-accent,#6366f1)';
        tabServer.style.borderBottom = '';
      });
      tabServer.addEventListener('click', function () {
        subnetPanel.style.display = 'none';
        serverPanel.style.display = '';
        tabSubnet.style.borderBottom = '';
        tabServer.style.borderBottom = '2px solid var(--mf-color-accent,#6366f1)';
      });

      /* Scan subnet */
      scanBtn.addEventListener('click', function () {
        var subnet = subnetInp.value.trim();
        if (!subnet) return;
        clear(resultsEl);
        var msg = el('div', 'mf-st__empty'); msg.textContent = 'Scanning…';
        resultsEl.appendChild(msg);

        apiPost('/api/storage/shares/discover', { scope: 'subnet', subnet: subnet })
          .then(function (data) {
            renderDiscoverResults(resultsEl, data.servers || [], function (s) {
              return { label: s.hostname + ' (' + s.ip + ')', prefill: { server: s.ip, protocol: 'smb' } };
            });
          })
          .catch(function (e) {
            clear(resultsEl);
            var errEl = el('div'); errEl.style.color = '#f87171'; errEl.textContent = e.message;
            resultsEl.appendChild(errEl);
          });
      });

      /* Probe server */
      probeBtn.addEventListener('click', function () {
        var server = srvInp.value.trim();
        if (!server) return;
        clear(resultsEl);
        var msg = el('div', 'mf-st__empty'); msg.textContent = 'Probing…';
        resultsEl.appendChild(msg);

        apiPost('/api/storage/shares/discover', { scope: 'server', server: server, protocol: 'smb' })
          .then(function (data) {
            renderDiscoverResults(resultsEl, data.shares || [], function (s) {
              var name = (s.name || (s.path || '').split('/').pop() || '').replace(/[^A-Za-z0-9_-]/g, '') || 'share';
              return {
                label: (s.name || s.path) + (s.comment ? ' — ' + s.comment : ''),
                prefill: { server: server, protocol: 'smb', share_path: s.name || s.path, name: name }
              };
            });
          })
          .catch(function (e) {
            clear(resultsEl);
            var errEl = el('div'); errEl.style.color = '#f87171'; errEl.textContent = e.message;
            resultsEl.appendChild(errEl);
          });
      });

      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);
      discoverModal = backdrop;

      backdrop.addEventListener('click', function (ev) {
        if (ev.target === backdrop) removeDiscoverModal();
      });
    }

    function removeDiscoverModal() {
      if (discoverModal && discoverModal.parentNode) {
        discoverModal.parentNode.removeChild(discoverModal);
      }
      discoverModal = null;
    }

    function renderDiscoverResults(container, items, toEntry) {
      clear(container);
      if (!items || !items.length) {
        var empty = el('div', 'mf-st__empty'); empty.textContent = 'No results found.';
        container.appendChild(empty);
        return;
      }
      items.forEach(function (it) {
        var entry = toEntry(it);
        var row = el('div', 'mf-st__disc-item');
        var lbl = el('span'); lbl.textContent = entry.label;
        var addBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        addBtn.textContent = 'Add';
        addBtn.addEventListener('click', (function (pf) {
          return function () {
            removeDiscoverModal();
            openAddShareModal(pf);
          };
        })(entry.prefill));
        row.appendChild(lbl);
        row.appendChild(addBtn);
        container.appendChild(row);
      });
    }

    /* ── Load Exclusions ──────────────────────────────────────────────── */

    function loadExclusions() {
      clear(exclTbody);
      apiGet('/api/storage/exclusions')
        .then(function (data) {
          clear(exclTbody);
          var exclusions = data.exclusions || [];
          if (!exclusions.length) {
            var tr = el('tr');
            var td = el('td'); td.colSpan = 2; td.className = 'mf-st__empty'; td.textContent = 'No exclusions configured.';
            tr.appendChild(td);
            exclTbody.appendChild(tr);
            return;
          }
          exclusions.forEach(function (x) {
            var tr = el('tr');
            var tdPath = el('td', 'mono'); tdPath.textContent = x.path_prefix;
            var tdAct = el('td', 'actions');
            var rmBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
            rmBtn.textContent = 'Remove';
            rmBtn.addEventListener('click', (function (id) {
              return function () { removeExclusion(id); };
            })(x.id));
            tdAct.appendChild(rmBtn);
            tr.appendChild(tdPath);
            tr.appendChild(tdAct);
            exclTbody.appendChild(tr);
          });
        })
        .catch(function (e) { showError('Failed to load exclusions: ' + e.message); });
    }

    function addExclusion() {
      var prefix = exclInp.value.trim();
      if (!prefix) { showError('Path prefix is required.'); return; }
      addExclBtn.disabled = true;
      apiPost('/api/storage/exclusions', { path_prefix: prefix })
        .then(function () {
          exclInp.value = '';
          showToast('Exclusion added');
          loadExclusions();
        })
        .catch(function (e) { showError('Failed to add exclusion: ' + e.message); })
        .then(function () { addExclBtn.disabled = false; });
    }

    function removeExclusion(id) {
      apiDelete('/api/storage/exclusions/' + encodeURIComponent(id))
        .then(function () { showToast('Exclusion removed'); loadExclusions(); })
        .catch(function (e) { showError('Failed to remove exclusion: ' + e.message); });
    }

    /* ── Cloud Prefetch ───────────────────────────────────────────────── */

    var PREFETCH_KEYS = [
      'cloud_prefetch_concurrency',
      'cloud_prefetch_rate_limit',
      'cloud_prefetch_timeout_seconds',
      'cloud_prefetch_min_size_bytes',
    ];

    function loadPrefetch() {
      apiGet('/api/preferences')
        .then(function (data) {
          var prefs = data.preferences || data || {};
          var enabled = String(prefs.cloud_prefetch_enabled || '').toLowerCase() === 'true';
          pfToggleChk.checked = enabled;
          PREFETCH_KEYS.forEach(function (k) {
            var inp = pfInputMap[k];
            if (inp && prefs[k] != null) inp.value = prefs[k];
          });
          var probeAll = String(prefs.cloud_prefetch_probe_all || '').toLowerCase() === 'true';
          pfProbeChk.checked = probeAll;
        })
        .catch(function (e) { showError('Failed to load prefetch settings: ' + e.message); });
    }

    function savePrefetch() {
      pfSaveBtn.disabled = true;
      pfStatus.textContent = 'Saving…';

      var allPrefs = [
        { key: 'cloud_prefetch_enabled', value: String(pfToggleChk.checked) },
        { key: 'cloud_prefetch_probe_all', value: String(pfProbeChk.checked) },
      ];
      PREFETCH_KEYS.forEach(function (k) {
        var inp = pfInputMap[k];
        if (inp) allPrefs.push({ key: k, value: inp.value });
      });

      var tasks = allPrefs.map(function (p) {
        return apiPut('/api/preferences/' + encodeURIComponent(p.key), { value: p.value });
      });

      Promise.all(tasks)
        .then(function () {
          pfStatus.textContent = 'Saved';
          setTimeout(function () { pfStatus.textContent = ''; }, 3000);
        })
        .catch(function (e) {
          pfStatus.textContent = 'Error: ' + e.message;
          pfStatus.style.color = '#f87171';
          setTimeout(function () { pfStatus.textContent = ''; pfStatus.style.color = ''; }, 5000);
        })
        .then(function () { pfSaveBtn.disabled = false; });
    }

    /* ── Wire events ──────────────────────────────────────────────────── */

    addSrcBtn.addEventListener('click', addSource);
    srcPathInp.addEventListener('keydown', function (e) { if (e.key === 'Enter') addSource(); });

    reverifyBtn.addEventListener('click', reverifyAll);

    discoverBtn.addEventListener('click', openDiscoverModal);

    saveOutBtn.addEventListener('click', saveOutput);

    addShareBtn.addEventListener('click', function () { openAddShareModal(); });
    discoverShareBtn.addEventListener('click', openDiscoverModal);

    addExclBtn.addEventListener('click', addExclusion);
    exclInp.addEventListener('keydown', function (e) { if (e.key === 'Enter') addExclusion(); });

    pfSaveBtn.addEventListener('click', savePrefetch);

    /* ── Initial load ─────────────────────────────────────────────────── */

    function loadAll() {
      loadSources();
      loadOutput();
      loadShares();
      loadExclusions();
      loadPrefetch();
    }

    loadAll();

    /* ── Return control handle ────────────────────────────────────────── */
    return {
      refresh: loadAll,
      destroy: function () { /* no poll timers to clean up */ },
    };
  }

  /* ── Export ──────────────────────────────────────────────────────────────── */
  global.MFStoragePage = { mount: mount };

})(window);
