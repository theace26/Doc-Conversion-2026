/**
 * global-status-bar.js
 * Injected into every page. Polls /api/admin/active-jobs every 5s.
 * Shows a persistent bar at the bottom when jobs are running.
 * Opens the Active Jobs panel when clicked.
 */

(function () {
  // Inject bar markup into body
  var bar = document.createElement('div');
  bar.id = 'global-status-bar';
  bar.className = 'gsb hidden';
  bar.innerHTML =
    '<div class="gsb-inner" id="gsb-inner">' +
      '<span class="gsb-indicator" id="gsb-indicator"></span>' +
      '<span class="gsb-text" id="gsb-text">No active jobs</span>' +
      '<span class="gsb-detail" id="gsb-detail"></span>' +
      '<div class="gsb-actions">' +
        '<button class="gsb-btn gsb-btn-view" id="gsb-view-btn">View Jobs</button>' +
        '<button class="gsb-btn gsb-btn-stop" id="gsb-stop-btn">STOP ALL</button>' +
      '</div>' +
    '</div>' +
    '<div class="gsb-stop-banner hidden" id="gsb-stop-banner">' +
      '\u26a0 Stop requested \u2014 jobs are winding down. ' +
      '<button class="gsb-link-btn" id="gsb-reset-btn">Reset &amp; allow new jobs</button>' +
    '</div>';
  document.body.appendChild(bar);

  var elText    = document.getElementById('gsb-text');
  var elDetail  = document.getElementById('gsb-detail');
  var elInd     = document.getElementById('gsb-indicator');
  var elStop    = document.getElementById('gsb-stop-btn');
  var elView    = document.getElementById('gsb-view-btn');
  var elBanner  = document.getElementById('gsb-stop-banner');
  var elReset   = document.getElementById('gsb-reset-btn');

  var pollTimer = null;
  var lastState = null;

  async function poll() {
    try {
      var res = await fetch('/api/admin/active-jobs');
      if (res.status === 401 || res.status === 403) return;
      var data = await res.json();
      lastState = data;
      render(data);
    } catch (e) { /* ignore */ }
  }

  function render(data) {
    var running = data.running_count > 0;
    var stopped = data.stop_requested;

    bar.classList.toggle('hidden',      !running && !stopped);
    bar.classList.toggle('gsb-running', running && !stopped);
    bar.classList.toggle('gsb-stopped', stopped);

    elBanner.classList.toggle('hidden', !stopped);
    elStop.disabled = stopped;

    if (stopped) {
      elInd.textContent  = '\u25fc';
      elText.textContent = 'Stop requested \u2014 finishing current files';
      elDetail.textContent = '';
      return;
    }

    if (!running) {
      bar.classList.add('hidden');
      return;
    }

    elInd.textContent = '\u27f3';

    var jobParts = [];
    (data.bulk_jobs || []).filter(function (j) {
      return ['scanning', 'running', 'paused'].indexOf(j.status) !== -1;
    }).forEach(function (j) {
      var pct = j.total_files ? Math.round(j.converted / j.total_files * 100) : null;
      jobParts.push('Bulk: ' + j.converted.toLocaleString() + (pct != null ? ' (' + pct + '%)' : '') + ' files');
    });
    if (data.lifecycle_scan && data.lifecycle_scan.running) {
      var ls = data.lifecycle_scan;
      var lsPct = ls.pct != null ? ' (' + ls.pct + '%)' : '';
      jobParts.push('Lifecycle scan: ' + (ls.scanned || 0).toLocaleString() + ' files' + lsPct);
    }

    elText.textContent   = data.running_count + ' job' + (data.running_count !== 1 ? 's' : '') + ' running';
    elDetail.textContent = jobParts.join(' \u00b7 ');
  }

  // STOP ALL
  elStop.addEventListener('click', async function () {
    if (!confirm('Hard stop all running jobs? Workers will finish their current file and exit.')) return;
    elStop.disabled = true;
    await fetch('/api/admin/stop-all', { method: 'POST' });
    poll();
  });

  // Reset stop flag
  elReset.addEventListener('click', async function () {
    await fetch('/api/admin/reset-stop', { method: 'POST' });
    poll();
  });

  // View Jobs
  elView.addEventListener('click', function () {
    if (typeof window.openActiveJobsPanel === 'function') {
      window.openActiveJobsPanel(lastState);
    }
  });

  // Polling - 5s active, 30s when tab hidden
  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, document.hidden ? 30000 : 5000);
  }
  document.addEventListener('visibilitychange', startPolling);
  poll();
  startPolling();
})();
