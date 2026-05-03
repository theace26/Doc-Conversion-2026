/* Boot script for the new-UX Document Viewer page (viewer-new.html).
 *
 * URL: /viewer?index=<index>&id=<id>[&q=<query>]
 *
 * The viewer is reachable from search-results / history links, not the
 * primary nav, so activePage is null. All authenticated roles can view
 * documents (member/operator/admin) — the search-doc-info API enforces
 * its own role gate.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot  = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-viewer-page');

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

  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    var me    = results[1];
    var build = me.build;
    var user  = { name: me.name, role: me.role, scope: me.scope };

    /* Layout popover (density / card size) */
    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'viewer_popover' });
      },
    });

    /* Top nav — viewer is not a primary nav item, reached via results/history. */
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

    /* Read URL params for index + id; pass through to the page component. */
    var params  = new URLSearchParams(location.search);
    var index   = params.get('index') || 'documents';
    var id      = params.get('id') || '';
    var returnQ = params.get('q') || '';

    MFViewer.mount(pageRoot, {
      role:        me.role,
      index:       index,
      id:          id,
      returnQuery: returnQ,
    });

  }).catch(function (e) {
    console.error('mf: viewer boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Document viewer unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
