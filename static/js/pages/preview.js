/* MFPreview — new-UX File Preview / Inspection page component.
 *
 * Feature parity with /preview.html:
 *   - Toolbar: breadcrumb, filename, status pill, action buttons
 *   - Chunked content view (markdown via marked + DOMPurify, plain text, image,
 *     audio, video, PDF iframe, archive table)
 *   - Sidecar metadata card (key/value pairs from /api/files/{id})
 *   - Conversion + Analysis cards from metadata
 *   - Flags card (shown only when flags exist)
 *   - Related Files card with Semantic / Keyword tabs
 *   - Search-within-file panel (selection-driven: selecting text in the content
 *     pane shows a chip that pre-fills the search input)
 *   - Siblings card (parent-directory context via related API)
 *   - Force-process button with inline progress tracking
 *   - Staleness banner when server data changes while the tab is hidden
 *
 * URL param: ?id=<source_file_id>
 *
 * Endpoints used:
 *   GET  /api/files/{id}                    -- file metadata + info
 *   GET  /api/files/{id}/preview            -- chunked content
 *   GET  /api/files/related?source_path=…   -- related files (siblings + semantic)
 *   POST /api/files/{id}/force-process      -- trigger re-conversion
 *
 * Safe DOM throughout — no innerHTML with user data.
 * Markdown is rendered via marked + DOMPurify (CDN, loaded in HTML shell) and
 * then inserted using DOMParser + adoptNode so no raw innerHTML assignment
 * appears at call sites.
 */
