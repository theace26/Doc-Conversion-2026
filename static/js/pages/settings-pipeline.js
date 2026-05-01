/* MFPipelineDetail — Pipeline & lifecycle settings detail page (Plan 6 Task 1).
 *
 * Usage:
 *   MFPipelineDetail.mount(slot, { status, prefs });
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout — no innerHTML anywhere.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'scan-schedule', label: 'Scan schedule' },
    { id: 'lifecycle',     label: 'Lifecycle & retention' },
    { id: 'trash',         label: 'Trash & cleanup' },
    { id: 'stale-check',   label: 'Stale data check' },
    { id: 'watchdog',      label: 'Pipeline watchdog' },
    { id: 'pause-resume',  label: 'Pause & resume' },
  ];

  var DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _makeToggle(isOn) {
    var toggle = el('div', 'mf-pip__toggle' + (isOn ? ' mf-pip__toggle--on' : ''));
    toggle.setAttribute('data-mf-on', isOn ? '1' : '0');
    var knob = el('div', 'mf-pip__toggle-knob');
    toggle.appendChild(knob);
    return toggle;
  }

  function _toggleOn(toggle) {
    return toggle.getAttribute('data-mf-on') === '1';
  }

  function _setToggle(toggle, on) {
    toggle.setAttribute('data-mf-on', on ? '1' : '0');
    if (on) {
      toggle.classList.add('mf-pip__toggle--on');
    } else {
      toggle.classList.remove('mf-pip__toggle--on');
    }
  }

  function _makeSaveBar(onSave, onDiscard) {
    var bar = el('div', 'mf-pip__save-bar');

    var saveBtn = el('button', 'mf-pill mf-pill--primary');
    saveBtn.type = 'button';
    saveBtn.textContent = 'Save changes';
    bar.appendChild(saveBtn);

    var discardBtn = el('button', 'mf-pill mf-pill--ghost');
    discardBtn.type = 'button';
    discardBtn.textContent = 'Discard';
    bar.appendChild(discardBtn);

    var feedback = el('span', 'mf-pip__save-feedback');
    bar.appendChild(feedback);

    saveBtn.addEventListener('click', function () {
      feedback.textContent = '';
      feedback.classList.remove('mf-pip__save-feedback--error');
      onSave(feedback);
    });

    discardBtn.addEventListener('click', function () {
      feedback.textContent = '';
      feedback.classList.remove('mf-pip__save-feedback--error');
      onDiscard();
    });

    return bar;
  }

  function _putPref(key, value) {
    return fetch('/api/preferences/' + encodeURIComponent(key), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: value }),
    }).then(function (r) {
      if (!r.ok) throw new Error('PUT /api/preferences/' + key + ' failed: ' + r.status);
    });
  }

  function _makeFieldLabel(text) {
    var label = el('label', 'mf-stg__field-label');
    label.textContent = text;
    return label;
  }

  function _makeNumberInput(value, min, max) {
    var input = el('input', 'mf-stg__field-input');
    input.type = 'number';
    input.min = String(min);
    input.max = String(max);
    input.value = value || '';
    input.style.fontFamily = 'inherit';
    return input;
  }

  function _makeTimeInput(value) {
    var input = el('input', 'mf-stg__field-input');
    input.type = 'time';
    input.value = value || '';
    input.style.fontFamily = 'inherit';
    return input;
  }

  function _renderScanSchedule(contentSlot, opts) {
    var prefs = opts.prefs || {};
    var status = opts.status || {};

    var isEnabled = prefs.pipeline_enabled !== undefined
      ? prefs.pipeline_enabled === 'true' || prefs.pipeline_enabled === true
      : (status.enabled !== false);

    var toggleRow = el('div', 'mf-pip__toggle-row');
    var toggle = _makeToggle(isEnabled);
    var toggleLabel = el('span', 'mf-pip__toggle-label');
    toggleLabel.textContent = 'Enable scheduled scanning';
    toggleRow.appendChild(toggle);
    toggleRow.appendChild(toggleLabel);
    toggle.addEventListener('click', function () {
      _setToggle(toggle, !_toggleOn(toggle));
    });
    contentSlot.appendChild(toggleRow);

    var startLabel = _makeFieldLabel('Window start');
    contentSlot.appendChild(startLabel);
    var startInput = _makeTimeInput(prefs.scan_window_start || '');
    contentSlot.appendChild(startInput);

    var endLabel = _makeFieldLabel('Window end');
    contentSlot.appendChild(endLabel);
    var endInput = _makeTimeInput(prefs.scan_window_end || '');
    contentSlot.appendChild(endInput);

    var daysLabel = _makeFieldLabel('Days of week');
    contentSlot.appendChild(daysLabel);

    var activeDays = {};
    var rawDays = prefs.scan_days_of_week || '';
    rawDays.split(',').forEach(function (d) {
      var t = d.trim();
      if (t) activeDays[t] = true;
    });

    var pillsRow = el('div', 'mf-pip__day-pills');
    var pillMap = {};
    DAYS.forEach(function (day) {
      var pill = el('button', 'mf-pip__day-pill' + (activeDays[day] ? ' mf-pip__day-pill--active' : ''));
      pill.type = 'button';
      pill.textContent = day;
      pill.addEventListener('click', function () {
        pill.classList.toggle('mf-pip__day-pill--active');
      });
      pillMap[day] = pill;
      pillsRow.appendChild(pill);
    });
    contentSlot.appendChild(pillsRow);

    function collectDays() {
      return DAYS.filter(function (day) {
        return pillMap[day].classList.contains('mf-pip__day-pill--active');
      }).join(',');
    }

    function doSave(feedback) {
      Promise.resolve()
        .then(function () { return _putPref('pipeline_enabled', _toggleOn(toggle) ? 'true' : 'false'); })
        .then(function () { return _putPref('scan_window_start', startInput.value); })
        .then(function () { return _putPref('scan_window_end', endInput.value); })
        .then(function () { return _putPref('scan_days_of_week', collectDays()); })
        .then(function () {
          feedback.classList.remove('mf-pip__save-feedback--error');
          feedback.textContent = 'Saved';
        })
        .catch(function (e) {
          feedback.classList.add('mf-pip__save-feedback--error');
          feedback.textContent = 'Error: ' + e.message;
        });
    }

    function doDiscard() {
      startInput.value = prefs.scan_window_start || '';
      endInput.value = prefs.scan_window_end || '';
      _setToggle(toggle, isEnabled);
      var resetDays = {};
      rawDays.split(',').forEach(function (d) {
        var t = d.trim();
        if (t) resetDays[t] = true;
      });
      DAYS.forEach(function (day) {
        if (resetDays[day]) {
          pillMap[day].classList.add('mf-pip__day-pill--active');
        } else {
          pillMap[day].classList.remove('mf-pip__day-pill--active');
        }
      });
    }

    contentSlot.appendChild(_makeSaveBar(doSave, doDiscard));
  }

  function _renderLifecycle(contentSlot, opts) {
    var prefs = opts.prefs || {};

    var graceLabel = _makeFieldLabel('Grace period (days)');
    contentSlot.appendChild(graceLabel);
    var graceInput = _makeNumberInput(prefs.lifecycle_grace_days || '', 1, 365);
    contentSlot.appendChild(graceInput);

    var retentionLabel = _makeFieldLabel('Retention period (days)');
    contentSlot.appendChild(retentionLabel);
    var retentionInput = _makeNumberInput(prefs.lifecycle_retention_days || '', 1, 3650);
    contentSlot.appendChild(retentionInput);

    function doSave(feedback) {
      Promise.resolve()
        .then(function () { return _putPref('lifecycle_grace_days', graceInput.value); })
        .then(function () { return _putPref('lifecycle_retention_days', retentionInput.value); })
        .then(function () {
          feedback.classList.remove('mf-pip__save-feedback--error');
          feedback.textContent = 'Saved';
        })
        .catch(function (e) {
          feedback.classList.add('mf-pip__save-feedback--error');
          feedback.textContent = 'Error: ' + e.message;
        });
    }

    function doDiscard() {
      graceInput.value = prefs.lifecycle_grace_days || '';
      retentionInput.value = prefs.lifecycle_retention_days || '';
    }

    contentSlot.appendChild(_makeSaveBar(doSave, doDiscard));
  }

  function _renderTrash(contentSlot, opts) {
    var prefs = opts.prefs || {};

    var autoDelete = prefs.trash_auto_delete === 'true' || prefs.trash_auto_delete === true;

    var toggleRow = el('div', 'mf-pip__toggle-row');
    var toggle = _makeToggle(autoDelete);
    var toggleLabel = el('span', 'mf-pip__toggle-label');
    toggleLabel.textContent = 'Auto-delete from trash';
    toggleRow.appendChild(toggle);
    toggleRow.appendChild(toggleLabel);
    toggle.addEventListener('click', function () {
      _setToggle(toggle, !_toggleOn(toggle));
    });
    contentSlot.appendChild(toggleRow);

    var retentionLabel = _makeFieldLabel('Keep in trash (days)');
    contentSlot.appendChild(retentionLabel);
    var retentionInput = _makeNumberInput(prefs.trash_retention_days || '', 1, 3650);
    contentSlot.appendChild(retentionInput);

    function doSave(feedback) {
      Promise.resolve()
        .then(function () { return _putPref('trash_auto_delete', String(_toggleOn(toggle))); })
        .then(function () { return _putPref('trash_retention_days', retentionInput.value); })
        .then(function () {
          feedback.classList.remove('mf-pip__save-feedback--error');
          feedback.textContent = 'Saved';
        })
        .catch(function (e) {
          feedback.classList.add('mf-pip__save-feedback--error');
          feedback.textContent = 'Error: ' + e.message;
        });
    }

    function doDiscard() {
      _setToggle(toggle, autoDelete);
      retentionInput.value = prefs.trash_retention_days || '';
    }

    contentSlot.appendChild(_makeSaveBar(doSave, doDiscard));
  }

  function _renderStaleCheck(contentSlot, opts) {
    var prefs = opts.prefs || {};

    var enabled = prefs.stale_check_enabled === 'true' || prefs.stale_check_enabled === true;

    var toggleRow = el('div', 'mf-pip__toggle-row');
    var toggle = _makeToggle(enabled);
    var toggleLabel = el('span', 'mf-pip__toggle-label');
    toggleLabel.textContent = 'Enable stale data check';
    toggleRow.appendChild(toggle);
    toggleRow.appendChild(toggleLabel);
    toggle.addEventListener('click', function () {
      _setToggle(toggle, !_toggleOn(toggle));
    });
    contentSlot.appendChild(toggleRow);

    var thresholdLabel = _makeFieldLabel('Flag files not seen for (days)');
    contentSlot.appendChild(thresholdLabel);
    var thresholdInput = _makeNumberInput(prefs.stale_check_threshold_days || '', 1, 3650);
    contentSlot.appendChild(thresholdInput);

    function doSave(feedback) {
      Promise.resolve()
        .then(function () { return _putPref('stale_check_enabled', String(_toggleOn(toggle))); })
        .then(function () { return _putPref('stale_check_threshold_days', thresholdInput.value); })
        .then(function () {
          feedback.classList.remove('mf-pip__save-feedback--error');
          feedback.textContent = 'Saved';
        })
        .catch(function (e) {
          feedback.classList.add('mf-pip__save-feedback--error');
          feedback.textContent = 'Error: ' + e.message;
        });
    }

    function doDiscard() {
      _setToggle(toggle, enabled);
      thresholdInput.value = prefs.stale_check_threshold_days || '';
    }

    contentSlot.appendChild(_makeSaveBar(doSave, doDiscard));
  }

  function _renderWatchdog(contentSlot, opts) {
    var prefs = opts.prefs || {};

    var enabled = prefs.watchdog_enabled === 'true' || prefs.watchdog_enabled === true;

    var toggleRow = el('div', 'mf-pip__toggle-row');
    var toggle = _makeToggle(enabled);
    var toggleLabel = el('span', 'mf-pip__toggle-label');
    toggleLabel.textContent = 'Enable pipeline watchdog';
    toggleRow.appendChild(toggle);
    toggleRow.appendChild(toggleLabel);
    toggle.addEventListener('click', function () {
      _setToggle(toggle, !_toggleOn(toggle));
    });
    contentSlot.appendChild(toggleRow);

    var timeoutLabel = _makeFieldLabel('Watchdog timeout (minutes)');
    contentSlot.appendChild(timeoutLabel);
    var timeoutInput = _makeNumberInput(prefs.watchdog_timeout_minutes || '', 1, 1440);
    contentSlot.appendChild(timeoutInput);

    function doSave(feedback) {
      Promise.resolve()
        .then(function () { return _putPref('watchdog_enabled', String(_toggleOn(toggle))); })
        .then(function () { return _putPref('watchdog_timeout_minutes', timeoutInput.value); })
        .then(function () {
          feedback.classList.remove('mf-pip__save-feedback--error');
          feedback.textContent = 'Saved';
        })
        .catch(function (e) {
          feedback.classList.add('mf-pip__save-feedback--error');
          feedback.textContent = 'Error: ' + e.message;
        });
    }

    function doDiscard() {
      _setToggle(toggle, enabled);
      timeoutInput.value = prefs.watchdog_timeout_minutes || '';
    }

    contentSlot.appendChild(_makeSaveBar(doSave, doDiscard));
  }

  function _makeLiveBadge(paused) {
    var badge = el('span', 'mf-pip__live-badge mf-pip__live-badge--' + (paused ? 'paused' : 'running'));
    badge.textContent = paused ? 'PAUSED' : 'LIVE';
    return badge;
  }

  function _renderPauseResume(contentSlot, opts) {
    var status = opts.status || {};
    var paused = !!status.paused;

    var toggleRow = el('div', 'mf-pip__toggle-row');

    var badge = _makeLiveBadge(paused);
    toggleRow.appendChild(badge);

    var toggle = _makeToggle(!paused);
    toggleRow.appendChild(toggle);

    var toggleLabel = el('span', 'mf-pip__toggle-label');
    toggleLabel.textContent = 'Pipeline running';
    toggleRow.appendChild(toggleLabel);

    toggle.addEventListener('click', function () {
      if (toggle.getAttribute('data-mf-loading') === '1') return;
      toggle.setAttribute('data-mf-loading', '1');
      var currentlyOn = _toggleOn(toggle);
      var url = currentlyOn ? '/api/pipeline/pause' : '/api/pipeline/resume';
      _setToggle(toggle, !currentlyOn);
      fetch(url, { method: 'POST', credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(url + ' failed: ' + r.status);
          var nowPaused = currentlyOn;
          badge.textContent = nowPaused ? 'PAUSED' : 'LIVE';
          badge.className = 'mf-pip__live-badge mf-pip__live-badge--' + (nowPaused ? 'paused' : 'running');
        })
        .catch(function (e) {
          console.warn('mf: pipeline pause/resume failed', e);
          _setToggle(toggle, currentlyOn);
        })
        .finally(function () {
          toggle.removeAttribute('data-mf-loading');
        });
    });

    contentSlot.appendChild(toggleRow);

    if (status.next_scan) {
      var nextScanDiv = el('div', 'mf-pip__next-scan');
      var ts = status.next_scan;
      try {
        var parsed = (typeof window.parseUTC === 'function')
          ? window.parseUTC(status.next_scan)
          : new Date(status.next_scan.replace(' ', 'T').replace(/Z?$/, 'Z'));
        ts = (parsed && !isNaN(parsed.getTime())) ? parsed.toLocaleString() : status.next_scan;
      } catch (e) {
        ts = status.next_scan;
      }
      nextScanDiv.textContent = 'Next scan: ' + ts;
      contentSlot.appendChild(nextScanDiv);
    }
  }

  function _renderContent(contentSlot, activeSection, opts) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var sectionDef = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === activeSection) { sectionDef = SECTIONS[i]; break; }
    }

    var head = el('h2', 'mf-stg__section-head');
    head.textContent = sectionDef ? sectionDef.label : activeSection;
    contentSlot.appendChild(head);

    if (activeSection === 'scan-schedule') {
      _renderScanSchedule(contentSlot, opts);
    } else if (activeSection === 'lifecycle') {
      _renderLifecycle(contentSlot, opts);
    } else if (activeSection === 'trash') {
      _renderTrash(contentSlot, opts);
    } else if (activeSection === 'stale-check') {
      _renderStaleCheck(contentSlot, opts);
    } else if (activeSection === 'watchdog') {
      _renderWatchdog(contentSlot, opts);
    } else if (activeSection === 'pause-resume') {
      _renderPauseResume(contentSlot, opts);
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFPipelineDetail.mount: slot is required');
    opts = opts || {};

    var activeSection = opts.activeSection || 'scan-schedule';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Pipeline.';
    body.appendChild(headline);

    var detail = el('div', 'mf-stg__detail');

    var sidebar = el('nav', 'mf-stg__sidebar');
    SECTIONS.forEach(function (sec) {
      var isActive = sec.id === activeSection;
      var link = el('a', 'mf-stg__sidebar-link' + (isActive ? ' mf-stg__sidebar-link--active' : ''));
      link.href = '#' + sec.id;
      link.textContent = sec.label;
      link.addEventListener('click', function (e) {
        e.preventDefault();
        activeSection = sec.id;
        sidebar.querySelectorAll('.mf-stg__sidebar-link').forEach(function (l) {
          l.classList.remove('mf-stg__sidebar-link--active');
        });
        link.classList.add('mf-stg__sidebar-link--active');
        _renderContent(contentSlot, activeSection, opts);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, opts);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFPipelineDetail = { mount: mount };
})(window);
