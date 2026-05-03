/* Display Preferences Drawer — theme, font, text scale, UX toggle.
 * Usage:
 *   var drawer = MFDisplayPrefsDrawer.create();
 *   drawer.open();   // appends to body, adds backdrop
 *   drawer.close();
 *
 * Requires: MFPrefs (preferences.js) loaded before this file.
 * Safe DOM: no innerHTML. All text via textContent.
 */
(function (global) {
  'use strict';

  var THEMES = [
    {g:'orig',id:'classic-light',label:'Classic Light',bg:'#f7f7f9',acc:'#5b3df5'},
    {g:'orig',id:'classic-dark', label:'Classic Dark', bg:'#1a1a1f',acc:'#7c5ff8'},
    {g:'orig',id:'cobalt',       label:'Cobalt',       bg:'#0d1628',acc:'#f0a500'},
    {g:'orig',id:'sage',         label:'Sage',         bg:'#f5f0e8',acc:'#2d6a4f'},
    {g:'orig',id:'slate',        label:'Slate',        bg:'#e8e8ec',acc:'#b05520'},
    {g:'orig',id:'crimson',      label:'Crimson',      bg:'#1a0a0f',acc:'#c8c8d8'},
    {g:'orig',id:'sandstone',    label:'Sandstone',    bg:'#f2e8d8',acc:'#c04520'},
    {g:'orig',id:'graphite',     label:'Graphite',     bg:'#22242a',acc:'#00a0a0'},
    {g:'new', id:'nebula',       label:'Nebula',       bg:'#05060e',acc:'#7c3aed'},
    {g:'new', id:'aurora',       label:'Aurora',       bg:'#030d10',acc:'#00d4aa'},
    {g:'new', id:'cobalt-new',   label:'Cobalt',       bg:'#030810',acc:'#f0a000'},
    {g:'new', id:'rose-quartz',  label:'Rose Quartz',  bg:'#180c0e',acc:'#d4a020'},
    {g:'new', id:'midnight-slate',label:'Midnight',    bg:'#08090f',acc:'#4080ff'},
    {g:'new', id:'forest',       label:'Forest',       bg:'#040c06',acc:'#ff6820'},
    {g:'new', id:'obsidian',     label:'Obsidian',     bg:'#000000',acc:'#e040fb'},
    {g:'new', id:'dusk',         label:'Dusk',         bg:'#0e0a06',acc:'#40c0f8'},
    {g:'hc',  id:'hc-light',     label:'HC Light',     bg:'#ffffff',acc:'#0000cc'},
    {g:'hc',  id:'hc-dark',      label:'HC Dark',      bg:'#000000',acc:'#ffff00'},
    {g:'hc',  id:'hc-light-new', label:'HC Light+',    bg:'#ffffff',acc:'#0000cc'},
    {g:'hc',  id:'hc-dark-new',  label:'HC Dark+',     bg:'#000000',acc:'#ffff00'},
    {g:'pas', id:'pastel-lavender',    label:'Lavender',   bg:'#f0eaf8',acc:'#c2195a'},
    {g:'pas', id:'pastel-mint',        label:'Mint',        bg:'#e8f8f0',acc:'#c04040'},
    {g:'pas', id:'pastel-lavender-new',label:'Lavender+',  bg:'#e8e0f5',acc:'#8020c8'},
    {g:'pas', id:'pastel-mint-new',    label:'Mint+',       bg:'#ddf5ea',acc:'#a83060'},
    {g:'sea', id:'spring-orig',  label:'Spring',       bg:'#fff0f3',acc:'#2d8a4e'},
    {g:'sea', id:'summer-orig',  label:'Summer',       bg:'#fef8e8',acc:'#0080a0'},
    {g:'sea', id:'fall-orig',    label:'Fall',         bg:'#fdf0d8',acc:'#a04020'},
    {g:'sea', id:'winter-orig',  label:'Winter',       bg:'#e8f4ff',acc:'#0a3060'},
    {g:'sea', id:'spring-new',   label:'Spring+',      bg:'#030f06',acc:'#f080a0'},
    {g:'sea', id:'summer-new',   label:'Summer+',      bg:'#030810',acc:'#ff6860'},
    {g:'sea', id:'fall-new',     label:'Fall+',        bg:'#0f0600',acc:'#e0a000'},
    {g:'sea', id:'winter-new',   label:'Winter+',      bg:'#020408',acc:'#c8e8ff'},
  ];

  var FONTS = [
    {id:'system',          label:'System UI'},
    {id:'roboto',          label:'Roboto'},
    {id:'source-sans-3',   label:'Source Sans 3'},
    {id:'lato',            label:'Lato'},
    {id:'merriweather',    label:'Merriweather'},
    {id:'jetbrains-mono',  label:'JetBrains Mono'},
    {id:'nunito',          label:'Nunito'},
    {id:'playfair-display',label:'Playfair Display'},
    {id:'raleway',         label:'Raleway'},
    {id:'crimson-pro',     label:'Crimson Pro'},
    {id:'comic-sans',      label:'Comic Sans MS'},
  ];

  var SCALES = [
    {id:'small',   label:'Small'},
    {id:'default', label:'Default'},
    {id:'large',   label:'Large'},
    {id:'xl',      label:'X-Large'},
  ];

  var GROUP_LABELS = {
    orig:'Original UX', new:'New UX', hc:'High Contrast',
    pas:'Pastel', sea:'Seasonal'
  };

  // Page-equivalence between original-UX and new-UX URLs.
  var ORIG_TO_NEW = {
    '/index.html':                   '/index-new.html',
    '/settings.html':                '/settings-new.html',
    '/settings-storage.html':        '/settings-storage.html',
    '/settings-pipeline.html':       '/settings-pipeline.html',
    '/settings-ai-providers.html':   '/settings-ai-providers.html',
    '/settings-notifications.html':  '/settings-notifications.html',
    '/settings-auth.html':           '/settings-auth.html',
    '/settings-db-health.html':      '/settings-db-health.html',
    '/settings-log-mgmt.html':       '/settings-log-mgmt.html',
    '/settings-cost-cap.html':       '/settings-cost-cap.html',
    '/settings-appearance.html':     '/settings-appearance.html',
    '/':                             '/index-new.html'
  };
  var NEW_TO_ORIG = {
    '/index-new.html':               '/index.html',
    '/settings-new.html':            '/settings.html',
    '/':                             '/index.html'
  };

  // Luminance-based classification of all themes (no-mate themes included).
  var LIGHT_THEMES = [
    'classic-light', 'sage', 'slate', 'sandstone',
    'spring-orig', 'summer-orig', 'fall-orig', 'winter-orig',
    'hc-light', 'hc-light-new',
    'pastel-lavender', 'pastel-mint', 'pastel-lavender-new', 'pastel-mint-new'
  ];
  var DARK_THEMES = [
    'classic-dark', 'cobalt', 'graphite', 'crimson', 'nebula', 'aurora',
    'cobalt-new', 'rose-quartz', 'midnight-slate', 'forest', 'obsidian', 'dusk',
    'hc-dark', 'hc-dark-new',
    'spring-new', 'summer-new', 'fall-new', 'winter-new'
  ];

  var FONT_FAMILIES = {
    'system':'system-ui,sans-serif',
    'roboto':'Roboto,system-ui,sans-serif',
    'source-sans-3':'Source Sans 3,system-ui,sans-serif',
    'lato':'Lato,system-ui,sans-serif',
    'merriweather':'Merriweather,Georgia,serif',
    'jetbrains-mono':'JetBrains Mono,monospace',
    'nunito':'Nunito,system-ui,sans-serif',
    'playfair-display':'Playfair Display,Georgia,serif',
    'raleway':'Raleway,system-ui,sans-serif',
    'crimson-pro':'Crimson Pro,Georgia,serif',
    'comic-sans':'"Comic Sans MS","Chalkboard SE",cursive'
  };

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  // Build a single swatch button element.
  function makeSwatch(t, activeTheme, noAutoPair) {
    var sw = el('button', 'mf-disp-drawer__swatch');
    sw.setAttribute('type', 'button');
    sw.setAttribute('title', t.label + (noAutoPair ? ' (no auto-pair)' : ''));
    sw.setAttribute('data-theme-id', t.id);
    if (t.id === activeTheme) sw.className += ' mf-disp-drawer__swatch--active';
    var bg = el('div', 'mf-disp-drawer__swatch-bg');
    bg.style.background = t.bg;
    var acc = el('div', 'mf-disp-drawer__swatch-acc');
    acc.style.background = t.acc;
    sw.appendChild(bg);
    sw.appendChild(acc);
    if (noAutoPair) {
      var badge = el('span', 'mf-disp-drawer__swatch-badge');
      badge.textContent = 'no auto-pair';
      sw.appendChild(badge);
    }
    return sw;
  }

  // Single combined swatch grid (auto_dark OFF — current behavior).
  function buildSwatchesSingle(currentTheme) {
    var wrap = el('div');
    var lastGroup = null;
    var grid = null;

    THEMES.forEach(function(t) {
      if (t.g !== lastGroup) {
        lastGroup = t.g;
        if (grid) wrap.appendChild(grid);
        grid = el('div', 'mf-disp-drawer__swatches');
        var glabel = el('div', 'mf-disp-drawer__group-label');
        glabel.textContent = GROUP_LABELS[t.g] || t.g;
        grid.appendChild(glabel);
      }
      grid.appendChild(makeSwatch(t, currentTheme, false));
    });
    if (grid) wrap.appendChild(grid);
    return wrap;
  }

  // Dual-row swatch view (auto_dark ON).
  // Shows "Light theme" row, "Dark theme" row, and optionally
  // an "Other (no light/dark variant)" row for themes outside both lists.
  function buildSwatchesDual(lightActive, darkActive) {
    var PAIR = MFPrefs.LIGHT_DARK_PAIR;
    var lightSet = {};
    var darkSet  = {};
    LIGHT_THEMES.forEach(function(id) { lightSet[id] = true; });
    DARK_THEMES.forEach(function(id)  { darkSet[id]  = true; });

    var wrap = el('div');

    function makeRow(rowLabel, themeIds, activeTheme) {
      var rowWrap = el('div', 'mf-disp-drawer__autotheme-row');
      var rlbl = el('div', 'mf-disp-drawer__group-label');
      rlbl.textContent = rowLabel;
      rowWrap.appendChild(rlbl);
      var grid = el('div', 'mf-disp-drawer__swatches mf-disp-drawer__swatches--inline');
      themeIds.forEach(function(id) {
        var t = null;
        for (var i = 0; i < THEMES.length; i++) {
          if (THEMES[i].id === id) { t = THEMES[i]; break; }
        }
        if (!t) return;
        var noAutoPair = !PAIR[id];
        grid.appendChild(makeSwatch(t, activeTheme, noAutoPair));
      });
      rowWrap.appendChild(grid);
      return rowWrap;
    }

    wrap.appendChild(makeRow('Light theme', LIGHT_THEMES, lightActive));
    wrap.appendChild(makeRow('Dark theme',  DARK_THEMES,  darkActive));

    // "Other" row: themes present in THEMES but not in either classification list.
    var otherIds = [];
    THEMES.forEach(function(t) {
      if (!lightSet[t.id] && !darkSet[t.id]) otherIds.push(t.id);
    });
    if (otherIds.length > 0) {
      wrap.appendChild(makeRow('Other (no light/dark variant)', otherIds, null));
    }

    return wrap;
  }

  // Entry point called by buildBody — delegates to single or dual layout.
  function buildSwatches(currentTheme, currentUx, autoDark, lightTheme, darkTheme) {
    if (autoDark) {
      return buildSwatchesDual(lightTheme, darkTheme);
    }
    return buildSwatchesSingle(currentTheme);
  }

  // Toggle row for "Match system dark/light".
  function buildAutoDarkRow(autoDark) {
    var row = el('div', 'mf-disp-drawer__ux-row');
    var lbl = el('span', 'mf-disp-drawer__ux-label');
    lbl.textContent = 'Match system dark/light';
    var toggle = el('button', 'mf-toggle mf-toggle--' + (autoDark ? 'on' : 'off'));
    toggle.setAttribute('type', 'button');
    toggle.setAttribute('data-autodark-toggle', '1');
    var knob = el('span', 'mf-toggle__knob');
    toggle.appendChild(knob);
    row.appendChild(lbl);
    row.appendChild(toggle);
    return row;
  }

  function buildFonts(currentFont) {
    var list = el('div', 'mf-disp-drawer__font-list');
    FONTS.forEach(function(f) {
      var item = el('button', 'mf-disp-drawer__font-item' + (f.id === currentFont ? ' mf-disp-drawer__font-item--active' : ''));
      item.setAttribute('type', 'button');
      item.setAttribute('data-font-id', f.id);
      item.style.fontFamily = FONT_FAMILIES[f.id] || 'system-ui';
      item.textContent = f.label;
      list.appendChild(item);
    });
    return list;
  }

  function buildScales(currentScale) {
    var row = el('div', 'mf-disp-drawer__scale-row');
    SCALES.forEach(function(s) {
      var btn = el('button', 'mf-disp-drawer__scale-btn' + (s.id === currentScale ? ' mf-disp-drawer__scale-btn--active' : ''));
      btn.setAttribute('type', 'button');
      btn.setAttribute('data-scale-id', s.id);
      btn.textContent = s.label;
      row.appendChild(btn);
    });
    return row;
  }

  function buildUxRow(currentUx) {
    var row = el('div', 'mf-disp-drawer__ux-row');
    var lbl = el('span', 'mf-disp-drawer__ux-label');
    lbl.textContent = 'New interface';
    var toggle = el('button', 'mf-toggle mf-toggle--' + (currentUx === 'new' ? 'on' : 'off'));
    toggle.setAttribute('type', 'button');
    toggle.setAttribute('data-ux-toggle', '1');
    var knob = el('span', 'mf-toggle__knob');
    toggle.appendChild(knob);
    row.appendChild(lbl);
    row.appendChild(toggle);
    return row;
  }

  function section(labelText, content) {
    var wrap = el('div');
    var lbl = el('div', 'mf-disp-drawer__section-label');
    lbl.textContent = labelText;
    wrap.appendChild(lbl);
    wrap.appendChild(content);
    return wrap;
  }

  function create() {
    var backdrop = el('div', 'mf-disp-drawer-backdrop');
    var drawer = el('div', 'mf-disp-drawer');

    // Header
    var head = el('div', 'mf-disp-drawer__head');
    var title = el('h2', 'mf-disp-drawer__title');
    title.textContent = 'Display preferences';
    var closeBtn = el('button', 'mf-disp-drawer__close');
    closeBtn.setAttribute('type', 'button');
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.textContent = '×';
    head.appendChild(title);
    head.appendChild(closeBtn);
    drawer.appendChild(head);

    // Body (rebuilt on each open so active states are current)
    function buildBody() {
      var old = drawer.querySelector('.mf-disp-drawer__body');
      if (old) drawer.removeChild(old);

      var currentTheme = (MFPrefs.get('theme') || 'nebula');
      var currentUx    = document.documentElement.getAttribute('data-ux') || 'new';
      var currentFont  = (MFPrefs.get('font') || 'system');
      var currentScale = (MFPrefs.get('text_scale') || 'default');
      var autoDark     = !!(MFPrefs.get('auto_dark'));
      var lightTheme   = MFPrefs.get('light_theme') || MFPrefs.FALLBACK_LIGHT;
      var darkTheme    = MFPrefs.get('dark_theme')  || MFPrefs.FALLBACK_DARK;

      var body = el('div', 'mf-disp-drawer__body');

      // "Match system dark/light" toggle — above Theme section for prominence.
      body.appendChild(section('Match system dark/light', buildAutoDarkRow(autoDark)));
      body.appendChild(section('Interface', buildUxRow(currentUx)));
      body.appendChild(section('Theme', buildSwatches(currentTheme, currentUx, autoDark, lightTheme, darkTheme)));
      body.appendChild(section('Font', buildFonts(currentFont)));
      body.appendChild(section('Text size', buildScales(currentScale)));

      body.addEventListener('click', function(ev) {
        var t = ev.target;

        // Auto-dark toggle.
        var ad = t.closest ? t.closest('[data-autodark-toggle]') : null;
        if (ad) {
          var enableAutoDark = !autoDark;
          if (enableAutoDark) {
            // Seed light_theme / dark_theme from current manual choice + its pair.
            var PAIR = MFPrefs.LIGHT_DARK_PAIR;
            var seedLight, seedDark;
            if (LIGHT_THEMES.indexOf(currentTheme) !== -1) {
              seedLight = currentTheme;
              seedDark  = PAIR[currentTheme] || MFPrefs.FALLBACK_DARK;
            } else {
              seedDark  = currentTheme;
              seedLight = PAIR[currentTheme] || MFPrefs.FALLBACK_LIGHT;
            }
            MFPrefs.setMany({
              auto_dark:   true,
              light_theme: seedLight,
              dark_theme:  seedDark
            });
            MFPrefs.applySystemTheme();
          } else {
            MFPrefs.setMany({ auto_dark: false });
            // Restore the manual theme pref to the current data-theme so the
            // display is consistent after turning off auto-dark.
            var currentDataTheme = document.documentElement.getAttribute('data-theme');
            if (currentDataTheme) {
              MFPrefs.set('theme', currentDataTheme);
            }
          }
          buildBody();
          return;
        }

        var sw = t.closest ? t.closest('[data-theme-id]') : null;
        if (sw) {
          MFPrefs.set('theme', sw.getAttribute('data-theme-id'));
          buildBody();
          return;
        }
        var fi = t.closest ? t.closest('[data-font-id]') : null;
        if (fi) {
          MFPrefs.set('font', fi.getAttribute('data-font-id'));
          buildBody();
          return;
        }
        var sc = t.closest ? t.closest('[data-scale-id]') : null;
        if (sc) {
          MFPrefs.set('text_scale', sc.getAttribute('data-scale-id'));
          buildBody();
          return;
        }
        var ux = t.closest ? t.closest('[data-ux-toggle]') : null;
        if (ux) {
          var useNew = currentUx !== 'new';
          MFPrefs.setMany({use_new_ux: useNew});
          var path = window.location.pathname;
          var dest = useNew ? (ORIG_TO_NEW[path] || null) : (NEW_TO_ORIG[path] || null);
          if (dest && dest !== path) {
            window.location.href = dest;  // navigate to equivalent in the other UX
          } else {
            buildBody();  // no equivalent or already correct — just refresh drawer
          }
          return;
        }
      });

      drawer.appendChild(body);
    }

    closeBtn.addEventListener('click', close);
    // Note: backdrop has pointer-events:none (live-preview mode); no click handler.
    // Drawer closes via the × button or Escape key (handler in openDrawer).

    var open = false;

    function openDrawer() {
      if (open) return;
      open = true;
      buildBody();
      document.body.appendChild(backdrop);
      document.body.appendChild(drawer);
      var onEsc = function(ev) {
        if (ev.key === 'Escape') { close(); document.removeEventListener('keydown', onEsc); }
      };
      document.addEventListener('keydown', onEsc);
    }

    function close() {
      if (!open) return;
      open = false;
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      if (drawer.parentNode)   drawer.parentNode.removeChild(drawer);
    }

    return { open: openDrawer, close: close };
  }

  global.MFDisplayPrefsDrawer = { create: create };
})(window);
