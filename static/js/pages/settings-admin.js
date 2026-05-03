/* MFSettingsAdmin — Admin settings detail page (Tier B #16).
 *
 * Usage:
 *   MFSettingsAdmin.mount(slot, { me });
 *
 * Admin-only. Role-gate at mount time: non-admin sees a warning and
 * redirects to /settings after 2 seconds. Confirmed admins see:
 *   — API Keys  (list / create / revoke)
 *   — Users     (read-only list)
 *   — System Actions (restart-watchers, force-rescan, flush-cache)
 *   — Database Tools (vacuum, integrity, backup, restore w/ typed-confirm)
 *   — Log Levels (link to /log-levels)
 *
 * BEM prefix: mf-adm__*
 * Token rule: var(--mf-*) only — zero hardcoded hex.
 * Safe DOM throughout — no innerHTML with template strings.
 */
(function (global) {
  'use strict';

  /* ── helpers ─────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function txt(str) {
    return document.createTextNode(str != null ? String(str) : '');
  }

  function apiFetch(method, url, body) {
    var opts = { method: method, credentials: 'same-origin' };
    if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          var msg = (d && d.detail) ? d.detail : ('HTTP ' + r.status);
          throw new Error(msg);
        });
      }
      return r.json();
    });
  }

  function relTime(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      var diff = Date.now() - d.getTime();
      var s = Math.abs(Math.floor(diff / 1000));
      if (s < 60) return 'just now';
      var m = Math.floor(s / 60);
      if (m < 60) return m + 'm ago';
      var h = Math.floor(m / 60);
      if (h < 24) return h + 'h ago';
      return Math.floor(h / 24) + 'd ago';
    } catch (e) { return '—'; }
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }); }
    catch (e) { return iso; }
  }

  /* ── toast helper ─────────────────────────────────────────────────────── */

  function showToast(msg, variant) {
    var t = el('div', 'mf-toast mf-toast--' + (variant || 'info'));
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 250);
    }, 2600);
  }

  /* ── modal helpers ────────────────────────────────────────────────────── */

  /**
   * Simple two-button confirmation modal.
   * onConfirm is called if user clicks the confirm button.
   * Returns a dismiss function.
   */
  function openConfirmModal(opts) {
    // opts: { title, message, confirmLabel, confirmVariant, onConfirm }
    var overlay = el('div', 'mf-adm__modal-overlay');
    var box = el('div', 'mf-adm__modal');

    var titleEl = el('h3', 'mf-adm__modal-title');
    titleEl.textContent = opts.title || 'Confirm';
    box.appendChild(titleEl);

    var msgEl = el('p', 'mf-adm__modal-msg');
    msgEl.textContent = opts.message || '';
    box.appendChild(msgEl);

    var actions = el('div', 'mf-adm__modal-actions');

    var cancelBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    cancelBtn.textContent = 'Cancel';
    actions.appendChild(cancelBtn);

    var confirmBtn = el('button', 'mf-btn mf-btn--' + (opts.confirmVariant || 'danger') + ' mf-btn--sm');
    confirmBtn.textContent = opts.confirmLabel || 'Confirm';
    actions.appendChild(confirmBtn);

    box.appendChild(actions);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    function dismiss() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }

    cancelBtn.addEventListener('click', dismiss);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) dismiss();
    });
    confirmBtn.addEventListener('click', function () {
      dismiss();
      opts.onConfirm();
    });

    return dismiss;
  }

  /**
   * Typed-confirmation modal. User must type the confirmWord to proceed.
   * Used for the most destructive operations (db restore).
   */
  function openTypedConfirmModal(opts) {
    // opts: { title, message, confirmWord, confirmLabel, onConfirm }
    var word = opts.confirmWord || 'CONFIRM';
    var overlay = el('div', 'mf-adm__modal-overlay');
    var box = el('div', 'mf-adm__modal');

    var titleEl = el('h3', 'mf-adm__modal-title');
    titleEl.textContent = opts.title || 'Confirm';
    box.appendChild(titleEl);

    var msgEl = el('p', 'mf-adm__modal-msg');
    msgEl.textContent = opts.message || '';
    box.appendChild(msgEl);

    var instrEl = el('p', 'mf-adm__modal-instr');
    instrEl.appendChild(txt('Type '));
    var code = el('code', 'mf-adm__modal-code');
    code.textContent = word;
    instrEl.appendChild(code);
    instrEl.appendChild(txt(' to continue:'));
    box.appendChild(instrEl);

    var input = el('input', 'mf-adm__modal-input');
    input.type = 'text';
    input.placeholder = word;
    input.autocomplete = 'off';
    box.appendChild(input);

    var actions = el('div', 'mf-adm__modal-actions');

    var cancelBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    cancelBtn.textContent = 'Cancel';
    actions.appendChild(cancelBtn);

    var confirmBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
    confirmBtn.textContent = opts.confirmLabel || 'Confirm';
    confirmBtn.disabled = true;
    actions.appendChild(confirmBtn);

    box.appendChild(actions);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    function dismiss() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }

    input.addEventListener('input', function () {
      confirmBtn.disabled = input.value !== word;
    });

    cancelBtn.addEventListener('click', dismiss);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) dismiss();
    });
    confirmBtn.addEventListener('click', function () {
      if (input.value !== word) return;
      dismiss();
      opts.onConfirm();
    });

    setTimeout(function () { input.focus(); }, 50);
    return dismiss;
  }

  /* ── role-gate guard ─────────────────────────────────────────────────── */

  function _renderRoleGuard(slot) {
    var wrap = el('div', 'mf-adm__guard');
    var icon = el('div', 'mf-adm__guard-icon');
    icon.textContent = '⛔';
    wrap.appendChild(icon);

    var title = el('h2', 'mf-adm__guard-title');
    title.textContent = 'Admin access required';
    wrap.appendChild(title);

    var msg = el('p', 'mf-adm__guard-msg');
    msg.textContent = 'This page is restricted to administrators. Redirecting you to Settings…';
    wrap.appendChild(msg);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(wrap);

    setTimeout(function () { window.location.href = '/settings'; }, 2000);
  }

  /* ── section: API Keys ───────────────────────────────────────────────── */

  var _newRawKey = '';

  function _renderApiKeys(contentSlot) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var head = el('h2', 'mf-adm__section-head');
    head.textContent = 'API Keys';
    contentSlot.appendChild(head);

    var desc = el('p', 'mf-adm__section-desc');
    desc.textContent = 'Service account keys for external integrations. Keys are shown once on creation and cannot be retrieved again.';
    contentSlot.appendChild(desc);

    // New-key success banner (hidden by default)
    var banner = el('div', 'mf-adm__key-banner mf-adm__key-banner--hidden');
    var bannerMsg = el('strong');
    bannerMsg.textContent = 'New key generated. Copy it now — it will not be shown again.';
    banner.appendChild(bannerMsg);

    var keyDisplay = el('div', 'mf-adm__key-display');
    var keyCode = el('code', 'mf-adm__key-code');
    keyDisplay.appendChild(keyCode);

    var copyBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', function () {
      if (!_newRawKey) return;
      navigator.clipboard.writeText(_newRawKey).then(function () {
        showToast('Key copied to clipboard');
      }).catch(function () {
        showToast('Copy failed — select and copy manually', 'error');
      });
    });
    keyDisplay.appendChild(copyBtn);
    banner.appendChild(keyDisplay);
    contentSlot.appendChild(banner);

    // Create form
    var form = el('div', 'mf-adm__key-form');

    var labelInput = el('input', 'mf-adm__key-label-input');
    labelInput.type = 'text';
    labelInput.placeholder = 'Key label (e.g. unioncore-prod)';
    form.appendChild(labelInput);

    var genBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    genBtn.textContent = 'Generate Key';
    genBtn.addEventListener('click', function () {
      var label = labelInput.value.trim();
      if (!label) { showToast('Enter a label for the key', 'error'); return; }
      genBtn.disabled = true;
      genBtn.textContent = 'Generating…';
      apiFetch('POST', '/api/admin/api-keys', { label: label })
        .then(function (result) {
          _newRawKey = result.raw_key;
          keyCode.textContent = result.raw_key;
          banner.classList.remove('mf-adm__key-banner--hidden');
          labelInput.value = '';
          _loadKeys(tbody, emptyRow);
        })
        .catch(function (e) {
          showToast('Failed to generate key: ' + e.message, 'error');
        })
        .finally(function () {
          genBtn.disabled = false;
          genBtn.textContent = 'Generate Key';
        });
    });
    form.appendChild(genBtn);
    contentSlot.appendChild(form);

    // Keys table
    var table = el('table', 'mf-adm__table');
    var thead = el('thead');
    var headRow = el('tr');
    ['Label', 'Key ID', 'Created', 'Last Used', 'Status', ''].forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    var emptyRow = el('tr');
    var emptyCell = el('td', 'mf-adm__table-empty');
    emptyCell.colSpan = 6;
    emptyCell.textContent = 'Loading…';
    emptyRow.appendChild(emptyCell);
    tbody.appendChild(emptyRow);
    table.appendChild(tbody);
    contentSlot.appendChild(table);

    _loadKeys(tbody, emptyRow);
  }

  function _loadKeys(tbody, emptyRow) {
    apiFetch('GET', '/api/admin/api-keys')
      .then(function (keys) {
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        if (!keys || !keys.length) {
          var r = el('tr');
          var c = el('td', 'mf-adm__table-empty');
          c.colSpan = 6;
          c.textContent = 'No API keys yet.';
          r.appendChild(c);
          tbody.appendChild(r);
          return;
        }
        keys.forEach(function (k) {
          var row = el('tr');

          var tdLabel = el('td', 'mf-adm__table-name');
          tdLabel.textContent = k.label;
          row.appendChild(tdLabel);

          var tdId = el('td');
          var code = el('code', 'mf-adm__key-id');
          code.textContent = (k.key_id || '').substring(0, 12) + '…';
          tdId.appendChild(code);
          row.appendChild(tdId);

          var tdCreated = el('td', 'mf-adm__table-meta');
          tdCreated.textContent = fmtDate(k.created_at);
          row.appendChild(tdCreated);

          var tdUsed = el('td', 'mf-adm__table-meta');
          tdUsed.textContent = k.last_used_at ? relTime(k.last_used_at) : 'Never';
          row.appendChild(tdUsed);

          var tdStatus = el('td');
          var pill = el('span', 'mf-adm__pill mf-adm__pill--' + (k.is_active ? 'ok' : 'bad'));
          pill.textContent = k.is_active ? 'Active' : 'Revoked';
          tdStatus.appendChild(pill);
          row.appendChild(tdStatus);

          var tdAction = el('td');
          if (k.is_active) {
            var revokeBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm mf-adm__btn-danger');
            revokeBtn.textContent = 'Revoke';
            revokeBtn.addEventListener('click', function () {
              openConfirmModal({
                title: 'Revoke API Key',
                message: 'Revoke the key "' + k.label + '"? This cannot be undone — any integrations using it will stop working immediately.',
                confirmLabel: 'Revoke Key',
                onConfirm: function () {
                  apiFetch('DELETE', '/api/admin/api-keys/' + k.key_id)
                    .then(function () {
                      showToast('Key revoked');
                      _loadKeys(tbody, emptyRow);
                    })
                    .catch(function (e) {
                      showToast('Failed to revoke key: ' + e.message, 'error');
                    });
                }
              });
            });
            tdAction.appendChild(revokeBtn);
          }
          row.appendChild(tdAction);
          tbody.appendChild(row);
        });
      })
      .catch(function (e) {
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        var r = el('tr');
        var c = el('td', 'mf-adm__table-empty mf-adm__table-error');
        c.colSpan = 6;
        c.textContent = 'Failed to load keys: ' + e.message;
        r.appendChild(c);
        tbody.appendChild(r);
      });
  }

  /* ── section: Users ──────────────────────────────────────────────────── */

  function _renderUsers(contentSlot) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var head = el('h2', 'mf-adm__section-head');
    head.textContent = 'Users';
    contentSlot.appendChild(head);

    var desc = el('p', 'mf-adm__section-desc');
    desc.textContent = 'All user accounts registered in MarkFlow. Read-only — user management is handled via your identity provider.';
    contentSlot.appendChild(desc);

    var table = el('table', 'mf-adm__table');
    var thead = el('thead');
    var headRow = el('tr');
    ['Name', 'Email', 'Role', 'Last Active'].forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    var loadRow = el('tr');
    var loadCell = el('td', 'mf-adm__table-empty');
    loadCell.colSpan = 4;
    loadCell.textContent = 'Loading…';
    loadRow.appendChild(loadCell);
    tbody.appendChild(loadRow);
    table.appendChild(tbody);
    contentSlot.appendChild(table);

    apiFetch('GET', '/api/admin/users')
      .then(function (data) {
        var users = Array.isArray(data) ? data : (data.users || []);
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        if (!users.length) {
          var r = el('tr');
          var c = el('td', 'mf-adm__table-empty');
          c.colSpan = 4;
          c.textContent = 'No users found.';
          r.appendChild(c);
          tbody.appendChild(r);
          return;
        }
        users.forEach(function (u) {
          var row = el('tr');

          var tdName = el('td', 'mf-adm__table-name');
          tdName.textContent = u.name || u.display_name || '—';
          row.appendChild(tdName);

          var tdEmail = el('td', 'mf-adm__table-meta');
          tdEmail.textContent = u.email || '—';
          row.appendChild(tdEmail);

          var tdRole = el('td');
          var pill = el('span', 'mf-adm__pill mf-adm__pill--role');
          pill.textContent = u.role || 'member';
          tdRole.appendChild(pill);
          row.appendChild(tdRole);

          var tdActive = el('td', 'mf-adm__table-meta');
          tdActive.textContent = u.last_active ? relTime(u.last_active) : '—';
          row.appendChild(tdActive);

          tbody.appendChild(row);
        });
      })
      .catch(function (e) {
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        var r = el('tr');
        var c = el('td', 'mf-adm__table-empty mf-adm__table-error');
        c.colSpan = 4;
        c.textContent = 'User list unavailable: ' + e.message;
        r.appendChild(c);
        tbody.appendChild(r);
      });
  }

  /* ── section: System Actions ─────────────────────────────────────────── */

  function _makeActionCard(opts) {
    // opts: { title, desc, btnLabel, btnVariant, dangerous, onRun }
    var card = el('div', 'mf-adm__action-card' + (opts.dangerous ? ' mf-adm__action-card--danger' : ''));

    var cardTitle = el('h3', 'mf-adm__action-card-title');
    cardTitle.textContent = opts.title;
    card.appendChild(cardTitle);

    var cardDesc = el('p', 'mf-adm__action-card-desc');
    cardDesc.textContent = opts.desc;
    card.appendChild(cardDesc);

    var resultEl = el('div', 'mf-adm__action-result mf-adm__action-result--hidden');
    card.appendChild(resultEl);

    var btn = el('button', 'mf-btn mf-btn--' + (opts.btnVariant || 'ghost') + ' mf-btn--sm');
    btn.textContent = opts.btnLabel || 'Run';
    btn.addEventListener('click', function () {
      opts.onRun(btn, resultEl);
    });
    card.appendChild(btn);

    return card;
  }

  function _runAction(url, btn, resultEl, originalLabel) {
    btn.disabled = true;
    btn.textContent = 'Running…';
    resultEl.className = 'mf-adm__action-result mf-adm__action-result--running';
    resultEl.textContent = 'Running…';

    apiFetch('POST', url)
      .then(function (data) {
        resultEl.className = 'mf-adm__action-result mf-adm__action-result--ok';
        resultEl.textContent = (data && data.message) ? data.message : '✓ Done';
      })
      .catch(function (e) {
        resultEl.className = 'mf-adm__action-result mf-adm__action-result--error';
        resultEl.textContent = '✗ ' + e.message;
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = originalLabel;
      });
  }

  function _renderSystemActions(contentSlot) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var head = el('h2', 'mf-adm__section-head');
    head.textContent = 'System Actions';
    contentSlot.appendChild(head);

    var desc = el('p', 'mf-adm__section-desc');
    desc.textContent = 'Operator controls for MarkFlow background services. Destructive actions require confirmation.';
    contentSlot.appendChild(desc);

    var grid = el('div', 'mf-adm__action-grid');

    // Restart Watchers — moderate risk, requires click confirmation
    grid.appendChild(_makeActionCard({
      title: 'Restart Watchers',
      desc: 'Restart the filesystem watcher processes. Active scans will be interrupted and restart automatically.',
      btnLabel: 'Restart Watchers',
      btnVariant: 'ghost',
      dangerous: false,
      onRun: function (btn, resultEl) {
        openConfirmModal({
          title: 'Restart Watchers',
          message: 'This will interrupt any active filesystem scans. They will restart automatically. Continue?',
          confirmLabel: 'Restart',
          confirmVariant: 'primary',
          onConfirm: function () {
            _runAction('/api/admin/system/restart-watchers', btn, resultEl, 'Restart Watchers');
          }
        });
      }
    }));

    // Force Rescan — moderate risk
    grid.appendChild(_makeActionCard({
      title: 'Force Rescan',
      desc: 'Trigger an immediate full filesystem scan outside the normal schedule. Useful after bulk file changes.',
      btnLabel: 'Force Rescan',
      btnVariant: 'ghost',
      dangerous: false,
      onRun: function (btn, resultEl) {
        openConfirmModal({
          title: 'Force Rescan',
          message: 'Start a full filesystem rescan now? This may take several minutes on large repositories.',
          confirmLabel: 'Start Rescan',
          confirmVariant: 'primary',
          onConfirm: function () {
            _runAction('/api/admin/system/force-rescan', btn, resultEl, 'Force Rescan');
          }
        });
      }
    }));

    // Flush Cache — low risk, no confirmation needed
    grid.appendChild(_makeActionCard({
      title: 'Flush Cache',
      desc: 'Clear in-memory caches (search index hot cache, disk usage cache, preference cache). Useful after external DB changes.',
      btnLabel: 'Flush Cache',
      btnVariant: 'ghost',
      dangerous: false,
      onRun: function (btn, resultEl) {
        _runAction('/api/admin/system/flush-cache', btn, resultEl, 'Flush Cache');
      }
    }));

    contentSlot.appendChild(grid);
  }

  /* ── section: Database Tools ─────────────────────────────────────────── */

  function _renderDbTools(contentSlot) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var head = el('h2', 'mf-adm__section-head');
    head.textContent = 'Database Tools';
    contentSlot.appendChild(head);

    var desc = el('p', 'mf-adm__section-desc');
    desc.textContent = 'Run maintenance operations against the active SQLite database. For detailed diagnostics see ';
    var dbLink = el('a', 'mf-adm__inline-link');
    dbLink.href = '/settings/db-health';
    dbLink.textContent = 'DB Health';
    desc.appendChild(dbLink);
    desc.appendChild(txt('.'));
    contentSlot.appendChild(desc);

    var grid = el('div', 'mf-adm__action-grid');

    // Vacuum — safe
    grid.appendChild(_makeActionCard({
      title: 'Vacuum',
      desc: 'Reclaim unused database pages and rebuild the file. Safe to run at any time. May take a few seconds.',
      btnLabel: 'Run Vacuum',
      btnVariant: 'ghost',
      dangerous: false,
      onRun: function (btn, resultEl) {
        _runAction('/api/admin/db/vacuum', btn, resultEl, 'Run Vacuum');
      }
    }));

    // Integrity Check — slow
    grid.appendChild(_makeActionCard({
      title: 'Integrity Check',
      desc: 'Full content verification of the database. May take 30+ seconds on large databases. Read-only.',
      btnLabel: 'Run Integrity Check',
      btnVariant: 'ghost',
      dangerous: false,
      onRun: function (btn, resultEl) {
        var origLabel = 'Run Integrity Check';
        btn.disabled = true;
        btn.textContent = 'Running…';
        resultEl.className = 'mf-adm__action-result mf-adm__action-result--running';
        resultEl.textContent = 'Running (may take 30+ seconds)…';

        apiFetch('POST', '/api/admin/db/integrity')
          .then(function (data) {
            if (data.ok === false) {
              resultEl.className = 'mf-adm__action-result mf-adm__action-result--error';
              var errMsg = (data.errors || []).join(', ') || data.error || 'Issues found';
              resultEl.textContent = '✗ ' + errMsg;
            } else {
              resultEl.className = 'mf-adm__action-result mf-adm__action-result--ok';
              resultEl.textContent = '✓ No integrity errors found';
            }
          })
          .catch(function (e) {
            resultEl.className = 'mf-adm__action-result mf-adm__action-result--error';
            resultEl.textContent = '✗ ' + e.message;
          })
          .finally(function () {
            btn.disabled = false;
            btn.textContent = origLabel;
          });
      }
    }));

    // Backup
    grid.appendChild(_makeActionCard({
      title: 'Backup',
      desc: 'Create a timestamped backup of the database on the server. Does not interrupt running jobs.',
      btnLabel: 'Create Backup',
      btnVariant: 'ghost',
      dangerous: false,
      onRun: function (btn, resultEl) {
        var origLabel = 'Create Backup';
        btn.disabled = true;
        btn.textContent = 'Backing up…';
        resultEl.className = 'mf-adm__action-result mf-adm__action-result--running';
        resultEl.textContent = 'Creating backup…';

        apiFetch('POST', '/api/admin/db/backup')
          .then(function (data) {
            resultEl.className = 'mf-adm__action-result mf-adm__action-result--ok';
            var saved = data.path || data.backup_path || '';
            resultEl.textContent = '✓ Backup saved' + (saved ? ': ' + saved : '');
          })
          .catch(function (e) {
            resultEl.className = 'mf-adm__action-result mf-adm__action-result--error';
            resultEl.textContent = '✗ Backup failed: ' + e.message;
          })
          .finally(function () {
            btn.disabled = false;
            btn.textContent = origLabel;
          });
      }
    }));

    // Restore — highly destructive, typed confirmation required
    grid.appendChild(_makeActionCard({
      title: 'Restore from Backup',
      desc: 'Overwrite the live database with a backup file. DESTRUCTIVE — all data since the backup will be lost. Stop all jobs first.',
      btnLabel: 'Restore…',
      btnVariant: 'ghost',
      dangerous: true,
      onRun: function (btn, resultEl) {
        openTypedConfirmModal({
          title: 'Restore Database',
          message: 'This will PERMANENTLY overwrite the live database with a backup. All data since the backup was created will be lost. Stop all running jobs before proceeding.',
          confirmWord: 'CONFIRM',
          confirmLabel: 'Restore Database',
          onConfirm: function () {
            _showRestorePathModal(btn, resultEl);
          }
        });
      }
    }));

    contentSlot.appendChild(grid);
  }

  function _showRestorePathModal(actionBtn, resultEl) {
    var overlay = el('div', 'mf-adm__modal-overlay');
    var box = el('div', 'mf-adm__modal');

    var titleEl = el('h3', 'mf-adm__modal-title');
    titleEl.textContent = 'Select Backup to Restore';
    box.appendChild(titleEl);

    var msgEl = el('p', 'mf-adm__modal-msg');
    msgEl.textContent = 'Enter the server-side backup filename (from the Backups directory) or upload a backup file:';
    box.appendChild(msgEl);

    var pathInput = el('input', 'mf-adm__modal-input');
    pathInput.type = 'text';
    pathInput.placeholder = 'backup-filename.db (server-side)';
    box.appendChild(pathInput);

    var uploadLabel = el('label', 'mf-adm__modal-upload-label');
    uploadLabel.textContent = 'Or upload a file:';
    box.appendChild(uploadLabel);

    var fileInput = el('input');
    fileInput.type = 'file';
    fileInput.accept = '.db,.sqlite,.sqlite3';
    fileInput.className = 'mf-adm__modal-file-input';
    box.appendChild(fileInput);

    var actions = el('div', 'mf-adm__modal-actions');

    var cancelBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    cancelBtn.textContent = 'Cancel';
    actions.appendChild(cancelBtn);

    var confirmBtn = el('button', 'mf-btn mf-btn--danger mf-btn--sm');
    confirmBtn.textContent = 'Restore Now';
    actions.appendChild(confirmBtn);

    box.appendChild(actions);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    function dismiss() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }

    cancelBtn.addEventListener('click', dismiss);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) dismiss();
    });

    confirmBtn.addEventListener('click', function () {
      var backupPath = pathInput.value.trim();
      var file = fileInput.files && fileInput.files[0];

      if (!backupPath && !file) {
        showToast('Enter a backup path or select a file', 'error');
        return;
      }
      if (backupPath && file) {
        showToast('Use server path OR file upload, not both', 'error');
        return;
      }

      dismiss();

      actionBtn.disabled = true;
      actionBtn.textContent = 'Restoring…';
      resultEl.className = 'mf-adm__action-result mf-adm__action-result--running';
      resultEl.textContent = 'Restoring database…';

      var formData = new FormData();
      if (file) {
        formData.append('file', file);
      } else {
        formData.append('backup_path', backupPath);
      }

      fetch('/api/db/restore', {
        method: 'POST',
        credentials: 'same-origin',
        body: formData
      })
        .then(function (r) {
          return r.json().then(function (d) {
            if (!r.ok) throw new Error((d && d.detail) ? d.detail : 'HTTP ' + r.status);
            return d;
          });
        })
        .then(function (data) {
          resultEl.className = 'mf-adm__action-result mf-adm__action-result--ok';
          resultEl.textContent = '✓ Database restored successfully';
        })
        .catch(function (e) {
          resultEl.className = 'mf-adm__action-result mf-adm__action-result--error';
          resultEl.textContent = '✗ Restore failed: ' + e.message;
        })
        .finally(function () {
          actionBtn.disabled = false;
          actionBtn.textContent = 'Restore…';
        });
    });
  }

  /* ── section: Log Levels ─────────────────────────────────────────────── */

  function _renderLogLevels(contentSlot) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var head = el('h2', 'mf-adm__section-head');
    head.textContent = 'Log Levels';
    contentSlot.appendChild(head);

    var desc = el('p', 'mf-adm__section-desc');
    desc.textContent = 'Adjust per-subsystem log verbosity at runtime. Changes take effect immediately without a restart.';
    contentSlot.appendChild(desc);

    var linkCard = el('div', 'mf-adm__link-card');
    var linkTitle = el('div', 'mf-adm__link-card-title');
    linkTitle.textContent = 'Log Level Manager';
    linkCard.appendChild(linkTitle);

    var linkDesc = el('p', 'mf-adm__link-card-desc');
    linkDesc.textContent = 'Log Levels has a dedicated page with the full list of subsystems and inline controls for each level.';
    linkCard.appendChild(linkDesc);

    var link = el('a', 'mf-btn mf-btn--ghost mf-btn--sm');
    link.href = '/log-levels';
    link.textContent = 'Open Log Levels →';
    linkCard.appendChild(link);

    contentSlot.appendChild(linkCard);
  }

  /* ── sidebar nav + section router ───────────────────────────────────── */

  var SECTIONS = [
    { id: 'api-keys',        label: 'API Keys',        render: _renderApiKeys },
    { id: 'users',           label: 'Users',           render: _renderUsers },
    { id: 'system-actions',  label: 'System Actions',  render: _renderSystemActions },
    { id: 'database',        label: 'Database Tools',  render: _renderDbTools },
    { id: 'log-levels',      label: 'Log Levels',      render: _renderLogLevels },
  ];

  /* ── mount ───────────────────────────────────────────────────────────── */

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSettingsAdmin.mount: slot is required');
    opts = opts || {};

    var me = opts.me || {};

    // Role gate — must be admin
    if (me.role !== 'admin') {
      _renderRoleGuard(slot);
      return;
    }

    var activeSection = opts.activeSection || 'api-keys';

    var body = el('div', 'mf-adm__body');

    // Breadcrumb
    var breadcrumb = el('a', 'mf-adm__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    // Headline
    var headline = el('h1', 'mf-adm__headline');
    headline.textContent = 'Admin.';
    body.appendChild(headline);

    // Layout: sidebar + content
    var detail = el('div', 'mf-adm__detail');

    var sidebar = el('nav', 'mf-adm__sidebar');
    SECTIONS.forEach(function (sec) {
      var isActive = sec.id === activeSection;
      var link = el('a', 'mf-adm__sidebar-link' + (isActive ? ' mf-adm__sidebar-link--active' : ''));
      link.href = '#' + sec.id;
      link.textContent = sec.label;
      link.addEventListener('click', function (e) {
        e.preventDefault();
        activeSection = sec.id;
        sidebar.querySelectorAll('.mf-adm__sidebar-link').forEach(function (l) {
          l.classList.remove('mf-adm__sidebar-link--active');
        });
        link.classList.add('mf-adm__sidebar-link--active');
        sec.render(contentSlot);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-adm__content');

    // Render initial section
    var initialSec = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === activeSection) { initialSec = SECTIONS[i]; break; }
    }
    if (initialSec) initialSec.render(contentSlot);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFSettingsAdmin = { mount: mount };
})(window);
