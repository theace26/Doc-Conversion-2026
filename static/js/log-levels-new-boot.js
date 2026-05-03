/* Boot script for the new-UX Per-Subsystem Log Levels page.
 * Fetches /api/me + /api/log-levels; mounts chrome + MFLogLevels.
 * Admin-only — non-admin users are redirected to /.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-log-levels-page');

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

  function fetchOrEmpty(url, fallback) {
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) { console.warn('mf: ' + url + ' returned 403'); return fallback; }
        if (!r.ok) throw new Error(url + ' failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        console.warn('mf: ' + url + ' fetch error, using fallback', e);
        return fallback;
      });
  }

  Promise.all([
    MFPrefs.load(),
    fetchMe(),
    fetchOrEmpty('/api/log-levels', { loggers: [] }),
  ]).then(function (results) {
    var me = results[1];
    var levelsData = results[2];

    if (me.role !== 'admin') {
      window.location.href = '/';
      return;
    }

    var build = me.build;
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

    MFLogLevels.mount(pageRoot, { loggers: levelsData.loggers || [] });

  }).catch(function (e) {
    console.error('mf: log-levels-new boot failed', e);
    if (pageRoot) {
      var msg = document.createElement('div');
      msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
      msg.textContent = 'Log levels page unavailable. Check console.';
      pageRoot.appendChild(msg);
    }
  });
})();
