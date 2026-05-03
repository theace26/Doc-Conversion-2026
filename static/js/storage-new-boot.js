/* Boot script for the new-UX Storage Management page (storage-new.html).
 * Feature parity with /storage.html (80%):
 *   - Source folders list with mount-health indicators
 *   - Add source / Discover sources / Remove source
 *   - Output directory display + change
 *   - Network shares list with test/remove
 *   - Storage stats summary
 *   - Exclusions management
 *   - Cloud prefetch settings
 *   - (Deferred) Advanced exclusion patterns UI, NFS/SMB credentials editor
 *
 * Operator-gated — non-operator users are redirected to /.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot  = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-storage-page');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
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

    /* Operator/admin only page */
    if (me.role !== 'operator' && me.role !== 'admin') {
      window.location.href = '/';
      return;
    }

    /* Layout popover (density / card size) */
    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'storage_popover' });
      },
    });

    /* Top nav — null activePage: Storage is not a primary nav item */
    MFTopNav.mount(navRoot, { role: me.role, activePage: null });

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

    MFStoragePage.mount(pageRoot, { role: me.role });

  }).catch(function (e) {
    console.error('mf: storage-new boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Storage management unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
