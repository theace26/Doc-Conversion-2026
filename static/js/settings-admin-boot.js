/* Boot script for the Admin settings detail page (Tier B #16).
 * Fetches /api/me, enforces admin role, then mounts chrome + MFSettingsAdmin.
 *
 * Non-admin roles are blocked at mount time (MFSettingsAdmin renders the
 * role-gate guard and redirects to /settings). The boot does not need to
 * pre-check role — MFSettingsAdmin.mount handles it — but we mirror the
 * storage boot pattern of passing me through so the nav chrome can render.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot   = document.getElementById('mf-top-nav');
  var adminRoot = document.getElementById('mf-settings-admin-page');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        console.warn('mf: /api/me failed; falling back to member', e);
        return {
          user_id: 'dev', name: 'dev', role: 'member', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }

  Promise.all([
    MFPrefs.load(),
    fetchMe(),
  ]).then(function (results) {
    var me = results[1];
    var build = me.build || {};
    var user = { name: me.name, role: me.role, scope: me.scope };

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
      },
    });

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'settings' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatarMenuWiring.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, build: build, pageSet: 'new' }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );

    MFSettingsAdmin.mount(adminRoot, { me: me });

  }).catch(function (e) {
    console.error('mf: admin-settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Admin settings unavailable. Check console.';
    if (adminRoot) adminRoot.appendChild(msg);
  });
})();
