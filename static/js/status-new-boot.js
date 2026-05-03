/* Boot script for the new-UX Active Jobs / Status page.
 * Fetches /api/me, mounts chrome + MFStatus.
 * Operator/admin only — members are redirected home.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot    = document.getElementById('mf-top-nav');
  var pageRoot   = document.getElementById('mf-status-page');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        /* Dev / offline fallback. */
        console.warn('mf: /api/me failed; falling back to operator', e);
        return {
          user_id: 'dev', name: 'dev', role: 'operator', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }

  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    var me    = results[1];
    var build = me.build;
    var user  = { name: me.name, role: me.role, scope: me.scope };

    /* Members should not land on the operator status page. */
    if (me.role === 'member') {
      window.location.href = '/';
      return;
    }

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'status_popover' });
      },
    });

    /* 'activity' is the closest primary nav item for operator pages. */
    MFTopNav.mount(navRoot, { role: me.role, activePage: 'activity' });

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

    MFStatus.mount(pageRoot, { role: me.role });

  }).catch(function (e) {
    console.error('mf: status boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Active Jobs unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
