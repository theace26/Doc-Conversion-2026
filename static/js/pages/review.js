/* MFReview — new-UX Review Queue page component.
 *
 * Feature parity with /review.html:
 *   - Review queue table: file, source path, confidence score, conversion
 *     status, accept/reject per-row actions
 *   - Bulk actions: accept-all-above-threshold, reject-all
 *   - Filter bar: score range (min/max), source prefix, date-from, date-to
 *   - URL param ?batch_id= scopes the queue to a single batch
 *   - Paginated table with loading / empty / error states
 *   - Done state when queue is empty
 *
 * Endpoints used:
 *   GET  /api/review/queue              -- list pending review items
 *   POST /api/review/{id}/accept        -- accept one item
 *   POST /api/review/{id}/reject        -- reject one item
 *   POST /api/review/accept-all         -- bulk accept above threshold
 *   POST /api/review/reject-all         -- bulk reject all
 *
 * Operator-gated. Safe DOM throughout — no innerHTML with user data.
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

  function timeAgo(dateStr) {
    if (!dateStr) return '';
    var now = Date.now();
    var d = new Date(dateStr).getTime();
    var elapsed = now - d;
    if (elapsed < 0) return 'just now';
    var mins = Math.floor(elapsed / 60000);
    if (mins < 60) return mins + 'm ago';
    var hrs = Math.floor(elapsed / 3600000);
    if (hrs < 24) return hrs + 'h ago';
    var ds = Math.floor(elapsed / 86400000);
    return ds + 'd ago';
  }

  function filename(path) {
    if (!path) return '';
    return path.split('/').pop() || path.split('\\').pop() || path;
  }

  /* ── API ────────────────────────────────────────────────────────────────── */

  function apiFetch(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}))
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (body) {
            var err = new Error(path + ' → ' + r.status + ' ' + r.statusText);
            err.status = r.status;
            try { err.detail = JSON.parse(body).detail; } catch (e) { err.detail = body; }
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
      body: JSON.stringify(body || {}),
    });
  }

  /* ── Confidence badge helpers ───────────────────────────────────────────── */

  var CONF_THRESHOLDS = { low: 50, mid: 80 };

  function confClass(score) {
    if (score == null) return 'unknown';
    if (score < CONF_THRESHOLDS.low) return 'low';
    if (score < CONF_THRESHOLDS.mid) return 'mid';
    return 'high';
  }

  function makeConfBadge(score) {
    var span = el('span', 'mf-rv__conf-badge mf-rv__conf-badge--' + confClass(score));
    span.textContent = score != null ? score.toFixed(1) + '%' : '—';
    return span;
  }

  /* ── Status badge ───────────────────────────────────────────────────────── */

  var STATUS_MAP = {
    completed:  'success',
    failed:     'error',
    pending:    'warn',
    processing: 'info',
    skipped:    'muted',
    excluded:   'muted',
  };

  function makeStatusBadge(status) {
    var mod = STATUS_MAP[status] || 'muted';
    var span = el('span', 'mf-rv__status-badge mf-rv__status-badge--' + mod);
    span.textContent = status || '—';
    return span;
  }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFReview.mount: root element is required');
    clear(root);
    opts = opts || {};

    var params  = new URLSearchParams(window.location.search);
    var batchId = params.get('batch_id') || '';

    /* ── State ──────────────────────────────────────────────────────────── */
    var currentPage = 1;
    var perPage     = 25;
    var filterMinScore  = '';
    var filterMaxScore  = '';
    var filterSource    = '';
    var filterDateFrom  = '';
    var filterDateTo    = '';
    var totalItems      = 0;

    /* ── Skeleton ───────────────────────────────────────────────────────── */

    var wrap = el('div', 'mf-rv');

    /* Header */
    var head = el('div', 'mf-rv__head');
    var headRow = el('div', 'mf-rv__head-row');
    var h1 = el('h1'); h1.textContent = 'Review Queue';
    var subhead = el('p');
    subhead.textContent = batchId
      ? 'Low-confidence conversions for batch: ' + batchId
      : 'Low-confidence conversions awaiting accept or reject decisions.';

    headRow.appendChild(h1);

    /* Progress label */
    var progressLabel = el('span', 'mf-rv__progress-label');
    progressLabel.textContent = '';
    headRow.appendChild(progressLabel);

    head.appendChild(headRow);
    head.appendChild(subhead);
    wrap.appendChild(head);

    /* Error banner */
    var errorBanner = el('div', 'mf-rv__error-banner');
    errorBanner.style.display = 'none';
    wrap.appendChild(errorBanner);

    /* Filters */
    var filtersRow = el('div', 'mf-rv__filters');

    var minFg = el('div', 'mf-rv__fg');
    var minLbl = el('label'); minLbl.textContent = 'Min Score'; minLbl.htmlFor = 'mf-rv-min';
    var minInp = el('input'); minInp.id = 'mf-rv-min'; minInp.type = 'number';
    minInp.min = '0'; minInp.max = '100'; minInp.step = '1'; minInp.placeholder = '0';
    minFg.appendChild(minLbl); minFg.appendChild(minInp);

    var maxFg = el('div', 'mf-rv__fg');
    var maxLbl = el('label'); maxLbl.textContent = 'Max Score'; maxLbl.htmlFor = 'mf-rv-max';
    var maxInp = el('input'); maxInp.id = 'mf-rv-max'; maxInp.type = 'number';
    maxInp.min = '0'; maxInp.max = '100'; maxInp.step = '1'; maxInp.placeholder = '100';
    maxFg.appendChild(maxLbl); maxFg.appendChild(maxInp);

    var srcFg = el('div', 'mf-rv__fg');
    var srcLbl = el('label'); srcLbl.textContent = 'Source Prefix'; srcLbl.htmlFor = 'mf-rv-src';
    var srcInp = el('input'); srcInp.id = 'mf-rv-src'; srcInp.type = 'text';
    srcInp.placeholder = '/mnt/source/…'; srcInp.size = 20;
    srcFg.appendChild(srcLbl); srcFg.appendChild(srcInp);

    var dateFg = el('div', 'mf-rv__fg');
    var dateLbl = el('label'); dateLbl.textContent = 'Date From'; dateLbl.htmlFor = 'mf-rv-date-from';
    var dateFromInp = el('input'); dateFromInp.id = 'mf-rv-date-from'; dateFromInp.type = 'date';
    dateFg.appendChild(dateLbl); dateFg.appendChild(dateFromInp);

    var dateFg2 = el('div', 'mf-rv__fg');
    var dateLbl2 = el('label'); dateLbl2.textContent = 'Date To'; dateLbl2.htmlFor = 'mf-rv-date-to';
    var dateToInp = el('input'); dateToInp.id = 'mf-rv-date-to'; dateToInp.type = 'date';
    dateFg2.appendChild(dateLbl2); dateFg2.appendChild(dateToInp);

    filtersRow.appendChild(minFg);
    filtersRow.appendChild(maxFg);
    filtersRow.appendChild(srcFg);
    filtersRow.appendChild(dateFg);
    filtersRow.appendChild(dateFg2);
    wrap.appendChild(filtersRow);

    /* Bulk actions bar */
    var bulkBar = el('div', 'mf-rv__bulk');
    var bulkLabel = el('span', 'mf-rv__bulk-label');

    var threshFg = el('div', 'mf-rv__fg mf-rv__fg--inline');
    var threshLbl = el('label'); threshLbl.textContent = 'Accept above'; threshLbl.htmlFor = 'mf-rv-thresh';
    var threshInp = el('input'); threshInp.id = 'mf-rv-thresh'; threshInp.type = 'number';
    threshInp.min = '0'; threshInp.max = '100'; threshInp.step = '1'; threshInp.value = '80';
    threshInp.style.width = '4.5rem';
    threshFg.appendChild(threshLbl); threshFg.appendChild(threshInp);

    var btnAcceptAbove = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    btnAcceptAbove.textContent = 'Accept All Above Threshold';

    var btnRejectAll = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
    btnRejectAll.textContent = 'Reject All';

    bulkBar.appendChild(bulkLabel);
    bulkBar.appendChild(threshFg);
    bulkBar.appendChild(btnAcceptAbove);
    bulkBar.appendChild(btnRejectAll);
    wrap.appendChild(bulkBar);

    /* Table */
    var tableWrap = el('div', 'mf-rv__table-wrap');
    var table = el('table', 'mf-rv__table');
    var thead = el('thead');
    var tbody = el('tbody');

    var hTr = el('tr');
    ['File', 'Source Path', 'Confidence', 'Status', 'Reviewed', 'Actions'].forEach(function (h) {
      var th = el('th'); th.textContent = h; hTr.appendChild(th);
    });
    thead.appendChild(hTr);
    table.appendChild(thead);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);

    /* Empty state */
    var emptyState = el('div', 'mf-rv__empty');
    emptyState.style.display = 'none';
    var emptyIcon = el('div', 'mf-rv__empty-icon'); emptyIcon.textContent = '✓';
    var emptyTitle = el('h3'); emptyTitle.textContent = 'Review queue empty';
    var emptyDesc = el('p'); emptyDesc.textContent = 'No items match the current filters.';
    emptyState.appendChild(emptyIcon);
    emptyState.appendChild(emptyTitle);
    emptyState.appendChild(emptyDesc);
    wrap.appendChild(emptyState);

    /* Done state (all items resolved, no filters) */
    var doneState = el('div', 'mf-rv__done');
    doneState.style.display = 'none';
    var doneIcon = el('div', 'mf-rv__done-icon'); doneIcon.textContent = '✓';
    var doneTitle = el('h2'); doneTitle.textContent = 'Review complete';
    var doneDesc = el('p'); doneDesc.textContent = 'All conversions in this queue have been reviewed.';
    var doneBack = el('a', 'mf-btn mf-btn--primary');
    doneBack.textContent = '← Back to history';
    doneBack.href = '/history';
    doneState.appendChild(doneIcon);
    doneState.appendChild(doneTitle);
    doneState.appendChild(doneDesc);
    doneState.appendChild(doneBack);
    wrap.appendChild(doneState);

    /* Pagination */
    var pagination = el('div', 'mf-rv__pagination');
    wrap.appendChild(pagination);

    root.appendChild(wrap);

    /* ── Load ───────────────────────────────────────────────────────────── */

    function buildUrl() {
      var url = '/api/review/queue?page=' + currentPage + '&per_page=' + perPage;
      if (batchId)       url += '&batch_id='    + encodeURIComponent(batchId);
      if (filterMinScore) url += '&min_score='  + encodeURIComponent(filterMinScore);
      if (filterMaxScore) url += '&max_score='  + encodeURIComponent(filterMaxScore);
      if (filterSource)   url += '&source_prefix=' + encodeURIComponent(filterSource);
      if (filterDateFrom) url += '&date_from='  + encodeURIComponent(filterDateFrom);
      if (filterDateTo)   url += '&date_to='    + encodeURIComponent(filterDateTo);
      return url;
    }

    function showLoadingRow() {
      clear(tbody);
      var tr = el('tr');
      var td = el('td');
      td.colSpan = 6;
      td.className = 'mf-rv__loading-cell';
      td.textContent = 'Loading…';
      tr.appendChild(td);
      tbody.appendChild(tr);
    }

    function showErrorRow(msg) {
      clear(tbody);
      var tr = el('tr');
      var td = el('td');
      td.colSpan = 6;
      td.className = 'mf-rv__error-cell';
      td.textContent = msg;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }

    function showError(msg) {
      errorBanner.textContent = msg;
      errorBanner.style.display = '';
    }

    function clearError() {
      errorBanner.textContent = '';
      errorBanner.style.display = 'none';
    }

    function loadData() {
      clearError();
      showLoadingRow();
      tableWrap.style.display = '';
      emptyState.style.display = 'none';
      doneState.style.display = 'none';
      clear(pagination);
      bulkBar.style.display = 'none';

      apiGet(buildUrl())
        .then(renderData)
        .catch(function (e) {
          showErrorRow('Failed to load review queue: ' + (e.detail || e.message));
        });
    }

    function renderData(data) {
      var items = data.items || data || [];
      totalItems = data.total || items.length;

      clear(tbody);

      if (!items.length) {
        var hasFilters = filterMinScore || filterMaxScore || filterSource || filterDateFrom || filterDateTo;
        tableWrap.style.display = 'none';
        if (hasFilters) {
          emptyState.style.display = '';
          emptyTitle.textContent = 'No items match filters';
          emptyDesc.textContent = 'Try adjusting the filter range or clearing filters.';
        } else {
          doneState.style.display = '';
        }
        progressLabel.textContent = '';
        return;
      }

      tableWrap.style.display = '';
      emptyState.style.display = 'none';
      doneState.style.display = 'none';

      progressLabel.textContent = totalItems + ' item' + (totalItems === 1 ? '' : 's');
      bulkLabel.textContent = items.length + ' on this page';
      bulkBar.style.display = '';

      items.forEach(function (item) {
        tbody.appendChild(renderRow(item));
      });

      renderPagination(totalItems, data.page || currentPage, data.per_page || perPage);
    }

    function renderRow(item) {
      var tr = el('tr');
      tr.setAttribute('data-id', item.id);

      /* File */
      var tdFile = el('td', 'mf-rv__td-file');
      var nameSpan = el('span', 'mf-rv__file-name');
      nameSpan.textContent = filename(item.source_path);
      nameSpan.title = item.source_path || '';
      tdFile.appendChild(nameSpan);
      tr.appendChild(tdFile);

      /* Source path */
      var tdPath = el('td', 'mf-rv__td-path');
      tdPath.textContent = item.source_path || '';
      tdPath.title = item.source_path || '';
      tr.appendChild(tdPath);

      /* Confidence */
      var tdConf = el('td', 'mf-rv__td-conf');
      tdConf.appendChild(makeConfBadge(item.confidence_score));
      tr.appendChild(tdConf);

      /* Status */
      var tdStatus = el('td', 'mf-rv__td-status');
      tdStatus.appendChild(makeStatusBadge(item.conversion_status));
      tr.appendChild(tdStatus);

      /* Reviewed at */
      var tdDate = el('td', 'mf-rv__td-date');
      tdDate.textContent = timeAgo(item.created_at);
      tdDate.title = item.created_at || '';
      tr.appendChild(tdDate);

      /* Actions */
      var tdActions = el('td', 'mf-rv__td-actions');

      var btnPreview = el('a', 'mf-btn mf-btn--ghost mf-btn--sm');
      btnPreview.textContent = 'Inspect';
      btnPreview.href = '/preview?id=' + encodeURIComponent(item.source_file_id || item.id);
      btnPreview.title = 'Open file in preview';

      var btnAccept = el('button', 'mf-btn mf-btn--success mf-btn--sm');
      btnAccept.textContent = 'Accept';
      btnAccept.addEventListener('click', (function (id, rowEl) {
        return function () { acceptItem(id, rowEl); };
      })(item.id, tr));

      var btnReject = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
      btnReject.textContent = 'Reject';
      btnReject.addEventListener('click', (function (id, rowEl) {
        return function () { rejectItem(id, rowEl); };
      })(item.id, tr));

      tdActions.appendChild(btnPreview);
      tdActions.appendChild(btnAccept);
      tdActions.appendChild(btnReject);
      tr.appendChild(tdActions);

      return tr;
    }

    /* ── Pagination ─────────────────────────────────────────────────────── */

    function renderPagination(total, page, pp) {
      clear(pagination);
      if (!total || !pp) return;
      var totalPages = Math.ceil(total / pp);
      if (totalPages <= 1) return;

      var prevBtn = el('button', 'mf-rv__page-btn');
      prevBtn.textContent = 'Prev';
      prevBtn.disabled = page <= 1;
      prevBtn.addEventListener('click', function () { currentPage = page - 1; loadData(); });
      pagination.appendChild(prevBtn);

      for (var i = 1; i <= totalPages; i++) {
        if (totalPages > 7 && i > 3 && i < totalPages - 1 && Math.abs(i - page) > 1) {
          if (i === 4 || i === totalPages - 2) {
            var dot = el('button', 'mf-rv__page-btn');
            dot.textContent = '…';
            dot.disabled = true;
            pagination.appendChild(dot);
          }
          continue;
        }
        var btn = el('button', 'mf-rv__page-btn' + (i === page ? ' mf-rv__page-btn--active' : ''));
        btn.textContent = i;
        btn.addEventListener('click', (function (p) {
          return function () { currentPage = p; loadData(); };
        })(i));
        pagination.appendChild(btn);
      }

      var nextBtn = el('button', 'mf-rv__page-btn');
      nextBtn.textContent = 'Next';
      nextBtn.disabled = page >= totalPages;
      nextBtn.addEventListener('click', function () { currentPage = page + 1; loadData(); });
      pagination.appendChild(nextBtn);
    }

    /* ── Row actions ────────────────────────────────────────────────────── */

    function setRowDone(rowEl, label) {
      clear(rowEl);
      var td = el('td');
      td.colSpan = 6;
      td.className = 'mf-rv__row-done';
      td.textContent = label;
      rowEl.appendChild(td);
      rowEl.classList.add('mf-rv__row--resolved');
    }

    function acceptItem(id, rowEl) {
      var btns = rowEl.querySelectorAll('button');
      btns.forEach(function (b) { b.disabled = true; });
      apiPost('/api/review/' + encodeURIComponent(id) + '/accept')
        .then(function () {
          setRowDone(rowEl, '✓ Accepted');
          showToast('Item accepted', 'success');
        })
        .catch(function (e) {
          btns.forEach(function (b) { b.disabled = false; });
          showToast('Accept failed: ' + (e.detail || e.message), 'error');
        });
    }

    function rejectItem(id, rowEl) {
      var btns = rowEl.querySelectorAll('button');
      btns.forEach(function (b) { b.disabled = true; });
      apiPost('/api/review/' + encodeURIComponent(id) + '/reject')
        .then(function () {
          setRowDone(rowEl, '✗ Rejected');
          showToast('Item rejected', 'info');
        })
        .catch(function (e) {
          btns.forEach(function (b) { b.disabled = false; });
          showToast('Reject failed: ' + (e.detail || e.message), 'error');
        });
    }

    /* ── Bulk actions ───────────────────────────────────────────────────── */

    btnAcceptAbove.addEventListener('click', function () {
      var threshold = parseFloat(threshInp.value);
      if (isNaN(threshold) || threshold < 0 || threshold > 100) {
        showToast('Enter a valid threshold (0–100)', 'error');
        return;
      }
      if (!confirm('Accept all items with confidence ≥ ' + threshold + '%?')) return;
      btnAcceptAbove.disabled = true;
      var body = { threshold: threshold };
      if (batchId) body.batch_id = batchId;
      apiPost('/api/review/accept-all', body)
        .then(function (res) {
          showToast('Accepted ' + ((res && res.accepted) || 0) + ' items', 'success');
          currentPage = 1;
          loadData();
        })
        .catch(function (e) {
          showToast('Bulk accept failed: ' + (e.detail || e.message), 'error');
        })
        .then(function () { btnAcceptAbove.disabled = false; });
    });

    btnRejectAll.addEventListener('click', function () {
      if (!confirm('Reject ALL items currently in the queue? This cannot be undone.')) return;
      btnRejectAll.disabled = true;
      var body = {};
      if (batchId) body.batch_id = batchId;
      apiPost('/api/review/reject-all', body)
        .then(function (res) {
          showToast('Rejected ' + ((res && res.rejected) || 0) + ' items', 'info');
          currentPage = 1;
          loadData();
        })
        .catch(function (e) {
          showToast('Bulk reject failed: ' + (e.detail || e.message), 'error');
        })
        .then(function () { btnRejectAll.disabled = false; });
    });

    /* ── Filter wiring ──────────────────────────────────────────────────── */

    var filterTimer;
    function debounceFilter() {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(function () {
        filterMinScore = minInp.value.trim();
        filterMaxScore = maxInp.value.trim();
        filterSource   = srcInp.value.trim();
        filterDateFrom = dateFromInp.value;
        filterDateTo   = dateToInp.value;
        currentPage    = 1;
        loadData();
      }, 450);
    }

    [minInp, maxInp, srcInp, dateFromInp, dateToInp].forEach(function (inp) {
      inp.addEventListener('input', debounceFilter);
      inp.addEventListener('change', debounceFilter);
    });

    /* ── Initial load ───────────────────────────────────────────────────── */
    loadData();

    /* ── Return control handle ──────────────────────────────────────────── */
    return {
      refresh: function () { loadData(); },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */
  global.MFReview = { mount: mount };

})(window);
