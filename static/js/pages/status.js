/* Active Jobs / Status page component (new-UX).
 *
 * Usage:
 *   MFStatus.mount(root, { role });
 *
 * Polls /api/admin/active-jobs every 5s (3s when visible, 30s when hidden).
 * Also polls /api/pipeline/stats every 30s for the pipeline pill strip.
 * Auto-conversion status polled every 15s.
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

  function fmtNum(n) { return n == null ? '?' : Number(n).toLocaleString(); }

  function fmtDur(s) {
    if (s == null || isNaN(s)) return '';
    s = Math.round(s);
    if (s < 60) return s + 's';
    if (s < 3600) return Math.round(s / 60) + 'm';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return m ? h + 'h ' + m + 'm' : h + 'h';
  }

  function formatRelative(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      var diff = (Date.now() - d) / 1000;
      if (diff < 60) return Math.floor(diff) + 's ago';
      if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
      if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
      return d.toLocaleDateString();
    } catch (e) { return ''; }
  }

  /* ── API endpoints ────────────────────────────────────────────────────── */

  var API_ACTIVE_JOBS    = '/api/admin/active-jobs';
  var API_PIPELINE_STATS = '/api/pipeline/stats';
  var API_STOP_ALL       = '/api/admin/stop-all';
  var API_RESET_STOP     = '/api/admin/reset-stop';
  var API_AUTO_CONVERT   = '/api/auto-convert/status';
  var API_AUTO_OVERRIDE  = '/api/auto-convert/override';
  var API_HEALTH         = '/api/health';
  var API_BULK_JOB_PAUSE  = function (id) { return '/api/bulk/jobs/' + encodeURIComponent(id) + '/pause'; };
  var API_BULK_JOB_RESUME = function (id) { return '/api/bulk/jobs/' + encodeURIComponent(id) + '/resume'; };
  var API_BULK_JOB_CANCEL = function (id) { return '/api/bulk/jobs/' + encodeURIComponent(id) + '/cancel'; };
  var API_BULK_JOB_FILES  = function (id, status, page) {
    return '/api/bulk/jobs/' + encodeURIComponent(id) + '/files?status=' + encodeURIComponent(status) + '&page=' + page + '&per_page=50';
  };

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFStatus.mount: root element is required');

    /* State */
    var pollTimer         = null;
    var statsTimer        = null;
    var acTimer           = null;
    var lastData          = null;
    var _flpPanelsByJob   = {};   /* jobId → { status, page, total, lastCount } */

    /* ── Skeleton ─────────────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-page-wrapper');

    /* ── Stop banner ──────────────────────────────────────────────────────── */
    var stopBanner = el('div', 'mf-status__stop-banner');
    stopBanner.style.display = 'none';
    var stopBannerText = el('span');
    stopBannerText.textContent = 'Stop requested — jobs are winding down.';
    var resetStopBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    resetStopBtn.textContent = 'Reset & allow new jobs';
    stopBanner.appendChild(stopBannerText);
    stopBanner.appendChild(resetStopBtn);
    wrapper.appendChild(stopBanner);

    /* ── Page header ──────────────────────────────────────────────────────── */
    var header = el('div', 'mf-page-header');
    var headingGroup = el('div');
    var heading = el('h1', 'mf-page-title');
    heading.textContent = 'Active Jobs';
    var subtitle = el('p', 'mf-page-subtitle');
    subtitle.textContent = 'Loading…';
    headingGroup.appendChild(heading);
    headingGroup.appendChild(subtitle);

    var actionsBar = el('div', 'mf-page-header__actions');
    var stopAllBtn = el('button', 'mf-btn mf-btn--danger');
    stopAllBtn.textContent = 'Stop All Jobs';
    actionsBar.appendChild(stopAllBtn);

    header.appendChild(headingGroup);
    header.appendChild(actionsBar);
    wrapper.appendChild(header);

    /* ── Pipeline stat strip ──────────────────────────────────────────────── */
    var statStrip = el('div', 'mf-status__stat-strip');
    var statLabel = el('span', 'mf-status__stat-label');
    statLabel.textContent = 'Pipeline';
    statStrip.appendChild(statLabel);

    var STAT_PILLS = [
      { id: 'ps-scanned',    href: '/pipeline-files.html?status=scanned',           cls: '',                        label: 'scanned' },
      { id: 'ps-pending',    href: '/pipeline-files.html?status=pending',            cls: '',                        label: 'pending' },
      { id: 'ps-failed',     href: '/pipeline-files.html?status=failed',             cls: 'mf-status__pill--failed', label: 'failed' },
      { id: 'ps-unrecog',    href: '/pipeline-files.html?status=unrecognized',       cls: '',                        label: 'unrecognized' },
      { id: 'ps-panalysis',  href: '/pipeline-files.html?status=pending_analysis',  cls: 'mf-status__pill--warn',   label: 'pending analysis' },
      { id: 'ps-batched',    href: '/batch-management.html',                         cls: 'mf-status__pill--accent', label: 'batched' },
      { id: 'ps-afailed',    href: '/pipeline-files.html?status=analysis_failed',   cls: 'mf-status__pill--failed', label: 'analysis failed' },
      { id: 'ps-indexed',    href: '/pipeline-files.html?status=indexed',            cls: 'mf-status__pill--good',   label: 'indexed' },
    ];

    var pillEls = {};
    STAT_PILLS.forEach(function (def) {
      var a = el('a', 'mf-status__pill' + (def.cls ? ' ' + def.cls : ''));
      a.href = def.href;
      a.textContent = '— ' + def.label;
      statStrip.appendChild(a);
      pillEls[def.id] = a;
    });
    wrapper.appendChild(statStrip);

    /* ── Jobs container ───────────────────────────────────────────────────── */
    var jobsContainer = el('div', 'mf-status__jobs');
    wrapper.appendChild(jobsContainer);

    /* ── Auto-Conversion card ─────────────────────────────────────────────── */
    var acCard = el('div', 'mf-card mf-status__ac-card');
    var acCardHead = el('div', 'mf-card__header');
    var acCardTitle = el('div', 'mf-card__title');
    var acPill = el('span', 'mf-badge mf-badge--success');
    acPill.textContent = 'AUTO-CONVERSION';
    var acModeLabel = el('span', 'mf-text--muted mf-text--sm');
    acModeLabel.textContent = 'Loading…';
    acCardTitle.appendChild(acPill);
    acCardTitle.appendChild(acModeLabel);
    acCardHead.appendChild(acCardTitle);
    acCard.appendChild(acCardHead);

    var acControls = el('div', 'mf-status__ac-controls');
    var acModeLabel2 = el('label', 'mf-text--sm');
    acModeLabel2.textContent = 'Mode override:';
    var acSelect = el('select', 'mf-select mf-select--sm');
    [
      { value: '', label: 'Use setting (no override)' },
      { value: 'off', label: 'Off' },
      { value: 'immediate', label: 'Immediate' },
      { value: 'queued', label: 'Queued' },
      { value: 'scheduled', label: 'Scheduled' },
    ].forEach(function (opt) {
      var o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      acSelect.appendChild(o);
    });
    var acDuration = el('select', 'mf-select mf-select--sm');
    [
      { value: '30', label: '30 min' },
      { value: '60', label: '1 hour', selected: true },
      { value: '120', label: '2 hours' },
      { value: '240', label: '4 hours' },
      { value: '480', label: '8 hours' },
    ].forEach(function (opt) {
      var o = document.createElement('option');
      o.value = opt.value;
      if (opt.selected) o.selected = true;
      o.textContent = opt.label;
      acDuration.appendChild(o);
    });
    var acApplyBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    acApplyBtn.textContent = 'Apply';
    var acClearBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    acClearBtn.textContent = 'Clear Override';
    acClearBtn.style.display = 'none';

    acControls.appendChild(acModeLabel2);
    acControls.appendChild(acSelect);
    acControls.appendChild(acDuration);
    acControls.appendChild(acApplyBtn);
    acControls.appendChild(acClearBtn);
    acCard.appendChild(acControls);

    var acLastDecision = el('div', 'mf-text--sm mf-text--muted');
    acCard.appendChild(acLastDecision);
    wrapper.appendChild(acCard);

    /* ── Health card ──────────────────────────────────────────────────────── */
    var healthCard = el('div', 'mf-card mf-status__health-card');
    var healthHead = el('div', 'mf-card__header');
    var healthTitle = el('div', 'mf-card__title');
    var healthPill = el('span', 'mf-badge mf-badge--success');
    healthPill.textContent = 'SYSTEM';
    var healthSubLabel = el('span', 'mf-text--muted mf-text--sm');
    healthSubLabel.textContent = 'Health Check';
    healthTitle.appendChild(healthPill);
    healthTitle.appendChild(healthSubLabel);
    healthHead.appendChild(healthTitle);
    healthCard.appendChild(healthHead);
    var healthStatus = el('div', 'mf-status__health-body');
    var healthSpinner = el('span', 'mf-spinner');
    healthStatus.appendChild(healthSpinner);
    healthStatus.appendChild(txt(' Checking…'));
    healthCard.appendChild(healthStatus);
    wrapper.appendChild(healthCard);

    root.appendChild(wrapper);

    /* ── Styles (page-scoped, injected once) ─────────────────────────────── */
    if (!document.getElementById('mf-status-styles')) {
      var style = document.createElement('style');
      style.id = 'mf-status-styles';
      style.textContent = [
        '.mf-status__stop-banner{display:none;align-items:center;gap:1rem;padding:0.75rem 1rem;',
        'background:rgba(220,38,38,0.1);border:1px solid rgba(220,38,38,0.3);',
        'border-radius:var(--mf-radius,8px);margin-bottom:1rem;',
        'color:var(--mf-color-error,#dc2626);}',
        '.mf-page-wrapper{max-width:960px;margin:0 auto;padding:1.5rem 1rem;}',
        '.mf-page-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;}',
        '.mf-page-title{margin:0 0 0.25rem 0;font-size:1.6rem;font-weight:700;}',
        '.mf-page-subtitle{margin:0;color:var(--mf-color-text-muted,#888);font-size:0.9rem;}',
        '.mf-page-header__actions{display:flex;gap:0.5rem;align-items:center;}',
        '.mf-status__stat-strip{display:flex;flex-wrap:wrap;gap:0.4rem;align-items:center;',
        'padding:0.65rem 0.9rem;background:var(--mf-surface-soft,rgba(0,0,0,0.04));',
        'border-radius:var(--mf-radius,8px);margin-bottom:1rem;}',
        '.mf-status__stat-label{font-size:0.7rem;font-weight:700;text-transform:uppercase;',
        'letter-spacing:.06em;color:var(--mf-color-text-muted,#888);margin-right:0.25rem;}',
        '.mf-status__pill{display:inline-block;padding:0.2em 0.6em;border-radius:1em;font-size:0.78rem;',
        'font-weight:600;text-decoration:none;color:var(--mf-color-text,#111);',
        'background:var(--mf-surface-alt,rgba(0,0,0,0.06));transition:opacity .15s;}',
        '.mf-status__pill:hover{opacity:0.7;text-decoration:underline;}',
        '.mf-status__pill--failed{color:var(--mf-color-error,#dc2626);',
        'background:rgba(220,38,38,0.1);}',
        '.mf-status__pill--warn{color:var(--mf-color-warn,#d97706);',
        'background:rgba(217,119,6,0.1);}',
        '.mf-status__pill--accent{color:var(--mf-color-accent,#4f5bd5);',
        'background:rgba(79,91,213,0.1);}',
        '.mf-status__pill--good{color:var(--mf-color-success,#16a34a);',
        'background:rgba(22,163,74,0.1);}',
        '.mf-status__jobs{display:flex;flex-direction:column;gap:1rem;margin-bottom:1.25rem;}',
        '.mf-card{background:var(--mf-surface,#fff);border:1px solid var(--mf-border,rgba(0,0,0,0.1));',
        'border-radius:var(--mf-radius,8px);padding:1rem;}',
        '.mf-card--active{border-color:var(--mf-color-accent,#4f5bd5);',
        'border-left:4px solid var(--mf-color-accent,#4f5bd5);}',
        '.mf-card__header{display:flex;justify-content:space-between;align-items:flex-start;}',
        '.mf-card__title{display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;}',
        '.mf-badge{display:inline-block;padding:0.15em 0.5em;border-radius:0.3em;font-size:0.72rem;',
        'font-weight:700;text-transform:uppercase;letter-spacing:.04em;}',
        '.mf-badge--success{background:rgba(22,163,74,0.1);color:var(--mf-color-success,#16a34a);}',
        '.mf-badge--running{background:rgba(79,91,213,0.12);color:var(--mf-color-accent,#4f5bd5);}',
        '.mf-badge--scanning{background:rgba(217,119,6,0.1);color:var(--mf-color-warn,#d97706);}',
        '.mf-badge--paused{background:rgba(0,0,0,0.06);color:var(--mf-color-text-muted,#888);}',
        '.mf-badge--failed{background:rgba(220,38,38,0.1);color:var(--mf-color-error,#dc2626);}',
        '.mf-badge--link{text-decoration:none;cursor:pointer;}',
        '.mf-badge--link:hover{opacity:0.75;}',
        '.mf-text--muted{color:var(--mf-color-text-muted,#888);}',
        '.mf-text--sm{font-size:0.84rem;}',
        '.mf-text--xs{font-size:0.76rem;}',
        '.mf-mono{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:0.82rem;}',
        '.mf-status__job-path{color:var(--mf-color-text-muted,#888);font-size:0.8rem;',
        'margin-top:0.2rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
        '.mf-status__job-open-link{font-size:0.78rem;color:var(--mf-color-accent,#4f5bd5);',
        'text-decoration:none;margin-left:0.25rem;}',
        '.mf-status__job-open-link:hover{text-decoration:underline;}',
        '.mf-card__actions{display:flex;gap:0.4rem;flex-shrink:0;}',
        '.mf-status__progress-link{display:block;text-decoration:none;color:inherit;margin-top:0.6rem;}',
        '.mf-status__progress-link:hover .mf-status__prog-bar{opacity:0.85;}',
        '.mf-status__prog-bar{height:6px;background:var(--mf-surface-alt,rgba(0,0,0,0.07));',
        'border-radius:3px;overflow:hidden;margin-bottom:0.3rem;}',
        '.mf-status__prog-fill{height:100%;border-radius:3px;',
        'background:var(--mf-color-accent,#4f5bd5);transition:width .4s;}',
        '.mf-status__prog-bar--indet .mf-status__prog-fill{width:40%;animation:mf-indet 1.6s ease-in-out infinite;}',
        '@keyframes mf-indet{0%{transform:translateX(-100%)}100%{transform:translateX(280%)}}',
        '.mf-status__prog-text{font-size:0.8rem;color:var(--mf-color-text-muted,#888);}',
        '.mf-status__counts{display:flex;gap:1rem;margin-top:0.5rem;font-size:0.82rem;}',
        '.mf-status__count--ok{color:var(--mf-color-success,#16a34a);}',
        '.mf-status__count--err{color:var(--mf-color-error,#dc2626);}',
        '.mf-status__count--skip{color:var(--mf-color-text-muted,#888);}',
        '.mf-status__count-btn{background:none;border:none;cursor:pointer;',
        'padding:0;font-size:inherit;color:inherit;transition:opacity .15s;}',
        '.mf-status__count-btn:hover{opacity:0.7;text-decoration:underline;}',
        '.mf-status__workers{margin-top:0.5rem;display:flex;flex-direction:column;gap:0.2rem;}',
        '.mf-status__worker-row{display:flex;gap:0.6rem;font-size:0.8rem;}',
        '.mf-status__worker-id{color:var(--mf-color-text-muted,#888);min-width:5em;}',
        '.mf-status__dir-details{margin-top:0.5rem;font-size:0.82rem;}',
        '.mf-status__dir-details summary{cursor:pointer;color:var(--mf-color-text-muted,#888);}',
        '.mf-status__dir-list{margin-top:0.4rem;display:flex;flex-direction:column;gap:0.2rem;padding-left:0.5rem;}',
        '.mf-status__dir-row{display:flex;justify-content:space-between;gap:0.5rem;}',
        '.mf-status__dir-counts{display:flex;gap:0.5rem;}',
        '.mf-status__empty{text-align:center;padding:2.5rem 1rem;color:var(--mf-color-text-muted,#888);}',
        '.mf-status__ac-card{margin-bottom:1rem;}',
        '.mf-status__ac-controls{display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap;margin-top:0.6rem;}',
        '.mf-select{padding:0.3em 0.5em;border:1px solid var(--mf-border,rgba(0,0,0,0.15));',
        'border-radius:var(--mf-radius-sm,4px);background:var(--mf-surface,#fff);',
        'color:var(--mf-color-text,#111);font-size:0.84rem;}',
        '.mf-select--sm{font-size:0.8rem;padding:0.25em 0.4em;}',
        '.mf-status__health-card{margin-bottom:1rem;}',
        '.mf-status__health-body{margin-top:0.5rem;}',
        '.mf-health-table{width:100%;border-collapse:collapse;font-size:0.84rem;}',
        '.mf-health-table td{padding:0.3rem 0.5rem;border-bottom:1px solid var(--mf-border,rgba(0,0,0,0.08));}',
        '.mf-health-table tr:last-child td{border-bottom:none;}',
        '.mf-status-ok{color:var(--mf-color-success,#16a34a);font-weight:600;}',
        '.mf-status-err{color:var(--mf-color-error,#dc2626);font-weight:600;}',
        /* File list panel */
        '.mf-flp{overflow:hidden;max-height:0;opacity:0;transition:max-height .35s ease,opacity .25s ease,margin .25s ease;margin-top:0;}',
        '.mf-flp.open{max-height:600px;opacity:1;margin-top:0.75rem;}',
        '.mf-flp__header{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;}',
        '.mf-flp__title{font-weight:600;font-size:0.82rem;text-transform:uppercase;}',
        '.mf-flp__close{background:none;border:none;cursor:pointer;color:var(--mf-color-text-muted,#888);',
        'font-size:1.1rem;padding:0.15rem 0.35rem;line-height:1;}',
        '.mf-flp__close:hover{color:var(--mf-color-text,#111);}',
        '.mf-flp__scroll{max-height:380px;overflow-y:auto;}',
        '.mf-flp__table{width:100%;border-collapse:collapse;font-size:0.8rem;}',
        '.mf-flp__table th{text-align:left;padding:0.3rem 0.5rem;',
        'border-bottom:2px solid var(--mf-border,rgba(0,0,0,0.12));',
        'font-weight:600;font-size:0.72rem;text-transform:uppercase;',
        'color:var(--mf-color-text-muted,#888);}',
        '.mf-flp__table td{padding:0.25rem 0.5rem;',
        'border-bottom:1px solid var(--mf-border,rgba(0,0,0,0.06));vertical-align:top;}',
        '.mf-flp__table tr:last-child td{border-bottom:none;}',
        '.mf-flp__fname{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
        '.mf-flp__path{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
        'color:var(--mf-color-text-muted,#888);font-size:0.76rem;}',
        '.mf-flp__err{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
        'color:var(--mf-color-error,#dc2626);font-size:0.76rem;}',
        '.mf-flp__size{white-space:nowrap;color:var(--mf-color-text-muted,#888);}',
        '.mf-flp__load-more{display:block;width:100%;margin-top:0.4rem;padding:0.35rem;text-align:center;',
        'background:var(--mf-surface-alt,rgba(0,0,0,0.05));border:1px solid var(--mf-border,rgba(0,0,0,0.1));',
        'border-radius:var(--mf-radius-sm,4px);cursor:pointer;font-size:0.8rem;',
        'color:var(--mf-color-text-muted,#888);}',
        '.mf-flp__load-more:hover{background:var(--mf-surface,#fff);color:var(--mf-color-text,#111);}',
        /* Confirm cancel inline */
        '.mf-status__confirm{display:flex;gap:0.4rem;align-items:center;font-size:0.82rem;}',
        /* Buttons */
        '.mf-btn{display:inline-flex;align-items:center;gap:0.3rem;padding:0.45em 0.9em;',
        'border-radius:var(--mf-radius-sm,5px);border:1px solid transparent;',
        'font-size:0.84rem;font-weight:500;cursor:pointer;transition:background .15s,opacity .15s;}',
        '.mf-btn--sm{padding:0.3em 0.65em;font-size:0.78rem;}',
        '.mf-btn--ghost{background:transparent;border-color:var(--mf-border,rgba(0,0,0,0.15));',
        'color:var(--mf-color-text,#111);}',
        '.mf-btn--ghost:hover{background:var(--mf-surface-alt,rgba(0,0,0,0.06));}',
        '.mf-btn--primary{background:var(--mf-color-accent,#4f5bd5);border-color:transparent;color:#fff;}',
        '.mf-btn--primary:hover{opacity:0.88;}',
        '.mf-btn--danger{background:var(--mf-color-error,#dc2626);border-color:transparent;color:#fff;}',
        '.mf-btn--danger:hover{opacity:0.88;}',
        '.mf-btn--danger-outline{background:transparent;',
        'border-color:var(--mf-color-error,#dc2626);color:var(--mf-color-error,#dc2626);}',
        '.mf-btn--danger-outline:hover{background:rgba(220,38,38,0.08);}',
        '.mf-btn:disabled{opacity:0.5;cursor:not-allowed;}',
        '.mf-spinner{display:inline-block;width:0.8em;height:0.8em;border-radius:50%;',
        'border:2px solid rgba(0,0,0,0.15);border-top-color:var(--mf-color-accent,#4f5bd5);',
        'animation:mf-spin 0.7s linear infinite;vertical-align:middle;}',
        '@keyframes mf-spin{to{transform:rotate(360deg)}}',
        '.mf-toast{position:fixed;bottom:1.5rem;right:1.5rem;padding:0.65rem 1rem;',
        'border-radius:var(--mf-radius-sm,5px);font-size:0.84rem;color:#fff;z-index:9999;',
        'opacity:0;transform:translateY(6px);transition:opacity .2s,transform .2s;}',
        '.mf-toast--visible{opacity:1;transform:none;}',
        '.mf-toast--info{background:#334155;}',
        '.mf-toast--success{background:var(--mf-color-success,#16a34a);}',
        '.mf-toast--error{background:var(--mf-color-error,#dc2626);}',
      ].join('');
      document.head.appendChild(style);
    }

    /* ── Poll logic ─────────────────────────────────────────────────────── */

    function pollInterval() {
      return document.hidden ? 30000 : 3000;
    }

    function startPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(function () {
        if (!document.hidden) pollJobs();
      }, pollInterval());
    }

    document.addEventListener('visibilitychange', function () {
      startPolling();
      if (!document.hidden) pollJobs();
    });

    function pollJobs() {
      fetch(API_ACTIVE_JOBS, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) { lastData = data; renderAll(data); })
        .catch(function (e) { console.warn('mf-status: active-jobs poll failed', e); });
    }

    function pollStats() {
      fetch(API_PIPELINE_STATS, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          pillEls['ps-scanned'].textContent  = fmtNum(d.scanned) + ' scanned';
          pillEls['ps-pending'].textContent  = fmtNum(d.pending_conversion) + ' pending';
          pillEls['ps-failed'].textContent   = fmtNum(d.failed) + ' failed';
          pillEls['ps-unrecog'].textContent  = fmtNum(d.unrecognized) + ' unrecognized';
          pillEls['ps-panalysis'].textContent = fmtNum(d.pending_analysis) + ' pending analysis';
          pillEls['ps-batched'].textContent  = fmtNum(d.batched_for_analysis) + ' batched';
          pillEls['ps-afailed'].textContent  = fmtNum(d.analysis_failed) + ' analysis failed';
          pillEls['ps-indexed'].textContent  = fmtNum(d.in_search_index) + ' indexed';
        })
        .catch(function (e) { /* non-critical */ });
    }

    /* ── Render jobs ─────────────────────────────────────────────────────── */

    function renderAll(data) {
      stopBanner.style.display = data.stop_requested ? 'flex' : 'none';
      stopAllBtn.disabled = !!data.stop_requested;

      var running = data.running_count || 0;
      subtitle.textContent = running > 0
        ? running + ' job' + (running !== 1 ? 's' : '') + ' running'
        : 'No active jobs';

      var jobs = data.bulk_jobs || [];
      clear(jobsContainer);

      if (!jobs.length) {
        var emptyDiv = el('div', 'mf-status__empty');
        var emptyP = el('p');
        emptyP.textContent = 'No active jobs. Everything is quiet.';
        emptyDiv.appendChild(emptyP);
        jobsContainer.appendChild(emptyDiv);
        return;
      }

      jobs.forEach(function (job) {
        jobsContainer.appendChild(buildJobCard(job));
      });

      restoreOpenPanels();
    }

    function buildJobCard(job) {
      var isActive = job.status === 'running' || job.status === 'scanning';
      var isPaused = job.status === 'paused';
      var enumerating = job.status === 'scanning';
      var pct = job.total_files ? Math.round(job.converted / job.total_files * 100) : 0;
      var bulkUrl = '/bulk.html?job_id=' + encodeURIComponent(job.job_id);

      var card = el('div', 'mf-card' + (isActive ? ' mf-card--active' : ''));

      /* Header row */
      var cardHead = el('div', 'mf-card__header');

      var titleGroup = el('div');
      var titleRow = el('div', 'mf-card__title');

      /* Status badge — links to log viewer */
      var statusLink = el('a', 'mf-badge mf-badge--' + (job.status || 'running') + ' mf-badge--link');
      statusLink.href = '/log-viewer.html?q=' + encodeURIComponent(job.job_id.slice(0, 8)) + '&mode=history';
      statusLink.title = 'Open log viewer filtered to this job ID';
      statusLink.textContent = (job.status || '').toUpperCase();
      titleRow.appendChild(statusLink);

      var idSpan = el('span', 'mf-text--muted mf-text--sm mf-mono');
      idSpan.textContent = job.job_id.slice(0, 8) + '…';
      titleRow.appendChild(idSpan);

      var openLink = el('a', 'mf-status__job-open-link');
      openLink.href = bulkUrl;
      openLink.title = 'Open in Bulk Jobs page';
      openLink.textContent = '↗ Open';
      titleRow.appendChild(openLink);

      titleGroup.appendChild(titleRow);

      var pathDiv = el('div', 'mf-status__job-path');
      pathDiv.title = (job.source_path || '') + ' → ' + (job.output_path || '');
      pathDiv.textContent = (job.display_source_path || job.source_path || '') +
        ' → ' + (job.display_output_path || job.output_path || '');
      titleGroup.appendChild(pathDiv);

      cardHead.appendChild(titleGroup);

      /* Action buttons */
      var actionsDiv = el('div', 'mf-card__actions');
      if (isActive) {
        var pauseBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        pauseBtn.textContent = 'Pause';
        pauseBtn.addEventListener('click', function () {
          pauseBtn.disabled = true;
          fetch(API_BULK_JOB_PAUSE(job.job_id), { method: 'POST', credentials: 'same-origin' })
            .then(function (r) {
              if (!r.ok) throw new Error(r.status);
              showToast('Job paused');
              pollJobs();
            })
            .catch(function () { showToast('Failed to pause', 'error'); pauseBtn.disabled = false; });
        });
        actionsDiv.appendChild(pauseBtn);

        var cancelBtn = buildCancelButton(job.job_id, actionsDiv);
        actionsDiv.appendChild(cancelBtn);
      } else if (isPaused) {
        var resumeBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
        resumeBtn.textContent = 'Resume';
        resumeBtn.addEventListener('click', function () {
          resumeBtn.disabled = true;
          fetch(API_BULK_JOB_RESUME(job.job_id), { method: 'POST', credentials: 'same-origin' })
            .then(function (r) {
              if (!r.ok) throw new Error(r.status);
              showToast('Job resumed');
              pollJobs();
            })
            .catch(function () { showToast('Failed to resume', 'error'); resumeBtn.disabled = false; });
        });
        actionsDiv.appendChild(resumeBtn);
        var cancelBtn2 = buildCancelButton(job.job_id, actionsDiv);
        actionsDiv.appendChild(cancelBtn2);
      }
      cardHead.appendChild(actionsDiv);
      card.appendChild(cardHead);

      /* Progress section */
      var progressLink = el('a', 'mf-status__progress-link');
      progressLink.href = bulkUrl;
      progressLink.title = 'Open in Bulk Jobs page';

      var progBar = el('div', 'mf-status__prog-bar' + (enumerating ? ' mf-status__prog-bar--indet' : ''));
      var progFill = el('div', 'mf-status__prog-fill');
      if (!enumerating) progFill.style.width = pct + '%';
      progBar.appendChild(progFill);
      progressLink.appendChild(progBar);

      var progText = el('div', 'mf-status__prog-text');
      if (enumerating) {
        var sp = job.scan_progress || {};
        var startedAt = job.started_at ? new Date(job.started_at) : null;
        var elapsedSec = startedAt ? Math.round((Date.now() - startedAt.getTime()) / 1000) : 0;
        var stuck = elapsedSec > 120 && !job.last_heartbeat && !sp.scanned;

        if (stuck) {
          var warnSpan = el('span');
          warnSpan.style.color = '#fbbf24';
          warnSpan.textContent = '⚠ Enumerating — stuck? No progress for ' + fmtDur(elapsedSec) + '. Stop the job and retry.';
          progText.appendChild(warnSpan);
        } else if (sp.scanned > 0) {
          var countStr = sp.total > 0
            ? fmtNum(sp.scanned) + ' / ' + fmtNum(sp.total) + ' files scanned'
            : fmtNum(sp.scanned) + ' files scanned';
          var spinnerEl = el('span', 'mf-spinner');
          progText.appendChild(spinnerEl);
          progText.appendChild(txt(' Scanning source files — ' + countStr + ' — ' + fmtDur(elapsedSec) + ' elapsed'));
          if (sp.current_file) {
            var fileDiv = el('div', 'mf-mono mf-text--xs mf-text--muted');
            fileDiv.style.marginTop = '0.2rem';
            fileDiv.style.overflow = 'hidden';
            fileDiv.style.textOverflow = 'ellipsis';
            fileDiv.style.whiteSpace = 'nowrap';
            fileDiv.textContent = sp.current_file;
            fileDiv.title = sp.current_file;
            progressLink.appendChild(fileDiv);
          }
        } else {
          var spinnerEl2 = el('span', 'mf-spinner');
          progText.appendChild(spinnerEl2);
          progText.appendChild(txt(' Enumerating source files… ' + fmtDur(elapsedSec) + ' elapsed'));
        }
      } else {
        var pctStr = job.total_files ? pct + '%' : '?%';
        progText.textContent = fmtNum(job.converted) + ' / ' + fmtNum(job.total_files) + ' files — ' + pctStr;
      }
      progressLink.appendChild(progText);
      card.appendChild(progressLink);

      /* Counts row (clickable — file list panels) */
      var countsRow = el('div', 'mf-status__counts');

      function makeCountBtn(clsCls, icon, count, flpStatus, label) {
        var span = el('span', clsCls);
        span.appendChild(txt(icon + ' '));
        var btn = el('button', 'mf-status__count-btn');
        btn.textContent = fmtNum(count);
        btn.title = 'Click to view ' + flpStatus + ' files';
        btn.addEventListener('click', function () {
          toggleFileList(job.job_id, flpStatus, flpPanel);
        });
        span.appendChild(btn);
        span.appendChild(txt(' ' + label));
        return span;
      }

      countsRow.appendChild(makeCountBtn('mf-status__count--ok',   '✓', job.converted, 'converted', 'converted'));
      countsRow.appendChild(makeCountBtn('mf-status__count--err',  '✗', job.failed,    'failed',    'failed'));
      countsRow.appendChild(makeCountBtn('mf-status__count--skip', '⏭', job.skipped,   'skipped',   'skipped'));
      card.appendChild(countsRow);

      /* File list panel (collapsed by default) */
      var flpPanel = el('div', 'mf-flp');
      flpPanel.setAttribute('data-flp-panel', job.job_id);
      card.appendChild(flpPanel);

      /* Workers */
      if ((job.current_files || []).length) {
        var workers = el('div', 'mf-status__workers');
        job.current_files.forEach(function (w) {
          var row = el('div', 'mf-status__worker-row');
          var wid = el('span', 'mf-status__worker-id');
          wid.textContent = 'Worker ' + w.worker_id;
          var fname = el('span', 'mf-mono mf-text--sm');
          fname.textContent = w.filename || '';
          row.appendChild(wid);
          row.appendChild(fname);
          workers.appendChild(row);
        });
        card.appendChild(workers);
      }

      /* Directory stats */
      if (job.dir_stats && Object.keys(job.dir_stats).length) {
        var dirDetails = el('details', 'mf-status__dir-details');
        var summary2 = document.createElement('summary');
        summary2.textContent = 'Directory Progress';
        dirDetails.appendChild(summary2);
        var dirList = el('div', 'mf-status__dir-list');
        Object.keys(job.dir_stats).forEach(function (dir) {
          var s = job.dir_stats[dir];
          var dirRow = el('div', 'mf-status__dir-row');
          var dirName = el('span', 'mf-mono mf-text--sm');
          dirName.textContent = dir + '/';
          dirName.title = dir;
          var dirCounts = el('div', 'mf-status__dir-counts');
          var doneSpan = el('span', 'mf-status__count--ok mf-text--sm');
          doneSpan.textContent = fmtNum(s.converted || 0) + ' done';
          dirCounts.appendChild(doneSpan);
          if (s.failed) {
            var failSpan = el('span', 'mf-status__count--err mf-text--sm');
            failSpan.textContent = fmtNum(s.failed) + ' failed';
            dirCounts.appendChild(failSpan);
          }
          dirRow.appendChild(dirName);
          dirRow.appendChild(dirCounts);
          dirList.appendChild(dirRow);
        });
        dirDetails.appendChild(dirList);
        card.appendChild(dirDetails);
      }

      return card;
    }

    /* Inline cancel confirm pattern */
    function buildCancelButton(jobId, parentEl) {
      var btn = el('button', 'mf-btn mf-btn--danger-outline mf-btn--sm');
      btn.textContent = 'Stop';
      btn.addEventListener('click', function () {
        clear(parentEl);
        var confirmRow = el('div', 'mf-status__confirm');
        var msg = el('span', 'mf-text--sm');
        msg.textContent = 'Stop this job?';
        var yesBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
        yesBtn.textContent = 'Yes, stop';
        var noBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
        noBtn.textContent = 'No';
        confirmRow.appendChild(msg);
        confirmRow.appendChild(yesBtn);
        confirmRow.appendChild(noBtn);
        parentEl.appendChild(confirmRow);

        yesBtn.addEventListener('click', function () {
          fetch(API_BULK_JOB_CANCEL(jobId), { method: 'POST', credentials: 'same-origin' })
            .then(function (r) {
              if (!r.ok) throw new Error(r.status);
              showToast('Job stopped');
              pollJobs();
            })
            .catch(function () { showToast('Failed to stop', 'error'); });
        });
        noBtn.addEventListener('click', pollJobs);
      });
      return btn;
    }

    /* ── Inline file list panels ──────────────────────────────────────────── */

    function humanSize(bytes) {
      if (bytes == null || bytes === '') return '';
      var b = Number(bytes);
      if (!b) return '0 B';
      var units = ['B', 'KB', 'MB', 'GB'];
      var i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), units.length - 1);
      return (i === 0 ? b : (b / Math.pow(1024, i)).toFixed(1)) + ' ' + units[i];
    }

    function baseName(path) {
      if (!path) return '';
      var parts = path.replace(/\\/g, '/').split('/');
      return parts[parts.length - 1] || '';
    }

    function dirName(path) {
      if (!path) return '';
      var norm = path.replace(/\\/g, '/');
      var idx = norm.lastIndexOf('/');
      return idx >= 0 ? norm.slice(0, idx) : '';
    }

    function truncate(s, max) {
      if (!s || s.length <= max) return s || '';
      return s.slice(0, max - 1) + '…';
    }

    function findPanel(jobId) {
      return jobsContainer.querySelector('.mf-flp[data-flp-panel="' + CSS.escape(jobId) + '"]');
    }

    function toggleFileList(jobId, status, panel) {
      var state = _flpPanelsByJob[jobId];
      if (state && state.status === status) {
        panel.classList.remove('open');
        delete _flpPanelsByJob[jobId];
        return;
      }
      _flpPanelsByJob[jobId] = { status: status, page: 1, total: 0, lastCount: null };
      clear(panel);
      var loading = el('div', 'mf-text--sm mf-text--muted');
      loading.textContent = 'Loading ' + status + ' files…';
      panel.appendChild(loading);
      panel.classList.add('open');
      fetchAndRenderFileList(jobId, status, false);
    }

    function fetchAndRenderFileList(jobId, status, append) {
      var panel = findPanel(jobId);
      if (!panel) return;
      var state = _flpPanelsByJob[jobId];
      if (!state) return;

      fetch(API_BULK_JOB_FILES(jobId, status, state.page), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          state.total = data.total || 0;
          state.lastCount = data.total || 0;
          if (!append) {
            clear(panel);
            renderFileListPanel(panel, data, jobId, status);
          } else {
            var tbody = panel.querySelector('tbody');
            if (tbody) appendFileRows(tbody, data.files, status);
            updateLoadMoreBtn(panel, data, jobId);
          }
        })
        .catch(function (e) {
          if (!append) {
            clear(panel);
            var errDiv = el('div', 'mf-text--sm');
            errDiv.style.color = 'var(--mf-color-error)';
            errDiv.textContent = 'Failed to load files: ' + (e.message || 'unknown');
            panel.appendChild(errDiv);
          }
        });
    }

    function renderFileListPanel(panel, data, jobId, status) {
      var state = _flpPanelsByJob[jobId] || { total: 0, page: 1 };
      var statusColors = {
        converted: 'var(--mf-color-success,#16a34a)',
        failed: 'var(--mf-color-error,#dc2626)',
        skipped: 'var(--mf-color-text-muted,#888)',
      };

      var hdr = el('div', 'mf-flp__header');
      var titleSpan = el('span', 'mf-flp__title');
      titleSpan.style.color = statusColors[status] || '';
      titleSpan.textContent = status.charAt(0).toUpperCase() + status.slice(1) +
        ' Files (' + fmtNum(state.total) + ')';
      var closeBtn = el('button', 'mf-flp__close');
      closeBtn.textContent = '×';
      closeBtn.title = 'Close';
      closeBtn.addEventListener('click', function () {
        panel.classList.remove('open');
        delete _flpPanelsByJob[jobId];
      });
      hdr.appendChild(titleSpan);
      hdr.appendChild(closeBtn);
      panel.appendChild(hdr);

      if (!data.files || !data.files.length) {
        var emptySpan = el('div', 'mf-text--sm mf-text--muted');
        emptySpan.textContent = 'No ' + status + ' files.';
        panel.appendChild(emptySpan);
        return;
      }

      var scroll = el('div', 'mf-flp__scroll');
      var table = el('table', 'mf-flp__table');
      var thead = document.createElement('thead');
      var headRow = document.createElement('tr');
      var cols = ['Filename', 'Path', 'Size'];
      if (status === 'failed') cols.push('Error');
      cols.forEach(function (col) {
        var th = document.createElement('th');
        th.textContent = col;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);
      var tbody = document.createElement('tbody');
      appendFileRows(tbody, data.files, status);
      table.appendChild(tbody);
      scroll.appendChild(table);
      panel.appendChild(scroll);

      if (data.total_pages > 1 && state.page < data.total_pages) {
        var loadBtn = el('button', 'mf-flp__load-more');
        var remaining = Math.max(0, state.total - data.files.length);
        loadBtn.textContent = 'Load more (' + fmtNum(remaining) + ' remaining)';
        loadBtn.addEventListener('click', function () {
          loadBtn.disabled = true;
          loadBtn.textContent = 'Loading…';
          var s = _flpPanelsByJob[jobId];
          if (!s) return;
          s.page++;
          fetchAndRenderFileList(jobId, s.status, true);
        });
        panel.appendChild(loadBtn);
      }
    }

    function appendFileRows(tbody, files, status) {
      (files || []).forEach(function (f) {
        var tr = document.createElement('tr');

        var tdName = document.createElement('td');
        tdName.className = 'mf-flp__fname';
        var fname = baseName(f.source_path);
        tdName.textContent = truncate(fname, 60);
        tdName.title = fname;
        tr.appendChild(tdName);

        var tdPath = document.createElement('td');
        tdPath.className = 'mf-flp__path';
        var dname = dirName(f.source_path);
        tdPath.textContent = truncate(dname, 60);
        tdPath.title = dname;
        tr.appendChild(tdPath);

        var tdSize = document.createElement('td');
        tdSize.className = 'mf-flp__size';
        tdSize.textContent = humanSize(f.file_size_bytes);
        tr.appendChild(tdSize);

        if (status === 'failed') {
          var tdErr = document.createElement('td');
          tdErr.className = 'mf-flp__err';
          tdErr.textContent = truncate(f.error_msg || '', 120);
          tdErr.title = f.error_msg || '';
          tr.appendChild(tdErr);
        }

        tbody.appendChild(tr);
      });
    }

    function updateLoadMoreBtn(panel, data, jobId) {
      var state = _flpPanelsByJob[jobId];
      if (!state) return;
      var existing = panel.querySelector('.mf-flp__load-more');
      if (!existing) return;
      if (state.page >= data.total_pages) {
        existing.remove();
      } else {
        var shown = state.page * 50;
        var remaining = Math.max(0, state.total - shown);
        existing.textContent = 'Load more (' + fmtNum(remaining) + ' remaining)';
        existing.disabled = false;
      }
    }

    function restoreOpenPanels() {
      /* Prune stale state for jobs that disappeared. */
      var liveJobIds = {};
      jobsContainer.querySelectorAll('[data-flp-panel]').forEach(function (p) {
        liveJobIds[p.getAttribute('data-flp-panel')] = true;
      });
      Object.keys(_flpPanelsByJob).forEach(function (jobId) {
        if (!liveJobIds[jobId]) delete _flpPanelsByJob[jobId];
      });

      Object.keys(_flpPanelsByJob).forEach(function (jobId) {
        var state = _flpPanelsByJob[jobId];
        var panel = findPanel(jobId);
        if (!panel) return;
        panel.classList.add('open');
        state.page = 1;
        fetchAndRenderFileList(jobId, state.status, false);
      });
    }

    /* ── Stop All / Reset Stop ──────────────────────────────────────────── */

    stopAllBtn.addEventListener('click', function () {
      if (!confirm('Hard stop ALL running jobs? Workers will finish their current file and exit.')) return;
      stopAllBtn.disabled = true;
      fetch(API_STOP_ALL, { method: 'POST', credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          showToast('Stop requested — jobs winding down');
          pollJobs();
        })
        .catch(function () { showToast('Failed to stop', 'error'); })
        .finally(function () { setTimeout(function () { stopAllBtn.disabled = false; }, 3000); });
    });

    resetStopBtn.addEventListener('click', function () {
      fetch(API_RESET_STOP, { method: 'POST', credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          showToast('Stop flag cleared');
          stopBanner.style.display = 'none';
          stopAllBtn.disabled = false;
          pollJobs();
        })
        .catch(function () { showToast('Reset failed — check logs', 'error'); });
    });

    /* ── Auto-Conversion override ──────────────────────────────────────── */

    function loadAutoConvertStatus() {
      fetch(API_AUTO_CONVERT, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          if (data.override_active) {
            acModeLabel.textContent = 'Override: ' + data.mode_override + ' (expires ' + data.override_expiry + ')';
            acModeLabel.style.color = 'var(--mf-color-warn,#d97706)';
            acClearBtn.style.display = '';
            acSelect.value = data.mode_override || '';
          } else {
            acModeLabel.textContent = 'Mode: ' + (data.configured_mode || 'off');
            acModeLabel.style.color = '';
            acClearBtn.style.display = 'none';
            acSelect.value = '';
          }
          if (data.last_decision) {
            acLastDecision.textContent = 'Last: ' + data.last_decision.reason;
          }
        })
        .catch(function () { acModeLabel.textContent = 'unavailable'; });
    }

    acApplyBtn.addEventListener('click', function () {
      var mode = acSelect.value;
      var duration = parseInt(acDuration.value, 10);
      if (!mode) { showToast('Select a mode to override', 'info'); return; }
      fetch(API_AUTO_OVERRIDE, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode, duration_minutes: duration }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || 'Override failed'); });
          showToast('Mode override set: ' + mode + ' for ' + duration + ' min');
          loadAutoConvertStatus();
        })
        .catch(function (e) { showToast(e.message || 'Override failed', 'error'); });
    });

    acClearBtn.addEventListener('click', function () {
      fetch(API_AUTO_OVERRIDE, { method: 'DELETE', credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          showToast('Mode override cleared');
          loadAutoConvertStatus();
        })
        .catch(function () { showToast('Failed to clear override', 'error'); });
    });

    /* ── Health check ──────────────────────────────────────────────────── */

    fetch(API_HEALTH, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (health) {
        var comps = health.components || health;
        clear(healthStatus);
        var table = el('table', 'mf-health-table');
        Object.keys(comps).forEach(function (dep) {
          var s = comps[dep];
          var tr = document.createElement('tr');

          var tdName = document.createElement('td');
          tdName.textContent = dep;
          tr.appendChild(tdName);

          var tdState = document.createElement('td');
          var badge = el('span', s.ok ? 'mf-status-ok' : 'mf-status-err');
          badge.textContent = s.ok ? 'OK' : 'FAIL';
          tdState.appendChild(badge);
          tr.appendChild(tdState);

          var tdDetail = document.createElement('td');
          tdDetail.className = 'mf-text--sm mf-text--muted';
          tdDetail.textContent = s.version || s.error || (s.free_gb != null ? s.free_gb + ' GB free' : '');
          tr.appendChild(tdDetail);

          table.appendChild(tr);
        });
        healthStatus.appendChild(table);
      })
      .catch(function () {
        clear(healthStatus);
        var errSpan = el('span', 'mf-status-err');
        errSpan.textContent = 'Could not reach server.';
        healthStatus.appendChild(errSpan);
      });

    /* ── Init ────────────────────────────────────────────────────────────── */

    pollJobs();
    startPolling();
    pollStats();
    statsTimer = setInterval(pollStats, 30000);

    loadAutoConvertStatus();
    acTimer = setInterval(loadAutoConvertStatus, 15000);

    return {
      refresh: pollJobs,
      destroy: function () {
        if (pollTimer)  clearInterval(pollTimer);
        if (statsTimer) clearInterval(statsTimer);
        if (acTimer)    clearInterval(acTimer);
      },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */

  global.MFStatus = { mount: mount };

})(window);
