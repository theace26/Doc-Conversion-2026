/* MFUnrecognized — new-UX Unrecognized Files page component.
 *
 * Feature parity with /unrecognized.html:
 *   - Stats summary (total unrecognized, by-extension breakdown)
 *   - Filter bar (by extension, by category, by job)
 *   - Paginated table with file details
 *   - Empty state when no unrecognized files
 *   - Auto-refresh every 60 s while tab is visible
 *
 * Endpoints used:
 *   GET /api/pipeline/unrecognized          -- list unrecognized files
 *   GET /api/pipeline/unrecognized/stats    -- stats
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

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFUnrecognized.mount: root element is required');
    clear(root);
    opts = opts || {};

    /* State */
    var currentPage = 1;
    var perPage = 25;
    var currentExtension = '';
    var currentCategory = '';
    var currentJob = '';

    /* ── Inject page styles (once) ──────────────────────────────────────── */
    if (!document.getElementById('mf-ur-styles')) {
      var style = document.createElement('style');
      style.id = 'mf-ur-styles';
      style.textContent = [
        '.mf-ur { max-width:1200px; margin:0 auto; padding:1.5rem 1rem; }',
        '.mf-ur__head { margin-bottom:1rem; }',
        '.mf-ur__head h1 { margin:0 0 0.25rem; font-size:1.6rem; font-weight:700; }',
        '.mf-ur__head p { margin:0; font-size:0.88rem; color:var(--mf-color-text-muted); }',
        /* Stats row */
        '.mf-ur__stats { display:flex; flex-wrap:wrap; gap:1rem; padding:0.75rem 0.9rem; background:var(--mf-surface-soft); border-radius:var(--mf-radius); margin-bottom:1.25rem; font-size:0.85rem; }',
        '.mf-ur__stat { display:flex; flex-direction:column; gap:0.1rem; }',
        '.mf-ur__stat-val { font-weight:700; font-size:1.1rem; }',
        '.mf-ur__stat-lab { font-size:0.73rem; color:var(--mf-color-text-muted); text-transform:uppercase; }',
        /* Filters */
        '.mf-ur__filters { display:flex; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem; align-items:flex-end; }',
        '.mf-ur__filter-group { display:flex; flex-direction:column; gap:0.2rem; }',
        '.mf-ur__filter-group label { font-size:0.73rem; color:var(--mf-color-text-muted); text-transform:uppercase; }',
        '.mf-ur__filter-group select { padding:0.35em 0.6em; border:1px solid var(--mf-border); border-radius:var(--mf-radius-sm); background:var(--mf-surface); color:var(--mf-color-text); font-size:0.84rem; }',
        /* Table */
        '.mf-ur__table-wrap { border:1px solid var(--mf-border); border-radius:var(--mf-radius); overflow:auto; margin-bottom:0.75rem; }',
        '.mf-ur__table { width:100%; border-collapse:collapse; font-size:0.84rem; }',
        '.mf-ur__table th { padding:0.55rem 0.75rem; text-align:left; font-size:0.73rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; background:var(--mf-surface-soft); border-bottom:2px solid var(--mf-border); color:var(--mf-color-text-muted); white-space:nowrap; }',
        '.mf-ur__table td { padding:0.55rem 0.75rem; border-bottom:1px solid var(--mf-border); vertical-align:middle; }',
        '.mf-ur__table tr:last-child td { border-bottom:none; }',
        '.mf-ur__table tbody tr:hover { background:var(--mf-surface-soft); }',
        '.mf-ur__table td.path { max-width:350px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:ui-monospace,monospace; font-size:0.8rem; }',
        '.mf-ur__ext-badge { display:inline-block; padding:0.1em 0.4em; border-radius:var(--mf-radius-sm); font-size:0.72rem; font-weight:700; text-transform:uppercase; background:var(--mf-surface-alt); color:var(--mf-color-text); }',
        /* Pagination */
        '.mf-ur__pagination { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:0.5rem; margin-top:0.5rem; font-size:0.82rem; }',
        '.mf-ur__paging-info { color:var(--mf-color-text-muted); }',
        '.mf-ur__paging-btns { display:flex; gap:0.25rem; }',
        '.mf-ur__paging-btns button { padding:0.25em 0.55em; border:1px solid var(--mf-border); border-radius:var(--mf-radius-sm); background:var(--mf-surface); color:var(--mf-color-text); cursor:pointer; font-size:0.8rem; }',
        '.mf-ur__paging-btns button:disabled { opacity:0.4; cursor:default; }',
        '.mf-ur__paging-btns button:hover:not(:disabled) { background:var(--mf-surface-soft); }',
        /* Empty state */
        '.mf-ur__empty { text-align:center; padding:2.5rem 1rem; color:var(--mf-color-text-muted); }',
        '.mf-ur__empty h3 { margin:0 0 0.5rem; font-size:1.1rem; }',
        '.mf-ur__empty p { margin:0; font-size:0.88rem; }',
      ].join('\n');
      document.head.appendChild(style);
    }

    /* ── Skeleton ─────────────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-ur');

    /* Header */
    var head = el('div', 'mf-ur__head');
    var h1 = el('h1');
    h1.textContent = 'Unrecognized Files';
    var subp = el('p');
    subp.textContent = 'Files cataloged during bulk scans that MarkFlow cannot convert yet.';
    head.appendChild(h1);
    head.appendChild(subp);
    wrapper.appendChild(head);

    /* Stats */
    var statsRow = el('div', 'mf-ur__stats');
    wrapper.appendChild(statsRow);

    /* Filters */
    var filterBar = el('div', 'mf-ur__filters');

    var extFg = el('div', 'mf-ur__filter-group');
    var extLbl = el('label');
    extLbl.textContent = 'Extension';
    var extSel = el('select');
    var extOpt = el('option');
    extOpt.value = '';
    extOpt.textContent = 'All';
    extSel.appendChild(extOpt);
    extFg.appendChild(extLbl);
    extFg.appendChild(extSel);
    filterBar.appendChild(extFg);

    var catFg = el('div', 'mf-ur__filter-group');
    var catLbl = el('label');
    catLbl.textContent = 'Category';
    var catSel = el('select');
    var catOpt = el('option');
    catOpt.value = '';
    catOpt.textContent = 'All';
    catSel.appendChild(catOpt);
    catFg.appendChild(catLbl);
    catFg.appendChild(catSel);
    filterBar.appendChild(catFg);

    var jobFg = el('div', 'mf-ur__filter-group');
    var jobLbl = el('label');
    jobLbl.textContent = 'Job';
    var jobSel = el('select');
    var jobOpt = el('option');
    jobOpt.value = '';
    jobOpt.textContent = 'All';
    jobSel.appendChild(jobOpt);
    jobFg.appendChild(jobLbl);
    jobFg.appendChild(jobSel);
    filterBar.appendChild(jobFg);

    wrapper.appendChild(filterBar);

    /* Table */
    var tableWrap = el('div', 'mf-ur__table-wrap');
    var table = el('table', 'mf-ur__table');
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    ['File Path', 'Extension', 'Category', 'Size', 'Job'].forEach(function (label) {
      var th = document.createElement('th');
      th.textContent = label;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = document.createElement('tbody');
    var loadRow = document.createElement('tr');
    var loadTd = document.createElement('td');
    loadTd.colSpan = 5;
    loadTd.style.cssText = 'text-align:center;padding:2rem;';
    loadTd.appendChild(txt('Loading…'));
    loadRow.appendChild(loadTd);
    tbody.appendChild(loadRow);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrapper.appendChild(tableWrap);

    /* Pagination */
    var pagination = el('div', 'mf-ur__pagination');
    var pagingInfo = el('span', 'mf-ur__paging-info');
    var pagingBtns = el('div', 'mf-ur__paging-btns');
    pagination.appendChild(pagingInfo);
    pagination.appendChild(pagingBtns);
    wrapper.appendChild(pagination);

    /* Empty state */
    var empty = el('div', 'mf-ur__empty');
    empty.style.display = 'none';
    var emptyH3 = el('h3');
    emptyH3.textContent = 'All files recognized';
    var emptyP = el('p');
    emptyP.textContent = 'Every file in your repository has a handler. Nothing unrecognized.';
    empty.appendChild(emptyH3);
    empty.appendChild(emptyP);
    wrapper.appendChild(empty);

    root.appendChild(wrapper);

    /* ── API Fetch ──────────────────────────────────────────────────────── */

    function apiFetch(path) {
      return fetch(path, { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
          return r.json();
        });
    }

    /* ── Load data ──────────────────────────────────────────────────────── */

    function loadData() {
      loadStats();
      loadFiles();
    }

    function loadStats() {
      apiFetch('/api/pipeline/unrecognized/stats')
        .then(function (stats) {
          clear(statsRow);
          var numCats = Object.keys(stats.by_category || {}).length;
          var numJobs = (stats.job_ids || []).length;
          var s = [
            { val: (stats.total || 0).toLocaleString(), lab: 'files' },
            { val: numCats.toLocaleString(), lab: 'categories' },
            { val: numJobs.toLocaleString(), lab: 'jobs' },
          ];
          s.forEach(function (stat) {
            var div = el('div', 'mf-ur__stat');
            var v = el('div', 'mf-ur__stat-val');
            v.textContent = stat.val;
            var l = el('div', 'mf-ur__stat-lab');
            l.textContent = stat.lab;
            div.appendChild(v);
            div.appendChild(l);
            statsRow.appendChild(div);
          });

          /* Populate extension dropdown */
          var exts = Object.keys(stats.by_format || {}).sort();
          while (extSel.options.length > 1) extSel.remove(1);
          exts.forEach(function (ext) {
            var o = el('option');
            o.value = ext;
            o.textContent = ext;
            if (ext === currentExtension) o.selected = true;
            extSel.appendChild(o);
          });

          /* Populate category dropdown */
          var cats = Object.keys(stats.by_category || {}).sort();
          while (catSel.options.length > 1) catSel.remove(1);
          cats.forEach(function (cat) {
            var o = el('option');
            o.value = cat;
            o.textContent = cat.replace(/_/g, ' ');
            if (cat === currentCategory) o.selected = true;
            catSel.appendChild(o);
          });

          /* Populate job dropdown */
          while (jobSel.options.length > 1) jobSel.remove(1);
          (stats.job_ids || []).forEach(function (jid) {
            var o = el('option');
            o.value = jid;
            o.textContent = jid.slice(0, 8) + '…';
            if (jid === currentJob) o.selected = true;
            jobSel.appendChild(o);
          });
        })
        .catch(function (e) {
          console.warn('Failed to load stats:', e);
        });
    }

    function loadFiles() {
      var qs = new URLSearchParams({ page: currentPage, per_page: perPage });
      if (currentExtension) qs.set('source_format', currentExtension);
      if (currentCategory) qs.set('category', currentCategory);
      if (currentJob) qs.set('job_id', currentJob);

      clear(tbody);
      var spinRow = document.createElement('tr');
      var spinTd = document.createElement('td');
      spinTd.colSpan = 5;
      spinTd.style.cssText = 'text-align:center;padding:2rem;';
      spinTd.appendChild(txt('Loading…'));
      spinRow.appendChild(spinTd);
      tbody.appendChild(spinRow);

      apiFetch('/api/pipeline/unrecognized?' + qs.toString())
        .then(function (data) {
          renderTable(data);
          renderPagination(data);
          var hasFiles = data.files && data.files.length > 0;
          tableWrap.style.display = hasFiles ? '' : 'none';
          pagination.style.display = hasFiles ? '' : 'none';
          empty.style.display = !hasFiles && data.total === 0 ? '' : 'none';
        })
        .catch(function (e) {
          clear(tbody);
          var errRow = document.createElement('tr');
          var errTd = document.createElement('td');
          errTd.colSpan = 5;
          errTd.style.cssText = 'text-align:center;padding:2rem;color:var(--mf-color-error);';
          errTd.textContent = 'Failed to load files: ' + e.message;
          errRow.appendChild(errTd);
          tbody.appendChild(errRow);
        });
    }

    function renderTable(data) {
      clear(tbody);
      if (!data.files || !data.files.length) return;
      data.files.forEach(function (f) {
        var tr = document.createElement('tr');

        /* Path */
        var tdPath = document.createElement('td');
        tdPath.className = 'path';
        var path = f.source_path || '';
        var display = path.length > 60 ? '…/' + path.slice(-57) : path;
        tdPath.textContent = display;
        tdPath.title = path;
        tr.appendChild(tdPath);

        /* Extension */
        var tdExt = document.createElement('td');
        var badge = el('span', 'mf-ur__ext-badge');
        badge.textContent = (f.file_ext || '').toUpperCase();
        tdExt.appendChild(badge);
        tr.appendChild(tdExt);

        /* Category */
        var tdCat = document.createElement('td');
        tdCat.textContent = (f.file_category || 'unknown').replace(/_/g, ' ');
        tr.appendChild(tdCat);

        /* Size */
        var tdSize = document.createElement('td');
        tdSize.textContent = fmtBytes(f.file_size_bytes || 0);
        tr.appendChild(tdSize);

        /* Job */
        var tdJob = document.createElement('td');
        tdJob.style.fontFamily = 'ui-monospace,monospace';
        tdJob.style.fontSize = '0.8rem';
        tdJob.textContent = (f.job_id || '').slice(0, 8);
        tr.appendChild(tdJob);

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
      prevBtn.addEventListener('click', function () { currentPage--; loadFiles(); });
      pagingBtns.appendChild(prevBtn);

      var pageSpan = el('span');
      pageSpan.style.cssText = 'margin:0 0.3rem;';
      pageSpan.textContent = data.page + ' / ' + data.pages;
      pagingBtns.appendChild(pageSpan);

      var nextBtn = el('button');
      nextBtn.textContent = '→';
      nextBtn.disabled = data.page >= data.pages;
      nextBtn.addEventListener('click', function () { currentPage++; loadFiles(); });
      pagingBtns.appendChild(nextBtn);
    }

    /* ── Event listeners ────────────────────────────────────────────────── */

    extSel.addEventListener('change', function () {
      currentExtension = extSel.value;
      currentPage = 1;
      loadFiles();
    });

    catSel.addEventListener('change', function () {
      currentCategory = catSel.value;
      currentPage = 1;
      loadFiles();
    });

    jobSel.addEventListener('change', function () {
      currentJob = jobSel.value;
      currentPage = 1;
      loadFiles();
    });

    /* ── Initial load ─────────────────────────────────────────────────────── */
    loadData();

    /* Auto-refresh every 60 seconds */
    var pollTimer = setInterval(function () {
      if (document.hidden) return;
      loadData();
    }, 60000);

    /* ── Return handle ────────────────────────────────────────────────────── */
    return {
      refresh: loadData,
      destroy: function () { clearInterval(pollTimer); },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */

  global.MFUnrecognized = { mount: mount };

})(window);
