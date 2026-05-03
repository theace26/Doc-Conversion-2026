/* Pipeline Files page component (new-UX).
 *
 * Usage:
 *   MFPipelineFiles.mount(root, { role });
 *
 * Polls /api/pipeline/stats every 30s for the stats strip.
 * Files list reloads on filter/page change and every 30s when tab is visible.
 *
 * API endpoints:
 *   GET /api/pipeline/stats   — counts per pipeline state
 *   GET /api/pipeline/files   — paginated file list (accepts ?status=, ?page=, ?per_page=, ?search=, ?include_trashed=)
 *
 * Safe DOM throughout — no innerHTML with user data.
 */
(function (global) {
  'use strict';

  /* ── Helpers ──────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function txt(s) { return document.createTextNode(s == null ? '' : String(s)); }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function fmtNum(n) { return n == null ? '?' : Number(n).toLocaleString(); }

  function fmtBytes(bytes) {
    if (bytes == null) return '';
    var b = Number(bytes);
    if (!b && b !== 0) return '';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = Math.min(Math.floor(Math.log(Math.max(b, 1)) / Math.log(1024)), units.length - 1);
    return (i === 0 ? b : (b / Math.pow(1024, i)).toFixed(1)) + ' ' + units[i];
  }

  function fmtLocalTime(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function shortPath(p) {
    if (!p) return '';
    var s = String(p).replace(/^\/mnt\/source\//, '');
    if (s.length > 80) s = '…' + s.slice(s.length - 79);
    return s;
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

  /* ── State-pill definitions ───────────────────────────────────────────── */

  var STATE_PILLS = [
    { key: 'all',              label: 'All',              statKey: null,                    mod: '' },
    { key: 'scanned',         label: 'Scanned',          statKey: 'scanned',               mod: '' },
    { key: 'pending',         label: 'Pending',          statKey: 'pending_conversion',    mod: '' },
    { key: 'batched',         label: 'Batched',          statKey: 'batched_for_analysis',  mod: 'mf-pf__pill--accent' },
    { key: 'pending_analysis',label: 'Pending Analysis', statKey: 'pending_analysis',      mod: 'mf-pf__pill--warn' },
    { key: 'failed',          label: 'Failed',           statKey: 'failed',                mod: 'mf-pf__pill--failed' },
    { key: 'analysis_failed', label: 'Analysis Failed',  statKey: 'analysis_failed',       mod: 'mf-pf__pill--failed' },
    { key: 'unrecognized',    label: 'Unrecognized',     statKey: 'unrecognized',          mod: '' },
    { key: 'indexed',         label: 'Indexed',          statKey: 'in_search_index',       mod: 'mf-pf__pill--good' },
  ];

  var STAT_STRIP_DEFS = [
    { statKey: 'scanned',            label: 'scanned' },
    { statKey: 'pending_conversion', label: 'pending' },
    { statKey: 'failed',             label: 'failed' },
    { statKey: 'batched_for_analysis', label: 'batched' },
    { statKey: 'pending_analysis',   label: 'pending analysis' },
    { statKey: 'analysis_failed',    label: 'analysis failed' },
    { statKey: 'in_search_index',    label: 'indexed' },
  ];

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFPipelineFiles.mount: root element is required');

    /* ── Page state ──────────────────────────────────────────────────────── */
    var activeStates  = new Set();   /* which state filter pills are active */
    var currentPage   = 1;
    var perPage       = 50;
    var searchQuery   = '';
    var includeTrashed = false;
    var totalFiles    = 0;
    var expandedRows  = new Set();
    var statsTimer    = null;
    var filesTimer    = null;
    var debounceTimer = null;

    /* ── Skeleton ─────────────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-page-wrapper');

    /* Page header */
    var header = el('div', 'mf-page-header');
    var headingGroup = el('div');
    var heading = el('h1', 'mf-page-title');
    heading.textContent = 'Pipeline Files';
    var subtitle = el('p', 'mf-page-subtitle');
    subtitle.textContent = 'Operator drill-down by pipeline state';
    headingGroup.appendChild(heading);
    headingGroup.appendChild(subtitle);
    header.appendChild(headingGroup);
    wrapper.appendChild(header);

    /* Stats strip */
    var statsRow = el('div', 'mf-pf__stats-row');
    var statsRowLabel = el('span', 'mf-pf__stats-label');
    statsRowLabel.textContent = 'Pipeline';
    statsRow.appendChild(statsRowLabel);
    var statEls = {};
    STAT_STRIP_DEFS.forEach(function (def) {
      var stat = el('div', 'mf-pf__stat');
      var val = el('div', 'mf-pf__stat-val');
      val.textContent = '—';
      var lbl = el('div', 'mf-pf__stat-lbl');
      lbl.textContent = def.label;
      stat.appendChild(val);
      stat.appendChild(lbl);
      statsRow.appendChild(stat);
      statEls[def.statKey] = val;
    });
    wrapper.appendChild(statsRow);

    /* State filter pills */
    var pillBar = el('div', 'mf-pf__pill-bar');
    var pillEls = {};
    STATE_PILLS.forEach(function (def) {
      var btn = el('button', 'mf-pf__pill' + (def.mod ? ' ' + def.mod : ''));
      btn.dataset.stateKey = def.key;
      var labelSpan = el('span', 'mf-pf__pill-label');
      labelSpan.textContent = def.label;
      btn.appendChild(labelSpan);
      if (def.statKey) {
        var countSpan = el('span', 'mf-pf__pill-count');
        countSpan.textContent = '';
        btn.appendChild(countSpan);
        pillEls[def.key] = { btn: btn, count: countSpan };
      } else {
        pillEls[def.key] = { btn: btn, count: null };
      }
      pillBar.appendChild(btn);
    });
    wrapper.appendChild(pillBar);

    /* Filter bar: search + include-trashed + result count */
    var filterBar = el('div', 'mf-pf__filter-bar');
    var searchInput = el('input', 'mf-pf__search');
    searchInput.type = 'search';
    searchInput.placeholder = 'Search file paths…';
    searchInput.autocomplete = 'off';

    var trashedLabel = el('label', 'mf-pf__trashed-label');
    var trashedCb = el('input');
    trashedCb.type = 'checkbox';
    trashedCb.id = 'mf-pf-include-trashed';
    var trashedLabelText = el('span');
    trashedLabelText.textContent = 'Include trashed / marked-for-deletion';
    trashedLabel.appendChild(trashedCb);
    trashedLabel.appendChild(trashedLabelText);

    var resultCount = el('span', 'mf-pf__result-count');
    filterBar.appendChild(searchInput);
    filterBar.appendChild(trashedLabel);
    filterBar.appendChild(resultCount);
    wrapper.appendChild(filterBar);

    /* Large-result warning */
    var largeWarn = el('div', 'mf-pf__large-warn');
    largeWarn.textContent = '⚠ Over 5,000 files match. Showing first page — use search or select fewer categories to narrow results.';
    largeWarn.style.display = 'none';
    wrapper.appendChild(largeWarn);

    /* Table container */
    var tableWrap = el('div', 'mf-pf__table-wrap');
    wrapper.appendChild(tableWrap);

    /* Pagination */
    var pagingEl = el('div', 'mf-pf__paging');
    pagingEl.style.display = 'none';
    var prevBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    prevBtn.textContent = '‹ Prev';
    var pageInfo = el('span', 'mf-pf__page-info');
    var nextBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    nextBtn.textContent = 'Next ›';
    var perPageLabel = el('span', 'mf-pf__per-page-label');
    perPageLabel.textContent = 'Per page:';
    var perPageSel = el('select', 'mf-select mf-select--sm');
    [10, 30, 50, 100].forEach(function (n) {
      var o = document.createElement('option');
      o.value = String(n);
      o.textContent = String(n);
      if (n === 50) o.selected = true;
      perPageSel.appendChild(o);
    });
    pagingEl.appendChild(prevBtn);
    pagingEl.appendChild(pageInfo);
    pagingEl.appendChild(nextBtn);
    pagingEl.appendChild(perPageLabel);
    pagingEl.appendChild(perPageSel);
    wrapper.appendChild(pagingEl);

    root.appendChild(wrapper);

    /* ── URL state ────────────────────────────────────────────────────────── */

    function readUrlState() {
      var params = new URLSearchParams(window.location.search);
      var raw = params.get('status') || '';
      raw.split(',').forEach(function (s) {
        s = s.trim();
        if (s) activeStates.add(s);
      });
      var folder = params.get('folder');
      if (folder) {
        searchQuery = folder;
        searchInput.value = folder;
        if (!activeStates.size) activeStates.add('scanned');
      }
    }

    function pushUrlState() {
      var params = new URLSearchParams();
      if (activeStates.size) params.set('status', Array.from(activeStates).join(','));
      var newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
      history.replaceState(null, '', newUrl);
    }

    /* ── Sync pill active state ───────────────────────────────────────────── */

    function syncPills() {
      STATE_PILLS.forEach(function (def) {
        var pe = pillEls[def.key];
        if (!pe) return;
        var isActive;
        if (def.key === 'all') {
          isActive = activeStates.size === 0;
        } else {
          isActive = activeStates.has(def.key);
        }
        pe.btn.classList.toggle('mf-pf__pill--active', isActive);
      });
    }

    /* ── Load stats ───────────────────────────────────────────────────────── */

    function loadStats() {
      var url = '/api/pipeline/stats' + (includeTrashed ? '?include_trashed=true' : '');
      fetch(url, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          /* Stats strip */
          STAT_STRIP_DEFS.forEach(function (def) {
            var ve = statEls[def.statKey];
            if (ve) ve.textContent = fmtNum(d[def.statKey]);
          });
          /* Pill counts */
          STATE_PILLS.forEach(function (def) {
            if (!def.statKey) return;
            var pe = pillEls[def.key];
            if (!pe || !pe.count) return;
            pe.count.textContent = fmtNum(d[def.statKey]);
          });
        })
        .catch(function () { /* non-critical */ });
    }

    /* ── Render empty state ───────────────────────────────────────────────── */

    function renderEmpty(msg) {
      clear(tableWrap);
      var div = el('div', 'mf-pf__empty');
      var icon = el('div', 'mf-pf__empty-icon');
      icon.textContent = '📂';
      var p = el('p');
      p.textContent = msg;
      div.appendChild(icon);
      div.appendChild(p);
      tableWrap.appendChild(div);
    }

    /* ── Render loading skeleton ──────────────────────────────────────────── */

    function renderSkeleton() {
      clear(tableWrap);
      var sk = el('div', 'mf-pf__skeleton');
      for (var i = 0; i < 6; i++) {
        var row = el('div', 'mf-pf__skel-row');
        sk.appendChild(row);
      }
      tableWrap.appendChild(sk);
    }

    /* ── Render table ─────────────────────────────────────────────────────── */

    function renderTable(files) {
      clear(tableWrap);

      var wrap = el('div', 'mf-pf__table-inner');
      var table = el('table', 'mf-pf__table');

      /* Head */
      var thead = document.createElement('thead');
      var htr = document.createElement('tr');
      ['', 'File Path', 'Ext', 'Size', 'Modified', 'State', 'Actions'].forEach(function (col) {
        var th = document.createElement('th');
        th.textContent = col;
        htr.appendChild(th);
      });
      thead.appendChild(htr);
      table.appendChild(thead);

      /* Body */
      var tbody = document.createElement('tbody');
      files.forEach(function (file, idx) {
        var rowKey = String(file.id || '') + '|' + String(file.source_path || '') + '|' + idx;

        /* Data row */
        var tr = document.createElement('tr');
        tr.className = 'mf-pf__data-row';
        tr.dataset.rowKey = rowKey;

        /* Expand arrow */
        var tdExp = document.createElement('td');
        tdExp.className = 'mf-pf__expand-cell';
        var arrow = el('span');
        arrow.textContent = expandedRows.has(rowKey) ? '▼' : '▶';
        arrow.title = 'Toggle details';
        tdExp.appendChild(arrow);
        tr.appendChild(tdExp);

        /* Path */
        var tdPath = document.createElement('td');
        tdPath.className = 'mf-pf__path-cell';
        tdPath.title = file.source_path || '';
        tdPath.textContent = shortPath(file.source_path);
        tr.appendChild(tdPath);

        /* Ext */
        var tdExt = document.createElement('td');
        tdExt.className = 'mf-pf__ext-cell';
        tdExt.textContent = file.file_ext || '';
        tr.appendChild(tdExt);

        /* Size */
        var tdSize = document.createElement('td');
        tdSize.className = 'mf-pf__size-cell';
        tdSize.textContent = fmtBytes(file.file_size_bytes);
        tr.appendChild(tdSize);

        /* Modified */
        var tdMod = document.createElement('td');
        tdMod.className = 'mf-pf__mod-cell';
        tdMod.textContent = fmtLocalTime(file.source_mtime);
        tr.appendChild(tdMod);

        /* State badge */
        var tdState = document.createElement('td');
        var badge = el('span', 'mf-pf__badge mf-pf__badge--' + (file.status || 'unknown'));
        badge.textContent = (file.status || '').replace(/_/g, ' ');
        tdState.appendChild(badge);
        tr.appendChild(tdState);

        /* Actions */
        var tdAct = document.createElement('td');
        tdAct.className = 'mf-pf__actions-cell';
        if (file.source_path) {
          var btnView = el('button', 'mf-pf__action-btn');
          btnView.title = 'Open in viewer';
          btnView.textContent = '👁️';
          (function (path) {
            btnView.addEventListener('click', function () {
              window.open('/static/viewer.html?path=' + encodeURIComponent(path), '_blank');
            });
          })(file.source_path);
          tdAct.appendChild(btnView);
        }
        tr.appendChild(tdAct);
        tbody.appendChild(tr);

        /* Detail row */
        var trDetail = document.createElement('tr');
        trDetail.className = 'mf-pf__detail-row';
        trDetail.dataset.detailFor = rowKey;
        if (!expandedRows.has(rowKey)) trDetail.hidden = true;

        var tdDetail = document.createElement('td');
        tdDetail.colSpan = 7;
        tdDetail.appendChild(buildDetailInner(file));
        trDetail.appendChild(tdDetail);
        tbody.appendChild(trDetail);

        /* Toggle expand */
        tdExp.addEventListener('click', function (e) {
          e.stopPropagation();
          var isExpanded = expandedRows.has(rowKey);
          if (isExpanded) {
            expandedRows.delete(rowKey);
            trDetail.hidden = true;
            arrow.textContent = '▶';
          } else {
            expandedRows.add(rowKey);
            trDetail.hidden = false;
            arrow.textContent = '▼';
          }
        });
      });

      table.appendChild(tbody);
      wrap.appendChild(table);
      tableWrap.appendChild(wrap);
    }

    /* ── Build detail panel ───────────────────────────────────────────────── */

    function buildDetailInner(file) {
      var inner = el('div', 'mf-pf__detail-inner');
      var dl = document.createElement('dl');
      dl.className = 'mf-pf__detail-grid';

      function addRow(label, value, cls) {
        if (value == null || value === '') return;
        var dt = document.createElement('dt');
        dt.textContent = label;
        dl.appendChild(dt);
        var dd = document.createElement('dd');
        if (cls) dd.className = cls;
        dd.textContent = String(value);
        dl.appendChild(dd);
      }

      addRow('Full Path', file.source_path);
      addRow('Error', file.error_msg, 'mf-pf__detail-err');
      addRow('Skip Reason', file.skip_reason, 'mf-pf__detail-warn');
      addRow('Converted At', fmtLocalTime(file.converted_at));
      addRow('Source Modified', fmtLocalTime(file.source_mtime));
      if (file.file_size_bytes != null) {
        addRow('Size (bytes)', Number(file.file_size_bytes).toLocaleString());
      }
      addRow('Content Hash', file.content_hash);

      if (file.job_id) {
        var dt = document.createElement('dt');
        dt.textContent = 'Job ID';
        dl.appendChild(dt);
        var dd = document.createElement('dd');
        var a = document.createElement('a');
        a.textContent = file.job_id;
        a.href = '/static/job-detail.html?job_id=' + encodeURIComponent(file.job_id);
        a.target = '_blank';
        dd.appendChild(a);
        dl.appendChild(dd);
      }

      inner.appendChild(dl);
      return inner;
    }

    /* ── Render pagination ────────────────────────────────────────────────── */

    function renderPaging(page, pages) {
      pagingEl.style.display = '';
      prevBtn.disabled = (page <= 1);
      nextBtn.disabled = (page >= pages);
      pageInfo.textContent = 'Page ' + page + ' of ' + pages;
    }

    /* ── Load files ───────────────────────────────────────────────────────── */

    function loadFiles() {
      if (!activeStates.size) {
        renderEmpty('Select one or more categories above to browse files.');
        resultCount.textContent = '';
        pagingEl.style.display = 'none';
        largeWarn.style.display = 'none';
        return;
      }

      renderSkeleton();

      var statusParam = Array.from(activeStates).join(',');
      var url = '/api/pipeline/files?status=' + encodeURIComponent(statusParam)
              + '&page=' + currentPage
              + '&per_page=' + perPage;
      if (searchQuery) url += '&search=' + encodeURIComponent(searchQuery);
      if (includeTrashed) url += '&include_trashed=true';

      fetch(url, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          totalFiles = data.total || 0;
          resultCount.textContent = fmtNum(totalFiles) + ' file' + (totalFiles !== 1 ? 's' : '');
          largeWarn.style.display = totalFiles > 5000 ? '' : 'none';

          if (!data.files || !data.files.length) {
            renderEmpty('No files match the selected filters.');
            pagingEl.style.display = 'none';
            return;
          }

          renderTable(data.files);
          renderPaging(data.page, data.pages);
        })
        .catch(function (e) {
          renderEmpty('Error loading files: ' + (e.message || 'unknown'));
          pagingEl.style.display = 'none';
        });
    }

    /* ── Pill bar click ───────────────────────────────────────────────────── */

    pillBar.addEventListener('click', function (e) {
      var btn = e.target.closest('.mf-pf__pill');
      if (!btn) return;
      var key = btn.dataset.stateKey;
      if (!key) return;

      if (key === 'all') {
        activeStates.clear();
      } else {
        if (activeStates.has(key)) {
          activeStates.delete(key);
        } else {
          activeStates.add(key);
        }
      }

      currentPage = 1;
      expandedRows.clear();
      syncPills();
      pushUrlState();
      loadFiles();
    });

    /* ── Search ───────────────────────────────────────────────────────────── */

    searchInput.addEventListener('input', function () {
      clearTimeout(debounceTimer);
      var val = searchInput.value.trim();
      debounceTimer = setTimeout(function () {
        searchQuery = val;
        currentPage = 1;
        expandedRows.clear();
        loadFiles();
      }, 300);
    });

    /* ── Include-trashed toggle ───────────────────────────────────────────── */

    trashedCb.addEventListener('change', function () {
      includeTrashed = trashedCb.checked;
      currentPage = 1;
      expandedRows.clear();
      loadStats();
      loadFiles();
    });

    /* ── Pagination controls ──────────────────────────────────────────────── */

    prevBtn.addEventListener('click', function () {
      if (currentPage > 1) {
        currentPage--;
        expandedRows.clear();
        loadFiles();
      }
    });

    nextBtn.addEventListener('click', function () {
      currentPage++;
      expandedRows.clear();
      loadFiles();
    });

    perPageSel.addEventListener('change', function () {
      perPage = parseInt(perPageSel.value, 10) || 50;
      currentPage = 1;
      expandedRows.clear();
      loadFiles();
    });

    /* ── Init ─────────────────────────────────────────────────────────────── */

    readUrlState();
    syncPills();
    loadStats();
    loadFiles();

    statsTimer = setInterval(function () {
      if (!document.hidden) loadStats();
    }, 30000);

    filesTimer = setInterval(function () {
      if (!document.hidden) loadFiles();
    }, 30000);

    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        loadStats();
        loadFiles();
      }
    });

    /* ── Return handle ────────────────────────────────────────────────────── */
    return {
      refresh: loadFiles,
      destroy: function () {
        if (statsTimer) clearInterval(statsTimer);
        if (filesTimer) clearInterval(filesTimer);
      },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */

  global.MFPipelineFiles = { mount: mount };

})(window);
