/* Boot script for the new Search-as-home page (Plan 4).
 * Fetches /api/me for real role + build info, then mounts chrome + home.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var homeRoot = document.getElementById('mf-home');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        // Defensive fallback — render as member with no build info so the
        // page still loads. Real auth surfaces a 401 via get_current_user;
        // this fallback only fires when /api/me is reachable but errors.
        console.warn('mf: /api/me failed; falling back to member', e);
        return {
          user_id: 'dev', name: 'dev', role: 'member', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }

  // Wire hover + context menu (body-level, no role dependency)
  var hp = MFHoverPreview.create({
    onAction: function (action, doc) { console.log('hover:', action, doc.id); },
  });
  var cm = MFContextMenu.create({
    onAction: function (action, doc) { console.log('ctx:', action, doc.id); },
  });
  document.addEventListener('mf:doc-contextmenu', function (ev) {
    cm.openAt(ev.detail.x, ev.detail.y, ev.detail.doc);
  });

  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    var me = results[1];
    var role = me.role;
    var build = me.build;
    var user = { name: me.name, role: role, scope: me.scope };

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

    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
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

    // Cmd+\ cycles layouts
    var MODES = ['maximal', 'recent', 'minimal'];
    MFKeybinds.on('mod+\\', function () {
      var current = MFPrefs.get('layout') || 'minimal';
      var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
      MFPrefs.set('layout', next);
      layoutPop.setCurrent(next);
      MFTelemetry.emit('ui.layout_mode_selected', { mode: next, source: 'kbd' });
      return true;
    });

    var homeHandle = MFSearchHome.mount(homeRoot, {
      systemStatus: 'All systems running · 12,847 indexed',
    });

    // Show onboarding overlay for first-time users
    if (!MFPrefs.get('onboarding_done')) {
      MFOnboarding.show({
        fetchSources: function () {
          return fetch('/api/storage/sources', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { sources: [] }; })
            .catch(function () { return { sources: [] }; });
        },
        onComplete: function () {
          MFPrefs.set('onboarding_done', '1');
        },
        onSkip: function () {
          MFPrefs.set('onboarding_done', '1');
        },
      });
    }

    // Re-arm hover-preview after each render
    function rearm() {
      var cards = homeRoot.querySelectorAll('.mf-doc-card');
      cards.forEach(function (card) {
        var docId = card.getAttribute('data-doc-id');
        var doc = (window.MFSampleDocs || []).find(function (d) { return d.id === docId; });
        if (doc) hp.armOn(card, doc);
      });
    }
    rearm();
    MFPrefs.subscribe('layout', function () {
      requestAnimationFrame(rearm);
    });
  });
})();
