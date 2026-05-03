/* MFBulkDetail — new-UX Bulk Job detail page component.
 *
 * Consolidates /bulk-review.html + /job-detail.html into a single tabbed page.
 *
 * Tabs:
 *   Overview  — stats + state machine controls (pause / resume / cancel)
 *   Files     — paginated file list with status filters (lazy-loaded)
 *   Errors    — failed files with expandable error messages (lazy-loaded)
 *   Log       — job event log (lazy-loaded, uses SSE for live jobs)
 *
 * Endpoints used:
 *   GET  /api/bulk/jobs/{id}           — single job
 *   GET  /api/bulk/jobs/{id}/files     — paginated file list
 *   GET  /api/bulk/jobs/{id}/errors    — failed files
 *   POST /api/bulk/jobs/{id}/pause
 *   POST /api/bulk/jobs/{id}/resume
 *   POST /api/bulk/jobs/{id}/cancel
 *   SSE  /api/bulk/jobs/{id}/stream    — live progress for active jobs
 *
 * Job ID is extracted from the URL path: /bulk/{id}
 * Safe DOM throughout — no innerHTML with user data.
 *
 * Usage:
 *   MFBulkDetail.mount(root, { role });
 */
(function (global) {
  'use strict';

  /* ── Helpers ────────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function txt(s) { return document.createTextNode(s == null ? '' : String(s)); }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

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
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  function fmtNum(n) { return (n == null || n === '') ? '—' : Number(n).toLocaleString(); }

  function fmtBytes(n) {
    if (n == null || n === '') return '—';
    n = Number(n);
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
    } catch (e) { return iso; }
  }

  function fmtDuration(startIso, endIso) {
    if (!startIso) return '—';
    var end = endIso ? new Date(endIso) : new Date();
    var ms = end - new Date(startIso);
    if (isNaN(ms) || ms < 0) return '—';
    var s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60);
    var rem = s % 60;
    if (m < 60) return rem > 0 ? m + 'm ' + rem + 's' : m + 'm';
    var h = Math.floor(m / 60);
    var remM = m % 60;
    return remM > 0 ? h + 'h ' + remM + 'm' : h + 'h';
  }

  function shortPath(p) {
    if (!p) return '—';
    var parts = p.replace(/\\/g, '/').split('/');
    if (parts.length <= 3) return p;
    return '…/' + parts.slice(-3).join('/');
  }

  function statusPillClass(status) {
    var map = {
      running:   'mf-bkd__pill--running',
      scanning:  'mf-bkd__pill--scanning',
      completed: 'mf-bkd__pill--completed',
      failed:    'mf-bkd__pill--failed',
      cancelled: 'mf-bkd__pill--cancelled',
      paused:    'mf-bkd__pill--paused',
    };
    return 'mf-bkd__pill ' + (map[status] || 'mf-bkd__pill--unknown');
  }

  function filePillClass(status) {
    var map = {
      converted:    'mf-bkd__file-pill--converted',
      failed:       'mf-bkd__file-pill--failed',
      adobe_failed: 'mf-bkd__file-pill--failed',
      skipped:      'mf-bkd__file-pill--skipped',
      pending:      'mf-bkd__file-pill--pending',
      for_review:   'mf-bkd__file-pill--review',
    };
    return 'mf-bkd__file-pill ' + (map[status] || '');
  }

  /* ── Extract job ID from URL path (/bulk/{id}) ────────────────────────── */

  function getJobIdFromUrl() {
    var pathname = window.location.pathname;
    var match = pathname.match(/\/bulk\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFBulkDetail.mount: root element is required');
    clear(root);
    opts = opts || {};

    var jobId = getJobIdFromUrl();

    if (!jobId) {
      var errEl = el('div', 'mf-bkd__error-page');
      errEl.textContent = 'No job ID found in URL. Expected /bulk/{id}.';
      root.appendChild(errEl);
      return;
    }

    /* ── State ─────────────────────────────────────────────────────────── */
    var job          = null;
    var currentTab   = 'overview';
    var tabLoaded    = { overview: false, files: false, errors: false, log: false };
    var sseSource    = null;
    var sseLog       = [];

    /* Files tab state */
    var filesPage    = 1;
    var filesPerPage = 50;
    var filesFilter  = 'all';
    var filesSearch  = '';
    var filesSearchTimer = null;

    /* Errors tab state */
    var allErrors    = [];
    var filteredErrors = [];
    var errSearchTimer = null;

    /* ── Skeleton ──────────────────────────────────────────────────────── */

    var wrap = el('div', 'mf-bkd');

    /* Back link */
    var backLink = el('a', 'mf-bkd__back');
    backLink.href = '/bulk';
    backLink.textContent = '← Back to Bulk Jobs';
    wrap.appendChild(backLink);

    /* Loading indicator */
    var loadingEl = el('div', 'mf-bkd__loading');
    loadingEl.textContent = 'Loading job…';
    wrap.appendChild(loadingEl);

    /* Content area (hidden until loaded) */
    var contentEl = el('div', 'mf-bkd__content');
    contentEl.style.display = 'none';

    /* ── Header ─────────────────────────────────────────────────────────── */
    var headerEl = el('div', 'mf-bkd__header');

    var headerLeft = el('div', 'mf-bkd__header-left');
    var jobTitleEl = el('h1', 'mf-bkd__job-title');
    var statusPillEl = el('span', 'mf-bkd__pill');
    var jobIdSpan = el('span', 'mf-bkd__job-id-text');
    jobTitleEl.appendChild(statusPillEl);
    jobTitleEl.appendChild(txt(' '));
    jobTitleEl.appendChild(jobIdSpan);
    var jobMetaEl = el('div', 'mf-bkd__job-meta');
    headerLeft.appendChild(jobTitleEl);
    headerLeft.appendChild(jobMetaEl);

    var headerRight = el('div', 'mf-bkd__header-right');
    var pauseBtn  = el('button', 'mf-bkd__action-btn mf-bkd__action-btn--pause');
    pauseBtn.textContent = 'Pause';
    var resumeBtn = el('button', 'mf-bkd__action-btn mf-bkd__action-btn--resume');
    resumeBtn.textContent = 'Resume';
    var cancelBtn = el('button', 'mf-bkd__action-btn mf-bkd__action-btn--cancel');
    cancelBtn.textContent = 'Cancel';
    headerRight.appendChild(pauseBtn);
    headerRight.appendChild(resumeBtn);
    headerRight.appendChild(cancelBtn);

    headerEl.appendChild(headerLeft);
    headerEl.appendChild(headerRight);
    contentEl.appendChild(headerEl);

    /* ── Tab strip ──────────────────────────────────────────────────────── */
    var tabsEl = el('div', 'mf-bkd__tabs');
    var tabBtns = {};
    var TAB_DEFS = [
      { key: 'overview', label: 'Overview' },
      { key: 'files',    label: 'Files',  badge: true },
      { key: 'errors',   label: 'Errors', badge: true },
      { key: 'log',      label: 'Log' },
    ];
    var tabBadges = {};
    TAB_DEFS.forEach(function (def) {
      var btn = el('button', 'mf-bkd__tab');
      btn.textContent = def.label;
      if (def.key === 'overview') btn.classList.add('mf-bkd__tab--active');
      if (def.badge) {
        var badge = el('span', 'mf-bkd__tab-badge');
        badge.textContent = '0';
        btn.appendChild(badge);
        tabBadges[def.key] = badge;
      }
      btn.addEventListener('click', function () { switchTab(def.key); });
      tabsEl.appendChild(btn);
      tabBtns[def.key] = btn;
    });
    contentEl.appendChild(tabsEl);

    /* ── Tab panels ─────────────────────────────────────────────────────── */
    var panelsEl = el('div', 'mf-bkd__panels');

    /* Overview panel */
    var overviewPanel = el('div', 'mf-bkd__panel mf-bkd__panel--active');
    overviewPanel.id = 'mf-bkd-panel-overview';

    /* Stats bar */
    var statsBar = el('div', 'mf-bkd__stats-bar');
    var statCards = {};
    [
      { key: 'total',     label: 'Total',     cls: '' },
      { key: 'converted', label: 'Converted', cls: 'mf-bkd__stat--ok' },
      { key: 'failed',    label: 'Failed',    cls: 'mf-bkd__stat--err' },
      { key: 'skipped',   label: 'Skipped',   cls: 'mf-bkd__stat--warn' },
      { key: 'adobe',     label: 'Adobe',     cls: 'mf-bkd__stat--muted' },
    ].forEach(function (item) {
      var card = el('div', 'mf-bkd__stat ' + item.cls);
      var valEl = el('div', 'mf-bkd__stat-val'); valEl.textContent = '—';
      var lblEl = el('div', 'mf-bkd__stat-lbl'); lblEl.textContent = item.label;
      card.appendChild(valEl);
      card.appendChild(lblEl);
      statsBar.appendChild(card);
      statCards[item.key] = valEl;
    });
    overviewPanel.appendChild(statsBar);

    /* Segmented progress bar */
    var progWrap = el('div', 'mf-bkd__prog-wrap');
    var progBar = el('div', 'mf-bkd__prog-bar');
    var segOk   = el('div', 'mf-bkd__seg mf-bkd__seg--ok');
    var segErr  = el('div', 'mf-bkd__seg mf-bkd__seg--err');
    var segSkip = el('div', 'mf-bkd__seg mf-bkd__seg--skip');
    segOk.style.width = '0%';
    segErr.style.width = '0%';
    segSkip.style.width = '0%';
    progBar.appendChild(segOk);
    progBar.appendChild(segErr);
    progBar.appendChild(segSkip);
    progWrap.appendChild(progBar);
    overviewPanel.appendChild(progWrap);

    /* Timing grid */
    var timingGrid = el('dl', 'mf-bkd__timing-grid');
    var timingPairs = [
      { key: 'started',  label: 'Started',  id: 'mf-bkd-t-started' },
      { key: 'finished', label: 'Finished', id: 'mf-bkd-t-finished' },
      { key: 'duration', label: 'Duration', id: 'mf-bkd-t-duration' },
    ];
    timingPairs.forEach(function (pair) {
      var dt = el('dt', 'mf-bkd__timing-label'); dt.textContent = pair.label;
      var dd = el('dd', 'mf-bkd__timing-val');   dd.id = pair.id;
      timingGrid.appendChild(dt);
      timingGrid.appendChild(dd);
    });
    overviewPanel.appendChild(timingGrid);

    /* Config details */
    var cfgGrid = el('dl', 'mf-bkd__timing-grid');
    cfgGrid.id = 'mf-bkd-cfg-grid';
    overviewPanel.appendChild(cfgGrid);

    /* Cancel/error reason banner */
    var reasonBanner = el('div', 'mf-bkd__reason-banner');
    reasonBanner.style.display = 'none';
    reasonBanner.id = 'mf-bkd-reason';
    overviewPanel.appendChild(reasonBanner);

    panelsEl.appendChild(overviewPanel);

    /* Files panel */
    var filesPanel = el('div', 'mf-bkd__panel');
    filesPanel.id = 'mf-bkd-panel-files';

    var filesToolbar = el('div', 'mf-bkd__toolbar');

    var filesSearchInput = el('input', 'mf-bkd__search');
    filesSearchInput.type = 'search';
    filesSearchInput.placeholder = 'Search filenames…';

    var filesFilterRow = el('div', 'mf-bkd__chip-row');
    ['all', 'converted', 'failed', 'skipped', 'pending', 'for_review'].forEach(function (status) {
      var chip = el('button', 'mf-bkd__chip' + (status === 'all' ? ' mf-bkd__chip--active' : ''));
      chip.textContent = status === 'for_review' ? 'Review' : status.charAt(0).toUpperCase() + status.slice(1);
      chip.dataset.status = status;
      chip.addEventListener('click', function () {
        filesPanel.querySelectorAll('.mf-bkd__chip').forEach(function (c) {
          c.classList.remove('mf-bkd__chip--active');
        });
        chip.classList.add('mf-bkd__chip--active');
        filesFilter = status;
        filesPage = 1;
        loadFiles();
      });
      filesFilterRow.appendChild(chip);
    });

    filesToolbar.appendChild(filesSearchInput);
    filesToolbar.appendChild(filesFilterRow);
    filesPanel.appendChild(filesToolbar);

    var filesTableWrap = el('div', 'mf-bkd__table-wrap');
    var filesTable = el('table', 'mf-bkd__table');
    var filesThead = el('thead');
    var filesHeadRow = el('tr');
    ['File', 'Status', 'Type', 'Size', 'Details'].forEach(function (label, i) {
      var th = el('th');
      th.textContent = label;
      if (i === 0) th.style.width = '50%';
      if (i === 1) th.style.width = '90px';
      if (i === 2) th.style.width = '70px';
      if (i === 3) th.style.width = '80px';
      filesHeadRow.appendChild(th);
    });
    filesThead.appendChild(filesHeadRow);
    filesTable.appendChild(filesThead);
    var filesTbody = el('tbody');
    filesTable.appendChild(filesTbody);
    filesTableWrap.appendChild(filesTable);
    filesPanel.appendChild(filesTableWrap);

    var filesPagEl = el('div', 'mf-bkd__pagination');
    filesPanel.appendChild(filesPagEl);

    panelsEl.appendChild(filesPanel);

    /* Errors panel */
    var errorsPanel = el('div', 'mf-bkd__panel');
    errorsPanel.id = 'mf-bkd-panel-errors';

    var errToolbar = el('div', 'mf-bkd__toolbar');
    var errSearchInput = el('input', 'mf-bkd__search');
    errSearchInput.type = 'search';
    errSearchInput.placeholder = 'Search errors…';
    errToolbar.appendChild(errSearchInput);
    errorsPanel.appendChild(errToolbar);

    var errTableWrap = el('div', 'mf-bkd__table-wrap');
    var errTable = el('table', 'mf-bkd__table');
    var errThead = el('thead');
    var errHeadRow = el('tr');
    ['File', 'Type', 'Size', 'Error'].forEach(function (label, i) {
      var th = el('th');
      th.textContent = label;
      if (i === 0) th.style.width = '50%';
      errHeadRow.appendChild(th);
    });
    errThead.appendChild(errHeadRow);
    errTable.appendChild(errThead);
    var errTbody = el('tbody');
    errTable.appendChild(errTbody);
    errTableWrap.appendChild(errTable);
    errorsPanel.appendChild(errTableWrap);

    var errEmptyEl = el('div', 'mf-bkd__empty');
    errEmptyEl.style.display = 'none';
    errEmptyEl.textContent = 'No errors in this job.';
    errorsPanel.appendChild(errEmptyEl);

    panelsEl.appendChild(errorsPanel);

    /* Log panel */
    var logPanel = el('div', 'mf-bkd__panel');
    logPanel.id = 'mf-bkd-panel-log';

    var logList = el('div', 'mf-bkd__log-list');
    logPanel.appendChild(logList);

    var logEmptyEl = el('div', 'mf-bkd__empty');
    logEmptyEl.style.display = 'none';
    logEmptyEl.textContent = 'No log events yet.';
    logPanel.appendChild(logEmptyEl);

    panelsEl.appendChild(logPanel);

    contentEl.appendChild(panelsEl);
    wrap.appendChild(contentEl);
    root.appendChild(wrap);

    /* ── Tab switch ─────────────────────────────────────────────────────── */

    function switchTab(tabKey) {
      currentTab = tabKey;
      Object.keys(tabBtns).forEach(function (k) {
        tabBtns[k].classList.toggle('mf-bkd__tab--active', k === tabKey);
      });
      var panels = panelsEl.querySelectorAll('.mf-bkd__panel');
      panels.forEach(function (p) { p.classList.remove('mf-bkd__panel--active'); });
      var target = document.getElementById('mf-bkd-panel-' + tabKey);
      if (target) target.classList.add('mf-bkd__panel--active');

      if (!tabLoaded[tabKey]) {
        tabLoaded[tabKey] = true;
        if (tabKey === 'files') loadFiles();
        if (tabKey === 'errors') loadErrors();
        if (tabKey === 'log') loadLog();
      }
    }

    /* Check URL for initial tab */
    function getInitialTab() {
      var params = new URLSearchParams(window.location.search);
      var t = params.get('tab');
      if (t && ['overview', 'files', 'errors', 'log'].indexOf(t) !== -1) return t;
      return 'overview';
    }

    /* ── Populate header after job load ─────────────────────────────────── */

    function populateHeader() {
      var status = job.status || 'unknown';

      /* Status pill */
      statusPillEl.className = statusPillClass(status);
      statusPillEl.textContent = status.charAt(0).toUpperCase() + status.slice(1);

      /* Job ID */
      var idCode = el('code', 'mf-bkd__job-id-code');
      idCode.textContent = jobId.substring(0, 8);
      clear(jobIdSpan);
      jobIdSpan.appendChild(txt('Job '));
      jobIdSpan.appendChild(idCode);
      document.title = 'Job ' + jobId.substring(0, 8) + ' — MarkFlow';

      /* Meta: source + output */
      clear(jobMetaEl);
      var sourceSpan = el('span'); sourceSpan.textContent = 'Source: ' + (job.source_path || '—');
      var sep = el('span', 'mf-bkd__meta-sep'); sep.textContent = ' · ';
      var outputSpan = el('span'); outputSpan.textContent = 'Output: ' + (job.output_path || '—');
      jobMetaEl.appendChild(sourceSpan);
      jobMetaEl.appendChild(sep);
      jobMetaEl.appendChild(outputSpan);

      /* Action buttons visibility */
      var isActive  = (status === 'running' || status === 'scanning');
      var isPaused  = (status === 'paused');
      var isTerminal = (status === 'completed' || status === 'cancelled' || status === 'failed');
      pauseBtn.style.display  = isActive ? '' : 'none';
      resumeBtn.style.display = isPaused ? '' : 'none';
      cancelBtn.style.display = (isActive || isPaused) ? '' : 'none';

      /* Cancellation/error reason */
      var reason = job.cancellation_reason || job.error_msg;
      if (reason && (status === 'cancelled' || status === 'failed')) {
        reasonBanner.style.display = '';
        reasonBanner.className = 'mf-bkd__reason-banner mf-bkd__reason-banner--' + status;
        reasonBanner.textContent = reason;
      } else {
        reasonBanner.style.display = 'none';
      }
    }

    function populateOverview() {
      var total     = job.total_files || 0;
      var converted = job.converted || 0;
      var failed    = job.failed || 0;
      var skipped   = job.skipped || 0;
      var adobe     = job.adobe_indexed || 0;

      statCards.total.textContent     = fmtNum(total);
      statCards.converted.textContent = fmtNum(converted);
      statCards.failed.textContent    = fmtNum(failed);
      statCards.skipped.textContent   = fmtNum(skipped);
      statCards.adobe.textContent     = fmtNum(adobe);

      if (total > 0) {
        segOk.style.width   = (converted / total * 100).toFixed(1) + '%';
        segErr.style.width  = (failed    / total * 100).toFixed(1) + '%';
        segSkip.style.width = (skipped   / total * 100).toFixed(1) + '%';
      }

      /* Update tab badges */
      if (tabBadges.files) tabBadges.files.textContent = fmtNum(total);
      if (tabBadges.errors) tabBadges.errors.textContent = fmtNum(failed);

      /* Timing */
      document.getElementById('mf-bkd-t-started').textContent  = fmtDate(job.started_at);
      document.getElementById('mf-bkd-t-finished').textContent = fmtDate(job.completed_at);
      document.getElementById('mf-bkd-t-duration').textContent = fmtDuration(job.started_at, job.completed_at);

      /* Config grid */
      var cfgG = document.getElementById('mf-bkd-cfg-grid');
      clear(cfgG);
      var cfgRows = [
        ['Job ID',       jobId],
        ['Workers',      (job.worker_count || '—') + ''],
        ['Fidelity',     (job.fidelity_tier || '—') + ''],
        ['OCR Mode',     job.ocr_mode || '—'],
        ['Include Adobe', job.include_adobe ? 'Yes' : 'No'],
      ];
      cfgRows.forEach(function (pair) {
        var dt = el('dt', 'mf-bkd__timing-label'); dt.textContent = pair[0];
        var dd = el('dd', 'mf-bkd__timing-val');   dd.textContent = pair[1];
        cfgG.appendChild(dt);
        cfgG.appendChild(dd);
      });
    }

    /* ── Files tab ──────────────────────────────────────────────────────── */

    function loadFiles() {
      clear(filesTbody);
      var loadingRow = el('tr');
      var loadingTd = el('td');
      loadingTd.colSpan = 5;
      loadingTd.className = 'mf-bkd__loading';
      loadingTd.textContent = 'Loading files…';
      loadingRow.appendChild(loadingTd);
      filesTbody.appendChild(loadingRow);

      var qs = '?page=' + filesPage + '&per_page=' + filesPerPage;
      if (filesFilter && filesFilter !== 'all') qs += '&status=' + encodeURIComponent(filesFilter);
      if (filesSearch) qs += '&search=' + encodeURIComponent(filesSearch);

      apiGet('/api/bulk/jobs/' + encodeURIComponent(jobId) + '/files' + qs)
        .then(function (data) {
          renderFilesTable(data);
          renderFilesPagination(data);
        })
        .catch(function (e) {
          clear(filesTbody);
          var errRow = el('tr');
          var errTd = el('td');
          errTd.colSpan = 5;
          errTd.className = 'mf-bkd__error';
          errTd.textContent = 'Failed to load files: ' + e.message;
          errRow.appendChild(errTd);
          filesTbody.appendChild(errRow);
        });
    }

    function renderFilesTable(data) {
      clear(filesTbody);
      var files = (data && data.files) ? data.files : [];
      if (!files.length) {
        var emptyRow = el('tr');
        var emptyTd = el('td');
        emptyTd.colSpan = 5;
        emptyTd.className = 'mf-bkd__empty-row';
        emptyTd.textContent = 'No files match the current filter.';
        emptyRow.appendChild(emptyTd);
        filesTbody.appendChild(emptyRow);
        return;
      }
      files.forEach(function (f) {
        var tr = el('tr');

        /* File path */
        var tdPath = el('td', 'mf-bkd__file-path');
        tdPath.title = f.source_path || '';
        tdPath.textContent = shortPath(f.source_path);

        /* Status */
        var tdStatus = el('td');
        var filePill = el('span', filePillClass(f.status));
        filePill.textContent = (f.status || 'pending').replace(/_/g, ' ');
        tdStatus.appendChild(filePill);

        /* Type */
        var tdType = el('td', 'mf-bkd__file-ext');
        tdType.textContent = f.file_ext || '—';

        /* Size */
        var tdSize = el('td');
        tdSize.textContent = fmtBytes(f.file_size_bytes);

        /* Details */
        var tdDetails = el('td');
        if (f.converted_at) {
          var timeSpan = el('span', 'mf-bkd__file-time');
          timeSpan.textContent = fmtDate(f.converted_at);
          tdDetails.appendChild(timeSpan);
        }
        if (f.error_msg) {
          var errDiv = el('div', 'mf-bkd__file-err');
          errDiv.textContent = f.error_msg;
          tdDetails.appendChild(errDiv);
        }
        if (f.skip_reason) {
          var skipDiv = el('div', 'mf-bkd__file-skip');
          skipDiv.textContent = f.skip_reason;
          tdDetails.appendChild(skipDiv);
        }

        tr.appendChild(tdPath);
        tr.appendChild(tdStatus);
        tr.appendChild(tdType);
        tr.appendChild(tdSize);
        tr.appendChild(tdDetails);
        filesTbody.appendChild(tr);
      });
    }

    function renderFilesPagination(data) {
      clear(filesPagEl);
      if (!data) return;
      var total      = data.total || 0;
      var totalPages = data.total_pages || 1;
      if (totalPages <= 1) {
        var info = el('span', 'mf-bkd__page-info');
        info.textContent = fmtNum(total) + ' files';
        filesPagEl.appendChild(info);
        return;
      }
      var prevBtn = el('button', 'mf-bkd__page-btn');
      prevBtn.textContent = '← Prev';
      prevBtn.disabled = filesPage <= 1;
      prevBtn.addEventListener('click', function () { filesPage--; loadFiles(); });
      filesPagEl.appendChild(prevBtn);

      var infoSpan = el('span', 'mf-bkd__page-info');
      infoSpan.textContent = 'Page ' + (data.page || filesPage) + ' of ' + totalPages + ' (' + fmtNum(total) + ' files)';
      filesPagEl.appendChild(infoSpan);

      var nextBtn = el('button', 'mf-bkd__page-btn');
      nextBtn.textContent = 'Next →';
      nextBtn.disabled = filesPage >= totalPages;
      nextBtn.addEventListener('click', function () { filesPage++; loadFiles(); });
      filesPagEl.appendChild(nextBtn);
    }

    /* ── Errors tab ─────────────────────────────────────────────────────── */

    function loadErrors() {
      apiGet('/api/bulk/jobs/' + encodeURIComponent(jobId) + '/errors')
        .then(function (data) {
          allErrors = (data && data.errors) ? data.errors : [];
          filteredErrors = allErrors.slice();
          renderErrorsTable(errSearchInput.value.trim());
        })
        .catch(function (e) {
          clear(errTbody);
          var errRow = el('tr');
          var errTd = el('td');
          errTd.colSpan = 4;
          errTd.className = 'mf-bkd__error';
          errTd.textContent = 'Failed to load errors: ' + e.message;
          errRow.appendChild(errTd);
          errTbody.appendChild(errRow);
        });
    }

    function renderErrorsTable(query) {
      clear(errTbody);
      var q = (query || '').toLowerCase();
      filteredErrors = q
        ? allErrors.filter(function (f) {
            return (f.source_path || '').toLowerCase().indexOf(q) !== -1 ||
                   (f.error_msg || '').toLowerCase().indexOf(q) !== -1;
          })
        : allErrors.slice();

      if (!filteredErrors.length) {
        errEmptyEl.style.display = '';
        return;
      }
      errEmptyEl.style.display = 'none';

      filteredErrors.forEach(function (f, idx) {
        var tr = el('tr', 'mf-bkd__err-row');

        var tdFile = el('td', 'mf-bkd__file-path');
        tdFile.title = f.source_path || '';
        tdFile.textContent = shortPath(f.source_path);

        var tdType = el('td', 'mf-bkd__file-ext');
        tdType.textContent = f.file_ext || '—';

        var tdSize = el('td');
        tdSize.textContent = fmtBytes(f.file_size_bytes);

        var tdErr = el('td');
        var errMsg = f.error_msg || 'Unknown error';
        var shortMsg = errMsg.length > 120 ? errMsg.substring(0, 120) + '…' : errMsg;
        var errSpan = el('span', 'mf-bkd__file-err');
        errSpan.textContent = shortMsg;
        tdErr.appendChild(errSpan);

        /* Expandable detail */
        if (errMsg.length > 120) {
          var detailDiv = el('div', 'mf-bkd__err-detail');
          detailDiv.textContent = errMsg;
          tdErr.appendChild(detailDiv);
          tr.addEventListener('click', function () {
            detailDiv.classList.toggle('mf-bkd__err-detail--open');
          });
          tr.style.cursor = 'pointer';
          tr.title = 'Click to expand error';
        }

        tr.appendChild(tdFile);
        tr.appendChild(tdType);
        tr.appendChild(tdSize);
        tr.appendChild(tdErr);
        errTbody.appendChild(tr);
      });
    }

    /* ── Log tab ────────────────────────────────────────────────────────── */

    function loadLog() {
      clear(logList);
      logEmptyEl.style.display = 'none';

      var status = job ? job.status : null;
      var isActive = (status === 'running' || status === 'scanning');

      if (isActive) {
        /* Live SSE feed */
        var liveNote = el('div', 'mf-bkd__log-live');
        liveNote.textContent = 'Live — streaming job events…';
        logList.appendChild(liveNote);
        connectSSE();
      } else {
        /* For completed/paused/cancelled/failed jobs, show what we have */
        if (sseLog.length === 0) {
          logEmptyEl.style.display = '';
        } else {
          renderLogEvents(sseLog);
        }
      }
    }

    function connectSSE() {
      if (sseSource) { sseSource.close(); sseSource = null; }
      sseSource = new EventSource('/api/bulk/jobs/' + encodeURIComponent(jobId) + '/stream');

      sseSource.addEventListener('progress', function (e) {
        try {
          var data = JSON.parse(e.data);
          sseLog.push({ type: 'progress', data: data, ts: new Date() });
          appendLogEvent('progress', data);
          updateLiveProgress(data);
        } catch (ex) {}
      });

      sseSource.addEventListener('file_done', function (e) {
        try {
          var data = JSON.parse(e.data);
          sseLog.push({ type: 'file_done', data: data, ts: new Date() });
          appendLogEvent('file_done', data);
        } catch (ex) {}
      });

      sseSource.addEventListener('error_event', function (e) {
        try {
          var data = JSON.parse(e.data);
          sseLog.push({ type: 'error', data: data, ts: new Date() });
          appendLogEvent('error', data);
        } catch (ex) {}
      });

      sseSource.addEventListener('done', function () {
        sseLog.push({ type: 'done', ts: new Date() });
        appendLogEvent('done', null);
        sseSource.close();
        sseSource = null;
        /* Refresh job state */
        loadJobData(false);
      });

      sseSource.onerror = function () {
        if (sseSource && sseSource.readyState === EventSource.CLOSED) {
          sseSource = null;
        }
      };
    }

    function appendLogEvent(type, data) {
      if (currentTab !== 'log') return;
      var row = el('div', 'mf-bkd__log-row mf-bkd__log-row--' + type);
      var tsSpan = el('span', 'mf-bkd__log-ts');
      tsSpan.textContent = new Date().toLocaleTimeString();
      var msgSpan = el('span', 'mf-bkd__log-msg');

      if (type === 'progress' && data) {
        msgSpan.textContent = 'Progress: ' + (data.completed || 0) + ' / ' + (data.total || '?') +
          (data.files_per_second ? ' (' + data.files_per_second.toFixed(1) + ' files/s)' : '');
      } else if (type === 'file_done' && data) {
        msgSpan.textContent = (data.status || 'done') + ': ' + (data.path || data.file_path || '');
      } else if (type === 'error' && data) {
        msgSpan.textContent = 'Error: ' + (data.path || '') + ' — ' + (data.error || data.message || '');
      } else if (type === 'done') {
        msgSpan.textContent = 'Job completed.';
      } else if (data) {
        msgSpan.textContent = JSON.stringify(data);
      }

      row.appendChild(tsSpan);
      row.appendChild(msgSpan);
      logList.appendChild(row);
      logList.scrollTop = logList.scrollHeight;
    }

    function renderLogEvents(events) {
      clear(logList);
      if (!events.length) {
        logEmptyEl.style.display = '';
        return;
      }
      events.forEach(function (ev) {
        appendLogEvent(ev.type, ev.data);
      });
    }

    /* ── Live progress update (SSE → overview panel) ─────────────────────── */

    function updateLiveProgress(data) {
      if (!data) return;
      var total     = data.total     || job.total_files || 0;
      var completed = data.completed || 0;
      var converted = data.converted || 0;
      var failed    = data.failed    || 0;
      var skipped   = data.skipped   || 0;

      if (total > 0) {
        statCards.total.textContent     = fmtNum(total);
        statCards.converted.textContent = fmtNum(converted);
        statCards.failed.textContent    = fmtNum(failed);
        statCards.skipped.textContent   = fmtNum(skipped);

        segOk.style.width   = (converted / total * 100).toFixed(1) + '%';
        segErr.style.width  = (failed    / total * 100).toFixed(1) + '%';
        segSkip.style.width = (skipped   / total * 100).toFixed(1) + '%';

        if (tabBadges.files) tabBadges.files.textContent = fmtNum(total);
        if (tabBadges.errors) tabBadges.errors.textContent = fmtNum(failed);
      }
    }

    /* ── State machine actions ──────────────────────────────────────────── */

    function doAction(action) {
      var url = '/api/bulk/jobs/' + encodeURIComponent(jobId) + '/' + action;
      var btn = action === 'pause' ? pauseBtn : action === 'resume' ? resumeBtn : cancelBtn;
      btn.disabled = true;
      var orig = btn.textContent;
      btn.textContent = action.charAt(0).toUpperCase() + action.slice(1) + 'ing…';

      apiPost(url)
        .then(function () {
          showToast('Job ' + action + 'd.', 'success');
          loadJobData(false);
        })
        .catch(function (e) {
          btn.disabled = false;
          btn.textContent = orig;
          showToast('Failed to ' + action + ': ' + e.message, 'error');
        });
    }

    pauseBtn.addEventListener('click',  function () { doAction('pause'); });
    resumeBtn.addEventListener('click', function () { doAction('resume'); });
    cancelBtn.addEventListener('click', function () {
      if (!confirm('Cancel this job? In-progress files will complete but no new files will be picked up.')) return;
      doAction('cancel');
    });

    /* ── Files search ───────────────────────────────────────────────────── */

    filesSearchInput.addEventListener('input', function () {
      clearTimeout(filesSearchTimer);
      var q = filesSearchInput.value.trim();
      filesSearchTimer = setTimeout(function () {
        filesSearch = q;
        filesPage = 1;
        loadFiles();
      }, 300);
    });

    /* ── Errors search ──────────────────────────────────────────────────── */

    errSearchInput.addEventListener('input', function () {
      clearTimeout(errSearchTimer);
      var q = errSearchInput.value.trim();
      errSearchTimer = setTimeout(function () {
        renderErrorsTable(q);
      }, 250);
    });

    /* ── Load job ───────────────────────────────────────────────────────── */

    function loadJobData(isInitial) {
      return apiGet('/api/bulk/jobs/' + encodeURIComponent(jobId))
        .then(function (data) {
          job = data;
          populateHeader();
          populateOverview();

          if (isInitial) {
            loadingEl.style.display = 'none';
            contentEl.style.display = '';

            /* Apply initial tab from URL */
            var initTab = getInitialTab();
            tabLoaded.overview = true;
            if (initTab !== 'overview') {
              switchTab(initTab);
            } else if (job.status === 'running' || job.status === 'scanning') {
              /* Auto-start SSE for live jobs */
              connectSSE();
            }
          }
        })
        .catch(function (e) {
          loadingEl.textContent = 'Failed to load job: ' + e.message;
        });
    }

    loadJobData(true);
  }

  global.MFBulkDetail = { mount: mount };
})(window);
