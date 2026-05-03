/* MFTrash — new-UX Trash page component.
 *
 * Feature parity with /trash.html:
 *   - Stats summary (total trashed, total size, earliest auto-delete)
 *   - Paginated table with restore/delete actions per row
 *   - Bulk actions: Restore All, Empty All
 *   - Empty state when trash is empty
 *
 * Endpoints used:
 *   GET /api/lifecycle/trash                  -- list trash
 *   POST /api/lifecycle/trash/restore         -- restore single file
 *   POST /api/lifecycle/trash/empty           -- empty single file
 *   POST /api/lifecycle/trash/restore-all     -- restore all
 *   POST /api/lifecycle/trash/empty-all       -- empty all
 *
 * Safe DOM throughout. */
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

  function fmtLocalTime(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function daysRemaining(purgeAt) {
    if (!purgeAt) return null;
    var now = new Date();
    var expiry = new Date(purgeAt);
    var diff = expiry - now;
    if (diff <= 0) return 0;
    return Math.ceil(diff / (1000 * 60 * 60 * 24));
  }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFTrash.mount: root element is required');
    clear(root);
    opts = opts || {};

    /* State */
    var currentPage = 1;
    var perPage = 25;
    var trashData = null;
    var selectedIds = new Set();

    /* ── Inject page styles (once) ──────────────────────────────────────── */
    if (!document.getElementById('mf-trash-styles')) {
      var style = document.createElement('style');
      style.id = 'mf-trash-styles';
      style.textContent = [
        '.mf-tr { max-width:1100px; margin:0 auto; padding:1.5rem 1rem; }',
        '.mf-tr__head { margin-bottom:1rem; }',
        '.mf-tr__head h1 { margin:0 0 0.25rem; font-size:1.6rem; font-weight:700; }',
        '.mf-tr__head p { margin:0; font-size:0.88rem; color:var(--mf-color-text-muted); }',
        /* Stats row */
        '.mf-tr__stats { display:flex; flex-wrap:wrap; gap:1rem; padding:0.75rem 0.9rem; background:var(--mf-surface-soft); border-radius:var(--mf-radius); margin-bottom:1.25rem; font-size:0.85rem; }',
        '.mf-tr__stat { display:flex; flex-direction:column; gap:0.1rem; }',
        '.mf-tr__stat-val { font-weight:700; font-size:1.1rem; }',
        '.mf-tr__stat-lab { font-size:0.73rem; color:var(--mf-color-text-muted); text-transform:uppercase; }',
        /* Bulk action bar */
        '.mf-tr__bulk-bar { display:none; margin-bottom:0.75rem; padding:0.55rem 0.75rem; background:rgba(79,91,213,0.08); border:1px solid rgba(79,91,213,0.3); border-radius:var(--mf-radius-sm); align-items:center; gap:0.5rem; font-size:0.84rem; }',
        '.mf-tr__bulk-bar--visible { display:flex; }',
        /* Table */
        '.mf-tr__table-wrap { border:1px solid var(--mf-border); border-radius:var(--mf-radius); overflow:auto; margin-bottom:0.75rem; }',
        '.mf-tr__table { width:100%; border-collapse:collapse; font-size:0.84rem; }',
        '.mf-tr__table th { padding:0.55rem 0.75rem; text-align:left; font-size:0.73rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; background:var(--mf-surface-soft); border-bottom:2px solid var(--mf-border); color:var(--mf-color-text-muted); white-space:nowrap; }',
        '.mf-tr__table td { padding:0.55rem 0.75rem; border-bottom:1px solid var(--mf-border); vertical-align:middle; }',
        '.mf-tr__table tr:last-child td { border-bottom:none; }',
        '.mf-tr__table tbody tr:hover { background:var(--mf-surface-soft); }',
        '.mf-tr__table td.path { max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:ui-monospace,monospace; font-size:0.8rem; }',
        '.mf-tr__days-pill { display:inline-block; padding:0.15em 0.5em; border-radius:var(--mf-radius-sm); font-size:0.75rem; font-weight:600; }',
        '.mf-tr__days-pill--urgent { background:rgba(220,38,38,0.15); color:var(--mf-color-error); }',
        '.mf-tr__days-pill--warn { background:rgba(217,119,6,0.15); color:var(--mf-color-warn); }',
        '.mf-tr__days-pill--ok { background:rgba(22,163,74,0.15); color:var(--mf-color-success); }',
        /* Pagination */
        '.mf-tr__pagination { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:0.5rem; margin-top:0.5rem; font-size:0.82rem; }',
        '.mf-tr__paging-info { color:var(--mf-color-text-muted); }',
        '.mf-tr__paging-btns { display:flex; gap:0.25rem; }',
        '.mf-tr__paging-btns button { padding:0.25em 0.55em; border:1px solid var(--mf-border); border-radius:var(--mf-radius-sm); background:var(--mf-surface); color:var(--mf-color-text); cursor:pointer; font-size:0.8rem; }',
        '.mf-tr__paging-btns button:disabled { opacity:0.4; cursor:default; }',
        '.mf-tr__paging-btns button:hover:not(:disabled) { background:var(--mf-surface-soft); }',
        /* Empty state */
        '.mf-tr__empty { text-align:center; padding:2.5rem 1rem; color:var(--mf-color-text-muted); }',
        '.mf-tr__empty h3 { margin:0 0 0.5rem; font-size:1.1rem; }',
        '.mf-tr__empty p { margin:0; font-size:0.88rem; }',
        /* Action buttons */
        '.mf-btn { display:inline-flex; align-items:center; gap:0.3rem; padding:0.4em 0.8em; border-radius:var(--mf-radius-sm); border:1px solid transparent; font-size:0.84rem; font-weight:500; cursor:pointer; transition:background .15s; }',
        '.mf-btn--ghost { background:transparent; border-color:var(--mf-border); color:var(--mf-color-text); }',
        '.mf-btn--ghost:hover { background:var(--mf-surface-soft); }',
        '.mf-btn--danger { background:transparent; border-color:#ffd0d0; color:var(--mf-color-error); }',
        '.mf-btn--danger:hover { background:rgba(220,38,38,0.08); }',
        '.mf-btn--sm { padding:0.3em 0.65em; font-size:0.78rem; }',
        '.mf-btn:disabled { opacity:0.5; cursor:not-allowed; }',
      ].join('\n');
      document.head.appendChild(style);
    }

    /* ── Skeleton ─────────────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-tr');

    /* Header */
    var head = el('div', 'mf-tr__head');
    var h1 = el('h1');
    h1.textContent = 'Trash';
    var subp = el('p');
    subp.textContent = 'Files are permanently deleted 60 days after being trashed.';
    head.appendChild(h1);
    head.appendChild(subp);
    wrapper.appendChild(head);

    /* Stats */
    var statsRow = el('div', 'mf-tr__stats');
    wrapper.appendChild(statsRow);

    /* Bulk action bar */
    var bulkBar = el('div', 'mf-tr__bulk-bar');
    var bulkLabel = el('span');
    bulkLabel.textContent = '';
    var bulkSpacer = el('span');
    bulkSpacer.style.flex = '1';
    var restoreAllBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    restoreAllBtn.textContent = 'Restore All';
    var emptyAllBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
    emptyAllBtn.textContent = 'Empty All';
    bulkBar.appendChild(bulkLabel);
    bulkBar.appendChild(bulkSpacer);
    bulkBar.appendChild(restoreAllBtn);
    bulkBar.appendChild(emptyAllBtn);
    wrapper.appendChild(bulkBar);

    /* Table */
    var tableWrap = el('div', 'mf-tr__table-wrap');
    var table = el('table', 'mf-tr__table');
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    ['Filename', 'Original Path', 'Trashed', 'Auto-Delete', 'Days Left', 'Actions'].forEach(function (label) {
      var th = document.createElement('th');
      th.textContent = label;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = document.createElement('tbody');
    var loadRow = document.createElement('tr');
    var loadTd = document.createElement('td');
    loadTd.colSpan = 6;
    loadTd.style.cssText = 'text-align:center;padding:2rem;';
    loadTd.appendChild(el('span'));
    loadTd.appendChild(txt(' Loading…'));
    loadRow.appendChild(loadTd);
    tbody.appendChild(loadRow);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrapper.appendChild(tableWrap);

    /* Pagination */
    var pagination = el('div', 'mf-tr__pagination');
    var pagingInfo = el('span', 'mf-tr__paging-info');
    var pagingBtns = el('div', 'mf-tr__paging-btns');
    pagination.appendChild(pagingInfo);
    pagination.appendChild(pagingBtns);
    wrapper.appendChild(pagination);

    /* Empty state */
    var empty = el('div', 'mf-tr__empty');
    empty.style.display = 'none';
    var emptyH3 = el('h3');
    emptyH3.textContent = 'Trash is empty';
    var emptyP = el('p');
    emptyP.textContent = 'No files are in the trash.';
    empty.appendChild(emptyH3);
    empty.appendChild(emptyP);
    wrapper.appendChild(empty);

    root.appendChild(wrapper);

    /* ── API Fetch ──────────────────────────────────────────────────────── */

    function apiFetch(path, opts) {
      return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}))
        .then(function (r) {
          if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
          return r.json();
        });
    }

    /* ── Load trash ─────────────────────────────────────────────────────── */

    function loadTrash() {
      var qs = new URLSearchParams({ page: currentPage, per_page: perPage });
      clear(tbody);
      var spinRow = document.createElement('tr');
      var spinTd = document.createElement('td');
      spinTd.colSpan = 6;
      spinTd.style.cssText = 'text-align:center;padding:2rem;';
      spinTd.appendChild(txt('Loading…'));
      spinRow.appendChild(spinTd);
      tbody.appendChild(spinRow);

      apiFetch('/api/lifecycle/trash?' + qs.toString())
        .then(function (data) {
          trashData = data;
          renderTable(data);
          renderStats(data);
          renderPagination(data);
          tableWrap.style.display = data.files && data.files.length > 0 ? '' : 'none';
          pagination.style.display = data.files && data.files.length > 0 ? '' : 'none';
          empty.style.display = data.files && data.files.length === 0 ? '' : 'none';
        })
        .catch(function (e) {
          clear(tbody);
          var errRow = document.createElement('tr');
          var errTd = document.createElement('td');
          errTd.colSpan = 6;
          errTd.style.cssText = 'text-align:center;padding:2rem;color:var(--mf-color-error);';
          errTd.textContent = 'Failed to load trash: ' + e.message;
          errRow.appendChild(errTd);
          tbody.appendChild(errRow);
        });
    }

    function renderStats(data) {
      clear(statsRow);
      if (!data || !data.files) return;
      var totalSize = data.files.reduce(function (s, f) { return s + (f.size_at_version || 0); }, 0);
      var earliest = data.files.reduce(function (min, f) {
        var d = f.purge_at;
        return d && (!min || d < min) ? d : min;
      }, null);
      var stats = [
        { val: (data.total || 0).toLocaleString(), lab: 'files in trash' },
        { val: fmtBytes(totalSize), lab: 'total size' },
      ];
      if (earliest) stats.push({ val: fmtLocalTime(earliest), lab: 'earliest auto-delete' });
      stats.forEach(function (s) {
        var stat = el('div', 'mf-tr__stat');
        var v = el('div', 'mf-tr__stat-val');
        v.textContent = s.val;
        var l = el('div', 'mf-tr__stat-lab');
        l.textContent = s.lab;
        stat.appendChild(v);
        stat.appendChild(l);
        statsRow.appendChild(stat);
      });
    }

    function renderTable(data) {
      clear(tbody);
      selectedIds.clear();
      if (!data.files || !data.files.length) return;
      data.files.forEach(function (f) {
        var tr = document.createElement('tr');
        var name = (f.source_path || '').split('/').pop() || f.source_path;

        /* Filename */
        var tdFile = document.createElement('td');
        tdFile.textContent = name;
        tr.appendChild(tdFile);

        /* Path */
        var tdPath = document.createElement('td');
        tdPath.className = 'path';
        tdPath.textContent = f.source_path || '';
        tdPath.title = f.source_path || '';
        tr.appendChild(tdPath);

        /* Trashed */
        var tdTrashed = document.createElement('td');
        tdTrashed.textContent = f.moved_to_trash_at ? fmtLocalTime(f.moved_to_trash_at) : '—';
        tr.appendChild(tdTrashed);

        /* Auto-Delete */
        var tdPurge = document.createElement('td');
        tdPurge.textContent = f.purge_at ? fmtLocalTime(f.purge_at) : '—';
        tr.appendChild(tdPurge);

        /* Days Left */
        var tdDays = document.createElement('td');
        var days = daysRemaining(f.purge_at);
        if (days != null) {
          var pill = el('span', 'mf-tr__days-pill');
          var daysCls = days <= 7 ? 'urgent' : days <= 14 ? 'warn' : 'ok';
          pill.className = 'mf-tr__days-pill mf-tr__days-pill--' + daysCls;
          pill.textContent = days + 'd';
          tdDays.appendChild(pill);
        } else {
          tdDays.textContent = '—';
        }
        tr.appendChild(tdDays);

        /* Actions */
        var tdActions = document.createElement('td');
        tdActions.style.whiteSpace = 'nowrap';
        var restoreBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        restoreBtn.textContent = 'Restore';
        (function (fileId) {
          restoreBtn.addEventListener('click', function () { restoreFile(fileId); });
        })(f.id);
        var deleteBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
        deleteBtn.textContent = 'Delete';
        (function (fileId) {
          deleteBtn.addEventListener('click', function () { deleteFile(fileId); });
        })(f.id);
        tdActions.appendChild(restoreBtn);
        tdActions.appendChild(deleteBtn);
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
      });
    }

    function renderPagination(data) {
      clear(pagingInfo);
      clear(pagingBtns);
      if (!data || !data.total) return;
      var start = (data.page - 1) * data.per_page + 1;
      var end = Math.min(data.page * data.per_page, data.total);
      var info = el('span');
      info.textContent = 'Showing ' + start + '–' + end + ' of ' + data.total.toLocaleString();
      pagingInfo.appendChild(info);

      if (data.pages <= 1) return;
      var prevBtn = el('button');
      prevBtn.textContent = '←';
      prevBtn.disabled = data.page <= 1;
      prevBtn.addEventListener('click', function () { currentPage--; loadTrash(); });
      pagingBtns.appendChild(prevBtn);

      var pageSpan = el('span');
      pageSpan.style.cssText = 'margin:0 0.3rem;';
      pageSpan.textContent = data.page + ' / ' + data.pages;
      pagingBtns.appendChild(pageSpan);

      var nextBtn = el('button');
      nextBtn.textContent = '→';
      nextBtn.disabled = data.page >= data.pages;
      nextBtn.addEventListener('click', function () { currentPage++; loadTrash(); });
      pagingBtns.appendChild(nextBtn);
    }

    /* ── Actions ────────────────────────────────────────────────────────── */

    function restoreFile(fileId) {
      restoreAllBtn.disabled = true;
      apiFetch('/api/lifecycle/trash/' + fileId + '/restore', { method: 'POST' })
        .then(function () {
          showToast('File restored', 'success');
          loadTrash();
        })
        .catch(function (e) {
          showToast('Failed: ' + e.message, 'error');
          restoreAllBtn.disabled = false;
        });
    }

    function deleteFile(fileId) {
      if (!confirm('Permanently delete this file?')) return;
      apiFetch('/api/lifecycle/trash/' + fileId + '/empty', { method: 'POST' })
        .then(function () {
          showToast('File deleted', 'success');
          loadTrash();
        })
        .catch(function (e) {
          showToast('Failed: ' + e.message, 'error');
        });
    }

    restoreAllBtn.addEventListener('click', function () {
      if (!trashData || !trashData.files || !trashData.files.length) return;
      if (!confirm('Restore all ' + trashData.total + ' files from trash?')) return;
      restoreAllBtn.disabled = true;
      apiFetch('/api/lifecycle/trash/restore-all', { method: 'POST' })
        .then(function () {
          showToast('All files restored', 'success');
          loadTrash();
        })
        .catch(function (e) {
          showToast('Failed: ' + e.message, 'error');
          restoreAllBtn.disabled = false;
        });
    });

    emptyAllBtn.addEventListener('click', function () {
      if (!trashData || !trashData.files || !trashData.files.length) return;
      if (!confirm('Permanently delete all ' + trashData.total + ' files in trash?')) return;
      emptyAllBtn.disabled = true;
      apiFetch('/api/lifecycle/trash/empty-all', { method: 'POST' })
        .then(function () {
          showToast('Trash emptied', 'success');
          loadTrash();
        })
        .catch(function (e) {
          showToast('Failed: ' + e.message, 'error');
          emptyAllBtn.disabled = false;
        });
    });

    /* ── Initial load ─────────────────────────────────────────────────────── */
    loadTrash();

    /* ── Return handle ────────────────────────────────────────────────────── */
    return {
      refresh: loadTrash,
      destroy: function () { /* no timers */ },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */

  global.MFTrash = { mount: mount };

})(window);
