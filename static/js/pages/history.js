/* Conversion History page component (new-UX).
 *
 * Usage:
 *   MFHistory.mount(root, { role });
 *
 * API endpoints:
 *   GET /api/history          — paginated conversion records
 *   GET /api/history/stats    — aggregate stats (totals, success rate, OCR)
 *   GET /api/history/:id/redownload — re-download output for a record
 *   GET /api/bulk/pending     — pending/failed files card
 *   POST /api/pipeline/run-now         — force transcribe/convert pending
 *   POST /api/pipeline/convert-selected — convert selected pending files
 *
 * Safe DOM throughout — no innerHTML with user data.
 *
 * TODO: date-range filter (defer — add date_from/date_to params to filter bar)
 * TODO: source-folder filter (defer — add folder dropdown once API supports it)
 * TODO: inline error drill-down modal (defer — currently links to /review.html)
 * TODO: "Clear all history" bulk-delete (admin only — defer until confirmation modal exists)
 * TODO: drag-and-drop batch operations (out of scope for initial build)
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

  function fmtBytes(bytes) {
    if (!bytes) return '0 B';
    var b = Number(bytes);
    if (!b) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), units.length - 1);
    return (i === 0 ? b : (b / Math.pow(1024, i)).toFixed(1)) + ' ' + units[i];
  }

  function fmtDur(ms) {
    if (!ms) return '—';
    var s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    if (s < 3600) return Math.round(s / 60) + 'm ' + Math.round(s % 60) + 's';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h + 'h ' + m + 'm';
  }

  function fmtLocalTime(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function fmtMediaDur(seconds) {
    if (!seconds) return '';
    var s = Math.floor(seconds);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
  }

  /* ── API endpoints ────────────────────────────────────────────────────── */

  var API_HISTORY          = '/api/history';
  var API_HISTORY_STATS    = '/api/history/stats';
  var API_REDOWNLOAD       = function (id) { return '/api/history/' + id + '/redownload'; };
  var API_BULK_PENDING     = '/api/bulk/pending';
  var API_PIPELINE_RUN     = '/api/pipeline/run-now';
  var API_CONVERT_SELECTED = '/api/pipeline/convert-selected';

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFHistory.mount: root element is required');

    /* State */
    var currentPage    = 1;
    var currentSort    = 'date_desc';
    var currentFormat  = '';
    var currentStatus  = '';
    var currentSearch  = '';
    var debounceTimer  = null;
    var expandedRowId  = null;

    var pendingPage    = 1;
    var pendingPerPage = 50;
    var pendingSelectedIds   = new Set();
    var pendingSelectedFiles = Object.create(null);
    var PENDING_SELECT_CAP   = 100;

    /* ── Inject page styles (once) ──────────────────────────────────────── */
    if (!document.getElementById('mf-history-styles')) {
      var style = document.createElement('style');
      style.id = 'mf-history-styles';
      style.textContent = [
        '.mf-page-wrapper{max-width:1100px;margin:0 auto;padding:1.5rem 1rem;}',
        '.mf-page-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;}',
        '.mf-page-title{margin:0 0 0.25rem 0;font-size:1.6rem;font-weight:700;}',
        '.mf-page-header__actions{display:flex;gap:0.5rem;align-items:center;}',
        '.mf-hist__stats-row{display:flex;flex-wrap:wrap;gap:1rem;padding:0.65rem 0.9rem;',
        'background:var(--mf-surface-soft,rgba(0,0,0,0.04));',
        'border-radius:var(--mf-radius,8px);margin-bottom:1rem;font-size:0.84rem;}',
        '.mf-hist__stat{display:flex;flex-direction:column;gap:0.1rem;}',
        '.mf-hist__stat-val{font-weight:700;font-size:1.1rem;}',
        '.mf-hist__stat-lab{font-size:0.72rem;color:var(--mf-color-text-muted,#888);text-transform:uppercase;}',
        /* Pending card */
        '.mf-hist__pending-card{background:var(--mf-surface,#fff);',
        'border:1px solid var(--mf-border,rgba(0,0,0,0.1));',
        'border-radius:var(--mf-radius,8px);padding:1rem;margin-bottom:1rem;}',
        '.mf-hist__pending-head{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;}',
        '.mf-hist__pending-title{display:flex;align-items:center;gap:0.5rem;margin:0;font-size:1rem;font-weight:600;}',
        '.mf-hist__pending-badge{font-size:0.8rem;padding:0.15em 0.5em;border-radius:var(--mf-radius-sm,4px);',
        'background:rgba(79,91,213,0.12);color:var(--mf-color-accent,#4f5bd5);}',
        '.mf-hist__pending-badge--fail{background:rgba(220,38,38,0.1);color:var(--mf-color-error,#dc2626);}',
        '.mf-hist__pending-controls{display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;}',
        '.mf-hist__bulk-bar{display:none;margin-top:0.75rem;padding:0.5rem 0.75rem;',
        'background:rgba(79,91,213,0.08);border:1px solid rgba(79,91,213,0.3);',
        'border-radius:var(--mf-radius-sm,4px);align-items:center;gap:0.6rem;font-size:0.84rem;}',
        '.mf-hist__bulk-bar--visible{display:flex;}',
        /* Filter bar */
        '.mf-hist__filter-bar{display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;align-items:center;}',
        '.mf-hist__filter-bar input[type=search],.mf-hist__filter-bar select{',
        'padding:0.35em 0.6em;border:1px solid var(--mf-border,rgba(0,0,0,0.15));',
        'border-radius:var(--mf-radius-sm,4px);background:var(--mf-surface,#fff);',
        'color:var(--mf-color-text,#111);font-size:0.84rem;}',
        '.mf-hist__filter-bar input[type=search]{min-width:180px;}',
        /* Table wrapper */
        '.mf-hist__table-wrap{background:var(--mf-surface,#fff);',
        'border:1px solid var(--mf-border,rgba(0,0,0,0.1));',
        'border-radius:var(--mf-radius,8px);overflow:auto;margin-bottom:0.75rem;}',
        '.mf-hist__table{width:100%;border-collapse:collapse;font-size:0.84rem;}',
        '.mf-hist__table th{text-align:left;padding:0.55rem 0.75rem;',
        'background:var(--mf-surface-soft,rgba(0,0,0,0.03));',
        'border-bottom:2px solid var(--mf-border,rgba(0,0,0,0.1));',
        'font-size:0.76rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;',
        'color:var(--mf-color-text-muted,#888);white-space:nowrap;}',
        '.mf-hist__table th[data-sort]{cursor:pointer;user-select:none;}',
        '.mf-hist__table th[data-sort]:hover{color:var(--mf-color-text,#111);}',
        '.mf-hist__table td{padding:0.45rem 0.75rem;border-bottom:1px solid var(--mf-border,rgba(0,0,0,0.07));',
        'vertical-align:top;}',
        '.mf-hist__table tr:last-child td{border-bottom:none;}',
        '.mf-hist__table .clickable:hover td{background:var(--mf-surface-soft,rgba(0,0,0,0.03));cursor:pointer;}',
        '.mf-hist__table .detail-row td{background:var(--mf-surface-alt,rgba(0,0,0,0.04));padding:1rem 1.25rem;}',
        '.mf-hist__fname{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
        '.mf-mono{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:0.8rem;}',
        '.mf-hist__format-badge{display:inline-block;padding:0.1em 0.4em;border-radius:0.3em;',
        'font-size:0.72rem;font-weight:700;text-transform:uppercase;',
        'background:var(--mf-surface-alt,rgba(0,0,0,0.07));color:var(--mf-color-text,#111);}',
        '.mf-status-ok{color:var(--mf-color-success,#16a34a);font-weight:600;}',
        '.mf-status-err{color:var(--mf-color-error,#dc2626);font-weight:600;}',
        /* OCR badge */
        '.mf-ocr-badge{display:inline-flex;align-items:center;gap:0.2em;',
        'font-size:0.72rem;font-weight:700;padding:0.15em 0.45em;border-radius:var(--mf-radius-sm,4px);}',
        '.mf-ocr-badge--ok{background:rgba(22,163,74,0.1);color:var(--mf-color-success,#16a34a);}',
        '.mf-ocr-badge--warn{background:rgba(217,119,6,0.1);color:var(--mf-color-warn,#d97706);}',
        '.mf-ocr-badge--error{background:rgba(220,38,38,0.1);color:var(--mf-color-error,#dc2626);}',
        /* Detail grid */
        '.mf-hist__detail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));',
        'gap:0.4rem 1.25rem;}',
        '.mf-hist__detail-grid dt{font-weight:600;color:var(--mf-color-text-muted,#888);',
        'font-size:0.75rem;text-transform:uppercase;letter-spacing:.03em;}',
        '.mf-hist__detail-grid dd{margin:0 0 0.5rem 0;font-size:0.88rem;}',
        '.mf-hist__detail-actions{margin-top:0.75rem;display:flex;gap:0.5rem;flex-wrap:wrap;}',
        /* Pagination */
        '.mf-hist__paging{display:flex;align-items:center;justify-content:space-between;',
        'flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem;font-size:0.82rem;}',
        '.mf-hist__paging-pages{display:flex;gap:0.25rem;flex-wrap:wrap;}',
        '.mf-hist__paging-pages button,.mf-hist__paging-pages .ellipsis{',
        'padding:0.25em 0.55em;border:1px solid var(--mf-border,rgba(0,0,0,0.12));',
        'border-radius:var(--mf-radius-sm,4px);background:var(--mf-surface,#fff);',
        'color:var(--mf-color-text,#111);cursor:pointer;font-size:0.8rem;}',
        '.mf-hist__paging-pages button.active{background:var(--mf-color-accent,#4f5bd5);',
        'border-color:var(--mf-color-accent,#4f5bd5);color:#fff;}',
        '.mf-hist__paging-pages button:disabled{opacity:0.4;cursor:default;}',
        '.mf-hist__paging-pages .ellipsis{border:none;background:none;cursor:default;}',
        /* Empty state */
        '.mf-hist__empty{text-align:center;padding:2.5rem 1rem;color:var(--mf-color-text-muted,#888);}',
        /* Pending table */
        '.mf-hist__pending-table{width:100%;border-collapse:collapse;font-size:0.8rem;margin-top:0.75rem;}',
        '.mf-hist__pending-table th{text-align:left;padding:0.3rem 0.5rem;',
        'border-bottom:2px solid var(--mf-border,rgba(0,0,0,0.1));',
        'font-size:0.72rem;font-weight:700;text-transform:uppercase;color:var(--mf-color-text-muted,#888);}',
        '.mf-hist__pending-table td{padding:0.3rem 0.5rem;',
        'border-bottom:1px solid var(--mf-border,rgba(0,0,0,0.06));vertical-align:middle;}',
        '.mf-hist__pending-table tr:last-child td{border-bottom:none;}',
        '.mf-hist__pending-paging{display:flex;gap:0.5rem;align-items:center;',
        'justify-content:center;margin-top:0.6rem;font-size:0.8rem;}',
        /* Shared buttons */
        '.mf-btn{display:inline-flex;align-items:center;gap:0.3rem;padding:0.45em 0.9em;',
        'border-radius:var(--mf-radius-sm,5px);border:1px solid transparent;',
        'font-size:0.84rem;font-weight:500;cursor:pointer;transition:background .15s,opacity .15s;}',
        '.mf-btn--sm{padding:0.3em 0.65em;font-size:0.78rem;}',
        '.mf-btn--ghost{background:transparent;border-color:var(--mf-border,rgba(0,0,0,0.15));',
        'color:var(--mf-color-text,#111);}',
        '.mf-btn--ghost:hover{background:var(--mf-surface-alt,rgba(0,0,0,0.06));}',
        '.mf-btn--primary{background:var(--mf-color-accent,#4f5bd5);border-color:transparent;color:#fff;}',
        '.mf-btn--primary:hover{opacity:0.88;}',
        '.mf-btn:disabled{opacity:0.5;cursor:not-allowed;}',
        '.mf-spinner{display:inline-block;width:0.8em;height:0.8em;border-radius:50%;',
        'border:2px solid rgba(0,0,0,0.15);border-top-color:var(--mf-color-accent,#4f5bd5);',
        'animation:mf-spin 0.7s linear infinite;vertical-align:middle;}',
        '@keyframes mf-spin{to{transform:rotate(360deg)}}',
        '.mf-text--muted{color:var(--mf-color-text-muted,#888);}',
        '.mf-text--sm{font-size:0.84rem;}',
        '.mf-toast{position:fixed;bottom:1.5rem;right:1.5rem;padding:0.65rem 1rem;',
        'border-radius:var(--mf-radius-sm,5px);font-size:0.84rem;color:#fff;z-index:9999;',
        'opacity:0;transform:translateY(6px);transition:opacity .2s,transform .2s;}',
        '.mf-toast--visible{opacity:1;transform:none;}',
        '.mf-toast--info{background:#334155;}',
        '.mf-toast--success{background:var(--mf-color-success,#16a34a);}',
        '.mf-toast--error{background:var(--mf-color-error,#dc2626);}',
        '.mf-select{padding:0.3em 0.5em;border:1px solid var(--mf-border,rgba(0,0,0,0.15));',
        'border-radius:var(--mf-radius-sm,4px);background:var(--mf-surface,#fff);',
        'color:var(--mf-color-text,#111);font-size:0.84rem;}',
        '.mf-select--sm{font-size:0.8rem;padding:0.25em 0.4em;}',
      ].join('');
      document.head.appendChild(style);
    }

    /* ── Skeleton ─────────────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-page-wrapper');

    /* Page header */
    var pageHeader = el('div', 'mf-page-header');
    var headingGroup = el('div');
    var heading = el('h1', 'mf-page-title');
    heading.textContent = 'Conversion History';
    headingGroup.appendChild(heading);
    pageHeader.appendChild(headingGroup);
    /* TODO: Add "Clear all" admin action once a confirmation modal exists */
    wrapper.appendChild(pageHeader);

    /* Stats row */
    var statsRow = el('div', 'mf-hist__stats-row');
    wrapper.appendChild(statsRow);

    /* Pending Files card */
    var pendingCard = el('div', 'mf-hist__pending-card');
    pendingCard.style.display = 'none';

    var pendingHead = el('div', 'mf-hist__pending-head');
    var pendingTitleEl = el('h3', 'mf-hist__pending-title');
    var pendingTitleText = el('span');
    pendingTitleText.textContent = 'Pending Files';
    var pendingBadge = el('span', 'mf-hist__pending-badge');
    pendingBadge.textContent = '0';
    pendingTitleEl.appendChild(pendingTitleText);
    pendingTitleEl.appendChild(pendingBadge);
    pendingHead.appendChild(pendingTitleEl);

    var pendingControls = el('div', 'mf-hist__pending-controls');
    var forceTranscribeBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    forceTranscribeBtn.textContent = 'Force Transcribe / Convert Pending';
    forceTranscribeBtn.title = 'Trigger an immediate scan + convert cycle';
    var pendingStatusFilter = el('select', 'mf-select mf-select--sm');
    [
      { value: 'pending', label: 'Pending' },
      { value: 'failed',  label: 'Failed' },
    ].forEach(function (opt) {
      var o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      pendingStatusFilter.appendChild(o);
    });
    var pendingSearch = el('input');
    pendingSearch.type = 'search';
    pendingSearch.placeholder = 'Search…';
    pendingSearch.style.cssText = 'font-size:0.8rem;padding:0.3rem 0.5rem;width:160px;' +
      'border:1px solid var(--mf-border,rgba(0,0,0,0.15));border-radius:4px;' +
      'background:var(--mf-surface,#fff);color:var(--mf-color-text,#111);';

    pendingControls.appendChild(forceTranscribeBtn);
    pendingControls.appendChild(pendingStatusFilter);
    pendingControls.appendChild(pendingSearch);
    pendingHead.appendChild(pendingControls);
    pendingCard.appendChild(pendingHead);

    /* Bulk action bar */
    var pendingBulkBar = el('div', 'mf-hist__bulk-bar');
    var pendingBulkCount = el('strong');
    pendingBulkCount.textContent = '0 selected';
    var pendingBulkCtx = el('span', 'mf-text--muted mf-text--sm');
    var pendingBulkSpacer = el('span');
    pendingBulkSpacer.style.flex = '1';
    var pendingBulkConvert = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    pendingBulkConvert.textContent = 'Convert Selected';
    var pendingBulkClear = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    pendingBulkClear.textContent = 'Clear selection';
    pendingBulkBar.appendChild(pendingBulkCount);
    pendingBulkBar.appendChild(pendingBulkCtx);
    pendingBulkBar.appendChild(pendingBulkSpacer);
    pendingBulkBar.appendChild(pendingBulkConvert);
    pendingBulkBar.appendChild(pendingBulkClear);
    pendingCard.appendChild(pendingBulkBar);

    /* Pending table */
    var pendingTableWrap = el('div');
    pendingTableWrap.style.overflowX = 'auto';
    var pendingTable = el('table', 'mf-hist__pending-table');
    var pendingThead = document.createElement('thead');
    var pendingHeadRow = document.createElement('tr');

    var pendingSelectAllTh = document.createElement('th');
    pendingSelectAllTh.style.cssText = 'width:32px;padding-right:0';
    var pendingSelectAll = document.createElement('input');
    pendingSelectAll.type = 'checkbox';
    pendingSelectAll.title = 'Select all files on this page';
    pendingSelectAll.style.cursor = 'pointer';
    pendingSelectAllTh.appendChild(pendingSelectAll);
    pendingHeadRow.appendChild(pendingSelectAllTh);

    ['File', 'Type', 'Size', 'Job Started', 'Status / Error'].forEach(function (col) {
      var th = document.createElement('th');
      th.textContent = col;
      pendingHeadRow.appendChild(th);
    });
    pendingThead.appendChild(pendingHeadRow);
    pendingTable.appendChild(pendingThead);
    var pendingTbody = document.createElement('tbody');
    pendingTable.appendChild(pendingTbody);
    pendingTableWrap.appendChild(pendingTable);
    pendingCard.appendChild(pendingTableWrap);

    var pendingPaging = el('div', 'mf-hist__pending-paging');
    pendingCard.appendChild(pendingPaging);

    wrapper.appendChild(pendingCard);

    /* Filter bar */
    var filterBar = el('div', 'mf-hist__filter-bar');
    var filterFormat = el('select');
    /* Default "All formats" option — additional ones added by populateFormatFilter */
    var defaultFmtOpt = document.createElement('option');
    defaultFmtOpt.value = '';
    defaultFmtOpt.textContent = 'All formats';
    filterFormat.appendChild(defaultFmtOpt);

    var filterStatus = el('select');
    [
      { value: '', label: 'All status' },
      { value: 'success', label: 'Success' },
      { value: 'error',   label: 'Error' },
    ].forEach(function (opt) {
      var o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      filterStatus.appendChild(o);
    });
    var filterSearch = el('input');
    filterSearch.type = 'search';
    filterSearch.placeholder = 'Search files…';
    filterBar.appendChild(filterFormat);
    filterBar.appendChild(filterStatus);
    filterBar.appendChild(filterSearch);
    var clearFilterBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    clearFilterBtn.textContent = 'Clear filters';
    filterBar.appendChild(clearFilterBtn);
    wrapper.appendChild(filterBar);

    /* History table */
    var tableWrap = el('div', 'mf-hist__table-wrap');
    var histTable = el('table', 'mf-hist__table');
    var histThead = document.createElement('thead');
    var histHeadRow = document.createElement('tr');

    var COL_DEFS = [
      { label: 'Filename', sort: 'date_desc'     },
      { label: 'Format',   sort: null            },
      { label: 'Status',   sort: null            },
      { label: 'Duration', sort: 'duration_desc' },
      { label: 'Date',     sort: 'date_desc'     },
      { label: 'OCR',      sort: null            },
    ];

    var sortIcons = {};
    COL_DEFS.forEach(function (col) {
      var th = document.createElement('th');
      if (col.sort) {
        th.setAttribute('data-sort', col.sort);
        var sortIcon = el('span');
        sortIcons[col.sort] = sortIcon;
        th.appendChild(txt(col.label + ' '));
        th.appendChild(sortIcon);
        /* Capture col in closure */
        (function (c, si) {
          th.addEventListener('click', function () {
            var base = c.sort.replace(/_(?:asc|desc)$/, '');
            var isAsc = currentSort === base + '_asc';
            currentSort = isAsc ? base + '_desc' : base + '_asc';
            currentPage = 1;
            Object.keys(sortIcons).forEach(function (k) { sortIcons[k].textContent = ''; });
            si.textContent = isAsc ? ' ↓' : ' ↑';
            loadHistory();
          });
        })(col, sortIcon);
      } else {
        th.textContent = col.label;
      }
      histHeadRow.appendChild(th);
    });
    histThead.appendChild(histHeadRow);
    histTable.appendChild(histThead);

    var histTbody = document.createElement('tbody');
    var loadingRow = document.createElement('tr');
    var loadingTd = document.createElement('td');
    loadingTd.colSpan = 6;
    loadingTd.style.cssText = 'text-align:center;padding:2rem;';
    var loadingSpinner = el('span', 'mf-spinner');
    loadingTd.appendChild(loadingSpinner);
    loadingTd.appendChild(txt(' Loading…'));
    loadingRow.appendChild(loadingTd);
    histTbody.appendChild(loadingRow);
    histTable.appendChild(histTbody);
    tableWrap.appendChild(histTable);
    wrapper.appendChild(tableWrap);

    /* Pagination */
    var pagingEl = el('div', 'mf-hist__paging');
    var pagingInfo = el('span', 'mf-text--muted mf-text--sm');
    var pagingPages = el('div', 'mf-hist__paging-pages');
    pagingEl.appendChild(pagingInfo);
    pagingEl.appendChild(pagingPages);
    wrapper.appendChild(pagingEl);

    /* Empty state */
    var emptyState = el('div', 'mf-hist__empty');
    emptyState.style.display = 'none';
    var emptyH3 = el('h3');
    emptyH3.textContent = 'No conversions yet';
    var emptyP = el('p');
    emptyP.textContent = 'Convert your first file to see it here.';
    var emptyLink = el('a', 'mf-btn mf-btn--primary');
    emptyLink.href = '/';
    emptyLink.textContent = 'Convert a file';
    emptyState.appendChild(emptyH3);
    emptyState.appendChild(emptyP);
    emptyState.appendChild(emptyLink);
    wrapper.appendChild(emptyState);

    var emptyFiltered = el('div', 'mf-hist__empty');
    emptyFiltered.style.display = 'none';
    var efH3 = el('h3');
    efH3.textContent = 'No results match your filters';
    var efP = el('p');
    var efBtn = el('button', 'mf-btn mf-btn--ghost');
    efBtn.textContent = 'Clear filters';
    efBtn.addEventListener('click', clearFilters);
    emptyFiltered.appendChild(efH3);
    emptyFiltered.appendChild(efP);
    emptyFiltered.appendChild(efBtn);
    wrapper.appendChild(emptyFiltered);

    root.appendChild(wrapper);

    /* ── Init URL params ──────────────────────────────────────────────────── */
    var urlParams = new URLSearchParams(location.search);
    if (urlParams.get('format')) { currentFormat = urlParams.get('format'); filterFormat.value = currentFormat; }
    if (urlParams.get('status')) { currentStatus = urlParams.get('status'); filterStatus.value = currentStatus; }
    if (urlParams.get('search')) { currentSearch = urlParams.get('search'); filterSearch.value = currentSearch; }
    if (urlParams.get('page'))   { currentPage = parseInt(urlParams.get('page'), 10) || 1; }
    if (urlParams.get('sort'))   { currentSort = urlParams.get('sort'); }

    /* ── OCR helpers ──────────────────────────────────────────────────────── */

    function ocrConfClass(conf, threshold) {
      if (conf == null) return 'ok';
      if (conf >= (threshold || 80)) return 'ok';
      if (conf >= 60) return 'warn';
      return 'error';
    }

    function buildOcrBadge(ocr) {
      if (!ocr || !ocr.ran) return null;
      if (ocr.confidence_mean == null) {
        var badge = el('span', 'mf-ocr-badge mf-ocr-badge--ok');
        badge.textContent = 'OCR';
        return badge;
      }
      var cls = ocrConfClass(ocr.confidence_mean, ocr.threshold);
      var badge = el('span', 'mf-ocr-badge mf-ocr-badge--' + cls);
      badge.textContent = 'OCR ' + Math.round(ocr.confidence_mean) + '%' +
        (cls === 'error' ? ' ⚠' : '');
      return badge;
    }

    /* ── Stats ────────────────────────────────────────────────────────────── */

    fetch(API_HISTORY_STATS, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (stats) {
        clear(statsRow);
        var rate = stats.total_conversions > 0 ? stats.success_rate_pct : 0;
        var defs = [
          { val: (stats.total_conversions || 0).toLocaleString(), lab: 'conversions' },
          { val: (rate || 0) + '%',                               lab: 'success rate' },
          { val: fmtDur(stats.avg_duration_ms),                   lab: 'avg duration' },
          { val: fmtBytes(stats.total_size_bytes_processed),      lab: 'processed' },
        ];
        if (stats.ocr_stats) {
          defs.push({
            val: stats.ocr_stats.mean_confidence_overall != null
              ? stats.ocr_stats.mean_confidence_overall.toFixed(1) + '%' : '—',
            lab: 'OCR avg confidence',
          });
          defs.push({
            val: String(stats.ocr_stats.files_below_threshold || 0),
            lab: 'below OCR threshold',
          });
        }
        defs.forEach(function (d) {
          var stat = el('div', 'mf-hist__stat');
          var v = el('div', 'mf-hist__stat-val');
          v.textContent = d.val;
          var l = el('div', 'mf-hist__stat-lab');
          l.textContent = d.lab;
          stat.appendChild(v);
          stat.appendChild(l);
          statsRow.appendChild(stat);
        });
      })
      .catch(function () { /* stats non-critical */ });

    /* ── Load history ─────────────────────────────────────────────────────── */

    function updateURL() {
      var p = new URLSearchParams();
      if (currentFormat) p.set('format', currentFormat);
      if (currentStatus) p.set('status', currentStatus);
      if (currentSearch) p.set('search', currentSearch);
      if (currentSort !== 'date_desc') p.set('sort', currentSort);
      if (currentPage > 1) p.set('page', String(currentPage));
      var qs = p.toString();
      history.replaceState(null, '', qs ? '?' + qs : location.pathname);
    }

    function loadHistory() {
      updateURL();
      var qs = new URLSearchParams({ page: currentPage, per_page: 25, sort: currentSort });
      if (currentFormat) qs.set('format', currentFormat);
      if (currentStatus) qs.set('status', currentStatus);
      if (currentSearch) qs.set('search', currentSearch);

      /* Spinner row while loading */
      clear(histTbody);
      var spinRow = document.createElement('tr');
      var spinTd = document.createElement('td');
      spinTd.colSpan = 6;
      spinTd.style.cssText = 'text-align:center;padding:2rem;';
      spinTd.appendChild(el('span', 'mf-spinner'));
      spinTd.appendChild(txt(' Loading…'));
      spinRow.appendChild(spinTd);
      histTbody.appendChild(spinRow);

      fetch(API_HISTORY + '?' + qs.toString(), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          renderTable(data);
          renderPagination(data);
          populateFormatFilter(data.formats_available || []);

          var hasRecords = data.records && data.records.length > 0;
          var isFiltered = !!(currentFormat || currentStatus || currentSearch);

          tableWrap.style.display = hasRecords ? '' : 'none';
          pagingEl.style.display = hasRecords ? '' : 'none';
          emptyState.style.display = (!hasRecords && !isFiltered) ? '' : 'none';
          emptyFiltered.style.display = (!hasRecords && isFiltered) ? '' : 'none';

          if (!hasRecords && isFiltered) {
            efP.textContent = 'No conversions' +
              (currentSearch ? ' matching "' + currentSearch + '"' : '') +
              ' with the current filters.';
          }
        })
        .catch(function (e) {
          clear(histTbody);
          var errRow = document.createElement('tr');
          var errTd = document.createElement('td');
          errTd.colSpan = 6;
          errTd.style.cssText = 'text-align:center;padding:2rem;color:var(--mf-color-error,#dc2626);';
          errTd.textContent = 'Failed to load history: ' + e.message;
          errRow.appendChild(errTd);
          histTbody.appendChild(errRow);
        });
    }

    /* ── Render table ─────────────────────────────────────────────────────── */

    var ENGINE_LABELS = {
      whisper_local:          'Whisper',
      whisper_cloud_openai:   'Cloud: OpenAI',
      whisper_cloud_gemini:   'Cloud: Gemini',
      caption_ingest:         'Caption',
    };

    var VIDEO_EXTS = ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'm4v', 'webm'];

    function renderTable(data) {
      clear(histTbody);
      expandedRowId = null;

      if (!data.records || !data.records.length) return;

      data.records.forEach(function (r) {
        var isMedia = r.media_engine != null;
        var mediaDur = isMedia && r.media_duration_seconds
          ? fmtMediaDur(r.media_duration_seconds) : '';
        var mediaIcon = isMedia
          ? (VIDEO_EXTS.indexOf(r.source_format) >= 0 ? '🎬 ' : '🎵 ')
          : '';

        /* Main row */
        var tr = document.createElement('tr');
        tr.className = 'clickable' + (r.status === 'error' ? ' row-error' : '');

        /* Filename */
        var tdFile = document.createElement('td');
        var fnameSpan = el('span', 'mf-hist__fname mf-mono');
        fnameSpan.textContent = mediaIcon + (r.source_filename || '');
        fnameSpan.title = r.source_filename || '';
        tdFile.appendChild(fnameSpan);
        tr.appendChild(tdFile);

        /* Format */
        var tdFormat = document.createElement('td');
        var fmtBadge = el('span', 'mf-hist__format-badge');
        fmtBadge.textContent = (r.source_format || '').toUpperCase();
        tdFormat.appendChild(fmtBadge);
        if (isMedia) {
          var mediaBadge = el('span', 'mf-hist__format-badge');
          mediaBadge.style.marginLeft = '4px';
          mediaBadge.textContent = ENGINE_LABELS[r.media_engine] || r.media_engine;
          tdFormat.appendChild(mediaBadge);
        }
        tr.appendChild(tdFormat);

        /* Status */
        var tdStatus = document.createElement('td');
        var statusSpan = el('span', r.status === 'success' ? 'mf-status-ok' : 'mf-status-err');
        statusSpan.textContent = r.status === 'success' ? 'Success' : 'Error';
        tdStatus.appendChild(statusSpan);
        tr.appendChild(tdStatus);

        /* Duration */
        var tdDur = document.createElement('td');
        tdDur.className = 'mf-mono mf-text--sm';
        tdDur.textContent = (isMedia && mediaDur) ? mediaDur : fmtDur(r.duration_ms);
        tr.appendChild(tdDur);

        /* Date */
        var tdDate = document.createElement('td');
        tdDate.className = 'mf-text--sm';
        tdDate.textContent = fmtLocalTime(r.created_at);
        tr.appendChild(tdDate);

        /* OCR */
        var tdOcr = document.createElement('td');
        var ocrBadge = buildOcrBadge(r.ocr);
        if (ocrBadge) tdOcr.appendChild(ocrBadge);
        tr.appendChild(tdOcr);

        /* Toggle detail row on click */
        (function (rec) {
          tr.addEventListener('click', function () {
            var detId = 'mf-hist-detail-' + rec.id;
            var det = document.getElementById(detId);
            if (!det) return;
            if (expandedRowId && expandedRowId !== rec.id) {
              var prev = document.getElementById('mf-hist-detail-' + expandedRowId);
              if (prev) prev.style.display = 'none';
            }
            var isOpen = det.style.display !== 'none';
            det.style.display = isOpen ? 'none' : '';
            expandedRowId = isOpen ? null : rec.id;
          });
        })(r);

        histTbody.appendChild(tr);

        /* Detail row */
        var detRow = document.createElement('tr');
        detRow.id = 'mf-hist-detail-' + r.id;
        detRow.className = 'detail-row';
        detRow.style.display = 'none';

        var detTd = document.createElement('td');
        detTd.colSpan = 6;

        var dlEl = document.createElement('dl');
        dlEl.className = 'mf-hist__detail-grid';

        function addDetail(label, value, mono) {
          if (value == null) return;
          var dt = document.createElement('dt');
          dt.textContent = label;
          var dd = document.createElement('dd');
          if (mono) dd.className = 'mf-mono';
          dd.textContent = String(value);
          dlEl.appendChild(dt);
          dlEl.appendChild(dd);
        }

        addDetail('Converted', r.created_at || '—');
        addDetail('Direction', r.direction === 'to_md'
          ? 'Document → Markdown' : 'Markdown → Document');
        addDetail('Output', (r.output_filename || '—') +
          (r.file_size_bytes ? ' (' + fmtBytes(r.file_size_bytes) + ')' : ''), true);
        addDetail('Batch ID', r.batch_id, true);

        if (isMedia) {
          addDetail('Engine', ENGINE_LABELS[r.media_engine] || r.media_engine);
          if (r.media_language)       addDetail('Language', r.media_language);
          if (r.media_word_count)     addDetail('Words', r.media_word_count.toLocaleString());
          if (r.media_duration_seconds) addDetail('Duration', fmtMediaDur(r.media_duration_seconds));
          if (r.media_whisper_model)  addDetail('Model', r.media_whisper_model);
        }

        addDetail('OCR flags', (r.ocr_flags_total || 0) + ' total, ' + (r.ocr_flags_resolved || 0) + ' resolved');
        if (r.scene_count) addDetail('Scenes', r.scene_count + ' detected');
        if (r.enrichment_level) {
          addDetail('Enrichment', 'Level ' + r.enrichment_level +
            (r.vision_provider
              ? ' · ' + r.vision_provider + (r.vision_model ? ' (' + r.vision_model + ')' : '')
              : ''));
        }
        if (r.frame_desc_count != null && r.keyframe_count) {
          addDetail('Descriptions', r.frame_desc_count + '/' + r.keyframe_count + ' successful' +
            (r.frame_desc_count < r.keyframe_count
              ? ' (' + (r.keyframe_count - r.frame_desc_count) + ' failed)' : ''));
        }
        if (r.error_message) {
          var errDt = document.createElement('dt');
          errDt.textContent = 'Error';
          var errDd = document.createElement('dd');
          errDd.className = 'mf-status-err';
          errDd.textContent = r.error_message;
          dlEl.appendChild(errDt);
          dlEl.appendChild(errDd);
        }
        if (r.warnings && r.warnings.length) {
          addDetail('Warnings', r.warnings.join(', '));
        }

        detTd.appendChild(dlEl);

        /* Detail actions */
        var detActions = el('div', 'mf-hist__detail-actions');

        var downloadBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        downloadBtn.textContent = 'Download';
        (function (recId, btn) {
          btn.addEventListener('click', function () { redownload(recId, btn); });
        })(r.id, downloadBtn);
        detActions.appendChild(downloadBtn);

        if (r.ocr_flags_total > 0) {
          var reviewLink = el('a', 'mf-btn mf-btn--ghost mf-btn--sm');
          reviewLink.href = '/review.html?batch_id=' + encodeURIComponent(r.batch_id || '');
          reviewLink.textContent = 'OCR Review';
          detActions.appendChild(reviewLink);
        }
        /* TODO: inline error drill-down modal */

        detTd.appendChild(detActions);
        detRow.appendChild(detTd);
        histTbody.appendChild(detRow);
      });
    }

    /* ── Pagination ───────────────────────────────────────────────────────── */

    function renderPagination(data) {
      var start = (data.page - 1) * data.per_page + 1;
      var end = Math.min(data.page * data.per_page, data.total);
      pagingInfo.textContent = data.total > 0
        ? 'Showing ' + start + '–' + end + ' of ' + data.total.toLocaleString()
        : '';

      clear(pagingPages);
      if (!data.total_pages || data.total_pages <= 1) return;

      var tp = data.total_pages;
      var cp = data.page;

      function addPageBtn(label, page, isActive, disabled) {
        var btn = document.createElement('button');
        btn.textContent = String(label);
        if (isActive) btn.className = 'active';
        if (disabled) btn.disabled = true;
        if (!disabled && typeof page === 'number') {
          (function (p) {
            btn.addEventListener('click', function () { currentPage = p; loadHistory(); });
          })(page);
        }
        pagingPages.appendChild(btn);
      }

      function addEllipsis() {
        var s = el('span', 'ellipsis');
        s.textContent = '…';
        pagingPages.appendChild(s);
      }

      addPageBtn('← Prev', cp - 1, false, cp <= 1);

      var nums = [];
      if (tp <= 7) {
        for (var i = 1; i <= tp; i++) nums.push(i);
      } else {
        nums.push(1);
        if (cp > 3) nums.push('...');
        for (var j = Math.max(2, cp - 1); j <= Math.min(tp - 1, cp + 1); j++) nums.push(j);
        if (cp < tp - 2) nums.push('...');
        nums.push(tp);
      }

      nums.forEach(function (n) {
        if (n === '...') { addEllipsis(); return; }
        addPageBtn(n, n, n === cp, false);
      });

      addPageBtn('Next →', cp + 1, false, cp >= tp);
    }

    /* ── Format filter ────────────────────────────────────────────────────── */

    function populateFormatFilter(formats) {
      /* Only rebuild when the set of formats actually changes. */
      if (filterFormat.options.length - 1 === formats.length) return;
      var cur = filterFormat.value;
      /* Remove all options except the first "All formats" one. */
      while (filterFormat.options.length > 1) {
        filterFormat.remove(1);
      }
      formats.forEach(function (f) {
        var o = document.createElement('option');
        o.value = f;
        o.textContent = f.toUpperCase();
        if (f === cur) o.selected = true;
        filterFormat.appendChild(o);
      });
    }

    /* ── Re-download ──────────────────────────────────────────────────────── */

    function redownload(id, btn) {
      btn.disabled = true;
      btn.textContent = 'Downloading…';
      fetch(API_REDOWNLOAD(id), { credentials: 'same-origin' })
        .then(function (res) {
          if (res.status === 410) {
            return res.json().catch(function () { return {}; }).then(function (data) {
              btn.textContent = 'Expired';
              btn.disabled = true;
              showToast(data.message || 'Output files expired', 'error');
              /* Resolved — swallow further chaining */
              return Promise.resolve(null);
            });
          }
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.blob().then(function (blob) {
            var cd = res.headers.get('content-disposition') || '';
            var match = cd.match(/filename="?([^"]+)"?/);
            var filename = match ? match[1] : 'download';
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            a.click();
            URL.revokeObjectURL(a.href);
            btn.textContent = 'Download';
            btn.disabled = false;
          });
        })
        .catch(function (e) {
          btn.textContent = 'Download';
          btn.disabled = false;
          showToast('Download failed: ' + (e && e.message || 'unknown'), 'error');
        });
    }

    /* ── Filters / clear ──────────────────────────────────────────────────── */

    function clearFilters() {
      currentFormat = '';
      currentStatus = '';
      currentSearch = '';
      currentPage = 1;
      filterFormat.value = '';
      filterStatus.value = '';
      filterSearch.value = '';
      loadHistory();
    }

    clearFilterBtn.addEventListener('click', clearFilters);

    filterFormat.addEventListener('change', function () {
      currentFormat = filterFormat.value;
      currentPage = 1;
      loadHistory();
    });
    filterStatus.addEventListener('change', function () {
      currentStatus = filterStatus.value;
      currentPage = 1;
      loadHistory();
    });
    filterSearch.addEventListener('input', function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        currentSearch = filterSearch.value.trim();
        currentPage = 1;
        loadHistory();
      }, 300);
    });

    /* ── Pending Files card ───────────────────────────────────────────────── */

    function updatePendingBulkBar() {
      var count = pendingSelectedIds.size;
      if (count === 0) {
        pendingBulkBar.classList.remove('mf-hist__bulk-bar--visible');
        return;
      }
      pendingBulkBar.classList.add('mf-hist__bulk-bar--visible');
      pendingBulkCount.textContent = count + ' selected';

      var totalBytes = 0;
      var typeCounts = Object.create(null);
      Object.keys(pendingSelectedFiles).forEach(function (id) {
        if (!pendingSelectedIds.has(id)) return;
        var f = pendingSelectedFiles[id];
        totalBytes += (f.file_size_bytes || 0);
        var ext = (f.file_ext || '?').toLowerCase();
        typeCounts[ext] = (typeCounts[ext] || 0) + 1;
      });
      var topTypes = Object.keys(typeCounts)
        .sort(function (a, b) { return typeCounts[b] - typeCounts[a]; })
        .slice(0, 3)
        .map(function (t) { return typeCounts[t] + '× ' + t; })
        .join(', ');

      var verb = pendingStatusFilter.value === 'failed' ? 'Retry' : 'Convert';
      pendingBulkConvert.textContent = verb + ' Selected (' + count + ')';

      var ctxParts = [];
      if (topTypes) ctxParts.push(topTypes);
      ctxParts.push(fmtBytes(totalBytes) + ' total');
      if (count > PENDING_SELECT_CAP) {
        ctxParts.push('⚠ above ' + PENDING_SELECT_CAP + '-file cap');
        pendingBulkConvert.disabled = true;
      } else {
        pendingBulkConvert.disabled = false;
      }
      pendingBulkCtx.textContent = ctxParts.join(' · ');
    }

    function clearPendingSelection() {
      pendingSelectedIds.clear();
      pendingSelectedFiles = Object.create(null);
      pendingTbody.querySelectorAll('.mf-pend-cb').forEach(function (cb) { cb.checked = false; });
      pendingSelectAll.checked = false;
      pendingSelectAll.indeterminate = false;
      updatePendingBulkBar();
    }

    function syncSelectAll() {
      var rows = pendingTbody.querySelectorAll('.mf-pend-cb');
      var checked = 0;
      rows.forEach(function (cb) { if (cb.checked) checked++; });
      if (checked === 0) {
        pendingSelectAll.checked = false;
        pendingSelectAll.indeterminate = false;
      } else if (checked === rows.length) {
        pendingSelectAll.checked = true;
        pendingSelectAll.indeterminate = false;
      } else {
        pendingSelectAll.checked = false;
        pendingSelectAll.indeterminate = true;
      }
    }

    function loadPending() {
      var statusFilter = pendingStatusFilter.value;
      var search = pendingSearch.value.trim();
      var qs = 'status=' + statusFilter + '&page=' + pendingPage + '&per_page=' + pendingPerPage;
      if (search) qs += '&search=' + encodeURIComponent(search);

      fetch(API_BULK_PENDING + '?' + qs, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          pendingCard.style.display = '';
          pendingBadge.textContent = (data.total || 0).toLocaleString();
          if (statusFilter === 'failed') {
            pendingBadge.className = 'mf-hist__pending-badge mf-hist__pending-badge--fail';
          } else {
            pendingBadge.className = 'mf-hist__pending-badge';
          }

          clear(pendingTbody);

          if (!data.files || !data.files.length) {
            var emptyRow = document.createElement('tr');
            var emptyTd = document.createElement('td');
            emptyTd.colSpan = 6;
            emptyTd.style.cssText = 'text-align:center;padding:1.5rem;color:var(--mf-color-text-muted,#888);font-size:0.84rem;';
            emptyTd.textContent = statusFilter === 'failed' ? 'No failed files.' : 'No pending files.';
            emptyRow.appendChild(emptyTd);
            pendingTbody.appendChild(emptyRow);
            clear(pendingPaging);
            return;
          }

          data.files.forEach(function (f) {
            var tr = document.createElement('tr');

            /* Checkbox */
            var tdCb = document.createElement('td');
            tdCb.style.paddingRight = '0';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'mf-pend-cb';
            cb.dataset.fileId = f.id;
            cb.style.cursor = 'pointer';
            if (pendingSelectedIds.has(f.id)) cb.checked = true;
            (function (file) {
              cb.addEventListener('change', function () {
                if (cb.checked) {
                  pendingSelectedIds.add(file.id);
                  pendingSelectedFiles[file.id] = file;
                } else {
                  pendingSelectedIds.delete(file.id);
                  delete pendingSelectedFiles[file.id];
                }
                syncSelectAll();
                updatePendingBulkBar();
              });
            })(f);
            tdCb.appendChild(cb);
            tr.appendChild(tdCb);

            /* File path */
            var tdFile = document.createElement('td');
            tdFile.style.wordBreak = 'break-all';
            var path = f.source_path || '';
            var parts = path.replace(/\\/g, '/').split('/');
            tdFile.textContent = parts.length > 3 ? '…/' + parts.slice(-3).join('/') : path;
            tdFile.title = path;
            tr.appendChild(tdFile);

            /* Type */
            var tdType = document.createElement('td');
            tdType.textContent = f.file_ext || '-';
            tdType.style.color = 'var(--mf-color-text-muted,#888)';
            tr.appendChild(tdType);

            /* Size */
            var tdSize = document.createElement('td');
            tdSize.textContent = fmtBytes(f.file_size_bytes);
            tr.appendChild(tdSize);

            /* Job started */
            var tdStarted = document.createElement('td');
            tdStarted.textContent = f.job_started_at ? fmtLocalTime(f.job_started_at) : '-';
            tdStarted.style.fontSize = '0.78rem';
            tr.appendChild(tdStarted);

            /* Status / Error */
            var tdSt = document.createElement('td');
            var statusSpan = document.createElement('span');
            statusSpan.style.fontSize = '0.8rem';
            var fileStatus = f.status || 'pending';
            if (fileStatus === 'failed' || fileStatus === 'adobe_failed') {
              statusSpan.style.color = 'var(--mf-color-error,#dc2626)';
              statusSpan.textContent = f.error_msg || fileStatus;
            } else if (fileStatus === 'for_review') {
              statusSpan.style.color = 'var(--mf-color-warn,#d97706)';
              statusSpan.textContent = 'Needs review';
            } else {
              statusSpan.style.color = 'var(--mf-color-success,#16a34a)';
              statusSpan.textContent = fileStatus;
            }
            tdSt.appendChild(statusSpan);
            tr.appendChild(tdSt);

            pendingTbody.appendChild(tr);
          });

          /* Pending pagination */
          clear(pendingPaging);
          if (data.total_pages > 1) {
            var prevBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
            prevBtn.textContent = '« Prev';
            prevBtn.disabled = data.page <= 1;
            prevBtn.addEventListener('click', function () { pendingPage--; loadPending(); });
            pendingPaging.appendChild(prevBtn);
            var pageInfo = el('span', 'mf-text--muted mf-text--sm');
            pageInfo.textContent = 'Page ' + data.page + ' of ' + data.total_pages +
              ' (' + (data.total || 0).toLocaleString() + ' files)';
            pendingPaging.appendChild(pageInfo);
            var nextBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
            nextBtn.textContent = 'Next »';
            nextBtn.disabled = data.page >= data.total_pages;
            nextBtn.addEventListener('click', function () { pendingPage++; loadPending(); });
            pendingPaging.appendChild(nextBtn);
          } else {
            var infoSpan = el('span', 'mf-text--muted mf-text--sm');
            infoSpan.textContent = (data.total || 0).toLocaleString() + ' files';
            pendingPaging.appendChild(infoSpan);
          }

          syncSelectAll();
          updatePendingBulkBar();
        })
        .catch(function () { /* silently fail — pending section is supplementary */ });
    }

    pendingStatusFilter.addEventListener('change', function () {
      pendingPage = 1;
      clearPendingSelection();
      loadPending();
    });

    var pendingSearchTimer;
    pendingSearch.addEventListener('input', function () {
      clearTimeout(pendingSearchTimer);
      pendingSearchTimer = setTimeout(function () { pendingPage = 1; loadPending(); }, 300);
    });

    pendingSelectAll.addEventListener('change', function () {
      var checked = pendingSelectAll.checked;
      pendingTbody.querySelectorAll('.mf-pend-cb').forEach(function (cb) {
        cb.checked = checked;
        var fid = cb.dataset.fileId;
        if (checked) {
          pendingSelectedIds.add(fid);
          if (!pendingSelectedFiles[fid]) pendingSelectedFiles[fid] = { id: fid };
        } else {
          pendingSelectedIds.delete(fid);
          delete pendingSelectedFiles[fid];
        }
      });
      updatePendingBulkBar();
    });

    pendingBulkClear.addEventListener('click', clearPendingSelection);

    pendingBulkConvert.addEventListener('click', function () {
      var ids = Array.from(pendingSelectedIds);
      if (!ids.length) return;
      if (ids.length > PENDING_SELECT_CAP) {
        showToast('Selection of ' + ids.length + ' exceeds the ' + PENDING_SELECT_CAP + '-file cap.', 'error');
        return;
      }
      var verb = pendingStatusFilter.value === 'failed' ? 'retry' : 'convert';
      if (!confirm('Schedule ' + ids.length + ' selected file' +
          (ids.length === 1 ? '' : 's') + ' for immediate ' + verb + '?')) return;

      pendingBulkConvert.disabled = true;
      var origText = pendingBulkConvert.textContent;
      pendingBulkConvert.textContent = 'Scheduling…';

      fetch(API_CONVERT_SELECTED, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: ids }),
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          var msg = 'Scheduled ' + data.queued + ' file' + (data.queued === 1 ? '' : 's');
          if (data.ineligible && data.ineligible.length) msg += ' (' + data.ineligible.length + ' skipped)';
          showToast(msg, 'success');
          clearPendingSelection();
          pendingBulkConvert.textContent = 'Scheduled ✓';
          setTimeout(function () {
            pendingBulkConvert.textContent = origText;
            pendingBulkConvert.disabled = false;
            loadPending();
          }, 2000);
        })
        .catch(function (e) {
          showToast('Scheduling failed: ' + (e.message || 'unknown'), 'error');
          pendingBulkConvert.textContent = origText;
          pendingBulkConvert.disabled = false;
        });
    });

    forceTranscribeBtn.addEventListener('click', function () {
      if (!confirm('Trigger an immediate scan + convert cycle? This will pick up every pending file ' +
          '(including audio/video for Whisper transcription) and may consume LLM/transcription quota.')) return;
      forceTranscribeBtn.disabled = true;
      var origText = forceTranscribeBtn.textContent;
      forceTranscribeBtn.textContent = 'Triggering…';
      fetch(API_PIPELINE_RUN, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); })
        .then(function () {
          showToast('Run Now triggered — pending files will be processed shortly', 'success');
          forceTranscribeBtn.textContent = 'Triggered ✓';
          setTimeout(function () {
            forceTranscribeBtn.textContent = origText;
            forceTranscribeBtn.disabled = false;
            loadPending();
          }, 2500);
        })
        .catch(function (e) {
          showToast('Failed to trigger: ' + (e.message || 'unknown'), 'error');
          forceTranscribeBtn.textContent = origText;
          forceTranscribeBtn.disabled = false;
        });
    });

    /* ── Initial load ─────────────────────────────────────────────────────── */
    loadHistory();
    loadPending();
    setInterval(loadPending, 30000);

    /* ── Return handle ────────────────────────────────────────────────────── */
    return {
      refresh: loadHistory,
      destroy: function () { /* timers are module-scoped; not cleaned up on destroy */ },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */

  global.MFHistory = { mount: mount };

})(window);
