/* Boot script for the new-UX File Preview page (preview-new.html).
 * Feature parity with /preview.html:
 *   - Toolbar: breadcrumb, filename, status pill, action buttons
 *   - Chunked content viewer (markdown, text, image, audio, video, PDF, archive)
 *   - Sidecar metadata, conversion, analysis, flags, related-files cards
 *   - Selection-driven search-within-file (highlights → search chip)
 *   - Force-process button with inline progress tracking
 *   - Staleness banner (30-second poll while page is visible)
 *   - URL param: ?id=<source_file_id>
 *
 * Deep-link only — Preview is not a primary nav item.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot  = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-preview-page');

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

    /* Layout popover (density / card size) */
    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'preview_popover' });
      },
    });

    /* Top nav — null activePage: Preview is a deep-link, not primary nav */
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

    MFPreview.mount(pageRoot, { role: me.role });

  }).catch(function (e) {
    console.error('mf: preview-new boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'File Preview unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
