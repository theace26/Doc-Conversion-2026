/* MFFlagged — new-UX Flagged Files page component.
 *
 * Feature parity with /flagged.html:
 *   - Stats summary (active / extended / dismissed / expired / removed)
 *   - Tabbed view: Active / History / Blocklist
 *   - Filter bar: reason, flagged-by, path prefix, sort
 *   - Paginated table with per-row actions
 *   - Bulk dismiss (clear all active flags) — operator-gated
 *   - Empty state when no flagged files
 *   - Auto-refresh every 30 s while tab is visible
 *
 * Endpoints used:
 *   GET /api/flags/stats                     -- summary counts
 *   GET /api/flags                           -- list flags (active / history)
 *   PUT /api/flags/:id/dismiss               -- dismiss a flag
 *   PUT /api/flags/:id/extend                -- extend a flag expiry
 *   PUT /api/flags/:id/remove                -- mark file for removal
 *   GET /api/flags/blocklist                 -- list blocklisted hashes
 *   DELETE /api/flags/blocklist/:id          -- remove from blocklist
 *
 * Operator-gated. Safe DOM throughout.
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
      '.mf-fl { max-width:1200px; margin:0 auto; padding:1.5rem 1rem 3rem; }',
      '.mf-fl__head { margin-bottom:1rem; }',
      '.mf-fl__head h1 { margin:0 0 0.2rem; font-size:1.65rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-fl__head p { margin:0; font-size:0.88rem; color:var(--mf-color-text-muted,#8892a4); }',
      /* Stats row */
      '.mf-fl__stats { display:flex; flex-wrap:wrap; gap:0.65rem; margin-bottom:1.25rem; }',
      '.mf-fl__stat { flex:1; min-width:100px; padding:0.75rem 0.9rem; background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); text-align:center; }',
      '.mf-fl__stat--active { border-color:rgba(248,113,113,.6); }',
      '.mf-fl__stat--extended { border-color:rgba(251,191,36,.6); }',
      '.mf-fl__stat-val { font-size:1.4rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-fl__stat-lbl { font-size:0.72rem; color:var(--mf-color-text-muted,#8892a4); text-transform:uppercase; letter-spacing:0.04em; margin-top:0.15rem; }',
      /* Tabs */
      '.mf-fl__tabs { display:flex; border-bottom:2px solid var(--mf-border,#2a2a4a); margin-bottom:1rem; gap:0; }',
      '.mf-fl__tab { padding:0.55rem 1.1rem; font-size:0.88rem; font-weight:500; color:var(--mf-color-text-muted,#8892a4); border:none; background:none; cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-2px; transition:color .12s,border-color .12s; }',
      '.mf-fl__tab:hover { color:var(--mf-color-text,#e2e8f0); }',
      '.mf-fl__tab--active { color:var(--mf-color-accent,#6366f1); border-bottom-color:var(--mf-color-accent,#6366f1); }',
      /* Filters */
      '.mf-fl__filters { display:flex; flex-wrap:wrap; gap:0.65rem; align-items:flex-end; margin-bottom:1rem; }',
      '.mf-fl__fg { display:flex; flex-direction:column; gap:0.25rem; }',
      '.mf-fl__fg label { font-size:0.75rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-fl__fg select, .mf-fl__fg input { padding:0.38rem 0.55rem; font-size:0.84rem; border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); background:var(--mf-surface,#16213e); color:var(--mf-color-text,#e2e8f0); font:inherit; }',
      /* Table */
      '.mf-fl__table-wrap { border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); overflow:auto; }',
      '.mf-fl__table { width:100%; border-collapse:collapse; font-size:0.86rem; }',
      '.mf-fl__table th { padding:0.55rem 0.75rem; text-align:left; font-size:0.73rem; color:var(--mf-color-text-muted,#8892a4); text-transform:uppercase; letter-spacing:0.04em; border-bottom:2px solid var(--mf-border,#2a2a4a); white-space:nowrap; }',
      '.mf-fl__table td { padding:0.55rem 0.75rem; border-bottom:1px solid var(--mf-border,#2a2a4a); vertical-align:middle; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-fl__table tr:last-child td { border-bottom:none; }',
      '.mf-fl__table tbody tr:hover { background:rgba(128,128,128,.04); }',
      '.mf-fl__table td.file { font-weight:500; }',
      '.mf-fl__table td.path { max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:ui-monospace,monospace; font-size:0.79rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-fl__table td.actions { white-space:nowrap; }',
      '.mf-fl__table td.hash { font-family:ui-monospace,monospace; font-size:0.77rem; color:var(--mf-color-text-muted,#8892a4); max-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }',
      /* Reason badges */
      '.mf-fl__badge { display:inline-block; padding:.12em .5em; border-radius:3px; font-size:.73rem; font-weight:600; text-transform:uppercase; letter-spacing:.03em; }',
      '.mf-fl__badge--pii { background:rgba(220,38,38,.12); color:#dc2626; }',
      '.mf-fl__badge--confidential { background:rgba(217,119,6,.12); color:#d97706; }',
      '.mf-fl__badge--unauthorized { background:rgba(79,70,229,.12); color:#4f46e5; }',
      '.mf-fl__badge--other { background:rgba(128,128,128,.12); color:var(--mf-color-text-muted,#8892a4); }',
      /* Status badges */
      '.mf-fl__status { display:inline-block; padding:.1em .45em; border-radius:3px; font-size:.72rem; font-weight:600; text-transform:uppercase; }',
      '.mf-fl__status--active { background:rgba(220,38,38,.12); color:#dc2626; }',
      '.mf-fl__status--extended { background:rgba(217,119,6,.12); color:#d97706; }',
      '.mf-fl__status--dismissed { background:rgba(128,128,128,.12); color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-fl__status--expired { background:rgba(128,128,128,.12); color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-fl__status--removed { background:rgba(79,70,229,.12); color:#4f46e5; }',
      '.mf-fl__status--retracted { background:rgba(128,128,128,.12); color:var(--mf-color-text-muted,#8892a4); }',
      /* Pagination */
      '.mf-fl__pagination { display:flex; gap:0.35rem; justify-content:center; margin-top:1rem; flex-wrap:wrap; }',
      '.mf-fl__page-btn { padding:.32rem .65rem; font-size:.82rem; border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); background:var(--mf-surface,#16213e); color:var(--mf-color-text,#e2e8f0); cursor:pointer; }',
      '.mf-fl__page-btn--active { background:var(--mf-color-accent,#6366f1); color:#fff; border-color:var(--mf-color-accent,#6366f1); }',
      '.mf-fl__page-btn:disabled { opacity:.4; cursor:default; }',
      /* Empty state */
      '.mf-fl__empty { padding:3rem 1rem; text-align:center; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-fl__empty h3 { margin:0 0 0.5rem; font-size:1.05rem; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-fl__empty p { margin:0; font-size:0.87rem; }',
      /* Bulk actions bar */
      '.mf-fl__bulk { display:flex; align-items:center; gap:0.5rem; padding:0.55rem 0; margin-bottom:0.5rem; flex-wrap:wrap; }',
      '.mf-fl__bulk-label { font-size:0.84rem; color:var(--mf-color-text-muted,#8892a4); margin-right:auto; }',
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
    var diff = d - now;
    if (diff > 0) {
      var days = Math.ceil(diff / 86400000);
      return 'in ' + days + ' day' + (days === 1 ? '' : 's');
    }
    var elapsed = now - d;
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

  var REASON_LABELS  = { pii: 'PII', confidential: 'Confidential', unauthorized: 'Unauthorized', other: 'Other' };
  var REASON_CLASSES = { pii: 'pii', confidential: 'confidential', unauthorized: 'unauthorized', other: 'other' };
  var STATUS_CLASSES = { active: 'active', extended: 'extended', dismissed: 'dismissed', expired: 'expired', removed: 'removed', retracted: 'retracted' };

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
    if (!root) throw new Error('MFFlagged.mount: root element is required');
    injectCss();
    clear(root);
    opts = opts || {};
    var role = opts.role || 'operator';

    /* ── State ────────────────────────────────────────────────────────── */
    var currentTab  = 'active';
    var currentPage = 1;
    var perPage     = 25;
    var pollTimer   = null;

    /* ── Skeleton ─────────────────────────────────────────────────────── */

    var wrap = el('div', 'mf-fl');

    /* Header */
    var head = el('div', 'mf-fl__head');
    var h1 = el('h1'); h1.textContent = 'Flagged Files';
    var subhead = el('p'); subhead.textContent = 'Content moderation: review, dismiss, extend, or remove flagged files.';
    head.appendChild(h1);
    head.appendChild(subhead);
    wrap.appendChild(head);

    /* Stats */
    var statsRow = el('div', 'mf-fl__stats');
    var statCards = {};
    [
      { key: 'active',    label: 'Active',    cls: 'mf-fl__stat mf-fl__stat--active' },
      { key: 'extended',  label: 'Extended',  cls: 'mf-fl__stat mf-fl__stat--extended' },
      { key: 'dismissed', label: 'Dismissed', cls: 'mf-fl__stat' },
      { key: 'expired',   label: 'Expired',   cls: 'mf-fl__stat' },
      { key: 'removed',   label: 'Removed',   cls: 'mf-fl__stat' },
    ].forEach(function (item) {
      var card = el('div', item.cls);
      var valEl = el('div', 'mf-fl__stat-val'); valEl.textContent = '—';
      var lblEl = el('div', 'mf-fl__stat-lbl'); lblEl.textContent = item.label;
      card.appendChild(valEl);
      card.appendChild(lblEl);
      statsRow.appendChild(card);
      statCards[item.key] = valEl;
    });
    wrap.appendChild(statsRow);

    /* Tabs */
    var tabsBar = el('div', 'mf-fl__tabs');
    var tabButtons = {};
    ['active', 'history', 'blocklist'].forEach(function (tabKey) {
      var btn = el('button', 'mf-fl__tab');
      btn.textContent = tabKey.charAt(0).toUpperCase() + tabKey.slice(1);
      if (tabKey === 'active') btn.classList.add('mf-fl__tab--active');
      btn.addEventListener('click', function () {
        Object.keys(tabButtons).forEach(function (k) {
          tabButtons[k].classList.toggle('mf-fl__tab--active', k === tabKey);
        });
        currentTab = tabKey;
        currentPage = 1;
        filtersEl.style.display = tabKey === 'blocklist' ? 'none' : '';
        loadData();
      });
      tabsBar.appendChild(btn);
      tabButtons[tabKey] = btn;
    });
    wrap.appendChild(tabsBar);

    /* Filters */
    var filtersEl = el('div', 'mf-fl__filters');

    var reasonFg = el('div', 'mf-fl__fg');
    var reasonLbl = el('label'); reasonLbl.textContent = 'Reason'; reasonLbl.htmlFor = 'mf-fl-reason';
    var reasonSel = el('select'); reasonSel.id = 'mf-fl-reason';
    [['', 'All'], ['pii', 'PII'], ['confidential', 'Confidential'], ['unauthorized', 'Unauthorized'], ['other', 'Other']].forEach(function (opt) {
      var o = el('option'); o.value = opt[0]; o.textContent = opt[1];
      reasonSel.appendChild(o);
    });
    reasonFg.appendChild(reasonLbl);
    reasonFg.appendChild(reasonSel);

    var flaggedByFg = el('div', 'mf-fl__fg');
    var flaggedByLbl = el('label'); flaggedByLbl.textContent = 'Flagged By'; flaggedByLbl.htmlFor = 'mf-fl-flagged-by';
    var flaggedByInp = el('input'); flaggedByInp.id = 'mf-fl-flagged-by'; flaggedByInp.type = 'text'; flaggedByInp.placeholder = 'email'; flaggedByInp.size = 16;
    flaggedByFg.appendChild(flaggedByLbl);
    flaggedByFg.appendChild(flaggedByInp);

    var pathFg = el('div', 'mf-fl__fg');
    var pathLbl = el('label'); pathLbl.textContent = 'Path Prefix'; pathLbl.htmlFor = 'mf-fl-path';
    var pathInp = el('input'); pathInp.id = 'mf-fl-path'; pathInp.type = 'text'; pathInp.placeholder = '/mnt/source/…'; pathInp.size = 20;
    pathFg.appendChild(pathLbl);
    pathFg.appendChild(pathInp);

    var sortFg = el('div', 'mf-fl__fg');
    var sortLbl = el('label'); sortLbl.textContent = 'Sort By'; sortLbl.htmlFor = 'mf-fl-sort';
    var sortSel = el('select'); sortSel.id = 'mf-fl-sort';
    [
      ['expires_at:asc',         'Expires soonest'],
      ['created_at:desc',        'Flagged newest'],
      ['reason:asc',             'Reason'],
      ['flagged_by_email:asc',   'Flagged By'],
    ].forEach(function (opt) {
      var o = el('option'); o.value = opt[0]; o.textContent = opt[1];
      sortSel.appendChild(o);
    });
    sortFg.appendChild(sortLbl);
    sortFg.appendChild(sortSel);

    filtersEl.appendChild(reasonFg);
    filtersEl.appendChild(flaggedByFg);
    filtersEl.appendChild(pathFg);
    filtersEl.appendChild(sortFg);
    wrap.appendChild(filtersEl);

    /* Bulk actions bar (visible only on active tab for operator+) */
    var bulkBar = el('div', 'mf-fl__bulk');
    bulkBar.style.display = 'none';
    var bulkLabel = el('span', 'mf-fl__bulk-label');
    bulkLabel.textContent = '';
    var dismissAllBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    dismissAllBtn.textContent = 'Dismiss All (current page)';
    bulkBar.appendChild(bulkLabel);
    bulkBar.appendChild(dismissAllBtn);
    wrap.appendChild(bulkBar);

    /* Table area */
    var tableWrap = el('div', 'mf-fl__table-wrap');
    var table = el('table', 'mf-fl__table');
    var thead = el('thead');
    var tbody = el('tbody');
    table.appendChild(thead);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);

    /* Empty state */
    var emptyState = el('div', 'mf-fl__empty');
    emptyState.style.display = 'none';
    var emptyTitle = el('h3'); emptyTitle.textContent = 'No flagged files';
    var emptyDesc  = el('p');  emptyDesc.textContent  = 'There are no flags matching this filter.';
    emptyState.appendChild(emptyTitle);
    emptyState.appendChild(emptyDesc);
    wrap.appendChild(emptyState);

    /* Pagination */
    var pagination = el('div', 'mf-fl__pagination');
    wrap.appendChild(pagination);

    root.appendChild(wrap);

    /* ── Build table headers ──────────────────────────────────────────── */

    function buildHeaders() {
      clear(thead);
      var tr = el('tr');
      var cols;
      if (currentTab === 'active') {
        cols = ['File', 'Path', 'Reason', 'Note', 'Flagged By', 'Flagged', 'Expires', 'Actions'];
      } else if (currentTab === 'history') {
        cols = ['File', 'Path', 'Reason', 'Note', 'Flagged By', 'Flagged', 'Status', 'Resolved By'];
      } else {
        cols = ['Source Path', 'Hash', 'Reason', 'Added By', 'Date', 'Action'];
      }
      cols.forEach(function (c) {
        var th = el('th'); th.textContent = c;
        tr.appendChild(th);
      });
      thead.appendChild(tr);
    }

    /* ── Load stats ───────────────────────────────────────────────────── */

    function loadStats() {
      apiGet('/api/flags/stats')
        .then(function (s) {
          ['active', 'extended', 'dismissed', 'expired', 'removed'].forEach(function (k) {
            if (statCards[k]) statCards[k].textContent = (s && s[k] != null) ? s[k] : 0;
          });
        })
        .catch(function (e) { console.warn('mf: flags/stats failed', e); });
    }

    /* ── Load main data ───────────────────────────────────────────────── */

    function showLoadingRow(colCount) {
      clear(tbody);
      var tr = el('tr');
      var td = el('td');
      td.colSpan = colCount;
      td.style.textAlign = 'center';
      td.style.padding = '2rem';
      td.style.color = 'var(--mf-color-text-muted,#8892a4)';
      td.textContent = 'Loading…';
      tr.appendChild(td);
      tbody.appendChild(tr);
    }

    function loadData() {
      buildHeaders();
      var colCount = currentTab === 'blocklist' ? 6 : 8;
      showLoadingRow(colCount);
      tableWrap.style.display = '';
      emptyState.style.display = 'none';
      clear(pagination);
      bulkBar.style.display = 'none';

      if (currentTab === 'blocklist') {
        loadBlocklist();
      } else {
        loadFlags();
      }
    }

    function loadFlags() {
      var reason     = reasonSel.value;
      var flaggedBy  = flaggedByInp.value.trim();
      var pathPrefix = pathInp.value.trim();
      var sortParts  = sortSel.value.split(':');
      var sortBy     = sortParts[0];
      var sortDir    = sortParts[1];
      var status     = currentTab === 'active' ? 'active' : '';

      var url = '/api/flags?page=' + currentPage + '&per_page=' + perPage;
      if (status)     url += '&status='     + encodeURIComponent(status);
      if (reason)     url += '&reason='     + encodeURIComponent(reason);
      if (flaggedBy)  url += '&flagged_by=' + encodeURIComponent(flaggedBy);
      if (pathPrefix) url += '&path_prefix='+ encodeURIComponent(pathPrefix);
      url += '&sort_by=' + encodeURIComponent(sortBy) + '&sort_dir=' + encodeURIComponent(sortDir);

      apiGet(url)
        .then(renderFlags)
        .catch(function (e) { showTableError('Failed to load flags: ' + e.message); });
    }

    function loadBlocklist() {
      var url = '/api/flags/blocklist?page=' + currentPage + '&per_page=' + perPage;
      apiGet(url)
        .then(renderBlocklist)
        .catch(function (e) { showTableError('Failed to load blocklist: ' + e.message); });
    }

    function showTableError(msg) {
      clear(tbody);
      var tr = el('tr');
      var td = el('td');
      td.colSpan = currentTab === 'blocklist' ? 6 : 8;
      td.style.cssText = 'padding:2rem;text-align:center;color:#f87171;';
      td.textContent = msg;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }

    /* ── Render flags table ───────────────────────────────────────────── */

    function renderFlags(data) {
      var items = data.items || [];
      clear(tbody);

      if (!items.length) {
        tableWrap.style.display = 'none';
        emptyState.style.display = '';
        emptyTitle.textContent = currentTab === 'active' ? 'No active flags' : 'No flag history';
        emptyDesc.textContent  = currentTab === 'active'
          ? 'No files are currently flagged.'
          : 'No flags match the current filters.';
        return;
      }

      tableWrap.style.display = '';
      emptyState.style.display = 'none';

      /* Show bulk bar for active tab */
      if (currentTab === 'active' && items.length > 0) {
        bulkLabel.textContent = items.length + ' flag' + (items.length === 1 ? '' : 's') + ' on this page';
        bulkBar.style.display = '';
      }

      items.forEach(function (item) {
        tbody.appendChild(renderFlagRow(item));
      });

      renderPagination(data.total, data.page, data.per_page);
    }

    function makeReasonBadge(reason) {
      var span = el('span', 'mf-fl__badge mf-fl__badge--' + (REASON_CLASSES[reason] || 'other'));
      span.textContent = REASON_LABELS[reason] || reason || 'Unknown';
      return span;
    }

    function makeStatusBadge(status) {
      var span = el('span', 'mf-fl__status mf-fl__status--' + (STATUS_CLASSES[status] || 'active'));
      span.textContent = (status || 'active').charAt(0).toUpperCase() + (status || 'active').slice(1);
      return span;
    }

    function renderFlagRow(item) {
      var tr = el('tr');

      /* File name */
      var tdFile = el('td', 'file'); tdFile.textContent = filename(item.source_path);
      tr.appendChild(tdFile);

      /* Path */
      var tdPath = el('td', 'path'); tdPath.textContent = item.source_path || ''; tdPath.title = item.source_path || '';
      tr.appendChild(tdPath);

      /* Reason badge */
      var tdReason = el('td'); tdReason.appendChild(makeReasonBadge(item.reason));
      tr.appendChild(tdReason);

      /* Note */
      var tdNote = el('td'); tdNote.style.cssText = 'max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.82rem;'; tdNote.textContent = item.note || ''; tdNote.title = item.note || '';
      tr.appendChild(tdNote);

      /* Flagged by */
      var tdBy = el('td'); tdBy.style.fontSize = '.83rem'; tdBy.textContent = item.flagged_by_email || '';
      tr.appendChild(tdBy);

      /* Flagged date */
      var tdDate = el('td'); tdDate.style.fontSize = '.83rem'; tdDate.style.color = 'var(--mf-color-text-muted,#8892a4)'; tdDate.textContent = timeAgo(item.created_at); tdDate.title = item.created_at || '';
      tr.appendChild(tdDate);

      if (currentTab === 'active') {
        /* Expires */
        var tdExpires = el('td'); tdExpires.style.fontSize = '.83rem'; tdExpires.textContent = timeAgo(item.expires_at); tdExpires.title = item.expires_at || '';
        tr.appendChild(tdExpires);

        /* Actions */
        var tdActions = el('td', 'actions');
        var btnDismiss = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        btnDismiss.textContent = 'Dismiss';
        btnDismiss.style.marginRight = '0.25rem';
        btnDismiss.addEventListener('click', (function (id) { return function () { dismissFlag(id); }; })(item.id));

        var btnExtend = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        btnExtend.textContent = 'Extend';
        btnExtend.style.marginRight = '0.25rem';
        btnExtend.addEventListener('click', (function (id) { return function () { extendFlag(id); }; })(item.id));

        var btnRemove = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
        btnRemove.textContent = 'Remove';
        btnRemove.addEventListener('click', (function (id) { return function () { removeFlag(id); }; })(item.id));

        tdActions.appendChild(btnDismiss);
        tdActions.appendChild(btnExtend);
        tdActions.appendChild(btnRemove);
        tr.appendChild(tdActions);

      } else {
        /* Status badge */
        var tdStatus = el('td'); tdStatus.appendChild(makeStatusBadge(item.status));
        tr.appendChild(tdStatus);

        /* Resolved by */
        var tdResolved = el('td'); tdResolved.style.fontSize = '.83rem'; tdResolved.textContent = item.resolved_by_email || '';
        tr.appendChild(tdResolved);
      }

      return tr;
    }

    /* ── Render blocklist ─────────────────────────────────────────────── */

    function renderBlocklist(data) {
      var items = data.items || [];
      clear(tbody);

      if (!items.length) {
        tableWrap.style.display = 'none';
        emptyState.style.display = '';
        emptyTitle.textContent = 'Blocklist empty';
        emptyDesc.textContent  = 'No content hashes are currently blocklisted.';
        return;
      }

      tableWrap.style.display = '';
      emptyState.style.display = 'none';

      items.forEach(function (item) {
        var tr = el('tr');

        var tdPath = el('td', 'path'); tdPath.textContent = item.source_path || ''; tdPath.title = item.source_path || '';
        tr.appendChild(tdPath);

        var tdHash = el('td', 'hash');
        var hash = item.content_hash || '';
        tdHash.textContent = hash.length > 16 ? hash.substring(0, 16) + '…' : hash;
        tdHash.title = hash;
        tr.appendChild(tdHash);

        var tdReason = el('td'); tdReason.textContent = item.reason || '';
        tr.appendChild(tdReason);

        var tdAddedBy = el('td'); tdAddedBy.style.fontSize = '.83rem'; tdAddedBy.textContent = item.added_by_email || '';
        tr.appendChild(tdAddedBy);

        var tdDate = el('td'); tdDate.style.fontSize = '.83rem'; tdDate.style.color = 'var(--mf-color-text-muted,#8892a4)'; tdDate.textContent = timeAgo(item.created_at); tdDate.title = item.created_at || '';
        tr.appendChild(tdDate);

        var tdAction = el('td', 'actions');
        var unblockBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        unblockBtn.textContent = 'Un-blocklist';
        unblockBtn.addEventListener('click', (function (id) { return function () { unblocklist(id); }; })(item.id));
        tdAction.appendChild(unblockBtn);
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
      });

      renderPagination(data.total, data.page, data.per_page);
    }

    /* ── Pagination ───────────────────────────────────────────────────── */

    function renderPagination(total, page, pp) {
      clear(pagination);
      if (!total || !pp) return;
      var totalPages = Math.ceil(total / pp);
      if (totalPages <= 1) return;

      var prevBtn = el('button', 'mf-fl__page-btn');
      prevBtn.textContent = 'Prev';
      prevBtn.disabled = page <= 1;
      prevBtn.addEventListener('click', function () { currentPage = page - 1; loadData(); });
      pagination.appendChild(prevBtn);

      for (var i = 1; i <= totalPages; i++) {
        /* Ellipsis compression for large page counts */
        if (totalPages > 7 && i > 3 && i < totalPages - 1 && Math.abs(i - page) > 1) {
          if (i === 4 || i === totalPages - 2) {
            var dot = el('button', 'mf-fl__page-btn');
            dot.textContent = '…';
            dot.disabled = true;
            pagination.appendChild(dot);
          }
          continue;
        }
        var btn = el('button', 'mf-fl__page-btn' + (i === page ? ' mf-fl__page-btn--active' : ''));
        btn.textContent = i;
        btn.addEventListener('click', (function (p) { return function () { currentPage = p; loadData(); }; })(i));
        pagination.appendChild(btn);
      }

      var nextBtn = el('button', 'mf-fl__page-btn');
      nextBtn.textContent = 'Next';
      nextBtn.disabled = page >= totalPages;
      nextBtn.addEventListener('click', function () { currentPage = page + 1; loadData(); });
      pagination.appendChild(nextBtn);
    }

    /* ── Actions ──────────────────────────────────────────────────────── */

    /* TODO: replace prompt() calls below with inline modal dialogs
     * for a fully polished new-UX experience. prompt() is acceptable
     * for initial operator tooling but is jarring in the new theme. */

    function dismissFlag(id) {
      var note = prompt('Resolution note (optional):');
      if (note === null) return;
      var body = {};
      if (note) body.resolution_note = note;
      apiPut('/api/flags/' + id + '/dismiss', body)
        .then(function () { showToast('Flag dismissed'); loadStats(); loadData(); })
        .catch(function (e) { showToast('Dismiss failed: ' + e.message, 'error'); });
    }

    function extendFlag(id) {
      var days = prompt('Extend by how many days?', '30');
      if (days === null) return;
      var parsed = parseInt(days, 10);
      if (isNaN(parsed) || parsed <= 0) { showToast('Invalid number of days', 'error'); return; }
      var note = prompt('Resolution note (optional):');
      if (note === null) return;
      var body = { days: parsed };
      if (note) body.resolution_note = note;
      apiPut('/api/flags/' + id + '/extend', body)
        .then(function () { showToast('Flag extended by ' + parsed + ' days'); loadStats(); loadData(); })
        .catch(function (e) { showToast('Extend failed: ' + e.message, 'error'); });
    }

    function removeFlag(id) {
      if (!confirm('Remove this file? This will mark the file for removal from the system.')) return;
      var note = prompt('Resolution note (optional):');
      if (note === null) return;
      var body = {};
      if (note) body.resolution_note = note;
      apiPut('/api/flags/' + id + '/remove', body)
        .then(function () { showToast('File marked for removal'); loadStats(); loadData(); })
        .catch(function (e) { showToast('Remove failed: ' + e.message, 'error'); });
    }

    function unblocklist(id) {
      if (!confirm('Remove this hash from the blocklist?')) return;
      apiDelete('/api/flags/blocklist/' + id)
        .then(function () { showToast('Removed from blocklist'); loadData(); })
        .catch(function (e) { showToast('Unblocklist failed: ' + e.message, 'error'); });
    }

    /* Dismiss all on current page */
    dismissAllBtn.addEventListener('click', function () {
      if (!confirm('Dismiss all flagged files on this page?')) return;
      /* Collect IDs from current rendered rows via a data attribute approach:
       * walk the button nodes already in the DOM and trigger each dismiss.
       * TODO: track IDs in an in-memory array for cleaner bulk ops. */
      var dismissBtns = tbody.querySelectorAll('.mf-btn--ghost');
      var fired = 0;
      dismissBtns.forEach(function (btn) {
        if (btn.textContent === 'Dismiss') { btn.click(); fired++; }
      });
      if (!fired) showToast('Nothing to dismiss', 'info');
    });

    /* ── Filter event wiring ──────────────────────────────────────────── */

    reasonSel.addEventListener('change', function () { currentPage = 1; loadData(); });
    sortSel.addEventListener('change', function () { currentPage = 1; loadData(); });

    var filterTimer;
    function debouncedFilter() {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(function () { currentPage = 1; loadData(); }, 400);
    }
    flaggedByInp.addEventListener('input', debouncedFilter);
    pathInp.addEventListener('input', debouncedFilter);

    /* ── Auto-refresh ─────────────────────────────────────────────────── */

    var POLL_MS = 30000;
    pollTimer = setInterval(function () {
      if (!document.hidden) { loadStats(); loadData(); }
    }, POLL_MS);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { loadStats(); loadData(); }
    });

    /* ── Initial load ─────────────────────────────────────────────────── */
    loadStats();
    loadData();

    /* ── Return control handle ────────────────────────────────────────── */
    return {
      refresh: function () { loadStats(); loadData(); },
      destroy: function () { clearInterval(pollTimer); },
    };
  }

  /* ── Export ──────────────────────────────────────────────────────────────── */
  global.MFFlagged = { mount: mount };

})(window);
