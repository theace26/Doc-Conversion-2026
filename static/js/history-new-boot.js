/* Boot script for the new-UX Conversion History page.
 * Fetches /api/me, mounts chrome + MFHistory.
 * Operator/admin only — members are redirected home.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot  = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-history-page');

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

    /* Members should not land on the operator history page. */
    if (me.role === 'member') {
      window.location.href = '/';
      return;
    }

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'history_popover' });
      },
    });

    /* 'activity' is the closest primary nav item for operator history. */
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

    MFHistory.mount(pageRoot, { role: me.role });

  }).catch(function (e) {
    console.error('mf: history boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Conversion History unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
