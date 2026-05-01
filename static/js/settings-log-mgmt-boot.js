/* Boot script for the Log Management settings detail page (Plan 6 Task 6).
 * Fetches /api/me + /api/logs + /api/logs/settings in parallel.
 * Admin only -- members and operators are redirected to /.
 * fetchOrEmpty handles 403 gracefully with empty fallbacks.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var logRoot = document.getElementById('mf-log-mgmt');

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
        if (r.status === 403) {
          console.warn('mf: ' + url + ' returned 403 (insufficient role)');
          return fallback;
        }
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
    fetchOrEmpty('/api/logs', { logs: [], total_size_bytes: 0, logs_dir: '' }),
    fetchOrEmpty('/api/logs/settings', {}),
  ]).then(function (results) {
    var me = results[1];
    var logsData = results[2];
    var settings = results[3];

    if (me.role !== 'admin') {
      window.location.href = '/';
      return;
    }

    var files = logsData.logs || [];

    var build = me.build;
    var user = { name: me.name, role: me.role, scope: me.scope };

    var avatarMenu = MFAvatarMenu.create({
      user: user,
      build: build,
      onSelectItem: function (id) {
        if (id === 'display') {
          var drawer = MFDisplayPrefsDrawer.create();
          drawer.open();
          return;
        }
        console.log('avatar item:', id);
      },
      onSignOut: function () {
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
          .finally(function () { window.location.href = '/'; });
      },
    });

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
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );

    MFLogMgmtDetail.mount(logRoot, { files: files, settings: settings });

  }).catch(function (e) {
    console.error('mf: log-mgmt-settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Log management settings unavailable. Check console.';
    if (logRoot) logRoot.appendChild(msg);
  });
})();
