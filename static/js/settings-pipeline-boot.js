/* Boot script for the Pipeline settings detail page (Plan 6 Task 1).
 * Fetches /api/me + pipeline status + preferences; mounts chrome + MFPipelineDetail.
 *
 * Members are redirected to /. Pipeline and preferences APIs return 403 for
 * non-managers; fetchOrEmpty handles that gracefully with empty fallbacks.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var pipelineRoot = document.getElementById('mf-pipeline');

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
    fetchOrEmpty('/api/pipeline/status', { enabled: true, paused: false, last_scan: null, next_scan: null }),
    fetchOrEmpty('/api/preferences', {}),
  ]).then(function (results) {
    var me = results[1];
    var statusData = results[2];
    var prefsRaw = results[3];

    if (me.role === 'member') {
      window.location.href = '/';
      return;
    }

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

    var prefsData = prefsRaw.preferences || prefsRaw;

    MFPipelineDetail.mount(pipelineRoot, { status: statusData, prefs: prefsData });

  }).catch(function (e) {
    console.error('mf: pipeline-settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Pipeline settings unavailable. Check console.';
    if (pipelineRoot) pipelineRoot.appendChild(msg);
  });
})();
