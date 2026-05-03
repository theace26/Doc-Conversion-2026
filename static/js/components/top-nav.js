/* MarkFlow top navigation bar. Static, role-gated link list.
 * Spec §1 (final IA), §2 (visual). Spec §6 (slot placement for chrome
 * companions: version-chip, layout-icon, avatar).
 *
 * Mount target: a <div id="mf-top-nav"></div> in the page.
 *
 * Safe DOM construction throughout — no innerHTML with template literals.
 *
 * Usage:
 *   <script src="/static/js/components/top-nav.js"></script>
 *   <script>
 *     MFTopNav.mount(document.getElementById('mf-top-nav'), {
 *       role: 'admin',         // 'member' | 'operator' | 'admin'
 *       activePage: 'search',  // 'search' | 'activity' | 'convert' | null
 *     });
 *   </script>
 */
(function (global) {
  'use strict';

  // Role-aware link sets. Activity is hidden for member.
  var ROLE_LINKS = {
    member:   [
      { id: 'search',   label: 'Search',   href: '/' },
      { id: 'convert',  label: 'Convert',  href: '/convert' }
    ],
    operator: [
      { id: 'search',   label: 'Search',   href: '/' },
      { id: 'activity', label: 'Activity', href: '/activity' },
      { id: 'convert',  label: 'Convert',  href: '/convert' }
    ],
    admin:    [
      { id: 'search',   label: 'Search',   href: '/' },
      { id: 'activity', label: 'Activity', href: '/activity' },
      { id: 'convert',  label: 'Convert',  href: '/convert' }
    ]
  };

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function makeSlot(name) {
    var s = document.createElement('span');
    s.setAttribute('data-mf-slot', name);
    return s;
  }

  function mount(root, opts) {
    if (!root) throw new Error('MFTopNav.mount: root element is required');
    var role = (opts && opts.role) || 'member';
    var active = (opts && opts.activePage) || null;
    var links = ROLE_LINKS[role] || ROLE_LINKS.member;

    clear(root);
    root.classList.add('mf-nav');

    // Logo + version-chip slot (chip goes inside the logo span per mockups).
    var logo = document.createElement('a');
    logo.className = 'mf-nav__logo';
    logo.href = '/';
    logo.appendChild(document.createTextNode('MarkFlow'));
    logo.appendChild(makeSlot('version-chip'));
    root.appendChild(logo);

    // Link bar. Per-user UX dispatch happens here: server-side /convert and /
    // routes use the system-wide ENABLE_NEW_UX flag, but the user's actual
    // mode lives in localStorage (read into the <html data-ux> attribute on
    // page load). When the user is in new UX, point links directly at the
    // new-UX HTML files so they don't get bounced to the original UX by the
    // server's static-file dispatch.
    var isNewUx = document.documentElement.getAttribute('data-ux') === 'new';
    var NEW_UX_OVERRIDE = {
      'search':  '/static/index-new.html',
      'convert': '/static/convert-new.html'
      // 'activity' has no separate new-UX file — mounted on /activity directly
    };
    var linkBar = document.createElement('div');
    linkBar.className = 'mf-nav__links';
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      var a = document.createElement('a');
      a.className = 'mf-nav__link';
      if (link.id === active) a.classList.add('mf-nav__link--on');
      a.href = (isNewUx && NEW_UX_OVERRIDE[link.id]) || link.href;
      a.textContent = link.label;
      linkBar.appendChild(a);
    }
    root.appendChild(linkBar);

    // Right cluster: layout-icon and avatar slots.
    var right = document.createElement('div');
    right.className = 'mf-nav__right';
    right.appendChild(makeSlot('layout-icon'));
    right.appendChild(makeSlot('avatar'));
    root.appendChild(right);
  }

  global.MFTopNav = { mount: mount };
})(window);
