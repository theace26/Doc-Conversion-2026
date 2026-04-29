/* Dev-chrome wiring. Mounts all chrome components and demonstrates the
 * full stateful flow:
 *   - Avatar click opens role-gated menu
 *   - Layout-icon click opens 3-mode popover
 *   - Cmd+\ cycles modes
 *   - Mode change persists via MFPrefs
 *   - All clicks emit telemetry events
 */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');

  // Demo identity (Plan 4 replaces with real session identity).
  var demoUser = {
    member:   { name: 'Sarah Mitchell',  role: 'member',   scope: 'IBEW Local 46' },
    operator: { name: 'Aaron Patel',     role: 'operator', scope: 'IBEW Local 46' },
    admin:    { name: 'Xerxes Shelley',  role: 'admin',    scope: 'IBEW Local 46' }
  };
  var build = {
    version: 'v0.34.2-dev', branch: 'main',
    sha: 'd15ddb3', date: '2026-04-28'
  };

  var avatarMenu = null;
  var layoutPop = null;

  function rebuildMenus(role) {
    avatarMenu = MFAvatarMenu.create({
      user: demoUser[role],
      build: build,
      onSelectItem: function (id) {
        console.log('avatar menu selected:', id);
        MFTelemetry.emit('ui.context_menu_action', { source: 'avatar', id: id });
      },
      onSignOut: function () {
        console.log('sign out');
        MFTelemetry.emit('ui.context_menu_action', { source: 'avatar', id: 'signout' });
      }
    });

    var current = MFPrefs.get('layout') || 'minimal';
    layoutPop = MFLayoutPopover.create({
      current: current,
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
      }
    });
  }

  function render(role) {
    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );
    rebuildMenus(role);
  }

  // Cmd+\ cycles modes.
  var MODES = ['maximal', 'recent', 'minimal'];
  MFKeybinds.on('mod+\\', function () {
    var current = MFPrefs.get('layout') || 'minimal';
    var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
    MFPrefs.set('layout', next);
    layoutPop.setCurrent(next);
    MFTelemetry.emit('ui.layout_mode_selected', { mode: next, source: 'kbd' });
    return true;  // preventDefault
  });

  // Subscribe so layout popover stays in sync if changed elsewhere.
  MFPrefs.subscribe('layout', function (mode) {
    if (layoutPop && mode) layoutPop.setCurrent(mode);
  });

  // Role switcher.
  var buttons = document.querySelectorAll('.role-switcher [data-role]');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener('click', function (ev) {
      var role = ev.currentTarget.getAttribute('data-role');
      for (var j = 0; j < buttons.length; j++) buttons[j].classList.remove('on');
      ev.currentTarget.classList.add('on');
      render(role);
    });
  }

  // Hydrate prefs, then initial render.
  MFPrefs.load().then(function () { render('admin'); });
})();
