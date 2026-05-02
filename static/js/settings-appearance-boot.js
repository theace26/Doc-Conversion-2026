/* Boot for Settings > Appearance page. Operator-only. */
(function () {
  'use strict';

  var navRoot      = document.getElementById('mf-top-nav');
  var contentRoot  = document.getElementById('mf-settings');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('me ' + r.status); return r.json(); })
      .catch(function () {
        return { user_id: 'dev', name: 'dev', role: 'operator', scope: '',
                 build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' } };
      });
  }

  function fetchEnvInfo() {
    return fetch('/api/version', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  Promise.all([MFPrefs.load(), fetchMe(), fetchEnvInfo()]).then(function (res) {
    var me   = res[1];
    var info = res[2];
    var user = { name: me.name, role: me.role, scope: me.scope };

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) { MFPrefs.set('layout', mode); },
    });

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'settings' });
    MFVersionChip.mount(navRoot.querySelector('[data-mf-slot="version-chip"]'), { version: me.build.version });
    MFAvatarMenuWiring.mount(navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, build: me.build, pageSet: 'new' });
    MFLayoutIcon.mount(navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } });

    if (me.role !== 'operator' && me.role !== 'admin') {
      window.location.href = '/settings-new.html';
      return;
    }

    var envUxOverride = info.env_enable_new_ux != null ? !!info.env_enable_new_ux : null;
    MFSettingsAppearance.mount(contentRoot, { envUxOverride: envUxOverride });
  });
})();