(function (global) {
  'use strict';

  /* ── Helpers ────────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function txt(s) { return document.createTextNode(s == null ? '' : String(s)); }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

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

  function fmtBytes(bytes) {
    if (!bytes) return '0 B';
    var b = Number(bytes);
    if (!b) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), units.length - 1);
    return (i === 0 ? b : (b / Math.pow(1024, i)).toFixed(1)) + ' ' + units[i];
  }

  function fmtDur(ms) {
    if (!ms) return '—';
    var s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    if (s < 3600) return Math.round(s / 60) + 'm ' + Math.round(s % 60) + 's';
    return Math.floor(s / 3600) + 'h ' + Math.round((s % 3600) / 60) + 'm';
  }

  function fmtLocal(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function filename(path) {
    if (!path) return '';
    return path.split('/').pop() || path.split('\\').pop() || path;
  }

  function parentDir(path) {
    if (!path) return '';
    var parts = path.split('/');
    parts.pop();
    return parts.join('/') || '/';
  }

  /* ── Safe markdown → DOM ────────────────────────────────────────────────── */
  /* marked.parse() + DOMPurify.sanitize() are both loaded by the HTML shell.
   * We use DOMParser to convert the sanitised HTML string into a DOM subtree,
   * then adopt its nodes so there is no raw assignment to .innerHTML. */

  function parseSafeMarkdown(text) {
    var container = el('div', 'mf-pv__md-body');

    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
      /* CDN scripts not yet available — fall back to pre-formatted text */
      var pre = el('pre', 'mf-pv__chunk-pre');
      pre.textContent = text || '';
      container.appendChild(pre);
      return container;
    }

    var rawHtml   = marked.parse(text || '');
    var cleanHtml = DOMPurify.sanitize(rawHtml);

    /* DOMParser produces a full document; walk its body children and adopt
     * them into the current document — zero raw innerHTML assignment. */
    var parser  = new DOMParser();
    var parsed  = parser.parseFromString(cleanHtml, 'text/html');
    var bodyChildren = Array.prototype.slice.call(parsed.body.childNodes);
    bodyChildren.forEach(function (child) {
      container.appendChild(document.adoptNode(child));
    });

    return container;
  }

  /* ── API ────────────────────────────────────────────────────────────────── */

  function apiFetch(path, opts) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}))
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (body) {
            var err = new Error(path + ' → ' + r.status + ' ' + r.statusText);
            err.status = r.status;
            try { err.detail = JSON.parse(body).detail; } catch (e2) { err.detail = body; }
            throw err;
          });
        }
        return r.status === 204 ? null : r.json();
      });
  }

  function apiGet(path) { return apiFetch(path); }

  function apiPost(path, body) {
    return apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  }

  /* ── Status pill classes ────────────────────────────────────────────────── */

  var STATUS_MOD = {
    completed:  'success',
    failed:     'failed',
    pending:    'pending',
    processing: 'pending',
    skipped:    'skipped',
    excluded:   'skipped',
    flagged:    'flagged',
    batched:    'batched',
  };

  function pillMod(status) { return STATUS_MOD[status] || 'unknown'; }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFPreview.mount: root element is required');
    clear(root);
    opts = opts || {};

    var params = new URLSearchParams(window.location.search);
    var fileId = params.get('id') || '';

    if (!fileId) {
      var noId = el('div', 'mf-pv__error');
      var noIdH = el('h2'); noIdH.textContent = 'No file ID';
      var noIdP = el('p'); noIdP.textContent = 'Navigate here with ?id=<source_file_id>.';
      noId.appendChild(noIdH);
      noId.appendChild(noIdP);
      root.appendChild(noId);
      return;
    }

    /* ── State ──────────────────────────────────────────────────────────── */
    var fileInfo         = null;
    var lastEtag         = null;
    var relatedMode      = 'semantic';
    var forceInProgress  = false;
    var forceStartMs     = 0;
    var forceTimer       = null;
    var stalenessTimer   = null;

    /* ── Skeleton ───────────────────────────────────────────────────────── */

    var wrap = el('div', 'mf-pv');

    /* Staleness banner (hidden until needed) */
    var stale = el('div', 'mf-pv__stale-banner');
    stale.style.display = 'none';
    var staleMsg = el('span'); staleMsg.textContent = 'File data has changed. ';
    var staleRefresh = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    staleRefresh.textContent = 'Reload';
    staleRefresh.addEventListener('click', function () { loadAll(); });
    var staleDismiss = el('button', 'mf-pv__stale-dismiss');
    staleDismiss.textContent = '×';
    staleDismiss.addEventListener('click', function () { stale.style.display = 'none'; });
    stale.appendChild(staleMsg);
    stale.appendChild(staleRefresh);
    stale.appendChild(staleDismiss);
    wrap.appendChild(stale);

    /* Toolbar */
    var toolbar = el('div', 'mf-pv__toolbar');
    toolbar.style.display = 'none';

    var breadcrumb = el('div', 'mf-pv__breadcrumb');
    var titleRow = el('div', 'mf-pv__title-row');
    var titleEl = el('h1', 'mf-pv__title');
    titleEl.textContent = 'Loading…';
    var statusPill = el('span', 'mf-pv__pill mf-pv__pill--unknown');
    statusPill.style.display = 'none';
    var flagPill = el('span', 'mf-pv__pill mf-pv__pill--flagged');
    flagPill.textContent = 'flagged';
    flagPill.style.display = 'none';
    titleRow.appendChild(titleEl);
    titleRow.appendChild(statusPill);
    titleRow.appendChild(flagPill);

    var actionsRow = el('div', 'mf-pv__actions');

    toolbar.appendChild(breadcrumb);
    toolbar.appendChild(titleRow);
    toolbar.appendChild(actionsRow);
    wrap.appendChild(toolbar);

    /* Loading */
    var loadingEl = el('div', 'mf-pv__loading');
    loadingEl.textContent = 'Loading file information…';
    wrap.appendChild(loadingEl);

    /* Error */
    var errorEl = el('div', 'mf-pv__error');
    errorEl.style.display = 'none';
    wrap.appendChild(errorEl);

    /* Main two-column layout */
    var main = el('div', 'mf-pv__main');
    main.style.display = 'none';

    /* Left: chunked content viewer */
    var viewer = el('div', 'mf-pv__viewer');

    /* Selection chip (floating, appended to body) */
    var selChip = el('div', 'mf-pv__sel-chip');
    var selSearchBtn = el('button');
    selSearchBtn.textContent = 'Search this';
    var selSep = el('span', 'mf-pv__sel-sep');
    var selCopyBtn = el('button');
    selCopyBtn.textContent = 'Copy';
    selChip.appendChild(selSearchBtn);
    selChip.appendChild(selSep);
    selChip.appendChild(selCopyBtn);
    document.body.appendChild(selChip);

    main.appendChild(viewer);

    /* Right: sidebar */
    var sidebar = el('aside', 'mf-pv__sidebar');

    /* ── Metadata card ──────────────────────────────────────────────────── */
    var metaCard = el('div', 'mf-pv__card');
    var metaH = el('h3'); metaH.textContent = 'Metadata';
    var metaBody = el('div', 'mf-pv__meta-rows');
    metaCard.appendChild(metaH);
    metaCard.appendChild(metaBody);
    sidebar.appendChild(metaCard);

    /* ── Conversion card ────────────────────────────────────────────────── */
    var convCard = el('div', 'mf-pv__card');
    var convH = el('h3'); convH.textContent = 'Conversion';
    var convBody = el('div', 'mf-pv__card-empty');
    convBody.textContent = 'No conversion record.';
    convCard.appendChild(convH);
    convCard.appendChild(convBody);
    sidebar.appendChild(convCard);

    /* ── Actions card ───────────────────────────────────────────────────── */
    var forceCard = el('div', 'mf-pv__card');
    var forceH = el('h3'); forceH.textContent = 'Actions';
    var forceBtn = el('button', 'mf-btn mf-btn--primary mf-pv__force-btn');
    forceBtn.textContent = 'Force Re-process';
    var forceProgress = el('div', 'mf-pv__force-progress');
    forceProgress.style.display = 'none';
    forceCard.appendChild(forceH);
    forceCard.appendChild(forceBtn);
    forceCard.appendChild(forceProgress);
    sidebar.appendChild(forceCard);

    /* ── Analysis card ──────────────────────────────────────────────────── */
    var analysisCard = el('div', 'mf-pv__card');
    var analysisH = el('h3'); analysisH.textContent = 'Analysis';
    var analysisBody = el('div', 'mf-pv__card-empty');
    analysisBody.textContent = 'No analysis record.';
    analysisCard.appendChild(analysisH);
    analysisCard.appendChild(analysisBody);
    sidebar.appendChild(analysisCard);

    /* ── Flags card (hidden until flags exist) ──────────────────────────── */
    var flagsCard = el('div', 'mf-pv__card');
    flagsCard.style.display = 'none';
    var flagsH = el('h3'); flagsH.textContent = 'Flags';
    var flagsBody = el('div');
    flagsCard.appendChild(flagsH);
    flagsCard.appendChild(flagsBody);
    sidebar.appendChild(flagsCard);

    /* ── Related Files card ─────────────────────────────────────────────── */
    var relatedCard = el('div', 'mf-pv__card');
    var relatedH = el('h3');
    var relatedTitleTxt = document.createTextNode('Related Files');
    relatedH.appendChild(relatedTitleTxt);
    var relatedFullLink = el('a', 'mf-pv__card-link');
    relatedFullLink.textContent = 'Full search ↗';
    relatedFullLink.href = '#';
    relatedFullLink.target = '_blank';
    relatedFullLink.rel = 'noopener';
    relatedH.appendChild(relatedFullLink);

    var relatedTabs = el('div', 'mf-pv__rel-tabs');
    var tabSemantic = el('button', 'mf-pv__rel-tab mf-pv__rel-tab--active');
    tabSemantic.textContent = 'Semantic';
    var tabKeyword = el('button', 'mf-pv__rel-tab');
    tabKeyword.textContent = 'Keyword';
    relatedTabs.appendChild(tabSemantic);
    relatedTabs.appendChild(tabKeyword);

    var relatedStatus = el('div', 'mf-pv__rel-status');
    var relatedList   = el('div', 'mf-pv__rel-list');

    relatedCard.appendChild(relatedH);
    relatedCard.appendChild(relatedTabs);
    relatedCard.appendChild(relatedStatus);
    relatedCard.appendChild(relatedList);
    sidebar.appendChild(relatedCard);

    /* ── Search-within-file card ────────────────────────────────────────── */
    var searchCard = el('div', 'mf-pv__card');
    var searchH = el('h3'); searchH.textContent = 'Search';
    var searchRow = el('div', 'mf-pv__search-row');
    var searchInput = el('input', 'mf-pv__search-input');
    searchInput.type = 'search';
    searchInput.placeholder = 'Search related context…';
    var searchMode = el('select', 'mf-pv__search-mode');
    [['semantic', 'Semantic'], ['keyword', 'Keyword']].forEach(function (opt) {
      var o = el('option'); o.value = opt[0]; o.textContent = opt[1];
      searchMode.appendChild(o);
    });
    searchRow.appendChild(searchInput);
    searchRow.appendChild(searchMode);

    var searchActRow = el('div', 'mf-pv__search-row mf-pv__search-act-row');
    var searchBtn = el('button', 'mf-btn mf-btn--primary mf-btn--sm');
    searchBtn.textContent = 'Search';
    var searchAiBtn = el('a', 'mf-btn mf-btn--ghost mf-btn--sm');
    searchAiBtn.textContent = 'AI Assist ↗';
    searchAiBtn.href = '#';
    searchAiBtn.target = '_blank';
    searchAiBtn.rel = 'noopener';
    searchAiBtn.title = 'Open full search with AI Assist';
    searchActRow.appendChild(searchBtn);
    searchActRow.appendChild(searchAiBtn);

    var searchStatus = el('div', 'mf-pv__rel-status');
    var searchList   = el('div', 'mf-pv__rel-list');

    searchCard.appendChild(searchH);
    searchCard.appendChild(searchRow);
    searchCard.appendChild(searchActRow);
    searchCard.appendChild(searchStatus);
    searchCard.appendChild(searchList);
    sidebar.appendChild(searchCard);

    main.appendChild(sidebar);
    wrap.appendChild(main);
    root.appendChild(wrap);

    /* ── Load all data ──────────────────────────────────────────────────── */

    function loadAll() {
      stale.style.display = 'none';
      clearTimeout(stalenessTimer);
      loadingEl.style.display = '';
      errorEl.style.display = 'none';
      toolbar.style.display = 'none';
      main.style.display = 'none';

      apiGet('/api/files/' + encodeURIComponent(fileId))
        .then(function (info) {
          fileInfo = info;
          lastEtag = info.etag || info.updated_at || null;
          renderInfo(info);
          loadPreview(info);
          loadRelated(info.source_path);
          scheduleStalenessCheck();
        })
        .catch(function (e) {
          loadingEl.style.display = 'none';
          clear(errorEl);
          var h = el('h2'); h.textContent = 'Failed to load file';
          var p = el('p'); p.textContent = e.detail || e.message;
          errorEl.appendChild(h);
          errorEl.appendChild(p);
          errorEl.style.display = '';
        });
    }

    /* ── Render file info ───────────────────────────────────────────────── */

    function addMetaRow(container, key, value) {
      if (value == null) return;
      var row = el('div', 'mf-pv__meta-row');
      var k = el('span', 'mf-pv__meta-key'); k.textContent = key;
      var v = el('span', 'mf-pv__meta-val'); v.textContent = String(value); v.title = String(value);
      row.appendChild(k);
      row.appendChild(v);
      container.appendChild(row);
    }

    function renderInfo(info) {
      document.title = filename(info.source_path) + ' — MarkFlow';

      /* Breadcrumb */
      clear(breadcrumb);
      var dir = parentDir(info.source_path);
      if (dir) {
        var crumb = el('span', 'mf-pv__crumb'); crumb.textContent = dir;
        var sep   = el('span', 'mf-pv__sep');   sep.textContent = ' / ';
        breadcrumb.appendChild(crumb);
        breadcrumb.appendChild(sep);
      }
      var fileCrumb = el('span', 'mf-pv__crumb mf-pv__crumb--file');
      fileCrumb.textContent = filename(info.source_path);
      breadcrumb.appendChild(fileCrumb);

      /* Title */
      titleEl.textContent = filename(info.source_path);

      /* Status pill */
      if (info.conversion_status) {
        statusPill.textContent = info.conversion_status;
        statusPill.className = 'mf-pv__pill mf-pv__pill--' + pillMod(info.conversion_status);
        statusPill.style.display = '';
      }

      /* Flag pill */
      if (info.is_flagged) { flagPill.style.display = ''; }

      /* Actions */
      clear(actionsRow);
      var backBtn = el('a', 'mf-btn mf-btn--ghost mf-btn--sm');
      backBtn.textContent = '← History';
      backBtn.href = '/history';
      actionsRow.appendChild(backBtn);

      if (info.batch_id) {
        var batchBtn = el('a', 'mf-btn mf-btn--ghost mf-btn--sm');
        batchBtn.textContent = 'Batch ↗';
        batchBtn.href = '/bulk/' + encodeURIComponent(info.batch_id);
        actionsRow.appendChild(batchBtn);
      }

      toolbar.style.display = '';

      /* Metadata card */
      clear(metaBody);
      [
        ['File',       filename(info.source_path)],
        ['Path',       info.source_path],
        ['Size',       fmtBytes(info.file_size)],
        ['Format',     info.detected_format || info.file_format],
        ['MIME',       info.mime_type],
        ['Modified',   fmtLocal(info.source_modified_at)],
        ['Discovered', fmtLocal(info.discovered_at)],
        ['Batch',      info.batch_id],
      ].forEach(function (p) { addMetaRow(metaBody, p[0], p[1] != null ? p[1] : '—'); });

      /* Conversion card */
      clear(convBody);
      convBody.className = '';
      if (info.conversion) {
        var c = info.conversion;
        [
          ['Status',     c.status],
          ['Duration',   fmtDur(c.duration_ms)],
          ['Output',     c.output_format],
          ['Confidence', c.confidence_score != null ? c.confidence_score.toFixed(1) + '%' : null],
          ['Completed',  fmtLocal(c.completed_at)],
        ].forEach(function (p) { if (p[1] != null) addMetaRow(convBody, p[0], p[1]); });
        if (c.error_message) {
          var errRow = el('div', 'mf-pv__meta-row');
          var errK = el('span', 'mf-pv__meta-key'); errK.textContent = 'Error';
          var errV = el('span', 'mf-pv__meta-val mf-pv__meta-val--error');
          errV.textContent = c.error_message; errV.title = c.error_message;
          errRow.appendChild(errK); errRow.appendChild(errV);
          convBody.appendChild(errRow);
        }
      } else {
        convBody.className = 'mf-pv__card-empty';
        convBody.textContent = 'No conversion record.';
      }

      /* Analysis card */
      clear(analysisBody);
      if (info.analysis) {
        var a = info.analysis;
        analysisBody.className = '';
        if (a.description) {
          var desc = el('p', 'mf-pv__analysis-desc'); desc.textContent = a.description;
          analysisBody.appendChild(desc);
        }
        if (a.extracted_text) {
          var extLabel = el('div', 'mf-pv__analysis-label'); extLabel.textContent = 'Extracted Text';
          var extBox = el('pre', 'mf-pv__analysis-pre'); extBox.textContent = a.extracted_text;
          analysisBody.appendChild(extLabel);
          analysisBody.appendChild(extBox);
        }
      } else {
        analysisBody.className = 'mf-pv__card-empty';
        analysisBody.textContent = 'No analysis record.';
      }

      /* Flags card */
      if (info.flags && info.flags.length) {
        clear(flagsBody);
        info.flags.forEach(function (f) {
          var item = el('div', 'mf-pv__flag-item');
          var reason = el('div', 'mf-pv__flag-reason'); reason.textContent = f.reason || 'flagged';
          var by = el('div', 'mf-pv__flag-by'); by.textContent = 'by ' + (f.flagged_by_email || 'system');
          item.appendChild(reason);
          item.appendChild(by);
          flagsBody.appendChild(item);
        });
        flagsCard.style.display = '';
      }

      /* Force button label */
      var sl = (info.conversion_status || '').toLowerCase();
      forceBtn.textContent = (sl === 'failed' || sl === 'pending') ? 'Force Process' : 'Force Re-process';

      /* Search links */
      searchAiBtn.href = '/search?q=' + encodeURIComponent(filename(info.source_path)) + '&ai=1';
      relatedFullLink.href = '/search?q=' + encodeURIComponent(filename(info.source_path));
    }

    /* ── Load chunked preview content ───────────────────────────────────── */

    function loadPreview(info) {
      clear(viewer);
      var loadMsg = el('div', 'mf-pv__viewer-loading');
      loadMsg.textContent = 'Loading content…';
      viewer.appendChild(loadMsg);

      apiGet('/api/files/' + encodeURIComponent(fileId) + '/preview')
        .then(function (data) {
          loadingEl.style.display = 'none';
          main.style.display = '';
          renderPreviewContent(data, info);
        })
        .catch(function (e) {
          loadingEl.style.display = 'none';
          main.style.display = '';
          clear(viewer);
          var errDiv = el('div', 'mf-pv__viewer-empty');
          errDiv.textContent = 'Preview unavailable: ' + (e.detail || e.message);
          viewer.appendChild(errDiv);
        });
    }

    function renderPreviewContent(data, info) {
      clear(viewer);

      var contentType = (data && data.content_type) || '';
      var chunks      = (data && data.chunks) || [];
      var rawContent  = (data && data.content) || '';

      if (!chunks.length && !rawContent) {
        var empty = el('div', 'mf-pv__viewer-empty');
        empty.textContent = 'No preview content available.';
        viewer.appendChild(empty);
        return;
      }

      var chunkList = chunks.length
        ? chunks
        : [{ type: contentType || 'text', content: rawContent }];

      chunkList.forEach(function (chunk, idx) {
        if (idx > 0) {
          var divider = el('div', 'mf-pv__chunk-divider');
          var divTxt = el('span'); divTxt.textContent = 'Chunk ' + (idx + 1);
          divider.appendChild(divTxt);
          viewer.appendChild(divider);
        }

        var chunkWrap = el('div', 'mf-pv__chunk');
        var ctype = chunk.type || 'text';

        if (ctype === 'markdown' || ctype === 'office_with_markdown') {
          /* parseSafeMarkdown uses DOMParser+adoptNode — no raw innerHTML */
          chunkWrap.appendChild(parseSafeMarkdown(chunk.content));

        } else if (ctype === 'image') {
          var imgWrap = el('div', 'mf-pv__img-wrap');
          var img = el('img');
          img.src = chunk.url || chunk.content || '';
          img.alt = filename(info.source_path);
          img.style.maxWidth = '100%';
          imgWrap.appendChild(img);
          chunkWrap.appendChild(imgWrap);

        } else if (ctype === 'audio') {
          var audio = el('audio');
          audio.controls = true;
          audio.src = chunk.url || chunk.content || '';
          audio.style.width = '100%';
          chunkWrap.appendChild(audio);
          if (chunk.transcript) {
            var tPane = el('div', 'mf-pv__transcript');
            var tHead = el('div', 'mf-pv__transcript-head'); tHead.textContent = 'Transcript';
            var tBody = el('div', 'mf-pv__transcript-body'); tBody.textContent = chunk.transcript;
            tPane.appendChild(tHead);
            tPane.appendChild(tBody);
            chunkWrap.appendChild(tPane);
          }

        } else if (ctype === 'video') {
          var video = el('video');
          video.controls = true;
          video.src = chunk.url || chunk.content || '';
          video.style.width = '100%';
          chunkWrap.appendChild(video);

        } else if (ctype === 'pdf') {
          var iframe = el('iframe');
          iframe.src = chunk.url || chunk.content || '';
          iframe.style.cssText = 'width:100%;height:80vh;border:0;';
          chunkWrap.appendChild(iframe);

        } else if (ctype === 'archive') {
          chunkWrap.appendChild(renderArchiveTable(chunk.entries || []));

        } else {
          /* Plain text fallback */
          var pre = el('pre', 'mf-pv__chunk-pre');
          pre.textContent = chunk.content || '';
          chunkWrap.appendChild(pre);
        }

        viewer.appendChild(chunkWrap);
      });

      /* Wire selection chip after content is in the DOM */
      wireSelectionChip(viewer);
    }

    function renderArchiveTable(entries) {
      var wrap = el('div', 'mf-pv__archive-wrap');
      var tbl = el('table', 'mf-pv__archive-table');
      var hdr = el('thead');
      var hRow = el('tr');
      ['Name', 'Size', 'Type'].forEach(function (h) {
        var th = el('th'); th.textContent = h; hRow.appendChild(th);
      });
      hdr.appendChild(hRow);
      tbl.appendChild(hdr);
      var body = el('tbody');
      (entries || []).forEach(function (entry) {
        var tr = el('tr');
        var tdName = el('td', 'mf-pv__archive-name'); tdName.textContent = entry.name || '';
        var tdSize = el('td', 'mf-pv__archive-size'); tdSize.textContent = fmtBytes(entry.size);
        var tdType = el('td'); tdType.textContent = entry.type || '';
        tr.appendChild(tdName);
        tr.appendChild(tdSize);
        tr.appendChild(tdType);
        body.appendChild(tr);
      });
      tbl.appendChild(body);
      wrap.appendChild(tbl);
      return wrap;
    }

    /* ── Selection chip ─────────────────────────────────────────────────── */

    function wireSelectionChip(contentEl) {
      contentEl.addEventListener('mouseup', function () {
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) {
          selChip.classList.remove('mf-pv__sel-chip--show');
          return;
        }
        var range = sel.getRangeAt(0);
        var rect  = range.getBoundingClientRect();
        selChip.style.top  = (window.scrollY + rect.top - 44) + 'px';
        selChip.style.left = (window.scrollX + rect.left) + 'px';
        selChip.classList.add('mf-pv__sel-chip--show');
        selSearchBtn._selText = sel.toString().trim();
      });

      document.addEventListener('mousedown', function (e) {
        if (!selChip.contains(e.target)) {
          selChip.classList.remove('mf-pv__sel-chip--show');
        }
      });
    }

    selSearchBtn.addEventListener('click', function () {
      var q = selSearchBtn._selText || '';
      if (q) {
        searchInput.value = q;
        selChip.classList.remove('mf-pv__sel-chip--show');
        doSearch();
      }
    });

    selCopyBtn.addEventListener('click', function () {
      var sel = window.getSelection();
      if (sel) {
        navigator.clipboard.writeText(sel.toString())
          .then(function () { showToast('Copied to clipboard', 'success'); })
          .catch(function () { showToast('Copy failed', 'error'); });
      }
      selChip.classList.remove('mf-pv__sel-chip--show');
    });

    /* ── Related files ──────────────────────────────────────────────────── */

    function loadRelated(sourcePath) {
      if (!sourcePath) return;
      relatedStatus.textContent = 'Loading…';
      relatedStatus.className = 'mf-pv__rel-status';
      clear(relatedList);

      apiGet('/api/files/related?source_path=' + encodeURIComponent(sourcePath) + '&mode=' + relatedMode)
        .then(function (data) {
          var items = data.items || data || [];
          relatedStatus.textContent = items.length ? '' : 'No related files found.';
          renderRelatedList(relatedList, items);
        })
        .catch(function (e) {
          relatedStatus.className = 'mf-pv__rel-status mf-pv__rel-status--err';
          relatedStatus.textContent = 'Error: ' + (e.detail || e.message);
        });
    }

    function renderRelatedList(listEl, items) {
      clear(listEl);
      items.forEach(function (item) {
        var link = el('a', 'mf-pv__rel-item');
        link.href = '/preview?id=' + encodeURIComponent(item.id || item.source_file_id || '');
        var name = el('div', 'mf-pv__rel-name');
        name.textContent = filename(item.source_path || '');
        name.title = item.source_path || '';
        var meta = el('div', 'mf-pv__rel-meta');
        var metaTxt = [item.detected_format, item.conversion_status].filter(Boolean).join(' · ');
        meta.textContent = metaTxt;
        if (item.score != null) {
          var score = el('span', 'mf-pv__rel-score');
          score.textContent = ' (' + item.score.toFixed(2) + ')';
          meta.appendChild(score);
        }
        link.appendChild(name);
        link.appendChild(meta);
        listEl.appendChild(link);
      });
    }

    tabSemantic.addEventListener('click', function () {
      relatedMode = 'semantic';
      tabSemantic.classList.add('mf-pv__rel-tab--active');
      tabKeyword.classList.remove('mf-pv__rel-tab--active');
      if (fileInfo) loadRelated(fileInfo.source_path);
    });

    tabKeyword.addEventListener('click', function () {
      relatedMode = 'keyword';
      tabKeyword.classList.add('mf-pv__rel-tab--active');
      tabSemantic.classList.remove('mf-pv__rel-tab--active');
      if (fileInfo) loadRelated(fileInfo.source_path);
    });

    /* ── Search within file ─────────────────────────────────────────────── */

    function doSearch() {
      var q = searchInput.value.trim();
      if (!q) { showToast('Enter a search query', 'info'); return; }
      var mode = searchMode.value;

      searchStatus.textContent = 'Searching…';
      searchStatus.className = 'mf-pv__rel-status';
      clear(searchList);

      var url = '/api/search?q=' + encodeURIComponent(q) +
        '&mode=' + encodeURIComponent(mode) +
        '&context_file_id=' + encodeURIComponent(fileId);

      apiGet(url)
        .then(function (data) {
          var hits = data.hits || data.results || data.items || data || [];
          searchStatus.textContent = hits.length
            ? hits.length + ' result' + (hits.length === 1 ? '' : 's')
            : 'No results.';
          renderRelatedList(searchList, hits);
          searchAiBtn.href = '/search?q=' + encodeURIComponent(q) +
            '&ai=1&context_file_id=' + encodeURIComponent(fileId);
        })
        .catch(function (e) {
          searchStatus.className = 'mf-pv__rel-status mf-pv__rel-status--err';
          searchStatus.textContent = 'Search failed: ' + (e.detail || e.message);
        });
    }

    searchBtn.addEventListener('click', doSearch);
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') doSearch();
    });

    /* ── Force process ──────────────────────────────────────────────────── */

    forceBtn.addEventListener('click', function () {
      if (forceInProgress) return;
      if (!confirm('Force re-process this file? Any existing conversion output will be replaced.')) return;
      forceInProgress = true;
      forceStartMs = Date.now();
      forceBtn.disabled = true;
      forceBtn.textContent = 'Processing…';

      forceProgress.style.display = '';
      clear(forceProgress);
      var progMsg = el('div', 'mf-pv__force-msg');
      progMsg.textContent = 'Queued. Waiting for worker…';
      var elapsed = el('div', 'mf-pv__force-elapsed');
      elapsed.textContent = '0s';
      forceProgress.appendChild(progMsg);
      forceProgress.appendChild(elapsed);

      forceTimer = setInterval(function () {
        elapsed.textContent = Math.floor((Date.now() - forceStartMs) / 1000) + 's';
      }, 1000);

      apiPost('/api/files/' + encodeURIComponent(fileId) + '/force-process')
        .then(function () {
          clearInterval(forceTimer);
          forceInProgress = false;
          forceBtn.disabled = false;
          forceBtn.textContent = 'Force Re-process';
          progMsg.textContent = 'Re-process triggered. Status will update automatically.';
          forceProgress.className = 'mf-pv__force-progress mf-pv__force-progress--success';
          showToast('Re-process queued', 'success');
          setTimeout(function () { loadAll(); }, 3000);
        })
        .catch(function (e) {
          clearInterval(forceTimer);
          forceInProgress = false;
          forceBtn.disabled = false;
          forceBtn.textContent = 'Force Re-process';
          progMsg.textContent = 'Failed: ' + (e.detail || e.message);
          forceProgress.className = 'mf-pv__force-progress mf-pv__force-progress--error';
        });
    });

    /* ── Staleness check ────────────────────────────────────────────────── */

    function scheduleStalenessCheck() {
      clearTimeout(stalenessTimer);
      stalenessTimer = setTimeout(function () {
        if (document.hidden) { scheduleStalenessCheck(); return; }
        apiGet('/api/files/' + encodeURIComponent(fileId))
          .then(function (info) {
            var newTag = info.etag || info.updated_at || null;
            if (newTag && lastEtag && newTag !== lastEtag) {
              stale.style.display = '';
            }
            scheduleStalenessCheck();
          })
          .catch(function () { scheduleStalenessCheck(); });
      }, 30000);
    }

    /* ── Initial load ───────────────────────────────────────────────────── */
    loadAll();

    /* ── Return control handle ──────────────────────────────────────────── */
    return {
      refresh: function () { loadAll(); },
      destroy: function () {
        clearTimeout(stalenessTimer);
        clearInterval(forceTimer);
        if (selChip.parentNode) selChip.parentNode.removeChild(selChip);
      },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */
  global.MFPreview = { mount: mount };

})(window);
