/* MFAuthDetail — Account & auth settings detail page (Plan 6 Task 3).
 *
 * Usage:
 *   MFAuthDetail.mount(slot, { me, prefs });
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout — no innerHTML.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'identity',  label: 'Identity' },
    { id: 'jwt',       label: 'JWT validation' },
    { id: 'roles',     label: 'Role mapping' },
    { id: 'sessions',  label: 'Sessions & timeout' },
    { id: 'audit',     label: 'Audit log' },
  ];

  var ROLE_MAP = [
    { uc: 'SEARCH_USER', mf: 'member' },
    { uc: 'OPERATOR',    mf: 'operator' },
    { uc: 'MANAGER',     mf: 'operator' },
    { uc: 'ADMIN',       mf: 'admin' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _fieldGroup(labelText, inputEl) {
    var frag = document.createDocumentFragment();
    var label = el('label', 'mf-stg__field-label');
    label.textContent = labelText;
    frag.appendChild(label);
    frag.appendChild(inputEl);
    return frag;
  }

  function _readonlyInput(value, extraCls) {
    var input = el('input', 'mf-stg__field-input' + (extraCls ? ' ' + extraCls : ''));
    input.type = 'text';
    input.readOnly = true;
    input.value = value;
    return input;
  }

  function _renderIdentity(me) {
    var frag = document.createDocumentFragment();

    frag.appendChild(_fieldGroup('Subject', _readonlyInput(me.sub || 'unknown', 'mf-auth__mono-field')));

    var spacer1 = el('div');
    spacer1.style.marginTop = '1rem';
    frag.appendChild(spacer1);

    frag.appendChild(_fieldGroup('Email', _readonlyInput(me.email || '—')));

    var spacer2 = el('div');
    spacer2.style.marginTop = '1rem';
    frag.appendChild(spacer2);

    var roleLabel = el('label', 'mf-stg__field-label');
    roleLabel.textContent = 'Role';
    frag.appendChild(roleLabel);

    var rolePill = el('span', 'mf-auth__role-pill mf-auth__role-pill--' + (me.role || 'member'));
    rolePill.textContent = me.role || 'member';
    frag.appendChild(rolePill);

    var spacer3 = el('div');
    spacer3.style.marginTop = '1rem';
    frag.appendChild(spacer3);

    var note = el('p', 'mf-auth__note');
    note.textContent = 'Managed by UnionCore — scope: IBEW Local 46';
    frag.appendChild(note);

    return frag;
  }

  function _renderJWT(prefs) {
    var frag = document.createDocumentFragment();

    frag.appendChild(_fieldGroup('Issuer', _readonlyInput(prefs.jwt_issuer || '—')));

    var spacer1 = el('div');
    spacer1.style.marginTop = '1rem';
    frag.appendChild(spacer1);

    frag.appendChild(_fieldGroup('Audience', _readonlyInput(prefs.jwt_audience || '—')));

    var spacer2 = el('div');
    spacer2.style.marginTop = '1rem';
    frag.appendChild(spacer2);

    var jwksVal = prefs.jwt_issuer ? (prefs.jwt_issuer + '/.well-known/jwks.json') : '—';
    frag.appendChild(_fieldGroup('JWKS URL', _readonlyInput(jwksVal)));

    var note = el('div', 'mf-auth__note');
    note.textContent = 'Managed by UnionCore deployment — contact your admin to change.';
    frag.appendChild(note);

    return frag;
  }

  function _renderRoles() {
    var frag = document.createDocumentFragment();

    var table = el('table', 'mf-auth__mapping-table');
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    var th1 = document.createElement('th');
    th1.textContent = 'UnionCore role';
    var th2 = document.createElement('th');
    th2.textContent = 'MarkFlow role';
    headRow.appendChild(th1);
    headRow.appendChild(th2);
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    ROLE_MAP.forEach(function (mapping) {
      var row = document.createElement('tr');
      var td1 = document.createElement('td');
      td1.textContent = mapping.uc;
      var td2 = document.createElement('td');
      td2.textContent = mapping.mf;
      row.appendChild(td1);
      row.appendChild(td2);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    frag.appendChild(table);

    return frag;
  }

  function _renderSessions(me, prefs, savedPrefs) {
    var frag = document.createDocumentFragment();
    var isDisabled = (me.role === 'member');

    var timeoutLabel = el('label', 'mf-stg__field-label');
    timeoutLabel.textContent = 'Session timeout (minutes)';
    frag.appendChild(timeoutLabel);

    var timeoutInput = el('input', 'mf-stg__field-input');
    timeoutInput.type = 'number';
    timeoutInput.value = prefs.session_timeout_minutes || 60;
    if (isDisabled) timeoutInput.disabled = true;
    frag.appendChild(timeoutInput);

    var spacer1 = el('div');
    spacer1.style.marginTop = '1.2rem';
    frag.appendChild(spacer1);

    var toggleRow = el('div');
    toggleRow.style.cssText = 'display:flex;align-items:center;gap:0.6rem;';

    var reauthCheck = document.createElement('input');
    reauthCheck.type = 'checkbox';
    reauthCheck.id = 'mf-auth-reauth-toggle';
    var reauthVal = prefs.reauth_for_system_settings;
    reauthCheck.checked = (reauthVal === true || reauthVal === 'true');
    if (isDisabled) reauthCheck.disabled = true;
    toggleRow.appendChild(reauthCheck);

    var toggleLabel = document.createElement('label');
    toggleLabel.htmlFor = 'mf-auth-reauth-toggle';
    toggleLabel.textContent = 'Re-authenticate for system settings';
    toggleLabel.style.cssText = 'font-size:0.9rem;color:var(--mf-color-text);cursor:pointer;';
    toggleRow.appendChild(toggleLabel);
    frag.appendChild(toggleRow);

    var spacer2 = el('div');
    spacer2.style.marginTop = '1.4rem';
    frag.appendChild(spacer2);

    var saveBar = el('div');
    saveBar.style.cssText = 'display:flex;align-items:center;gap:0.75rem;';

    var saveBtn = el('button', 'mf-btn mf-btn--primary');
    saveBtn.textContent = 'Save changes';
    saveBar.appendChild(saveBtn);

    var discardBtn = el('button', 'mf-btn mf-btn--ghost');
    discardBtn.textContent = 'Discard';
    saveBar.appendChild(discardBtn);

    var savedMsg = el('span');
    savedMsg.style.cssText = 'font-size:0.85rem;color:var(--mf-color-success);opacity:0;transition:opacity 0.2s;';
    savedMsg.textContent = 'Saved';
    saveBar.appendChild(savedMsg);

    frag.appendChild(saveBar);

    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      var timeoutVal = parseInt(timeoutInput.value, 10);
      var reauthVal2 = reauthCheck.checked ? 'true' : 'false';

      fetch('/api/preferences/session_timeout_minutes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ value: timeoutVal }),
      }).then(function () {
        return fetch('/api/preferences/reauth_for_system_settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ value: reauthVal2 }),
        });
      }).then(function () {
        savedPrefs.session_timeout_minutes = timeoutVal;
        savedPrefs.reauth_for_system_settings = reauthVal2;
        savedMsg.style.opacity = '1';
        setTimeout(function () { savedMsg.style.opacity = '0'; }, 2000);
        saveBtn.disabled = false;
      }).catch(function (e) {
        console.error('mf: failed to save session prefs', e);
        saveBtn.disabled = false;
      });
    });

    discardBtn.addEventListener('click', function () {
      timeoutInput.value = savedPrefs.session_timeout_minutes || 60;
      var rv = savedPrefs.reauth_for_system_settings;
      reauthCheck.checked = (rv === true || rv === 'true');
    });

    return frag;
  }

  function _renderAudit() {
    var frag = document.createDocumentFragment();

    var note = el('p', 'mf-auth__note');
    note.textContent = 'View the full audit trail in Log management.';
    frag.appendChild(note);

    var link = el('a', 'mf-btn mf-btn--primary');
    link.href = '/settings/log-management';
    link.textContent = 'Go to Log management →';
    link.style.marginTop = '1rem';
    link.style.display = 'inline-block';
    link.style.textDecoration = 'none';
    frag.appendChild(link);

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

    if (activeSection === 'identity') {
      contentSlot.appendChild(_renderIdentity(me));
    } else if (activeSection === 'jwt') {
      contentSlot.appendChild(_renderJWT(prefs));
    } else if (activeSection === 'roles') {
      contentSlot.appendChild(_renderRoles());
    } else if (activeSection === 'sessions') {
      contentSlot.appendChild(_renderSessions(me, prefs, savedPrefs));
    } else if (activeSection === 'audit') {
      contentSlot.appendChild(_renderAudit());
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFAuthDetail.mount: slot is required');
    opts = opts || {};

    var me = opts.me || {};
    var prefs = opts.prefs || {};
    var savedPrefs = {
      session_timeout_minutes: prefs.session_timeout_minutes,
      reauth_for_system_settings: prefs.reauth_for_system_settings,
    };

    var activeSection = 'identity';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Account & auth.';
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

  global.MFAuthDetail = { mount: mount };
})(window);
