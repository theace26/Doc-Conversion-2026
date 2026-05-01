/* Boot script for the Activity page.
 * Fetches /api/me + /api/activity/summary; mounts chrome + MFActivity.
 * Polls /api/activity/summary every 30s for live updates.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var actRoot = document.getElementById('mf-activity');
  var POLL_INTERVAL = 30000;

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      });
  }

  function fetchSummary() {
    return fetch('/api/activity/summary', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('summary fetch failed: ' + r.status);
        return r.json();
      });
  }

  Promise.all([MFPrefs.load(), fetchMe(), fetchSummary()]).then(function (results) {
    var me = results[1];
    var summary = results[2];

    if (me.role === 'member') {
      // Member shouldn't see this page — redirect home.
      window.location.href = '/';
      return;
    }

    var build = me.build;
    var user = { name: me.name, role: me.role, scope: me.scope };

    var avatarMenu = MFAvatarMenu.create({
      user: user,
      build: build,
      onSelectItem: function (id) { console.log('avatar item:', id); },
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

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'activity' });
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

    MFActivity.mount(actRoot, { summary: summary });

    // Poll for fresh data every 30s.
    setInterval(function () {
      fetchSummary()
        .then(function (s) { MFActivity.refresh(actRoot, s); })
        .catch(function (e) { console.warn('mf: activity poll failed', e); });
    }, POLL_INTERVAL);

  }).catch(function (e) {
    console.error('mf: activity boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Activity dashboard unavailable. Check console.';
    if (actRoot) actRoot.appendChild(msg);
  });
})();
