/* Search-as-home page mount. Spec §3 (three layout modes).
 *
 * Usage:
 *   MFSearchHome.mount(document.getElementById('mf-home'), {
 *     systemStatus: 'All systems running · 12,847 indexed',
 *   });
 *
 * Reads MFPrefs.layout for which mode to render. Subscribes to layout
 * changes for re-render. Search submit navigates to /search.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildPulse(text) {
    var p = el('div', 'mf-pulse');
    var dot = el('span', 'mf-pulse__dot');
    p.appendChild(dot);
    p.appendChild(document.createTextNode(' ' + text));
    return p;
  }

  function buildHeadline(text, sub, opts) {
    var head = el('h1', 'mf-home__headline' + (opts && opts.huge ? ' mf-home__headline--huge' : ''));
    text.split('\n').forEach(function (line, i) {
      if (i > 0) head.appendChild(document.createElement('br'));
      head.appendChild(document.createTextNode(line));
    });
    var subEl = sub ? el('p', 'mf-home__subtitle') : null;
    if (subEl) subEl.textContent = sub;
    return { headline: head, subtitle: subEl };
  }

  function buildSearchBar(onSubmit) {
    var wrap = el('div', 'mf-home__search-wrap');
    MFSearchBar.mount(wrap, { onSubmit: onSubmit });
    return wrap;
  }

  function navigateToSearch(payload) {
    var qs = new URLSearchParams();
    if (payload.q) qs.set('q', payload.q);
    if (payload.format) qs.set('format', payload.format);
    if (payload.when) qs.set('when', payload.when);
    window.location.href = '/search' + (qs.toString() ? '?' + qs : '');
  }

  // === Layout renderers ===

  function renderMaximal(slot, ctx) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-home__body');
    body.appendChild(buildPulse(ctx.systemStatus));
    var heading = buildHeadline("Find anything you've ever\nconverted.");
    body.appendChild(heading.headline);
    body.appendChild(buildSearchBar(navigateToSearch));

    // Browse rows
    var rows = el('div', 'mf-home__rows');
    body.appendChild(rows);
    addPinnedFoldersRow(rows);
    addCardRow(rows, 'From watched folders', MFSampleRows.fromWatchedFolders, '87 ingested today');
    addCardRow(rows, 'Most accessed this week', MFSampleRows.mostAccessedThisWeek, 'top ' + MFSampleRows.mostAccessedThisWeek.length);
    addCardRow(rows, 'Flagged for review', MFSampleRows.flaggedForReview, MFSampleRows.flaggedForReview.length + ' need review');
    addTopicsRow(rows);

    slot.appendChild(body);
  }

  function renderRecent(slot, ctx) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-home__body');
    body.appendChild(buildPulse(ctx.systemStatus));
    var heading = buildHeadline("Find anything you've ever\nconverted.");
    body.appendChild(heading.headline);
    body.appendChild(buildSearchBar(navigateToSearch));

    // Recent searches chip row
    var rs = MFPrefs.get('recent_searches') || MFSampleRows.recentSearches || [];
    if (rs.length) {
      var chipRow = el('div', 'mf-home__rows');
      var chipSlot = el('div');
      MFBrowseRow.mount(chipSlot, {
        title: 'Recent searches',
        content: buildRecentChips(rs),
      });
      chipRow.appendChild(chipSlot);
      body.appendChild(chipRow);
    }

    // Recently opened (cards)
    var rows = el('div', 'mf-home__rows');
    body.appendChild(rows);
    addCardRow(rows, 'Recently opened', MFSampleDocs ? MFSampleDocs.slice(0, 6) : [], null);

    slot.appendChild(body);
  }

  function renderMinimal(slot, ctx) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-home__body mf-home__body--minimal');
    body.appendChild(buildPulse(ctx.systemStatus));
    var heading = buildHeadline('MarkFlow.', "Find anything you've ever converted.", { huge: true });
    body.appendChild(heading.headline);
    if (heading.subtitle) body.appendChild(heading.subtitle);
    body.appendChild(buildSearchBar(navigateToSearch));
    slot.appendChild(body);
  }

  function buildRecentChips(queries) {
    var wrap = el('div', 'mf-recent-chips');
    queries.forEach(function (q) {
      var chip = el('a', 'mf-recent-chip');
      chip.href = '/search?q=' + encodeURIComponent(q);
      var icon = el('span', 'mf-recent-chip__icon');
      icon.textContent = '⚲';   // search-glyph-ish dingbat
      chip.appendChild(icon);
      var t = el('span'); t.textContent = q;
      chip.appendChild(t);
      var x = el('span', 'mf-recent-chip__x');
      x.textContent = '×';   // ×
      x.setAttribute('aria-label', 'Remove from recent');
      x.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var rs = (MFPrefs.get('recent_searches') || []).filter(function (s) { return s !== q; });
        MFPrefs.set('recent_searches', rs);
      });
      chip.appendChild(x);
      wrap.appendChild(chip);
    });
    return wrap;
  }

  function addPinnedFoldersRow(rows) {
    var slot = el('div');
    var grid = el('div', 'mf-folder-cards');
    (MFSampleRows.pinnedFolders || []).forEach(function (f) {
      var card = el('a', 'mf-folder-card');
      card.href = '/folder' + f.path;
      var icon = el('div', 'mf-folder-card__icon');
      icon.textContent = '⧇';   // folder-ish dingbat
      var name = el('h4', 'mf-folder-card__name');
      name.textContent = f.path;
      var meta = el('div', 'mf-folder-card__meta');
      meta.textContent = f.count.toLocaleString() + ' docs · ' + f.meta;
      card.appendChild(icon);
      card.appendChild(name);
      card.appendChild(meta);
      grid.appendChild(card);
    });
    MFBrowseRow.mount(slot, {
      title: 'Pinned folders',
      count: (MFSampleRows.pinnedFolders || []).length,
      countSuffix: 'pinned',
      content: grid,
      onSeeAll: function () { console.log('see all pinned folders'); },
    });
    rows.appendChild(slot);
  }

  function addCardRow(rows, title, docs, countText) {
    var slot = el('div');
    var grid = el('div');
    grid.className = 'mf-card-grid mf-card-grid--cards';
    docs.forEach(function (d) { grid.appendChild(MFDocCard.create(d)); });
    MFBrowseRow.mount(slot, {
      title: title,
      count: countText ? null : docs.length,
      content: grid,
      onSeeAll: function () { console.log('see all:', title); },
    });
    if (countText) {
      var c = slot.querySelector('.mf-row__controls');
      if (c) {
        var span = el('span', 'mf-row__count');
        span.textContent = countText;
        c.insertBefore(span, c.firstChild);
      }
    }
    rows.appendChild(slot);
  }

  function addTopicsRow(rows) {
    var slot = el('div');
    var cloud = MFTopicCloud.build(MFSampleRows.topics, function (t) {
      window.location.href = '/search?topic=' + encodeURIComponent(t.name);
    });
    MFBrowseRow.mount(slot, {
      title: 'Browse by topic',
      content: cloud,
      onSeeAll: function () { console.log('see all topics'); },
    });
    rows.appendChild(slot);
  }

  // === Top-level mount ===

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSearchHome.mount: slot is required');
    var ctx = {
      systemStatus: (opts && opts.systemStatus) || 'All systems running',
    };

    function render() {
      var mode = MFPrefs.get('layout') || 'minimal';
      if (mode === 'maximal') renderMaximal(slot, ctx);
      else if (mode === 'recent') renderRecent(slot, ctx);
      else renderMinimal(slot, ctx);
    }

    render();
    var unsub = MFPrefs.subscribe('layout', render);
    return function unmount() {
      unsub();
      while (slot.firstChild) slot.removeChild(slot.firstChild);
    };
  }

  global.MFSearchHome = { mount: mount };
})(window);
