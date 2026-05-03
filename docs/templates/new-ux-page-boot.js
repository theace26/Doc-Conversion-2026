/* ============================================================
   NEW-UX PAGE BOOT SCRIPT TEMPLATE
   ============================================================
   How to use this file:
     1. Copy to static/js/{{PAGE_ID}}-new-boot.js
        (e.g. static/js/history-new-boot.js)
     2. Replace every {{PLACEHOLDER}} with a real value.
     3. Update the activePage value in MFTopNav.mount() call.
     4. Update MF{{COMPONENT_NAME}}.mount() to match your component.

   REPLACE THIS: all {{...}} markers below.
   ============================================================ */
(function () {
  'use strict';

  /* ── Mount-point references ─────────────────────────────────────────────── */

  var navRoot  = document.getElementById('mf-top-nav');

  /* REPLACE THIS: update to match the div id in your HTML file */
  /* e.g. document.getElementById('mf-history-page') */
  var pageRoot = document.getElementById('mf-{{PAGE_ID}}-page');


  /* ── /api/me helper ─────────────────────────────────────────────────────── */

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        /* Dev / offline fallback — replace the role as appropriate for this page. */
        console.warn('mf: /api/me failed; falling back to operator', e);
        return {
          user_id: 'dev', name: 'dev', role: 'operator', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }


  /* ── Boot ───────────────────────────────────────────────────────────────── */

  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    var me    = results[1];
    var build = me.build;
    var user  = { name: me.name, role: me.role, scope: me.scope };

    /* Layout popover (density / card size) */
    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        /* REPLACE THIS: update 'page_name' to identify this page in telemetry */
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: '{{PAGE_ID}}_popover' });
      },
    });

    /* Top nav — REPLACE THIS: update activePage to one of:
     *   'search' | 'activity' | 'convert' | null
     * Use null if this page isn't a primary nav item. */
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

    /* REPLACE THIS: call your page component's mount function.
     * Pass role so the component can gate operator/admin-only actions. */
    MF{{COMPONENT_NAME}}.mount(pageRoot, { role: me.role });

  }).catch(function (e) {
    console.error('mf: {{PAGE_ID}} boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    /* REPLACE THIS: update the page name in the error message */
    msg.textContent = '{{PAGE_TITLE}} unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
