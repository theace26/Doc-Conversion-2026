/**
 * active-jobs-panel.js
 * Slide-in panel showing all active jobs with real-time progress.
 * Included on all pages alongside global-status-bar.js.
 * Defines window.openActiveJobsPanel() which the status bar calls.
 */

(function () {
  // Inject panel markup
  var panel = document.createElement('div');
  panel.id = 'ajp-panel';
  panel.className = 'ajp-panel ajp-hidden';
  panel.setAttribute('role', 'dialog');
  panel.innerHTML =
    '<div class="ajp-header">' +
      '<h2>Active Jobs</h2>' +
      '<div class="ajp-header-actions">' +
        '<button class="ajp-stop-all-btn" id="ajp-stop-all">STOP ALL</button>' +
        '<button class="ajp-close-btn" id="ajp-close">\u2715</button>' +
      '</div>' +
    '</div>' +
    '<div class="ajp-body" id="ajp-body">' +
      '<p class="ajp-empty">No active jobs.</p>' +
    '</div>';

  var backdrop = document.createElement('div');
  backdrop.id = 'ajp-backdrop';
  backdrop.className = 'ajp-backdrop ajp-hidden';

  document.body.appendChild(backdrop);
  document.body.appendChild(panel);

  var refreshTimer = null;

  // Public API
  window.openActiveJobsPanel = function (initialData) {
    panel.classList.remove('ajp-hidden');
    backdrop.classList.remove('ajp-hidden');
    document.body.style.overflow = 'hidden';
    if (initialData) renderPanel(initialData);
    startRefresh();
  };

  function closePanel() {
    panel.classList.add('ajp-hidden');
    backdrop.classList.add('ajp-hidden');
    document.body.style.overflow = '';
    clearInterval(refreshTimer);
  }

  document.getElementById('ajp-close').addEventListener('click', closePanel);
  backdrop.addEventListener('click', closePanel);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePanel(); });

  document.getElementById('ajp-stop-all').addEventListener('click', async function () {
    if (!confirm('Stop ALL running jobs? This cannot be undone.')) return;
    await fetch('/api/admin/stop-all', { method: 'POST' });
    refresh();
  });

  async function refresh() {
    try {
      var res = await fetch('/api/admin/active-jobs');
      if (!res.ok) return;
      renderPanel(await res.json());
    } catch (e) { /* ignore */ }
  }

  function startRefresh() {
    clearInterval(refreshTimer);
    refreshTimer = setInterval(refresh, 2000);
    refresh();
  }

  function renderPanel(data) {
    var body = document.getElementById('ajp-body');
    var stop = document.getElementById('ajp-stop-all');
    stop.disabled = data.stop_requested;

    var sections = [];

    (data.bulk_jobs || []).forEach(function (job) {
      sections.push(renderBulkJob(job, data.stop_requested));
    });

    if (data.lifecycle_scan) {
      var ls = renderLifecycleScan(data.lifecycle_scan);
      if (ls) sections.push(ls);
    }

    if (!sections.length) {
      body.innerHTML = '<p class="ajp-empty">No active jobs.</p>';
      return;
    }

    body.innerHTML = sections.join('');

    body.querySelectorAll('[data-stop-job]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        var jobId = btn.dataset.stopJob;
        if (!confirm('Stop job ' + jobId.slice(0, 8) + '\u2026?')) return;
        btn.disabled = true;
        await fetch('/api/bulk/jobs/' + jobId + '/cancel', { method: 'POST' });
        refresh();
      });
    });
  }

  function renderBulkJob(job, stopRequested) {
    var isActive = ['scanning', 'running'].indexOf(job.status) !== -1;
    var pct = job.total_files ? Math.round(job.converted / job.total_files * 100) : null;
    var pctStr = pct != null ? pct + '%' : '?%';

    var activeWorkers = (job.current_files || []).map(function (w) {
      return '<div class="ajp-worker-row">' +
        '<span class="ajp-worker-id">W' + w.worker_id + '</span>' +
        '<span class="ajp-worker-file" title="' + escHtml(w.filename) + '">' + _truncPath(w.filename, 55) + '</span>' +
        '</div>';
    }).join('');

    var dirTree = buildDirSummary(job);
    var optsHtml = job.options ? renderOptions(job.options) : '';

    return '<div class="ajp-job-card ' + (isActive ? 'ajp-job-active' : '') + '">' +
      '<div class="ajp-job-header">' +
        '<div>' +
          '<span class="ajp-job-status ajp-status-' + job.status + '">' + job.status.toUpperCase() + '</span>' +
          '<span class="ajp-job-id">' + job.job_id.slice(0, 8) + '\u2026</span>' +
        '</div>' +
        (isActive && !stopRequested
          ? '<button class="ajp-stop-job-btn" data-stop-job="' + job.job_id + '">Stop</button>'
          : '') +
      '</div>' +
      '<div class="ajp-job-paths">' +
        '<div><span class="ajp-label">Source</span><span class="ajp-mono">' + escHtml(job.source_path) + '</span></div>' +
        '<div><span class="ajp-label">Output</span><span class="ajp-mono">' + escHtml(job.output_path) + '</span></div>' +
      '</div>' +
      '<div class="ajp-progress-row">' +
        '<div class="ajp-progress-track"><div class="ajp-progress-fill" style="width:' + (pct || 0) + '%"></div></div>' +
        '<span class="ajp-progress-label">' +
          job.converted.toLocaleString() + ' converted' +
          (job.total_files ? ' / ' + job.total_files.toLocaleString() + ' total' : '') +
          ' \u2014 ' + pctStr +
        '</span>' +
      '</div>' +
      '<div class="ajp-counters">' +
        '<span class="ajp-counter">\u2713 ' + job.converted.toLocaleString() + ' converted</span>' +
        '<span class="ajp-counter ajp-err">\u2717 ' + job.failed.toLocaleString() + ' failed</span>' +
        '<span class="ajp-counter ajp-skip">\u23ed ' + job.skipped.toLocaleString() + ' skipped</span>' +
      '</div>' +
      optsHtml +
      (activeWorkers
        ? '<details class="ajp-workers-detail" open>' +
            '<summary>Active Workers (' + (job.current_files ? job.current_files.length : 0) + ')</summary>' +
            '<div class="ajp-workers-list">' + activeWorkers + '</div>' +
          '</details>'
        : '') +
      (dirTree
        ? '<details class="ajp-dir-detail">' +
            '<summary>Directory Progress</summary>' +
            '<div class="ajp-dir-tree">' + dirTree + '</div>' +
          '</details>'
        : '') +
    '</div>';
  }

  function renderLifecycleScan(ls) {
    if (!ls.running && !ls.last_scan_at) return null;
    var pct = ls.pct != null ? ls.pct + '%' : '?%';
    var eta = ls.eta_seconds != null ? ' \u2014 ~' + fmtDuration(ls.eta_seconds) + ' remaining' : '';

    if (ls.running) {
      return '<div class="ajp-job-card ajp-job-active">' +
        '<div class="ajp-job-header">' +
          '<span class="ajp-job-status ajp-status-running">LIFECYCLE SCAN</span>' +
        '</div>' +
        '<div class="ajp-progress-row">' +
          '<div class="ajp-progress-track"><div class="ajp-progress-fill" style="width:' + (ls.pct || 0) + '%"></div></div>' +
          '<span class="ajp-progress-label">' +
            (ls.scanned || 0).toLocaleString() + ' files scanned' +
            (ls.total ? ' / ' + ls.total.toLocaleString() + ' total' : '') +
            ' \u2014 ' + pct + eta +
          '</span>' +
        '</div>' +
        (ls.current_file
          ? '<div class="ajp-current-file"><span class="ajp-label">Current</span>' +
            '<span class="ajp-mono">' + escHtml(_truncPath(ls.current_file, 70)) + '</span></div>'
          : '') +
      '</div>';
    }

    return '<div class="ajp-job-card">' +
      '<div class="ajp-job-header">' +
        '<span class="ajp-job-status ajp-status-done">LAST LIFECYCLE SCAN</span>' +
      '</div>' +
      '<div class="ajp-job-paths">' +
        '<div><span class="ajp-label">Last run</span>' +
        '<span>' + (ls.last_scan_at ? _fmtRelative(ls.last_scan_at) : 'unknown') + '</span></div>' +
      '</div>' +
    '</div>';
  }

  function renderOptions(opts) {
    var rows = Object.keys(opts)
      .filter(function (k) { return opts[k] != null; })
      .map(function (k) {
        return '<span class="ajp-opt"><span class="ajp-opt-key">' + k.replace(/_/g, ' ') + '</span>: ' + opts[k] + '</span>';
      });
    return rows.length ? '<div class="ajp-options">' + rows.join('') + '</div>' : '';
  }

  function buildDirSummary(job) {
    if (!job.dir_stats || !Object.keys(job.dir_stats).length) return null;
    return Object.keys(job.dir_stats).map(function (dir) {
      var s = job.dir_stats[dir];
      return '<div class="ajp-dir-row">' +
        '<span class="ajp-dir-name">' + escHtml(dir) + '/</span>' +
        '<span class="ajp-dir-counts">' +
          '<span class="ajp-ok">\u2713' + (s.converted || 0) + '</span>' +
          (s.failed ? '<span class="ajp-err">\u2717' + s.failed + '</span>' : '') +
          (s.pending ? '<span class="ajp-muted">' + s.pending + ' pending</span>' : '') +
        '</span>' +
      '</div>';
    }).join('');
  }

  // Helpers
  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fmtDuration(s) {
    if (s < 60)   return s + 's';
    if (s < 3600) return Math.round(s / 60) + 'm';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return m ? h + 'h ' + m + 'm' : h + 'h';
  }

  function _truncPath(p, maxLen) {
    if (!p || p.length <= maxLen) return p || '';
    var parts = p.split('/');
    var fname = parts.pop();
    while (parts.length && (parts.join('/') + '/\u2026/' + fname).length > maxLen) parts.shift();
    return '\u2026/' + (parts.length ? parts.join('/') + '/' : '') + fname;
  }

  function _fmtRelative(iso) {
    if (!iso) return 'unknown';
    var diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60)    return diff + 's ago';
    if (diff < 3600)  return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  // Expose helpers globally as fallbacks
  if (!window.truncatePath) window.truncatePath = _truncPath;
  if (!window.formatRelativeTime) window.formatRelativeTime = _fmtRelative;
})();
