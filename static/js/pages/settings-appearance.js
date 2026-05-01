/* Settings -- Appearance page. Operator-only system defaults for theme + UX.
 * Usage: MFSettingsAppearance.mount(slot, { envUxOverride: bool|null });
 * Safe DOM: no innerHTML.
 */
(function (global) {
  'use strict';

  var ENDPOINT_PREFS = '/api/preferences';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function row(labelText, control, hint) {
    var wrap = el('div', 'mf-settings__pref-row');
    var lbl = el('label', 'mf-settings__pref-label');
    lbl.textContent = labelText;
    wrap.appendChild(lbl);
    wrap.appendChild(control);
    if (hint) {
      var h = el('p', 'mf-settings__pref-hint');
      h.textContent = hint;
      wrap.appendChild(h);
    }
    return wrap;
  }

  function buildToggle(isOn, onChange) {
    var btn = el('button', 'mf-toggle mf-toggle--' + (isOn ? 'on' : 'off'));
    btn.setAttribute('type', 'button');
    var knob = el('span', 'mf-toggle__knob');
    btn.appendChild(knob);
    btn.addEventListener('click', function () {
      var next = btn.classList.contains('mf-toggle--off');
      btn.className = 'mf-toggle mf-toggle--' + (next ? 'on' : 'off');
      onChange(next);
    });
    return btn;
  }

  function mount(slot, opts) {
    if (!slot) return;
    var envOverride = opts && opts.envUxOverride != null ? opts.envUxOverride : null;

    var body = el('div', 'mf-settings__body');

    var h1 = el('h1', 'mf-settings__headline');
    h1.textContent = 'Appearance';
    body.appendChild(h1);

    var sub = el('p', 'mf-settings__subtitle');
    sub.textContent = 'System-wide defaults for interface and theme. Users can override these in their own Display preferences.';
    body.appendChild(sub);

    var card = el('div', 'mf-card');
    card.style.cssText = 'padding:1.5rem;display:flex;flex-direction:column;gap:1.2rem;';

    // New UX toggle
    var uxNote = null;
    if (envOverride !== null) {
      uxNote = 'Deployment default: ' + (envOverride ? 'on' : 'off') + ' (ENABLE_NEW_UX env var). Toggle sets the DB fallback used when the env var is absent.';
    }
    var uxToggle = buildToggle(
      envOverride !== null ? envOverride : false,
      function (next) {
        fetch(ENDPOINT_PREFS, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ enable_new_ux: next ? 'true' : 'false' }),
        }).catch(function (e) { console.warn('appearance: pref save failed', e); });
      }
    );
    card.appendChild(row('New interface (default)', uxToggle, uxNote));

    // Allow per-user overrides toggle
    var overrideToggle = buildToggle(true, function (next) {
      fetch(ENDPOINT_PREFS, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ allow_user_theme_override: next ? 'true' : 'false' }),
      }).catch(function (e) { console.warn('appearance: pref save failed', e); });
    });
    card.appendChild(row(
      'Allow per-user display overrides',
      overrideToggle,
      'When off, the Display preferences option is hidden from the avatar menu.'
    ));

    body.appendChild(card);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFSettingsAppearance = { mount: mount };
})(window);
