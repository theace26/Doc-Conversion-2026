/* Boot script for the new Search-as-home page (Plan 3).
 * Mounts top-nav + companions, then mounts MFSearchHome.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var homeRoot = document.getElementById('mf-home');

  // TODO Plan 4: pull real role from /api/me. For now default to 'admin'
  // so Activity link is visible during development.
  var role = 'admin';
  var build = { version: 'v0.34.5-dev', branch: 'main', sha: 'unknown', date: 'today' };
  var user = { name: 'Operator', role: role, scope: '' };

  var avatarMenu = MFAvatarMenu.create({
    user: user,
    build: build,
    onSelectItem: function (id) { console.log('avatar item:', id); },
    onSignOut: function () { console.log('sign out'); },
  });

  var layoutPop = MFLayoutPopover.create({
    current: MFPrefs.get('layout') || 'minimal',
    onChoose: function (mode) {
      MFPrefs.set('layout', mode);
      MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
    },
  });

  function mountChrome() {
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
  }

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

  // Wire hover + context menu + selection (the doc-card interaction
  // event listeners are global at body level, just like dev-chrome).
  var hp = MFHoverPreview.create({
    onAction: function (action, doc) { console.log('hover:', action, doc.id); },
  });
  var cm = MFContextMenu.create({
    onAction: function (action, doc) { console.log('ctx:', action, doc.id); },
  });
  document.addEventListener('mf:doc-contextmenu', function (ev) {
    cm.openAt(ev.detail.x, ev.detail.y, ev.detail.doc);
  });

  // Hydrate prefs, then render
  MFPrefs.load().then(function () {
    mountChrome();
    var homeHandle = MFSearchHome.mount(homeRoot, {
      systemStatus: 'All systems running · 12,847 indexed',
    });
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
