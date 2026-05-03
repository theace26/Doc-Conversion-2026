/* Boot script for the new-UX Search Results page.
 * Fetches /api/me, mounts chrome + MFSearchResults.
 * All roles can access the search page.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot     = document.getElementById('mf-top-nav');
  var pageRoot    = document.getElementById('mf-search-results-page');

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
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'search_results_popover' });
      },
    });

    /* Top nav — 'search' is the active primary nav item */
    MFTopNav.mount(navRoot, { role: me.role, activePage: 'search' });

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

    /* Mount the search-results page component */
    MFSearchResults.mount(pageRoot, { role: me.role });

    /* Init AI Assist after the page component builds its DOM nodes
     * (toggle + hint + run-btn are rendered by the component). */
    if (typeof AIAssist !== 'undefined') {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { AIAssist.init(); });
      } else {
        AIAssist.init();
      }
    }

  }).catch(function (e) {
    console.error('mf: search-results boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Search unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
