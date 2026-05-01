/* MFNotificationsDetail — Notifications settings detail page (Plan 6 Task 4).
 *
 * Usage:
 *   MFNotificationsDetail.mount(slot, { me, prefs });
 *
 * All roles can view; only operators+ can save. Members see disabled inputs.
 * Safe DOM throughout — no innerHTML.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'channels',      label: 'Channels' },
    { id: 'trigger-rules', label: 'Trigger rules' },
    { id: 'quiet-hours',   label: 'Quiet hours' },
    { id: 'test-send',     label: 'Test send' },
  ];

  var TRIGGERS = [
    { key: 'bulk_job_failed',          label: 'Bulk job failed' },
    { key: 'pipeline_auto_aborted',    label: 'Pipeline auto-aborted' },
    { key: 'consecutive_scan_errors',  label: 'Consecutive scan errors' },
    { key: 'disk_space_warning',       label: 'Disk space warning' },
    { key: 'mount_health_degraded',    label: 'Mount health degraded' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _makeSaveBar(onSave, onDiscard) {
    var bar = el('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-top:1.4rem;';

    var saveBtn = el('button', 'mf-btn mf-btn--primary');
    saveBtn.textContent = 'Save changes';
    bar.appendChild(saveBtn);

    var discardBtn = el('button', 'mf-btn mf-btn--ghost');
    discardBtn.textContent = 'Discard';
    bar.appendChild(discardBtn);

    var savedMsg = el('span');
    savedMsg.style.cssText = 'font-size:0.85rem;color:var(--mf-color-success);opacity:0;transition:opacity 0.2s;';
    savedMsg.textContent = 'Saved';
    bar.appendChild(savedMsg);

    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      onSave(saveBtn, savedMsg);
    });

    discardBtn.addEventListener('click', function () {
      onDiscard();
    });

    return { bar: bar, saveBtn: saveBtn, savedMsg: savedMsg };
  }

  function _putPref(key, value) {
    return fetch('/api/preferences/' + key, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ value: value }),
    });
  }

  function _showSaved(saveBtn, savedMsg) {
    savedMsg.style.opacity = '1';
    setTimeout(function () { savedMsg.style.opacity = '0'; }, 2000);
    saveBtn.disabled = false;
  }

  function _renderChannels(me, prefs, savedPrefs) {
    var frag = document.createDocumentFragment();
    var isReadOnly = (me.role === 'member');

    /* ── Slack card ── */
    var slackCard = el('div', 'mf-notif__channel-card');

    var slackTitle = el('div', 'mf-notif__channel-title');
    slackTitle.textContent = 'Slack';
    slackCard.appendChild(slackTitle);

    var slackToggleRow = el('div');
    slackToggleRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;margin-bottom:0.85rem;';

    var slackEnabledCheck = document.createElement('input');
    slackEnabledCheck.type = 'checkbox';
    slackEnabledCheck.id = 'mf-notif-slack-enabled';
    var slackEnabledVal = prefs.slack_notifications_enabled;
    slackEnabledCheck.checked = (slackEnabledVal === true || slackEnabledVal === 'true');
    if (isReadOnly) slackEnabledCheck.disabled = true;
    slackToggleRow.appendChild(slackEnabledCheck);

    var slackEnabledLabel = document.createElement('label');
    slackEnabledLabel.htmlFor = 'mf-notif-slack-enabled';
    slackEnabledLabel.textContent = 'Enable Slack notifications';
    slackEnabledLabel.style.cssText = 'font-size:0.9rem;color:var(--mf-color-text);cursor:pointer;';
    slackToggleRow.appendChild(slackEnabledLabel);
    slackCard.appendChild(slackToggleRow);

    var slackUrlLabel = el('label', 'mf-stg__field-label');
    slackUrlLabel.textContent = 'Webhook URL';
    slackCard.appendChild(slackUrlLabel);

    var slackUrlInput = el('input', 'mf-stg__field-input');
    slackUrlInput.type = 'text';
    slackUrlInput.value = prefs.slack_webhook_url || '';
    slackUrlInput.placeholder = 'https://hooks.slack.com/services/...';
    if (isReadOnly) slackUrlInput.disabled = true;
    slackCard.appendChild(slackUrlInput);

    if (!isReadOnly) {
      var slackSaved = {
        slack_notifications_enabled: prefs.slack_notifications_enabled,
        slack_webhook_url: prefs.slack_webhook_url || '',
      };

      var slackBarObj = _makeSaveBar(
        function (saveBtn, savedMsg) {
          var enabledVal = slackEnabledCheck.checked ? 'true' : 'false';
          var urlVal = slackUrlInput.value;

          _putPref('slack_notifications_enabled', enabledVal)
            .then(function () {
              return _putPref('slack_webhook_url', urlVal);
            })
            .then(function () {
              slackSaved.slack_notifications_enabled = enabledVal;
              slackSaved.slack_webhook_url = urlVal;
              savedPrefs.slack_notifications_enabled = enabledVal;
              savedPrefs.slack_webhook_url = urlVal;
              _showSaved(saveBtn, savedMsg);
            })
            .catch(function (e) {
              console.error('mf: failed to save slack prefs', e);
              saveBtn.disabled = false;
            });
        },
        function () {
          var rv = slackSaved.slack_notifications_enabled;
          slackEnabledCheck.checked = (rv === true || rv === 'true');
          slackUrlInput.value = slackSaved.slack_webhook_url || '';
        }
      );

      slackCard.appendChild(slackBarObj.bar);
    }

    frag.appendChild(slackCard);

    /* ── Email card ── */
    var emailCard = el('div', 'mf-notif__channel-card');

    var emailTitle = el('div', 'mf-notif__channel-title');
    emailTitle.textContent = 'Email';
    emailCard.appendChild(emailTitle);

    var emailToggleRow = el('div');
    emailToggleRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;margin-bottom:0.85rem;';

    var emailEnabledCheck = document.createElement('input');
    emailEnabledCheck.type = 'checkbox';
    emailEnabledCheck.id = 'mf-notif-email-enabled';
    var emailEnabledVal = prefs.email_notifications_enabled;
    emailEnabledCheck.checked = (emailEnabledVal === true || emailEnabledVal === 'true');
    if (isReadOnly) emailEnabledCheck.disabled = true;
    emailToggleRow.appendChild(emailEnabledCheck);

    var emailEnabledLabel = document.createElement('label');
    emailEnabledLabel.htmlFor = 'mf-notif-email-enabled';
    emailEnabledLabel.textContent = 'Enable email notifications';
    emailEnabledLabel.style.cssText = 'font-size:0.9rem;color:var(--mf-color-text);cursor:pointer;';
    emailToggleRow.appendChild(emailEnabledLabel);
    emailCard.appendChild(emailToggleRow);

    var smtpHostLabel = el('label', 'mf-stg__field-label');
    smtpHostLabel.textContent = 'SMTP host';
    emailCard.appendChild(smtpHostLabel);

    var smtpHostInput = el('input', 'mf-stg__field-input');
    smtpHostInput.type = 'text';
    smtpHostInput.value = prefs.email_smtp_host || '';
    if (isReadOnly) smtpHostInput.disabled = true;
    emailCard.appendChild(smtpHostInput);

    var spacer1 = el('div');
    spacer1.style.marginTop = '0.75rem';
    emailCard.appendChild(spacer1);

    var smtpPortLabel = el('label', 'mf-stg__field-label');
    smtpPortLabel.textContent = 'SMTP port';
    emailCard.appendChild(smtpPortLabel);

    var smtpPortInput = el('input', 'mf-stg__field-input');
    smtpPortInput.type = 'number';
    smtpPortInput.value = prefs.email_smtp_port || 587;
    if (isReadOnly) smtpPortInput.disabled = true;
    emailCard.appendChild(smtpPortInput);

    var spacer2 = el('div');
    spacer2.style.marginTop = '0.75rem';
    emailCard.appendChild(spacer2);

    var toLabel = el('label', 'mf-stg__field-label');
    toLabel.textContent = 'To address';
    emailCard.appendChild(toLabel);

    var toInput = el('input', 'mf-stg__field-input');
    toInput.type = 'text';
    toInput.value = prefs.email_to || '';
    if (isReadOnly) toInput.disabled = true;
    emailCard.appendChild(toInput);

    if (!isReadOnly) {
      var emailSaved = {
        email_notifications_enabled: prefs.email_notifications_enabled,
        email_smtp_host: prefs.email_smtp_host || '',
        email_smtp_port: prefs.email_smtp_port || 587,
        email_to: prefs.email_to || '',
      };

      var emailBarObj = _makeSaveBar(
        function (saveBtn, savedMsg) {
          var enabledVal = emailEnabledCheck.checked ? 'true' : 'false';
          var hostVal = smtpHostInput.value;
          var portVal = parseInt(smtpPortInput.value, 10) || 587;
          var toVal = toInput.value;

          _putPref('email_notifications_enabled', enabledVal)
            .then(function () { return _putPref('email_smtp_host', hostVal); })
            .then(function () { return _putPref('email_smtp_port', portVal); })
            .then(function () { return _putPref('email_to', toVal); })
            .then(function () {
              emailSaved.email_notifications_enabled = enabledVal;
              emailSaved.email_smtp_host = hostVal;
              emailSaved.email_smtp_port = portVal;
              emailSaved.email_to = toVal;
              savedPrefs.email_notifications_enabled = enabledVal;
              savedPrefs.email_smtp_host = hostVal;
              savedPrefs.email_smtp_port = portVal;
              savedPrefs.email_to = toVal;
              _showSaved(saveBtn, savedMsg);
            })
            .catch(function (e) {
              console.error('mf: failed to save email prefs', e);
              saveBtn.disabled = false;
            });
        },
        function () {
          var rv = emailSaved.email_notifications_enabled;
          emailEnabledCheck.checked = (rv === true || rv === 'true');
          smtpHostInput.value = emailSaved.email_smtp_host || '';
          smtpPortInput.value = emailSaved.email_smtp_port || 587;
          toInput.value = emailSaved.email_to || '';
        }
      );

      emailCard.appendChild(emailBarObj.bar);
    }

    frag.appendChild(emailCard);

    return frag;
  }

  function _renderTriggerRules(me, prefs, savedPrefs) {
    var frag = document.createDocumentFragment();
    var isReadOnly = (me.role === 'member');

    var triggersJson = prefs.notification_triggers_json || '{}';
    var triggerState;
    try {
      triggerState = JSON.parse(triggersJson);
    } catch (e) {
      triggerState = {};
    }

    var checkboxes = [];

    TRIGGERS.forEach(function (trigger) {
      var row = el('div', 'mf-notif__trigger-row');

      var check = document.createElement('input');
      check.type = 'checkbox';
      check.id = 'mf-notif-trigger-' + trigger.key;
      check.checked = !!triggerState[trigger.key];
      if (isReadOnly) check.disabled = true;
      row.appendChild(check);

      var label = document.createElement('label');
      label.htmlFor = 'mf-notif-trigger-' + trigger.key;
      label.textContent = trigger.label;
      row.appendChild(label);

      frag.appendChild(row);
      checkboxes.push({ key: trigger.key, check: check });
    });

    if (!isReadOnly) {
      var savedTriggersJson = triggersJson;

      var barObj = _makeSaveBar(
        function (saveBtn, savedMsg) {
          var state = {};
          checkboxes.forEach(function (item) {
            state[item.key] = item.check.checked;
          });
          var jsonStr = JSON.stringify(state);

          _putPref('notification_triggers_json', jsonStr)
            .then(function () {
              savedTriggersJson = jsonStr;
              savedPrefs.notification_triggers_json = jsonStr;
              _showSaved(saveBtn, savedMsg);
            })
            .catch(function (e) {
              console.error('mf: failed to save trigger rules', e);
              saveBtn.disabled = false;
            });
        },
        function () {
          var restoredState;
          try {
            restoredState = JSON.parse(savedTriggersJson);
          } catch (e) {
            restoredState = {};
          }
          checkboxes.forEach(function (item) {
            item.check.checked = !!restoredState[item.key];
          });
        }
      );

      frag.appendChild(barObj.bar);
    }

    return frag;
  }

  function _renderQuietHours(me, prefs, savedPrefs) {
    var frag = document.createDocumentFragment();
    var isReadOnly = (me.role === 'member');

    var toggleRow = el('div');
    toggleRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;';

    var enabledCheck = document.createElement('input');
    enabledCheck.type = 'checkbox';
    enabledCheck.id = 'mf-notif-quiet-enabled';
    var qhEnabledVal = prefs.quiet_hours_enabled;
    enabledCheck.checked = (qhEnabledVal === true || qhEnabledVal === 'true');
    if (isReadOnly) enabledCheck.disabled = true;
    toggleRow.appendChild(enabledCheck);

    var enabledLabel = document.createElement('label');
    enabledLabel.htmlFor = 'mf-notif-quiet-enabled';
    enabledLabel.textContent = 'Enable quiet hours';
    enabledLabel.style.cssText = 'font-size:0.9rem;color:var(--mf-color-text);cursor:pointer;';
    toggleRow.appendChild(enabledLabel);
    frag.appendChild(toggleRow);

    var timeRow = el('div', 'mf-notif__time-row');

    var fromLabel = el('label', 'mf-stg__field-label');
    fromLabel.textContent = 'Quiet from';
    fromLabel.style.marginBottom = '0';
    timeRow.appendChild(fromLabel);

    var startInput = el('input', 'mf-stg__field-input');
    startInput.type = 'time';
    startInput.value = prefs.quiet_hours_start || '22:00';
    startInput.style.width = 'auto';
    if (isReadOnly) startInput.disabled = true;
    timeRow.appendChild(startInput);

    var untilLabel = el('label', 'mf-stg__field-label');
    untilLabel.textContent = 'Until';
    untilLabel.style.marginBottom = '0';
    timeRow.appendChild(untilLabel);

    var endInput = el('input', 'mf-stg__field-input');
    endInput.type = 'time';
    endInput.value = prefs.quiet_hours_end || '07:00';
    endInput.style.width = 'auto';
    if (isReadOnly) endInput.disabled = true;
    timeRow.appendChild(endInput);

    frag.appendChild(timeRow);

    if (!isReadOnly) {
      var saved = {
        quiet_hours_enabled: prefs.quiet_hours_enabled,
        quiet_hours_start: prefs.quiet_hours_start || '22:00',
        quiet_hours_end: prefs.quiet_hours_end || '07:00',
      };

      var barObj = _makeSaveBar(
        function (saveBtn, savedMsg) {
          var enabledVal = enabledCheck.checked ? 'true' : 'false';
          var startVal = startInput.value;
          var endVal = endInput.value;

          _putPref('quiet_hours_enabled', enabledVal)
            .then(function () { return _putPref('quiet_hours_start', startVal); })
            .then(function () { return _putPref('quiet_hours_end', endVal); })
            .then(function () {
              saved.quiet_hours_enabled = enabledVal;
              saved.quiet_hours_start = startVal;
              saved.quiet_hours_end = endVal;
              savedPrefs.quiet_hours_enabled = enabledVal;
              savedPrefs.quiet_hours_start = startVal;
              savedPrefs.quiet_hours_end = endVal;
              _showSaved(saveBtn, savedMsg);
            })
            .catch(function (e) {
              console.error('mf: failed to save quiet hours prefs', e);
              saveBtn.disabled = false;
            });
        },
        function () {
          var rv = saved.quiet_hours_enabled;
          enabledCheck.checked = (rv === true || rv === 'true');
          startInput.value = saved.quiet_hours_start || '22:00';
          endInput.value = saved.quiet_hours_end || '07:00';
        }
      );

      frag.appendChild(barObj.bar);
    }

    return frag;
  }

  function _renderTestSend() {
    var frag = document.createDocumentFragment();

    var heading = el('p', 'mf-stg__field-label');
    heading.textContent = 'Send a test notification';
    heading.style.cssText = 'color:var(--mf-text-muted);font-weight:600;font-size:0.95rem;margin-bottom:0.5rem;';
    frag.appendChild(heading);

    var desc = el('p');
    desc.textContent = 'Sends a test alert to all enabled channels.';
    desc.style.cssText = 'font-size:0.88rem;color:var(--mf-text-muted);margin-bottom:1rem;';
    frag.appendChild(desc);

    var testBtn = el('button', 'mf-btn mf-btn--primary');
    testBtn.textContent = 'Send test notification';
    frag.appendChild(testBtn);

    var stubMsg = el('div', 'mf-notif__stub-msg');
    frag.appendChild(stubMsg);

    testBtn.addEventListener('click', function () {
      stubMsg.textContent = 'Test send not yet implemented — configure channels first.';
    });

    var note = el('p', 'mf-notif__test-note');
    note.textContent = 'Alert delivery (Slack/email) requires notification channels to be configured in Channels.';
    frag.appendChild(note);

    return frag;
  }

  function _renderContent(contentSlot, activeSection, me, prefs, savedPrefs) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var sectionDef = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === activeSection) { sectionDef = SECTIONS[i]; break; }
    }

    var head = el('h2', 'mf-stg__section-head');
    head.textContent = sectionDef ? sectionDef.label : activeSection;
    contentSlot.appendChild(head);

    if (activeSection === 'channels') {
      contentSlot.appendChild(_renderChannels(me, prefs, savedPrefs));
    } else if (activeSection === 'trigger-rules') {
      contentSlot.appendChild(_renderTriggerRules(me, prefs, savedPrefs));
    } else if (activeSection === 'quiet-hours') {
      contentSlot.appendChild(_renderQuietHours(me, prefs, savedPrefs));
    } else if (activeSection === 'test-send') {
      contentSlot.appendChild(_renderTestSend());
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFNotificationsDetail.mount: slot is required');
    opts = opts || {};

    var me = opts.me || {};
    var prefs = opts.prefs || {};
    var savedPrefs = {
      slack_notifications_enabled: prefs.slack_notifications_enabled,
      slack_webhook_url: prefs.slack_webhook_url,
      email_notifications_enabled: prefs.email_notifications_enabled,
      email_smtp_host: prefs.email_smtp_host,
      email_smtp_port: prefs.email_smtp_port,
      email_to: prefs.email_to,
      notification_triggers_json: prefs.notification_triggers_json,
      quiet_hours_enabled: prefs.quiet_hours_enabled,
      quiet_hours_start: prefs.quiet_hours_start,
      quiet_hours_end: prefs.quiet_hours_end,
    };

    var activeSection = 'channels';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Notifications.';
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
        _renderContent(contentSlot, activeSection, me, prefs, savedPrefs);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, me, prefs, savedPrefs);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFNotificationsDetail = { mount: mount };
})(window);
