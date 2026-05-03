/* MarkFlow Search Results page component (new UX).
 *
 * Usage:
 *   MFSearchResults.mount(document.getElementById('mf-search-results-page'), { role: 'member' });
 *
 * Reads query from URL params (?q=, ?format=, ?sort=, ?page=, ?pp=).
 * Calls GET /api/search/all for results.
 * Calls GET /api/search/autocomplete for suggestions (TODO: polish).
 * Calls GET /api/search/index/status for the index stat line.
 * Calls POST /api/search/batch-download for ZIP download.
 *
 * TODO (follow-ups, not MVP):
 *   - Autocomplete dropdown polish (keyboard nav, debounce tuning)
 *   - Per-result preview hover (plug in new-UX hover-preview component)
 *   - Multi-select batch operations (select-all, shift+click range)
 *   - Advanced filters: date range, mime type picker, file-size range
 *   - Saved searches / search history chips
 *   - Search-within-results refinement
 *
 * Safe DOM throughout — no innerHTML with user-controlled content.
 */
(function (global) {
  'use strict';


  /* ── Helpers ────────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function txt(node, str) {
    node.textContent = str;
    return node;
  }

  function showToast(msg, type) {
    var t = el('div', 'mf-toast mf-toast--' + (type || 'info'));
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, 2500);
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function formatLocalTime(isoStr) {
    if (!isoStr) return '';
    var d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
  }

  function formatSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }


  /* ── API endpoints ──────────────────────────────────────────────────────── */

  var API_SEARCH_ALL       = '/api/search/all';
  var API_AUTOCOMPLETE     = '/api/search/autocomplete';
  var API_INDEX_STATUS     = '/api/search/index/status';
  var API_BATCH_DOWNLOAD   = '/api/search/batch-download';
  var API_VIEWER_BASE      = '/viewer.html';


  /* ── Mount ───────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFSearchResults.mount: root element is required');

    var role = (opts && opts.role) || 'member';

    /* ── State ──────────────────────────────────────────────────────────────── */
    var urlParams    = new URLSearchParams(location.search);
    var currentQ     = urlParams.get('q') || '';
    var currentSort  = urlParams.get('sort') || 'relevance';
    var currentFmt   = urlParams.get('format') || '';
    var currentPage  = parseInt(urlParams.get('page') || '1', 10) || 1;
    var currentPP    = parseInt(urlParams.get('pp') || '10', 10) || 10;
    var lastFacets   = {};
    var searchSeq    = 0;
    var searchTimer  = null;
    var acTimer      = null;
    var activeAcIdx  = -1;
    /* TODO: multi-select — selectedItems map kept here for batch-download */
    var selectedItems = {};

    /* ── Build skeleton ──────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-page-wrapper mf-search-results');

    /* ── Sticky search bar ───────────────────────────────────────────────── */
    var stickyBar = el('div', 'mf-search-results__sticky-bar');

    var searchRow = el('div', 'mf-search-results__search-row');

    /* Search input wrapper (for autocomplete positioning) */
    var acWrapper = el('div', 'mf-search-results__ac-wrapper');
    var searchInput = el('input', 'mf-search-results__input');
    searchInput.type = 'search';
    searchInput.placeholder = 'Search all documents, files, and transcripts…';
    searchInput.autocomplete = 'off';
    searchInput.value = currentQ;
    searchInput.setAttribute('title',
      'Press / to focus • Alt+Shift+A toggles AI Assist'
    );
    acWrapper.appendChild(searchInput);

    var acList = el('ul', 'mf-search-results__ac-list');
    acList.hidden = true;
    acWrapper.appendChild(acList);

    searchRow.appendChild(acWrapper);

    var searchBtn = el('button', 'mf-btn mf-btn--primary');
    searchBtn.textContent = 'Search';
    searchRow.appendChild(searchBtn);

    var browseBtn = el('button', 'mf-btn mf-btn--ghost');
    browseBtn.textContent = 'Browse All';
    browseBtn.title = 'Browse all indexed documents';
    searchRow.appendChild(browseBtn);

    /* AI Assist toggle (uses .ai-assist-toggle from ai-assist.css) */
    var aiToggle = el('button', 'ai-assist-toggle');
    aiToggle.id = 'ai-assist-toggle';
    aiToggle.type = 'button';
    aiToggle.setAttribute('aria-pressed', 'false');
    aiToggle.title = 'Toggle AI-assisted synthesis of search results';
    var toggleIcon = el('span', 'toggle-icon');
    toggleIcon.textContent = '✪';
    aiToggle.appendChild(toggleIcon);
    var toggleDot = el('span', 'toggle-dot');
    aiToggle.appendChild(toggleDot);
    aiToggle.appendChild(document.createTextNode('AI Assist'));
    var toggleState = el('span', 'toggle-state');
    toggleState.textContent = 'On';
    aiToggle.appendChild(toggleState);
    searchRow.appendChild(aiToggle);

    stickyBar.appendChild(searchRow);

    /* AI Assist hint (shown before first search when toggle is on) */
    var aiHint = el('div', 'ai-assist-hint');
    aiHint.id = 'ai-assist-hint';
    aiHint.hidden = true;
    var hintIcon = el('span', 'hint-icon');
    hintIcon.textContent = '✪';
    aiHint.appendChild(hintIcon);
    var hintText = el('span');
    hintText.textContent = 'AI synthesis will run on your next search.';
    aiHint.appendChild(hintText);
    stickyBar.appendChild(aiHint);

    wrapper.appendChild(stickyBar);

    /* ── Page body ───────────────────────────────────────────────────────── */
    var body = el('div', 'mf-page-content mf-search-results__body');

    /* Index status line */
    var indexStatus = el('div', 'mf-search-results__index-status');
    body.appendChild(indexStatus);

    /* Progress bar (shown while search in flight) */
    var progressBar = el('div', 'mf-search-results__progress');
    progressBar.setAttribute('aria-hidden', 'true');
    progressBar.hidden = true;
    body.appendChild(progressBar);

    /* Results toolbar (facets + sort + per-page + AI run btn) */
    var toolbar = el('div', 'mf-search-results__toolbar');
    toolbar.hidden = true;

    var facetChips = el('div', 'mf-search-results__facets');
    toolbar.appendChild(facetChips);

    var toolbarRight = el('div', 'mf-search-results__toolbar-right');

    /* AI run button */
    var aiRunBtn = el('button', 'ai-assist-run-btn');
    aiRunBtn.id = 'ai-assist-run-btn';
    aiRunBtn.type = 'button';
    aiRunBtn.hidden = true;
    aiRunBtn.title = 'Run AI synthesis on the results currently shown';
    aiRunBtn.textContent = '✪ Synthesize these results';
    toolbarRight.appendChild(aiRunBtn);

    /* Sort control */
    var sortWrap = el('div', 'mf-search-results__sort');
    var sortLabel = el('label', 'mf-search-results__sort-label');
    sortLabel.textContent = 'Sort:';
    sortLabel.htmlFor = 'mf-sort-select';
    sortWrap.appendChild(sortLabel);
    var sortSelect = el('select', 'mf-search-results__sort-select');
    sortSelect.id = 'mf-sort-select';
    [
      ['relevance', 'Relevance'],
      ['date',      'Date (newest)'],
      ['size',      'File size'],
      ['format',    'Format'],
    ].forEach(function (pair) {
      var opt = document.createElement('option');
      opt.value = pair[0];
      opt.textContent = pair[1];
      if (pair[0] === currentSort) opt.selected = true;
      sortSelect.appendChild(opt);
    });
    sortWrap.appendChild(sortSelect);
    toolbarRight.appendChild(sortWrap);

    /* Per-page buttons */
    var ppBtns = el('div', 'mf-search-results__perpage');
    [10, 30, 50, 100].forEach(function (pp) {
      var btn = el('button', 'mf-search-results__pp-btn' + (pp === currentPP ? ' active' : ''));
      btn.dataset.pp = String(pp);
      btn.textContent = String(pp);
      btn.addEventListener('click', function () {
        currentPP = pp;
        currentPage = 1;
        updatePpButtons();
        doSearch();
      });
      ppBtns.appendChild(btn);
    });
    toolbarRight.appendChild(ppBtns);

    toolbar.appendChild(toolbarRight);
    body.appendChild(toolbar);

    /* Batch download bar
     * TODO: enable once multi-select is implemented */
    var batchBar = el('div', 'mf-search-results__batch-bar');
    batchBar.hidden = true;
    var batchCount = el('span', 'mf-search-results__batch-count');
    batchCount.textContent = '0 selected';
    batchBar.appendChild(batchCount);
    var batchDownloadBtn = el('button', 'mf-btn mf-btn--sm');
    batchDownloadBtn.textContent = 'Download ZIP';
    batchBar.appendChild(batchDownloadBtn);
    var batchClearBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    batchClearBtn.textContent = 'Clear';
    batchBar.appendChild(batchClearBtn);
    body.appendChild(batchBar);

    /* Search meta (result count + timing) */
    var searchMeta = el('div', 'mf-search-results__meta');
    searchMeta.hidden = true;
    body.appendChild(searchMeta);

    /* Results card */
    var resultsCard = el('div', 'mf-card mf-search-results__card');
    resultsCard.style.padding = '0';
    resultsCard.hidden = true;
    var resultsList = el('div', 'mf-search-results__list');
    resultsCard.appendChild(resultsList);
    body.appendChild(resultsCard);

    /* Pagination */
    var pagination = el('div', 'mf-search-results__pagination');
    pagination.hidden = true;
    var paginationInfo = el('span', 'mf-search-results__pagination-info');
    pagination.appendChild(paginationInfo);
    var paginationPages = el('div', 'mf-search-results__pagination-pages');
    pagination.appendChild(paginationPages);
    body.appendChild(pagination);

    /* Empty state */
    var emptyState = el('div', 'mf-empty-state');
    emptyState.hidden = true;
    var emptyTitle = el('h3');
    emptyTitle.textContent = 'No results';
    var emptyText = el('p');
    emptyText.textContent = 'Try different keywords or broaden your search.';
    emptyState.appendChild(emptyTitle);
    emptyState.appendChild(emptyText);
    body.appendChild(emptyState);

    wrapper.appendChild(body);
    root.appendChild(wrapper);

    /* ── Index status ────────────────────────────────────────────────────── */
    fetch(API_INDEX_STATUS, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.available) {
          var parts = [];
          if (data.documents && data.documents.document_count > 0)
            parts.push(data.documents.document_count.toLocaleString() + ' documents');
          if (data.adobe_files && data.adobe_files.document_count > 0)
            parts.push(data.adobe_files.document_count.toLocaleString() + ' Adobe files');
          if (data.transcripts && data.transcripts.document_count > 0)
            parts.push(data.transcripts.document_count.toLocaleString() + ' transcripts');
          indexStatus.textContent = parts.length
            ? parts.join(' + ') + ' indexed'
            : 'Search index ready';
        } else {
          indexStatus.textContent = 'Search index offline';
          indexStatus.classList.add('mf-search-results__index-status--offline');
        }
      })
      .catch(function () { /* non-critical */ });

    /* ── Search ──────────────────────────────────────────────────────────── */

    function doSearch() {
      var q = searchInput.value.trim();
      if (q.length > 0 && q.length < 2) return;

      updateURL(q);

      var seq = ++searchSeq;
      progressBar.hidden = false;
      resultsCard.classList.add('mf-search-results__card--loading');
      toolbar.classList.add('mf-search-results__toolbar--loading');

      var qs = new URLSearchParams({
        q:        q,
        sort:     q ? currentSort : 'date',
        page:     String(currentPage),
        per_page: String(currentPP),
      });
      if (currentFmt) qs.set('format', currentFmt);

      fetch(API_SEARCH_ALL + '?' + qs.toString(), { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) {
            return r.json().catch(function () { return {}; }).then(function (body) {
              var e = new Error(body.detail || ('API error ' + r.status));
              e.status = r.status;
              throw e;
            });
          }
          return r.json();
        })
        .then(function (data) {
          if (seq !== searchSeq) return;
          lastFacets = data.facets || {};
          renderFacets(lastFacets);
          renderResults(data);
          /* Persist recent search to prefs */
          if (q) {
            var recent = (MFPrefs.get('recent_searches') || []).filter(function (s) { return s !== q; });
            recent.unshift(q);
            MFPrefs.set('recent_searches', recent.slice(0, 10));
          }
          /* Trigger AI Assist synthesis */
          if (typeof AIAssist !== 'undefined') {
            AIAssist.onResults(q, data.hits || []);
          }
        })
        .catch(function (e) {
          if (seq !== searchSeq) return;
          if (e.status === 503) {
            showError('Search index is offline.');
          } else {
            showError('Search failed: ' + (e.message || 'unknown error'));
          }
        })
        .finally(function () {
          if (seq === searchSeq) {
            progressBar.hidden = true;
            resultsCard.classList.remove('mf-search-results__card--loading');
            toolbar.classList.remove('mf-search-results__toolbar--loading');
          }
        });
    }

    function showError(msg) {
      showToast(msg, 'error');
    }

    /* ── Facet chips ─────────────────────────────────────────────────────── */

    function renderFacets(facets) {
      clear(facetChips);
      toolbar.hidden = false;

      var entries = Object.keys(facets)
        .map(function (k) { return [k, facets[k]]; })
        .sort(function (a, b) { return b[1] - a[1]; });

      entries.forEach(function (pair) {
        var fmt = pair[0];
        var count = pair[1];
        var isActive = currentFmt === fmt;

        var chip = el('button',
          'mf-search-results__facet-chip' + (isActive ? ' active' : ''));
        chip.dataset.format = fmt;
        chip.title = 'Filter by ' + fmt.toUpperCase();

        var labelNode = document.createTextNode(fmt + ' ');
        chip.appendChild(labelNode);
        var countSpan = el('span', 'mf-search-results__facet-count');
        countSpan.textContent = String(count);
        chip.appendChild(countSpan);

        chip.addEventListener('click', function () {
          currentFmt = (currentFmt === fmt) ? '' : fmt;
          currentPage = 1;
          doSearch();
        });
        facetChips.appendChild(chip);
      });
    }

    /* ── Results rendering ───────────────────────────────────────────────── */

    function viewerUrl(hit) {
      var q = searchInput.value.trim();
      return API_VIEWER_BASE +
        '?index=' + encodeURIComponent(hit.source_index || 'documents') +
        '&id=' + encodeURIComponent(hit.id) +
        (q ? '&q=' + encodeURIComponent(q) : '');
    }

    var INDEX_LABELS = {
      'documents':   'Doc',
      'adobe-files': 'Adobe',
      'transcripts': 'Transcript',
    };

    function renderResults(data) {
      /* Search meta */
      searchMeta.hidden = false;
      var filterNote = currentFmt ? ' (filtered: ' + currentFmt.toUpperCase() + ')' : '';
      searchMeta.textContent =
        data.total_hits.toLocaleString() + ' result' +
        (data.total_hits !== 1 ? 's' : '') +
        ' for “' + data.query + '”' +
        filterNote +
        ' (' + data.processing_time_ms + 'ms)';

      if (!data.hits || !data.hits.length) {
        resultsCard.hidden = true;
        emptyState.hidden = false;
        clear(emptyTitle);
        emptyTitle.textContent = 'No results for “' + data.query + '”';
        emptyText.textContent = 'Try different keywords or broaden your search.';
        pagination.hidden = true;
        return;
      }

      resultsCard.hidden = false;
      emptyState.hidden = true;
      clear(resultsList);

      data.hits.forEach(function (hit) {
        var fmt      = (hit.format || '').toUpperCase();
        var indexTag = hit.source_index || 'documents';
        var indexLbl = INDEX_LABELS[indexTag] || indexTag;
        var snippet  = hit.highlight || hit.content_preview || '';
        var path     = hit.path || '';
        var dateStr  = formatLocalTime(hit.date);
        var sizeStr  = formatSize(hit.file_size_bytes);
        var vUrl     = viewerUrl(hit);
        var selKey   = indexTag + '|' + hit.id;

        var row = el('div', 'mf-search-results__row');
        row.setAttribute('data-doc-id', hit.id);

        /* TODO: multi-select checkbox — deferred to follow-up
         *   var cb = el('input'); cb.type = 'checkbox'; ... row.appendChild(cb);
         */

        /* Flag button */
        var flagBtn = el('button', 'mf-search-results__flag-btn');
        flagBtn.title = 'Flag this file';
        flagBtn.setAttribute('aria-label', 'Flag ' + (hit.title || 'file') + ' for review');
        flagBtn.textContent = '⚑';
        flagBtn.setAttribute('data-source-path', hit.source_path || hit.path || '');
        flagBtn.setAttribute('data-doc-id', hit.id);
        flagBtn.setAttribute('data-source-index', indexTag);
        flagBtn.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          openFlagModal(hit.source_path || hit.path || '', hit.id, indexTag);
        });
        row.appendChild(flagBtn);

        /* Body (anchor wraps the clickable region) */
        var body = el('div', 'mf-search-results__row-body');

        var link = el('a', 'mf-search-results__row-link');
        link.href = vUrl;
        link.target = '_blank';
        link.rel = 'noopener';
        link.addEventListener('click', function (e) {
          /* Alt+click: download original source file */
          if (e.altKey) {
            e.preventDefault();
            e.stopPropagation();
            window.location.href =
              '/api/search/download/' +
              encodeURIComponent(indexTag) + '/' +
              encodeURIComponent(hit.id);
          }
        });

        /* Header row: title + badges */
        var rowHeader = el('div', 'mf-search-results__row-header');

        var titleSpan = el('span', 'mf-search-results__row-title');
        titleSpan.textContent = hit.title || '';
        rowHeader.appendChild(titleSpan);

        var badges = el('span', 'mf-search-results__badges');

        var tagSpan = el('span', 'mf-search-results__index-tag mf-search-results__index-tag--' + indexTag);
        tagSpan.textContent = indexLbl;
        badges.appendChild(tagSpan);

        if (fmt) {
          var fmtSpan = el('span', 'mf-search-results__fmt-badge');
          fmtSpan.textContent = fmt;
          badges.appendChild(fmtSpan);
        }

        rowHeader.appendChild(badges);
        link.appendChild(rowHeader);

        /* File path */
        if (path) {
          var pathDiv = el('div', 'mf-search-results__row-path');
          pathDiv.textContent = path;
          link.appendChild(pathDiv);
        }

        /* Snippet — server emits <em> tags for highlights.
         * We parse the snippet text and reconstruct safe DOM nodes. */
        if (snippet) {
          var snippetDiv = el('div', 'mf-search-results__row-snippet');
          renderSnippet(snippetDiv, snippet);
          link.appendChild(snippetDiv);
        }

        /* Meta (date, size) */
        var metaParts = [dateStr, sizeStr].filter(Boolean);
        if (metaParts.length) {
          var metaDiv = el('div', 'mf-search-results__row-meta');
          metaParts.forEach(function (p) {
            var s = el('span');
            s.textContent = p;
            metaDiv.appendChild(s);
          });
          link.appendChild(metaDiv);
        }

        body.appendChild(link);
        row.appendChild(body);
        resultsList.appendChild(row);
      });

      /* ── Pagination ─────────────────────────────────────────────────────── */
      var totalPages = Math.ceil(data.total_hits / data.per_page);
      if (totalPages <= 1) {
        pagination.hidden = true;
      } else {
        pagination.hidden = false;
        var start = (data.page - 1) * data.per_page + 1;
        var end   = Math.min(data.page * data.per_page, data.total_hits);
        paginationInfo.textContent =
          start + '–' + end + ' of ' + data.total_hits.toLocaleString();

        clear(paginationPages);

        var prevBtn = el('button', 'mf-search-results__page-btn');
        prevBtn.textContent = '←';
        prevBtn.disabled = data.page <= 1;
        prevBtn.addEventListener('click', function () { goPage(data.page - 1); });
        paginationPages.appendChild(prevBtn);

        var rangeStart = Math.max(1, data.page - 2);
        var rangeEnd   = Math.min(totalPages, data.page + 2);
        for (var i = rangeStart; i <= rangeEnd; i++) {
          (function (pageNum) {
            var pb = el('button',
              'mf-search-results__page-btn' + (pageNum === data.page ? ' active' : ''));
            pb.textContent = String(pageNum);
            pb.addEventListener('click', function () { goPage(pageNum); });
            paginationPages.appendChild(pb);
          })(i);
        }

        var nextBtn = el('button', 'mf-search-results__page-btn');
        nextBtn.textContent = '→';
        nextBtn.disabled = data.page >= totalPages;
        nextBtn.addEventListener('click', function () { goPage(data.page + 1); });
        paginationPages.appendChild(nextBtn);
      }
    }

    /* Safe snippet renderer.
     * The server returns snippets like "foo <em>bar</em> baz". We split on
     * <em> and </em> tags and reconstruct as DOM nodes — no innerHTML. */
    function renderSnippet(container, snippetHtml) {
      /* Fast path: no highlight tags */
      if (snippetHtml.indexOf('<em>') === -1) {
        container.textContent = snippetHtml;
        return;
      }
      var parts = snippetHtml.split(/(<em>|<\/em>)/);
      var inEm = false;
      parts.forEach(function (part) {
        if (part === '<em>') { inEm = true; return; }
        if (part === '</em>') { inEm = false; return; }
        if (!part) return;
        if (inEm) {
          var em = document.createElement('em');
          em.className = 'mf-search-results__highlight';
          em.textContent = part;
          container.appendChild(em);
        } else {
          container.appendChild(document.createTextNode(part));
        }
      });
    }

    /* ── URL state management ────────────────────────────────────────────── */

    function updateURL(q) {
      var p = new URLSearchParams();
      if (q) p.set('q', q);
      if (currentSort !== 'relevance') p.set('sort', currentSort);
      if (currentFmt) p.set('format', currentFmt);
      if (currentPage > 1) p.set('page', String(currentPage));
      if (currentPP !== 10) p.set('pp', String(currentPP));
      var qs = p.toString();
      history.replaceState(null, '', qs ? '?' + qs : location.pathname);
    }

    function goPage(p) {
      currentPage = p;
      doSearch();
      root.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function updatePpButtons() {
      var btns = ppBtns.querySelectorAll('.mf-search-results__pp-btn');
      btns.forEach(function (btn) {
        var pp = parseInt(btn.dataset.pp, 10);
        btn.classList.toggle('active', pp === currentPP);
      });
    }

    /* ── Autocomplete ────────────────────────────────────────────────────── */
    /* TODO: polish — keyboard navigation, better styling, recent-search integration */

    function hideAC() {
      acList.hidden = true;
      clear(acList);
      activeAcIdx = -1;
    }

    function fetchSuggestions(q) {
      fetch(API_AUTOCOMPLETE + '?q=' + encodeURIComponent(q) + '&limit=6',
        { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) { renderAC(data.suggestions || []); })
        .catch(function () { hideAC(); });
    }

    function renderAC(suggestions) {
      clear(acList);
      activeAcIdx = -1;
      if (!suggestions.length) { hideAC(); return; }
      suggestions.forEach(function (s, idx) {
        var li = document.createElement('li');
        li.className = 'mf-search-results__ac-item';
        li.dataset.idx = String(idx);
        var titleSpan = el('span', 'mf-search-results__ac-title');
        titleSpan.textContent = s.title;
        li.appendChild(titleSpan);
        var fmtSpan = el('span', 'mf-search-results__ac-fmt');
        fmtSpan.textContent = (s.format || '').toUpperCase();
        li.appendChild(fmtSpan);
        li.addEventListener('mouseenter', function () { setAcActive(idx); });
        li.addEventListener('click', function () {
          searchInput.value = s.title;
          hideAC();
          clearTimeout(searchTimer);
          currentPage = 1;
          doSearch();
        });
        acList.appendChild(li);
      });
      acList.hidden = false;
    }

    function setAcActive(idx) {
      var items = acList.querySelectorAll('li');
      items.forEach(function (li, i) {
        li.classList.toggle('mf-search-results__ac-item--active', i === idx);
      });
      activeAcIdx = idx;
    }

    function moveAC(dir) {
      var items = acList.querySelectorAll('li');
      activeAcIdx = Math.max(-1, Math.min(items.length - 1, activeAcIdx + dir));
      setAcActive(activeAcIdx);
    }

    /* ── Batch download ──────────────────────────────────────────────────── */

    function updateBatchBar() {
      var count = Object.keys(selectedItems).length;
      batchBar.hidden = count === 0;
      batchCount.textContent = count + ' selected';
    }

    batchClearBtn.addEventListener('click', function () {
      selectedItems = {};
      updateBatchBar();
    });

    batchDownloadBtn.addEventListener('click', function () {
      var items = Object.keys(selectedItems).map(function (k) {
        return selectedItems[k];
      });
      if (!items.length) return;

      batchDownloadBtn.textContent = 'Preparing…';
      batchDownloadBtn.disabled = true;

      fetch(API_BATCH_DOWNLOAD, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(items),
      })
        .then(function (r) {
          if (!r.ok) {
            return r.json().catch(function () { return {}; }).then(function (body) {
              throw new Error(body.detail || 'Download failed');
            });
          }
          return r.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'markflow-search-results.zip';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        })
        .catch(function (e) {
          showToast('Batch download failed: ' + e.message, 'error');
        })
        .finally(function () {
          batchDownloadBtn.textContent = 'Download ZIP';
          batchDownloadBtn.disabled = false;
        });
    });

    /* ── Flag modal ──────────────────────────────────────────────────────── */
    /* Reuses the modal markup inline — lightweight, no separate DOM injection */

    var flagModalState = {};
    var flagBackdrop = buildFlagModal();
    document.body.appendChild(flagBackdrop);

    function buildFlagModal() {
      var backdrop = el('div', 'dialog-backdrop');
      backdrop.id = 'mf-flag-modal-backdrop';

      var dialog = el('div', 'dialog');
      dialog.style.maxWidth = '420px';

      var dlgTitle = el('h3');
      dlgTitle.style.marginTop = '0';
      dlgTitle.textContent = 'Flag File for Review';
      dialog.appendChild(dlgTitle);

      var fnameP = el('p');
      fnameP.id = 'mf-flag-filename';
      fnameP.style.cssText = 'color:var(--mf-color-text-muted);word-break:break-all;';
      dialog.appendChild(fnameP);

      var reasonGrp = el('div', 'form-group');
      var reasonLabel = el('label');
      reasonLabel.htmlFor = 'mf-flag-reason';
      reasonLabel.textContent = 'Reason';
      reasonGrp.appendChild(reasonLabel);
      var reasonSelect = el('select');
      reasonSelect.id = 'mf-flag-reason';
      [
        ['', 'Select a reason…'],
        ['pii', 'Contains PII'],
        ['confidential', 'Confidential / Privileged'],
        ['unauthorized', 'Not Authorized to Share'],
        ['other', 'Other'],
      ].forEach(function (pair) {
        var opt = document.createElement('option');
        opt.value = pair[0];
        opt.textContent = pair[1];
        reasonSelect.appendChild(opt);
      });
      reasonGrp.appendChild(reasonSelect);
      dialog.appendChild(reasonGrp);

      var noteGrp = el('div', 'form-group');
      var noteLabel = el('label');
      noteLabel.htmlFor = 'mf-flag-note';
      noteLabel.textContent = 'Note (optional)';
      noteGrp.appendChild(noteLabel);
      var noteInput = el('input');
      noteInput.type = 'text';
      noteInput.id = 'mf-flag-note';
      noteInput.placeholder = 'Additional context…';
      noteGrp.appendChild(noteInput);
      dialog.appendChild(noteGrp);

      var btnRow = el('div');
      btnRow.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';

      var cancelBtn = el('button', 'mf-btn mf-btn--ghost');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', closeFlagModal);
      btnRow.appendChild(cancelBtn);

      var submitBtn = el('button', 'mf-btn mf-btn--danger');
      submitBtn.id = 'mf-flag-submit-btn';
      submitBtn.textContent = 'Flag File';
      submitBtn.addEventListener('click', submitFlag);
      btnRow.appendChild(submitBtn);

      dialog.appendChild(btnRow);
      backdrop.appendChild(dialog);
      return backdrop;
    }

    function openFlagModal(sourcePath, docId, sourceIndex) {
      flagModalState = { sourcePath: sourcePath, docId: docId, sourceIndex: sourceIndex };
      var fnameP = document.getElementById('mf-flag-filename');
      if (fnameP) fnameP.textContent = sourcePath || docId;
      var r = document.getElementById('mf-flag-reason');
      if (r) r.value = '';
      var n = document.getElementById('mf-flag-note');
      if (n) n.value = '';
      flagBackdrop.classList.add('open');
    }

    function closeFlagModal() {
      flagBackdrop.classList.remove('open');
    }

    function submitFlag() {
      var reasonEl = document.getElementById('mf-flag-reason');
      var reason = reasonEl ? reasonEl.value : '';
      if (!reason) { showToast('Please select a reason.', 'error'); return; }

      var noteEl  = document.getElementById('mf-flag-note');
      var note    = noteEl ? noteEl.value : '';
      var submitBtn = document.getElementById('mf-flag-submit-btn');
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Flagging…'; }

      var sourcePath = flagModalState.sourcePath;
      fetch('/api/flags/lookup-source?source_path=' + encodeURIComponent(sourcePath),
        { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (sfResp) {
          return fetch('/api/flags', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              source_file_id: sfResp.source_file_id,
              reason: reason,
              note: note,
            }),
          });
        })
        .then(function () {
          closeFlagModal();
          showToast('File flagged — hidden from search.', 'success');
          var hitEl = resultsList.querySelector('[data-doc-id="' + flagModalState.docId + '"]');
          if (hitEl) {
            hitEl.style.opacity = '0.3';
            hitEl.style.pointerEvents = 'none';
          }
        })
        .catch(function (err) {
          showToast((err && err.message) || 'Failed to flag file.', 'error');
        })
        .finally(function () {
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Flag File'; }
        });
    }

    /* ── Event wiring ────────────────────────────────────────────────────── */

    searchBtn.addEventListener('click', function () {
      clearTimeout(searchTimer);
      currentPage = 1;
      doSearch();
    });

    browseBtn.addEventListener('click', function () {
      searchInput.value = '';
      currentPage = 1;
      currentSort = 'date';
      sortSelect.value = 'date';
      doSearch();
    });

    sortSelect.addEventListener('change', function () {
      currentSort = sortSelect.value;
      currentPage = 1;
      doSearch();
    });

    searchInput.addEventListener('input', function () {
      clearTimeout(acTimer);
      clearTimeout(searchTimer);
      var q = searchInput.value.trim();
      if (q.length < 2) { hideAC(); return; }
      acTimer = setTimeout(function () { fetchSuggestions(q); }, 150);
      searchTimer = setTimeout(function () { currentPage = 1; doSearch(); }, 600);
    });

    searchInput.addEventListener('keydown', function (e) {
      var items = acList.querySelectorAll('li');
      if (e.key === 'ArrowDown') { e.preventDefault(); moveAC(1); return; }
      if (e.key === 'ArrowUp')   { e.preventDefault(); moveAC(-1); return; }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (activeAcIdx >= 0 && items[activeAcIdx]) {
          items[activeAcIdx].click();
        } else {
          hideAC();
          clearTimeout(searchTimer);
          currentPage = 1;
          doSearch();
        }
        return;
      }
      if (e.key === 'Escape') hideAC();
    });

    document.addEventListener('click', function (e) {
      if (!e.target.closest('.mf-search-results__ac-wrapper')) hideAC();
    });

    /* ── Keyboard shortcuts ──────────────────────────────────────────────── */

    function isEditable(target) {
      if (!target) return false;
      var tag = target.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
        target.isContentEditable === true;
    }

    function handleEscape() {
      /* 1. AI Assist drawer */
      var drawer = document.getElementById('ai-assist-drawer');
      if (drawer && drawer.classList.contains('open')) {
        var closeBtn = document.getElementById('ai-drawer-close');
        if (closeBtn) closeBtn.click();
        return true;
      }
      /* 2. Flag modal */
      if (flagBackdrop.classList.contains('open')) {
        closeFlagModal();
        return true;
      }
      /* 3. Autocomplete */
      if (!acList.hidden) {
        hideAC();
        return true;
      }
      /* 4. Batch bar */
      if (!batchBar.hidden) {
        batchClearBtn.click();
        return true;
      }
      /* 5. Blur search input */
      if (document.activeElement === searchInput) {
        searchInput.blur();
        return true;
      }
      return false;
    }

    document.addEventListener('keydown', function (e) {
      /* / — focus search input */
      if (e.key === '/' && !isEditable(e.target)) {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
        return;
      }

      /* Esc — contextual close */
      if (e.key === 'Escape') {
        if (handleEscape()) e.preventDefault();
        return;
      }

      if (!e.altKey) return;
      if (e.ctrlKey || e.metaKey) return;

      var k = e.key.toLowerCase();

      /* Alt+Shift+A — toggle AI Assist */
      if (e.shiftKey && k === 'a') {
        e.preventDefault();
        aiToggle.click();
        return;
      }

      /* Alt+Shift+D — download ZIP */
      if (e.shiftKey && k === 'd') {
        e.preventDefault();
        if (!batchBar.hidden) batchDownloadBtn.click();
        else showToast('Select some results first.', 'info');
        return;
      }

      if (e.shiftKey) return;

      /* Alt+B — browse all */
      if (k === 'b') { e.preventDefault(); browseBtn.click(); return; }
      /* Alt+R — re-run search */
      if (k === 'r') { e.preventDefault(); searchBtn.click(); return; }
    });

    /* ── Initial load ────────────────────────────────────────────────────── */

    if (currentQ.length >= 2) {
      doSearch();
    } else {
      /* Nothing to show yet — wait for user input */
      resultsCard.hidden = true;
      toolbar.hidden = true;
      searchMeta.hidden = true;
      pagination.hidden = true;
      emptyState.hidden = true;
      searchInput.focus();
    }

    /* ── Return handle ───────────────────────────────────────────────────── */
    return {
      refresh: function () { doSearch(); },
      destroy: function () {
        clearTimeout(searchTimer);
        clearTimeout(acTimer);
        if (flagBackdrop.parentNode) flagBackdrop.parentNode.removeChild(flagBackdrop);
      },
    };
  }


  /* ── Export ────────────────────────────────────────────────────────────── */

  global.MFSearchResults = { mount: mount };

})(window);
