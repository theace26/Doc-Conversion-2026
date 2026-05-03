/* MFSettingsLocations — Locations CRUD settings sub-page.
 *
 * Usage:
 *   MFSettingsLocations.mount(root, opts);
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout (no innerHTML with template strings).
 * BEM prefix: mf-loc__*
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'sources',    label: 'Source locations' },
    { id: 'output',     label: 'Output locations' },
    { id: 'both',       label: 'Source & Output' },
    { id: 'exclusions', label: 'Exclusions' },
  ];

  // ── DOM helpers ────────────────────────────────────────────────────────────

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function txt(str) {
    return document.createTextNode(str || '');
  }

  function esc(str) {
    var d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  // ── Spinner ────────────────────────────────────────────────────────────────

  function makeSpinner() {
    var s = el('span', 'mf-loc__spinner');
    return s;
  }

  // ── Status pill (accessible / not accessible) ──────────────────────────────

  function makeStatusPill(accessible, writable, count) {
    if (accessible === null) {
      var pill = el('span', 'mf-loc__pill mf-loc__pill--checking');
      pill.appendChild(makeSpinner());
      pill.appendChild(txt(' Checking…'));
      return pill;
    }
    if (!accessible) {
      var errPill = el('span', 'mf-loc__pill mf-loc__pill--bad');
      errPill.textContent = 'Not accessible';
      return errPill;
    }
    var okPill = el('span', 'mf-loc__pill mf-loc__pill--ok');
    var parts = ['Accessible'];
    if (writable === true) parts.push('Writable');
    else if (writable === false) parts.push('Read-only');
    if (count != null) parts.push('~' + count.toLocaleString() + ' files');
    okPill.textContent = parts.join(' · ');
    return okPill;
  }

  // ── Card builder (location or exclusion) ──────────────────────────────────

  function _makeCard(item, onEdit, onDelete) {
    var card = el('div', 'mf-loc__card');
    card.id = 'mf-loc-card-' + item.id;

    var header = el('div', 'mf-loc__card-header');

    var nameSpan = el('span', 'mf-loc__card-name');
    nameSpan.textContent = item.name;
    header.appendChild(nameSpan);

    var actions = el('div', 'mf-loc__card-actions');

    var editBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    editBtn.type = 'button';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', function () { onEdit(item); });
    actions.appendChild(editBtn);

    var delBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    delBtn.type = 'button';
    delBtn.id = 'mf-loc-del-' + item.id;
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', function () { onDelete(item, card, delBtn); });
    actions.appendChild(delBtn);

    header.appendChild(actions);
    card.appendChild(header);

    var pathLine = el('div', 'mf-loc__card-path');
    pathLine.textContent = item.path;
    if (item.notes) {
      var noteDot = txt(' · ');
      var noteSpan = el('span', 'mf-loc__card-notes');
      noteSpan.textContent = item.notes;
      pathLine.appendChild(noteDot);
      pathLine.appendChild(noteSpan);
    }
    card.appendChild(pathLine);

    var metaRow = el('div', 'mf-loc__card-meta');
    var statusSlot = el('span', 'mf-loc__status-slot');
    statusSlot.id = 'mf-loc-status-' + item.id;
    statusSlot.appendChild(makeStatusPill(null, null, null));
    metaRow.appendChild(statusSlot);
    card.appendChild(metaRow);

    return card;
  }

  function _makeExclCard(item, onEdit, onDelete) {
    var card = el('div', 'mf-loc__card');
    card.id = 'mf-loc-excl-card-' + item.id;

    var header = el('div', 'mf-loc__card-header');

    var nameSpan = el('span', 'mf-loc__card-name');
    nameSpan.textContent = item.name;
    header.appendChild(nameSpan);

    var actions = el('div', 'mf-loc__card-actions');

    var editBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    editBtn.type = 'button';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', function () { onEdit(item); });
    actions.appendChild(editBtn);

    var delBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    delBtn.type = 'button';
    delBtn.id = 'mf-loc-excl-del-' + item.id;
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', function () { onDelete(item, card, delBtn); });
    actions.appendChild(delBtn);

    header.appendChild(actions);
    card.appendChild(header);

    var pathLine = el('div', 'mf-loc__card-path');
    pathLine.textContent = item.path;
    if (item.notes) {
      var noteDot = txt(' · ');
      var noteSpan = el('span', 'mf-loc__card-notes');
      noteSpan.textContent = item.notes;
      pathLine.appendChild(noteDot);
      pathLine.appendChild(noteSpan);
    }
    card.appendChild(pathLine);

    return card;
  }

  // ── Empty state ────────────────────────────────────────────────────────────

  function _makeEmpty(message) {
    var d = el('div', 'mf-loc__empty');
    d.textContent = message || 'None configured.';
    return d;
  }

  // ── Toast helper ───────────────────────────────────────────────────────────

  function _toast(msg, kind) {
    var t = el('div', 'mf-toast mf-toast--' + (kind || 'info'));
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 250);
    }, 2800);
  }

  // ── API helpers ────────────────────────────────────────────────────────────

  function _fetch(method, url, body) {
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          var err = new Error(data.detail || (method + ' ' + url + ' failed: ' + r.status));
          err.data = data;
          throw err;
        });
      }
      return r.json().catch(function () { return {}; });
    });
  }

  function apiGet(url) { return _fetch('GET', url); }
  function apiPost(url, body) { return _fetch('POST', url, body); }
  function apiPut(url, body) { return _fetch('PUT', url, body); }
  function apiDel(url) { return _fetch('DELETE', url); }

  // ── Validate badge (async) ─────────────────────────────────────────────────

  function _fetchBadge(itemId, path, prefix) {
    prefix = prefix || 'mf-loc-status-';
    var slot = document.getElementById(prefix + itemId);
    if (!slot) return;
    apiGet('/api/locations/validate?path=' + encodeURIComponent(path))
      .then(function (r) {
        while (slot.firstChild) slot.removeChild(slot.firstChild);
        var accessible = !!r.accessible;
        var writable = r.writable != null ? !!r.writable : null;
        if (!accessible && r.error === 'not_a_container_path') {
          var bp = el('span', 'mf-loc__pill mf-loc__pill--bad');
          bp.textContent = 'Not a container path';
          slot.appendChild(bp);
        } else {
          slot.appendChild(makeStatusPill(accessible, writable, r.file_count_estimate));
        }
      })
      .catch(function () {
        while (slot.firstChild) slot.removeChild(slot.firstChild);
        var ep = el('span', 'mf-loc__pill mf-loc__pill--bad');
        ep.textContent = 'Check failed';
        slot.appendChild(ep);
      });
  }

  // ── Form builder ──────────────────────────────────────────────────────────

  function _buildLocForm(opts) {
    /*
     * opts: {
     *   isExclusion: bool,
     *   onSave(data): Promise,
     *   onCancel(),
     * }
     * Returns { formEl, populate(item|null), reset() }
     */
    var isExcl = !!opts.isExclusion;
    var wrap = el('div', 'mf-loc__form-wrap');

    // Label
    var labelRow = el('div', 'mf-loc__form-row');
    var lblLabel = el('label', 'mf-stg__field-label');
    lblLabel.textContent = 'Name';
    lblLabel.htmlFor = isExcl ? 'mf-loc-excl-name' : 'mf-loc-name';
    var nameInput = el('input', 'mf-stg__field-input');
    nameInput.type = 'text';
    nameInput.id = isExcl ? 'mf-loc-excl-name' : 'mf-loc-name';
    nameInput.maxLength = 80;
    nameInput.placeholder = isExcl ? 'e.g. Old Archives' : 'e.g. Company Share';
    labelRow.appendChild(lblLabel);
    labelRow.appendChild(nameInput);
    wrap.appendChild(labelRow);

    // Path
    var pathRow = el('div', 'mf-loc__form-row');
    var pathLabel = el('label', 'mf-stg__field-label');
    pathLabel.textContent = 'Path';
    pathLabel.htmlFor = isExcl ? 'mf-loc-excl-path' : 'mf-loc-path';
    var pathInputWrap = el('div', 'mf-loc__path-input-wrap');
    var pathInput = el('input', 'mf-stg__field-input mf-loc__path-input');
    pathInput.type = 'text';
    pathInput.id = isExcl ? 'mf-loc-excl-path' : 'mf-loc-path';
    pathInput.placeholder = '/host/...';
    var browseBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    browseBtn.type = 'button';
    browseBtn.textContent = 'Browse…';
    var checkBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    checkBtn.type = 'button';
    checkBtn.textContent = 'Check Access';
    pathInputWrap.appendChild(pathInput);
    pathInputWrap.appendChild(browseBtn);
    pathInputWrap.appendChild(checkBtn);
    pathRow.appendChild(pathLabel);
    pathRow.appendChild(pathInputWrap);
    wrap.appendChild(pathRow);

    // Validate result
    var validateMsg = el('div', 'mf-loc__validate-msg');
    wrap.appendChild(validateMsg);

    // Type selector (locations only)
    var typeSelect = null;
    if (!isExcl) {
      var typeRow = el('div', 'mf-loc__form-row');
      var typeLabel = el('label', 'mf-stg__field-label');
      typeLabel.textContent = 'Type';
      typeLabel.htmlFor = 'mf-loc-type';
      typeSelect = el('select', 'mf-stg__field-input');
      typeSelect.id = 'mf-loc-type';
      [['source', 'Source'], ['output', 'Output'], ['both', 'Both (Source & Output)']].forEach(function (pair) {
        var opt = document.createElement('option');
        opt.value = pair[0];
        opt.textContent = pair[1];
        typeSelect.appendChild(opt);
      });
      typeRow.appendChild(typeLabel);
      typeRow.appendChild(typeSelect);
      wrap.appendChild(typeRow);

      // Path-type compatibility check on change
      typeSelect.addEventListener('change', function () {
        var t = typeSelect.value;
        var p = pathInput.value;
        if (t === 'source' && p.startsWith('/mnt/output-repo')) {
          pathInput.value = '';
          validateMsg.textContent = 'Path cleared — source locations must be under /host/.';
          validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
        } else if (t === 'output' && p.startsWith('/host/')) {
          pathInput.value = '';
          validateMsg.textContent = 'Path cleared — output locations use /mnt/output-repo/.';
          validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
        }
      });
    }

    // Notes
    var notesRow = el('div', 'mf-loc__form-row');
    var notesLabel = el('label', 'mf-stg__field-label');
    notesLabel.textContent = 'Notes';
    notesLabel.htmlFor = isExcl ? 'mf-loc-excl-notes' : 'mf-loc-notes';
    var notesInput = el('textarea', 'mf-stg__field-input mf-loc__notes-input');
    notesInput.id = isExcl ? 'mf-loc-excl-notes' : 'mf-loc-notes';
    notesInput.maxLength = 500;
    notesInput.rows = 2;
    notesInput.placeholder = isExcl ? 'Optional reason for exclusion' : 'Optional description';
    notesRow.appendChild(notesLabel);
    notesRow.appendChild(notesInput);
    wrap.appendChild(notesRow);

    // Actions
    var actionsRow = el('div', 'mf-loc__form-actions');
    var saveBtn = el('button', 'mf-btn mf-btn--primary');
    saveBtn.type = 'button';
    saveBtn.textContent = 'Save';
    var cancelBtn = el('button', 'mf-btn mf-btn--ghost');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'Cancel';
    actionsRow.appendChild(saveBtn);
    actionsRow.appendChild(cancelBtn);
    wrap.appendChild(actionsRow);

    // ── Check-access logic ───────────────────────────────────────────────

    function doCheckAccess() {
      var p = pathInput.value.trim();
      if (!p) {
        validateMsg.textContent = 'Enter a path first.';
        validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
        return;
      }
      while (validateMsg.firstChild) validateMsg.removeChild(validateMsg.firstChild);
      var sp = makeSpinner();
      validateMsg.appendChild(sp);
      validateMsg.appendChild(txt(' Checking…'));
      validateMsg.className = 'mf-loc__validate-msg';

      apiGet('/api/locations/validate?path=' + encodeURIComponent(p))
        .then(function (r) {
          while (validateMsg.firstChild) validateMsg.removeChild(validateMsg.firstChild);
          if (r.error === 'not_a_container_path') {
            validateMsg.textContent = 'Not a container path — use /mnt/… not C:\\…';
            validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
          } else if (!r.exists) {
            validateMsg.textContent = 'Path not found — check the container mount.';
            validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
          } else if (r.accessible) {
            var parts = ['Accessible'];
            if (r.writable) parts.push('Writable');
            else parts.push('Read-only');
            if (r.file_count_estimate != null) {
              var countSuffix = isExcl
                ? ' (~' + r.file_count_estimate.toLocaleString() + ' files will be excluded)'
                : ' (~' + r.file_count_estimate.toLocaleString() + ' files)';
              parts.push(countSuffix.trim());
            }
            validateMsg.textContent = parts.join(' · ');
            validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--ok';
          } else {
            validateMsg.textContent = 'Path exists but is not readable.';
            validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
          }
        })
        .catch(function () {
          while (validateMsg.firstChild) validateMsg.removeChild(validateMsg.firstChild);
          validateMsg.textContent = 'Check failed.';
          validateMsg.className = 'mf-loc__validate-msg mf-loc__validate-msg--err';
        });
    }

    checkBtn.addEventListener('click', doCheckAccess);

    // ── Browse picker ───────────────────────────────────────────────────

    browseBtn.addEventListener('click', function () {
      if (typeof FolderPicker === 'undefined') {
        _toast('Folder picker unavailable. Enter path manually.', 'error');
        return;
      }
      var mode = 'source';
      if (!isExcl && typeSelect) {
        var t = typeSelect.value;
        mode = t === 'output' ? 'output' : t === 'source' ? 'source' : 'any';
      }
      var picker = new FolderPicker({
        title: isExcl ? 'Select Folder to Exclude' : 'Select Folder',
        mode: mode,
        initialPath: pathInput.value || '/host',
        onSelect: function (p) {
          pathInput.value = p;
          doCheckAccess();
        },
      });
      picker.open();
    });

    // ── Save ────────────────────────────────────────────────────────────

    saveBtn.addEventListener('click', function () {
      var name = nameInput.value.trim();
      var path = pathInput.value.trim();
      if (!name || !path) {
        _toast('Name and path are required.', 'error');
        return;
      }
      var data = { name: name, path: path, notes: notesInput.value.trim() || null };
      if (!isExcl && typeSelect) data.type = typeSelect.value;
      saveBtn.disabled = true;
      opts.onSave(data).finally(function () { saveBtn.disabled = false; });
    });

    cancelBtn.addEventListener('click', function () { opts.onCancel(); });

    // ── Public helpers ──────────────────────────────────────────────────

    function populate(item) {
      nameInput.value = item ? item.name : '';
      pathInput.value = item ? item.path : '';
      notesInput.value = item ? (item.notes || '') : '';
      if (!isExcl && typeSelect) typeSelect.value = item ? item.type : 'source';
      while (validateMsg.firstChild) validateMsg.removeChild(validateMsg.firstChild);
      validateMsg.className = 'mf-loc__validate-msg';
      saveBtn.textContent = item ? 'Update' : 'Save';
      setTimeout(function () { nameInput.focus(); }, 50);
    }

    function reset() { populate(null); }

    return { formEl: wrap, populate: populate, reset: reset };
  }

  // ── Section renderers ──────────────────────────────────────────────────────

  function _renderLocationsSection(contentSlot, activeSection, state) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    if (activeSection === 'exclusions') {
      _renderExclusions(contentSlot, state);
      return;
    }

    // head + add button
    var headWrap = el('div', 'mf-loc__section-head-wrap');
    var head = el('h2', 'mf-stg__section-head');
    var labels = { sources: 'Source Locations', output: 'Output Locations', both: 'Source & Output' };
    head.textContent = labels[activeSection] || activeSection;
    headWrap.appendChild(head);

    var addBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    addBtn.type = 'button';
    addBtn.textContent = '+ Add Location';
    headWrap.appendChild(addBtn);
    contentSlot.appendChild(headWrap);

    // Form area (hidden by default)
    var formArea = el('div', 'mf-loc__form-area');
    formArea.hidden = true;
    var formObj = _buildLocForm({
      isExclusion: false,
      onSave: function (data) {
        var isEdit = !!state.editingLocId;
        var req = isEdit
          ? apiPut('/api/locations/' + state.editingLocId, data)
          : apiPost('/api/locations', data);
        return req.then(function () {
          _toast(isEdit ? 'Location updated.' : 'Location added.', 'success');
          formArea.hidden = true;
          state.editingLocId = null;
          return state.reload();
        }).catch(function (e) {
          _toast(e.message, 'error');
        });
      },
      onCancel: function () {
        formArea.hidden = true;
        state.editingLocId = null;
      },
    });
    formArea.appendChild(formObj.formEl);
    contentSlot.appendChild(formArea);

    addBtn.addEventListener('click', function () {
      state.editingLocId = null;
      formObj.reset();
      formArea.hidden = false;
    });

    // Filter by type
    var typeMap = { sources: 'source', output: 'output', both: 'both' };
    var targetType = typeMap[activeSection];
    var locs = (state.allLocations || []).filter(function (l) { return l.type === targetType; });

    if (locs.length === 0) {
      contentSlot.appendChild(_makeEmpty('No ' + head.textContent.toLowerCase() + ' configured.'));
    } else {
      var list = el('div', 'mf-loc__list');
      locs.forEach(function (loc) {
        var card = _makeCard(
          loc,
          function (item) {
            state.editingLocId = item.id;
            formObj.populate(item);
            formArea.hidden = false;
          },
          function (item, cardEl, delBtnEl) {
            _confirmDeleteLoc(item, cardEl, delBtnEl, state);
          }
        );
        list.appendChild(card);
      });
      contentSlot.appendChild(list);
      // Fetch status badges async
      locs.forEach(function (loc) { _fetchBadge(loc.id, loc.path); });
    }
  }

  function _confirmDeleteLoc(item, cardEl, delBtnEl, state) {
    delBtnEl.hidden = true;
    var row = el('span', 'mf-loc__confirm-row');

    var confirmText = txt('Delete ‘' + item.name + '’? ');
    row.appendChild(confirmText);

    var confirmBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm mf-loc__btn-danger');
    confirmBtn.type = 'button';
    confirmBtn.textContent = 'Confirm';
    row.appendChild(confirmBtn);

    var space = txt(' ');
    row.appendChild(space);

    var cancelBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'Cancel';
    row.appendChild(cancelBtn);

    delBtnEl.parentNode.appendChild(row);

    cancelBtn.addEventListener('click', function () {
      row.remove();
      delBtnEl.hidden = false;
    });

    confirmBtn.addEventListener('click', function () {
      apiDel('/api/locations/' + item.id)
        .then(function () {
          _toast('Location deleted.', 'success');
          return state.reload();
        })
        .catch(function (e) {
          var detail = (e.data && e.data.detail) || e.message;
          if (detail && typeof detail === 'object' && detail.error === 'location_in_use') {
            // Force-delete option
            while (row.firstChild) row.removeChild(row.firstChild);
            row.appendChild(txt('Used by ' + detail.job_count + ' job(s). '));
            var forceBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm mf-loc__btn-danger');
            forceBtn.type = 'button';
            forceBtn.textContent = 'Delete anyway';
            var cancelBtn2 = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
            cancelBtn2.type = 'button';
            cancelBtn2.textContent = 'Cancel';
            row.appendChild(forceBtn);
            row.appendChild(txt(' '));
            row.appendChild(cancelBtn2);
            forceBtn.addEventListener('click', function () {
              apiDel('/api/locations/' + item.id + '?force=true')
                .then(function () {
                  _toast('Location deleted.', 'success');
                  return state.reload();
                })
                .catch(function (e2) { _toast(e2.message, 'error'); });
            });
            cancelBtn2.addEventListener('click', function () {
              row.remove();
              delBtnEl.hidden = false;
            });
          } else {
            _toast(typeof detail === 'string' ? detail : JSON.stringify(detail), 'error');
            row.remove();
            delBtnEl.hidden = false;
          }
        });
    });
  }

  function _renderExclusions(contentSlot, state) {
    var headWrap = el('div', 'mf-loc__section-head-wrap');
    var head = el('h2', 'mf-stg__section-head');
    head.textContent = 'Exclusions';
    headWrap.appendChild(head);

    var addBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    addBtn.type = 'button';
    addBtn.textContent = '+ Add Exclusion';
    headWrap.appendChild(addBtn);
    contentSlot.appendChild(headWrap);

    var descP = el('p', 'mf-loc__section-desc');
    descP.textContent = 'Paths excluded from scanning. Any file or folder under an excluded path is skipped (prefix match).';
    contentSlot.appendChild(descP);

    // Form area
    var formArea = el('div', 'mf-loc__form-area');
    formArea.hidden = true;
    var formObj = _buildLocForm({
      isExclusion: true,
      onSave: function (data) {
        var isEdit = !!state.editingExclId;
        var req = isEdit
          ? apiPut('/api/locations/exclusions/' + state.editingExclId, data)
          : apiPost('/api/locations/exclusions', data);
        return req.then(function () {
          _toast(isEdit ? 'Exclusion updated.' : 'Exclusion added.', 'success');
          formArea.hidden = true;
          state.editingExclId = null;
          return state.reloadExclusions();
        }).catch(function (e) {
          _toast(e.message, 'error');
        });
      },
      onCancel: function () {
        formArea.hidden = true;
        state.editingExclId = null;
      },
    });
    formArea.appendChild(formObj.formEl);
    contentSlot.appendChild(formArea);

    addBtn.addEventListener('click', function () {
      state.editingExclId = null;
      formObj.reset();
      formArea.hidden = false;
    });

    var excls = state.allExclusions || [];
    if (excls.length === 0) {
      contentSlot.appendChild(_makeEmpty('No exclusions configured.'));
    } else {
      var list = el('div', 'mf-loc__list');
      excls.forEach(function (excl) {
        var card = _makeExclCard(
          excl,
          function (item) {
            state.editingExclId = item.id;
            formObj.populate(item);
            formArea.hidden = false;
          },
          function (item, cardEl, delBtnEl) {
            _confirmDeleteExcl(item, cardEl, delBtnEl, state);
          }
        );
        list.appendChild(card);
      });
      contentSlot.appendChild(list);
    }
  }

  function _confirmDeleteExcl(item, cardEl, delBtnEl, state) {
    delBtnEl.hidden = true;
    var row = el('span', 'mf-loc__confirm-row');

    row.appendChild(txt('Delete ‘' + item.name + '’? '));

    var confirmBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm mf-loc__btn-danger');
    confirmBtn.type = 'button';
    confirmBtn.textContent = 'Confirm';
    row.appendChild(confirmBtn);
    row.appendChild(txt(' '));

    var cancelBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'Cancel';
    row.appendChild(cancelBtn);

    delBtnEl.parentNode.appendChild(row);

    cancelBtn.addEventListener('click', function () {
      row.remove();
      delBtnEl.hidden = false;
    });

    confirmBtn.addEventListener('click', function () {
      apiDel('/api/locations/exclusions/' + item.id)
        .then(function () {
          _toast('Exclusion deleted.', 'success');
          return state.reloadExclusions();
        })
        .catch(function (e) {
          _toast(e.message, 'error');
          row.remove();
          delBtnEl.hidden = false;
        });
    });
  }

  // ── Main mount ─────────────────────────────────────────────────────────────

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSettingsLocations.mount: slot is required');
    opts = opts || {};

    var activeSection = 'sources';
    var state = {
      allLocations: opts.locations || [],
      allExclusions: opts.exclusions || [],
      editingLocId: null,
      editingExclId: null,
      reload: null,
      reloadExclusions: null,
    };

    // ── Shell ────────────────────────────────────────────────────────────

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Locations.';
    body.appendChild(headline);

    var detail = el('div', 'mf-stg__detail');

    // ── Sidebar ──────────────────────────────────────────────────────────

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
        _renderLocationsSection(contentSlot, activeSection, state);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    // ── Content slot ─────────────────────────────────────────────────────

    var contentSlot = el('div', 'mf-stg__content');
    detail.appendChild(contentSlot);
    body.appendChild(detail);

    // ── Reload callbacks ──────────────────────────────────────────────────

    state.reload = function () {
      return apiGet('/api/locations').then(function (locs) {
        state.allLocations = locs;
        _renderLocationsSection(contentSlot, activeSection, state);
      }).catch(function (e) {
        _toast('Failed to reload locations: ' + e.message, 'error');
      });
    };

    state.reloadExclusions = function () {
      return apiGet('/api/locations/exclusions').then(function (excls) {
        state.allExclusions = excls;
        _renderLocationsSection(contentSlot, activeSection, state);
      }).catch(function (e) {
        _toast('Failed to reload exclusions: ' + e.message, 'error');
      });
    };

    // Initial render
    _renderLocationsSection(contentSlot, activeSection, state);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFSettingsLocations = { mount: mount };
})(window);
