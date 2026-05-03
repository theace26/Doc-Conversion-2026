/* MFBulk — new-UX Bulk Jobs overview page component.
 *
 * Feature parity with /bulk.html:
 *   - Stats strip: running / paused / completed / failed counts
 *   - Filter/sort bar: status, date range, job name/path search
 *   - Jobs table: name | status pill | progress bar | files | started | duration
 *   - Pagination
 *   - Empty state
 *   - Row click navigates to /bulk/{id} (new-UX detail page)
 *
 * Endpoints used:
 *   GET /api/bulk/jobs  — list jobs (most recent 20)
 *
 * Operator-gated. Safe DOM throughout — no innerHTML with user data.
 *
 * Usage:
 *   MFBulk.mount(root, { role });
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

  function fmtNum(n) { return (n == null || n === '') ? '—' : Number(n).toLocaleString(); }

  function fmtDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
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

  function statusClass(status) {
    var map = {
      running:   'mf-bk__pill--running',
      scanning:  'mf-bk__pill--scanning',
      completed: 'mf-bk__pill--completed',
      failed:    'mf-bk__pill--failed',
      cancelled: 'mf-bk__pill--cancelled',
      paused:    'mf-bk__pill--paused',
    };
    return 'mf-bk__pill ' + (map[status] || 'mf-bk__pill--unknown');
  }

  function jobLabel(job) {
    /* Prefer a short job name; fall back to last path segment */
    if (job.job_name) return job.job_name;
    var p = job.source_path || '';
    var parts = p.replace(/\\/g, '/').split('/');
    return parts[parts.length - 1] || p || job.job_id || '—';
  }

  function shortPath(p) {
    if (!p) return '—';
    var parts = p.replace(/\\/g, '/').split('/');
    if (parts.length <= 3) return p;
    return '…/' + parts.slice(-2).join('/');
  }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFBulk.mount: root element is required');
    clear(root);
    opts = opts || {};

    /* ── State ─────────────────────────────────────────────────────────── */
    var allJobs      = [];
    var filteredJobs = [];
    var currentPage  = 1;
    var perPage      = 20;
    var filterStatus = 'all';
    var filterSearch = '';
    var sortKey      = 'started';   /* started | name | status */
    var sortDir      = 'desc';
    var searchTimer  = null;

    /* ── Skeleton ──────────────────────────────────────────────────────── */

    var wrap = el('div', 'mf-bk');

    /* Header */
    var head = el('div', 'mf-bk__head');
    var headLeft = el('div', 'mf-bk__head-left');
    var h1 = el('h1', 'mf-bk__title'); h1.textContent = 'Bulk Jobs';
    var sub = el('p', 'mf-bk__subtitle'); sub.textContent = 'Manage and monitor document conversion batch jobs.';
    headLeft.appendChild(h1);
    headLeft.appendChild(sub);

    var headRight = el('div', 'mf-bk__head-right');
    var newJobBtn = el('a', 'mf-bk__btn mf-bk__btn--primary');
    newJobBtn.href = '/bulk.html';
    newJobBtn.textContent = '+ New Job';
    headRight.appendChild(newJobBtn);

    head.appendChild(headLeft);
    head.appendChild(headRight);
    wrap.appendChild(head);

    /* Stats strip */
    var statsStrip = el('div', 'mf-bk__stats');
    var statEls = {};
    [
      { key: 'running',   label: 'Running',   cls: 'mf-bk__stat--running' },
      { key: 'paused',    label: 'Paused',    cls: 'mf-bk__stat--paused' },
      { key: 'completed', label: 'Completed', cls: 'mf-bk__stat--completed' },
      { key: 'failed',    label: 'Failed',    cls: 'mf-bk__stat--failed' },
    ].forEach(function (item) {
      var card = el('div', 'mf-bk__stat ' + item.cls);
      var valEl = el('div', 'mf-bk__stat-val'); valEl.textContent = '—';
      var lblEl = el('div', 'mf-bk__stat-lbl'); lblEl.textContent = item.label;
      card.appendChild(valEl);
      card.appendChild(lblEl);
      statsStrip.appendChild(card);
      statEls[item.key] = valEl;
    });
    wrap.appendChild(statsStrip);

    /* Filter/sort bar */
    var filterBar = el('div', 'mf-bk__filters');

    /* Status filter */
    var statusFg = el('div', 'mf-bk__fg');
    var statusLbl = el('label', 'mf-bk__fg-label');
    statusLbl.textContent = 'Status';
    statusLbl.htmlFor = 'mf-bk-status';
    var statusSel = el('select', 'mf-bk__select');
    statusSel.id = 'mf-bk-status';
    [
      { value: 'all',       label: 'All statuses' },
      { value: 'running',   label: 'Running' },
      { value: 'scanning',  label: 'Scanning' },
      { value: 'paused',    label: 'Paused' },
      { value: 'completed', label: 'Completed' },
      { value: 'failed',    label: 'Failed' },
      { value: 'cancelled', label: 'Cancelled' },
    ].forEach(function (o) {
      var opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      statusSel.appendChild(opt);
    });
    statusFg.appendChild(statusLbl);
    statusFg.appendChild(statusSel);

    /* Sort */
    var sortFg = el('div', 'mf-bk__fg');
    var sortLbl = el('label', 'mf-bk__fg-label');
    sortLbl.textContent = 'Sort by';
    sortLbl.htmlFor = 'mf-bk-sort';
    var sortSel = el('select', 'mf-bk__select');
    sortSel.id = 'mf-bk-sort';
    [
      { value: 'started_desc', label: 'Started (newest)' },
      { value: 'started_asc',  label: 'Started (oldest)' },
      { value: 'name_asc',     label: 'Name A–Z' },
      { value: 'name_desc',    label: 'Name Z–A' },
      { value: 'status_asc',   label: 'Status' },
    ].forEach(function (o) {
      var opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      sortSel.appendChild(opt);
    });
    sortFg.appendChild(sortLbl);
    sortFg.appendChild(sortSel);

    /* Search */
    var searchFg = el('div', 'mf-bk__fg mf-bk__fg--grow');
    var searchLbl = el('label', 'mf-bk__fg-label');
    searchLbl.textContent = 'Search';
    searchLbl.htmlFor = 'mf-bk-search';
    var searchInput = el('input', 'mf-bk__search');
    searchInput.type = 'search';
    searchInput.id = 'mf-bk-search';
    searchInput.placeholder = 'Filter by name or path…';
    searchFg.appendChild(searchLbl);
    searchFg.appendChild(searchInput);

    filterBar.appendChild(statusFg);
    filterBar.appendChild(sortFg);
    filterBar.appendChild(searchFg);
    wrap.appendChild(filterBar);

    /* Table wrapper */
    var tableWrap = el('div', 'mf-bk__table-wrap');
    var table = el('table', 'mf-bk__table');

    /* Table head */
    var thead = el('thead');
    var headRow = el('tr');
    ['Job', 'Status', 'Progress', 'Files', 'Started', 'Duration'].forEach(function (label, i) {
      var th = el('th');
      th.textContent = label;
      if (i === 0) th.style.minWidth = '200px';
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    /* Table body */
    var tbody = el('tbody', 'mf-bk__tbody');
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);

    /* Pagination */
    var paginationEl = el('div', 'mf-bk__pagination');
    wrap.appendChild(paginationEl);

    /* Empty state */
    var emptyEl = el('div', 'mf-bk__empty');
    emptyEl.style.display = 'none';
    var emptyH = el('h3'); emptyH.textContent = 'No bulk jobs found';
    var emptyP = el('p'); emptyP.textContent = 'Start a new job from the bulk jobs page.';
    emptyEl.appendChild(emptyH);
    emptyEl.appendChild(emptyP);
    wrap.appendChild(emptyEl);

    root.appendChild(wrap);

    /* ── Render ─────────────────────────────────────────────────────────── */

    function updateStats() {
      var counts = { running: 0, paused: 0, completed: 0, failed: 0 };
      allJobs.forEach(function (j) {
        var s = j.status || '';
        if (s === 'running' || s === 'scanning') counts.running++;
        else if (s === 'paused') counts.paused++;
        else if (s === 'completed') counts.completed++;
        else if (s === 'failed' || s === 'cancelled') counts.failed++;
      });
      Object.keys(counts).forEach(function (k) {
        if (statEls[k]) statEls[k].textContent = counts[k];
      });
    }

    function applyFiltersAndSort() {
      var q = filterSearch.toLowerCase();
      filteredJobs = allJobs.filter(function (j) {
        if (filterStatus !== 'all') {
          var s = j.status || '';
          if (filterStatus === 'running' && s !== 'running' && s !== 'scanning') return false;
          if (filterStatus !== 'running' && filterStatus !== 'all' && s !== filterStatus) return false;
        }
        if (q) {
          var label = jobLabel(j).toLowerCase();
          var path  = (j.source_path || '').toLowerCase();
          if (label.indexOf(q) === -1 && path.indexOf(q) === -1) return false;
        }
        return true;
      });

      filteredJobs.sort(function (a, b) {
        if (sortKey === 'started') {
          var ta = a.started_at ? new Date(a.started_at).getTime() : 0;
          var tb = b.started_at ? new Date(b.started_at).getTime() : 0;
          return sortDir === 'desc' ? tb - ta : ta - tb;
        }
        if (sortKey === 'name') {
          var na = jobLabel(a).toLowerCase();
          var nb = jobLabel(b).toLowerCase();
          return sortDir === 'desc'
            ? (na < nb ? 1 : na > nb ? -1 : 0)
            : (na < nb ? -1 : na > nb ? 1 : 0);
        }
        if (sortKey === 'status') {
          var sa = a.status || '';
          var sb = b.status || '';
          return sa < sb ? -1 : sa > sb ? 1 : 0;
        }
        return 0;
      });

      currentPage = 1;
      renderTable();
      renderPagination();
    }

    function renderTable() {
      clear(tbody);
      var start = (currentPage - 1) * perPage;
      var end   = Math.min(start + perPage, filteredJobs.length);
      var page  = filteredJobs.slice(start, end);

      tableWrap.style.display = page.length ? '' : 'none';
      emptyEl.style.display   = filteredJobs.length === 0 ? '' : 'none';

      page.forEach(function (job) {
        var tr = el('tr', 'mf-bk__row');
        tr.style.cursor = 'pointer';
        tr.setAttribute('tabindex', '0');
        tr.setAttribute('role', 'link');
        tr.setAttribute('aria-label', 'Open job ' + jobLabel(job));

        var detailUrl = '/bulk/' + encodeURIComponent(job.job_id);
        tr.addEventListener('click', function () { window.location.href = detailUrl; });
        tr.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            window.location.href = detailUrl;
          }
        });

        /* Job name cell */
        var tdName = el('td', 'mf-bk__td-name');
        var nameSpan = el('span', 'mf-bk__job-name');
        nameSpan.textContent = jobLabel(job);
        var pathSpan = el('span', 'mf-bk__job-path');
        pathSpan.textContent = shortPath(job.source_path);
        tdName.appendChild(nameSpan);
        tdName.appendChild(pathSpan);

        /* Status cell */
        var tdStatus = el('td');
        var pill = el('span', statusClass(job.status));
        pill.textContent = (job.status || 'unknown').replace('_', ' ');
        tdStatus.appendChild(pill);

        /* Progress cell */
        var tdProgress = el('td', 'mf-bk__td-progress');
        var total     = job.total_files || 0;
        var completed = (job.converted || 0) + (job.failed || 0) + (job.skipped || 0);
        var pct       = total > 0 ? Math.round(completed / total * 100) : 0;
        var isActive  = (job.status === 'running' || job.status === 'scanning');

        var barWrap = el('div', 'mf-bk__prog-bar');
        var barFill = el('div', 'mf-bk__prog-fill' + (isActive && total === 0 ? ' mf-bk__prog-fill--indet' : ''));
        if (!isActive || total > 0) barFill.style.width = pct + '%';
        barWrap.appendChild(barFill);

        var pctLabel = el('span', 'mf-bk__prog-pct');
        pctLabel.textContent = total > 0 ? pct + '%' : (isActive ? 'scanning…' : '—');
        tdProgress.appendChild(barWrap);
        tdProgress.appendChild(pctLabel);

        /* Files cell */
        var tdFiles = el('td', 'mf-bk__td-files');
        tdFiles.textContent = total > 0 ? fmtNum(total) : '—';

        /* Started cell */
        var tdStarted = el('td', 'mf-bk__td-date');
        tdStarted.textContent = fmtDate(job.started_at);

        /* Duration cell */
        var tdDur = el('td', 'mf-bk__td-dur');
        tdDur.textContent = fmtDuration(job.started_at, job.completed_at || (isActive ? null : job.started_at));

        tr.appendChild(tdName);
        tr.appendChild(tdStatus);
        tr.appendChild(tdProgress);
        tr.appendChild(tdFiles);
        tr.appendChild(tdStarted);
        tr.appendChild(tdDur);
        tbody.appendChild(tr);
      });
    }

    function renderPagination() {
      clear(paginationEl);
      var totalPages = Math.ceil(filteredJobs.length / perPage);
      if (totalPages <= 1) return;

      var prevBtn = el('button', 'mf-bk__page-btn');
      prevBtn.textContent = '←';
      prevBtn.disabled = currentPage <= 1;
      prevBtn.addEventListener('click', function () { currentPage--; renderTable(); renderPagination(); });
      paginationEl.appendChild(prevBtn);

      var infoSpan = el('span', 'mf-bk__page-info');
      infoSpan.textContent = 'Page ' + currentPage + ' of ' + totalPages + ' (' + filteredJobs.length + ' jobs)';
      paginationEl.appendChild(infoSpan);

      var nextBtn = el('button', 'mf-bk__page-btn');
      nextBtn.textContent = '→';
      nextBtn.disabled = currentPage >= totalPages;
      nextBtn.addEventListener('click', function () { currentPage++; renderTable(); renderPagination(); });
      paginationEl.appendChild(nextBtn);
    }

    /* ── Load ───────────────────────────────────────────────────────────── */

    function loadJobs() {
      clear(tbody);
      var loadingRow = el('tr');
      var loadingTd = el('td');
      loadingTd.colSpan = 6;
      loadingTd.className = 'mf-bk__loading';
      loadingTd.textContent = 'Loading jobs…';
      loadingRow.appendChild(loadingTd);
      tbody.appendChild(loadingRow);
      tableWrap.style.display = '';
      emptyEl.style.display = 'none';

      apiGet('/api/bulk/jobs').then(function (data) {
        allJobs = (data && data.jobs) ? data.jobs : [];
        updateStats();
        applyFiltersAndSort();
      }).catch(function (e) {
        clear(tbody);
        var errRow = el('tr');
        var errTd = el('td');
        errTd.colSpan = 6;
        errTd.className = 'mf-bk__error';
        errTd.textContent = 'Failed to load jobs: ' + e.message;
        errRow.appendChild(errTd);
        tbody.appendChild(errRow);
        showToast('Failed to load jobs: ' + e.message, 'error');
      });
    }

    /* ── Event wiring ───────────────────────────────────────────────────── */

    statusSel.addEventListener('change', function () {
      filterStatus = statusSel.value;
      applyFiltersAndSort();
    });

    sortSel.addEventListener('change', function () {
      var parts = sortSel.value.split('_');
      sortDir = parts.pop();
      sortKey = parts.join('_');
      applyFiltersAndSort();
    });

    searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      var q = searchInput.value.trim();
      searchTimer = setTimeout(function () {
        filterSearch = q;
        applyFiltersAndSort();
      }, 250);
    });

    /* ── Init ───────────────────────────────────────────────────────────── */

    loadJobs();
  }

  global.MFBulk = { mount: mount };
})(window);
