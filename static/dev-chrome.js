/* Dev-chrome wiring. Mounts the four static chrome components against
 * the role currently selected by the role-switcher. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');

  function render(role) {
    MFTopNav.mount(navRoot, { role: role, activePage: 'search' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: 'v0.34.2-dev' }
    );
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { onClick: function () { console.log('avatar clicked'); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function () { console.log('layout-icon clicked'); } }
    );
  }

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

  // Initial render.
  render('admin');
})();
