/* Avatar dropdown menu. Role-gated content. Spec §6.
 *
 * Usage:
 *   var menu = MFAvatarMenu.create({
 *     user: { name: 'Xerxes', role: 'admin', scope: 'IBEW Local 46' },
 *     build: { version: 'v0.34.2-dev', branch: 'main', sha: 'd15ddb3', date: '2026-04-28' },
 *     onSelectItem: function(id) { ... },
 *     onSignOut: function() { ... }
 *   });
 *   menu.openAt(avatarButton);
 *   menu.close();
 *
 * Safe DOM throughout — every text via textContent.
 */
(function (global) {
  'use strict';

  // Personal items shown to all roles. API keys gated to operator+.
  var PERSONAL_ITEMS = [
    { id: 'profile',       label: 'Profile',                 minRole: 'member'   },
    { id: 'display',       label: 'Display preferences',     minRole: 'member'   },
    { id: 'pinned',        label: 'Pinned folders & topics', minRole: 'member'   },
    { id: 'notifications', label: 'Notifications',           minRole: 'member'   },
    { id: 'api-keys',      label: 'API keys',                minRole: 'operator' }
  ];

  // System items only for operator+ (rendered with Admin only gate badge).
  var SYSTEM_ITEMS = [
    { id: 'storage',  label: 'Storage & mounts' },
    { id: 'pipeline', label: 'Pipeline & lifecycle' },
    { id: 'ai',       label: 'AI providers' },
    { id: 'auth',     label: 'Account & auth' },
    { id: 'db',       label: 'Database health' },
    { id: 'logs',     label: 'Log management' }
  ];

  var ROLE_RANK = { member: 0, operator: 1, admin: 2 };

  function meetsRole(item, userRole) {
    return ROLE_RANK[userRole] >= ROLE_RANK[item.minRole || 'member'];
  }

  function el(tag, className) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    return n;
  }

  function buildHeader(user) {
    var head = el('div', 'mf-av-menu__who');
    head.appendChild(el('div', 'mf-av-menu__avatar'));

    var text = el('div', 'mf-av-menu__who-text');
    var name = el('div', 'mf-av-menu__who-name');
    name.textContent = user.name || '';
    text.appendChild(name);

    var role = el('div', 'mf-av-menu__who-role');
    var rolePill = el('span', 'mf-role-pill mf-role-pill--' + (user.role || 'member'));
    rolePill.textContent = user.role || 'member';
    role.appendChild(rolePill);
    if (user.scope) {
      role.appendChild(document.createTextNode(' ' + user.scope));
    }
    text.appendChild(role);

    head.appendChild(text);
    return head;
  }

  function buildSectionLabel(text, opts) {
    var lab = el('div', 'mf-av-menu__sec-label');
    var span = el('span');
    span.textContent = text;
    lab.appendChild(span);
    if (opts && opts.adminOnly) {
      var gate = el('span', 'mf-av-menu__gate');
      gate.textContent = 'Admin only';
      lab.appendChild(gate);
    }
    return lab;
  }

  function buildItem(item, opts) {
    var a = el('a', 'mf-av-menu__item');
    if (opts && opts.danger) a.className += ' mf-av-menu__item--danger';
    a.setAttribute('role', 'menuitem');
    a.setAttribute('data-mf-item', item.id);
    a.appendChild(el('span', 'mf-av-menu__ico'));
    var label = el('span', 'mf-av-menu__grow');
    label.textContent = item.label;
    a.appendChild(label);
    if (opts && opts.kbd) {
      var kbd = el('span', 'mf-av-menu__kbd');
      kbd.textContent = opts.kbd;
      a.appendChild(kbd);
    }
    return a;
  }

  function buildSep() { return el('div', 'mf-av-menu__sep'); }

  function buildCta(label, id) {
    var cta = el('div', 'mf-av-menu__cta');
    cta.setAttribute('data-mf-item', id);
    var l = el('span'); l.textContent = label; cta.appendChild(l);
    var r = el('span'); r.textContent = '→'; cta.appendChild(r);
    return cta;
  }

  function buildBuild(build) {
    var b = el('div', 'mf-av-menu__build');
    var v = el('span', 'mf-av-menu__build-v');
    v.textContent = (build && build.version) || 'dev';
    b.appendChild(v);
    b.appendChild(document.createTextNode(' · '));
    var branch = el('span', 'mf-av-menu__build-b');
    branch.textContent = (build && build.branch) || '';
    b.appendChild(branch);
    b.appendChild(document.createElement('br'));
    b.appendChild(document.createTextNode('build '));
    var sha = el('span'); sha.style.color = 'var(--mf-color-text)';
    sha.textContent = (build && build.sha) || '';
    b.appendChild(sha);
    if (build && build.date) {
      b.appendChild(document.createTextNode(' · ' + build.date));
    }
    return b;
  }

  function create(opts) {
    var user = (opts && opts.user) || { name: '', role: 'member' };
    var build = (opts && opts.build) || null;
    var onSelectItem = (opts && opts.onSelectItem) || function () {};
    var onSignOut = (opts && opts.onSignOut) || function () {};

    var root = el('div', 'mf-av-menu');
    root.setAttribute('role', 'menu');
    root.style.display = 'none';

    // Header
    root.appendChild(buildHeader(user));

    // Personal section
    root.appendChild(buildSectionLabel('Personal'));
    PERSONAL_ITEMS.forEach(function (item) {
      if (meetsRole(item, user.role)) root.appendChild(buildItem(item));
    });

    // System section (admin/operator only)
    if (user.role === 'admin' || user.role === 'operator') {
      root.appendChild(buildSectionLabel('System', { adminOnly: true }));
      SYSTEM_ITEMS.forEach(function (item) {
        root.appendChild(buildItem(item));
      });
    }

    root.appendChild(buildSep());
    root.appendChild(buildCta('All settings', 'all-settings'));
    root.appendChild(buildSep());

    // Help section
    root.appendChild(buildSectionLabel('Help'));
    root.appendChild(buildItem({ id: 'help',      label: 'Help & docs' }));
    root.appendChild(buildItem({ id: 'shortcuts', label: 'Keyboard shortcuts' }, { kbd: '?' }));
    root.appendChild(buildItem({ id: 'bug',       label: 'Report a bug' }));

    root.appendChild(buildSep());
    root.appendChild(buildItem({ id: 'signout', label: 'Sign out' }, { danger: true }));

    if (build) root.appendChild(buildBuild(build));

    // Click handling — single delegate.
    root.addEventListener('click', function (ev) {
      var t = ev.target;
      while (t && t !== root && !t.getAttribute('data-mf-item')) t = t.parentNode;
      if (!t || t === root) return;
      var id = t.getAttribute('data-mf-item');
      if (id === 'signout') onSignOut();
      else onSelectItem(id);
      close();
    });

    var anchor = null;
    var onOutside = null;
    var onEsc = null;

    function openAt(triggerBtn) {
      anchor = triggerBtn;
      anchor.setAttribute('aria-expanded', 'true');
      var r = anchor.getBoundingClientRect();
      root.style.position = 'absolute';
      root.style.top = (window.scrollY + r.bottom + 8) + 'px';
      root.style.right = (document.documentElement.clientWidth - (window.scrollX + r.right)) + 'px';
      root.style.display = 'block';
      document.body.appendChild(root);
      requestAnimationFrame(function () {
        onOutside = function (ev) {
          if (!root.contains(ev.target) && ev.target !== anchor) close();
        };
        onEsc = function (ev) { if (ev.key === 'Escape') close(); };
        document.addEventListener('click', onOutside);
        document.addEventListener('keydown', onEsc);
      });
    }

    function close() {
      if (!anchor) return;
      anchor.setAttribute('aria-expanded', 'false');
      root.style.display = 'none';
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener('click', onOutside);
      document.removeEventListener('keydown', onEsc);
      anchor = null;
    }

    return { openAt: openAt, close: close, el: root };
  }

  global.MFAvatarMenu = { create: create };
})(window);
