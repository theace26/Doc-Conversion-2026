/* MarkFlow Document Viewer page component (new UX).
 *
 * Usage:
 *   MFViewer.mount(root, { role, index, id, returnQuery });
 *
 * Reads document metadata and content from the search APIs (which the
 * legacy viewer also uses — this is the established contract):
 *   GET /api/search/doc-info/{index}/{id}      — metadata + capability flags
 *   GET /api/search/source/{index}/{id}        — original file (inline-viewable)
 *   GET /api/search/view/{index}/{id}          — converted markdown (text/markdown)
 *   GET /api/search/download/{index}/{id}      — original file (attachment)
 *
 * Related-files context (operator/admin only — gracefully hidden on 403):
 *   GET /api/preview/related?path=<source_path>&mode=keyword&limit=8
 *
 * Force re-process (operator/admin only):
 *   POST /api/preview/force-action  with { path, action: 'reconvert' }
 *
 * Flag for review:
 *   GET /api/flags/lookup-source?source_path=<path>  (resolves source_file_id)
 *   POST /api/flags  with { source_file_id, reason, note }
 *
 * All BEM classes are prefixed `mf-vw__*`. Color/font/font-size tokens
 * are driven entirely by var(--mf-*); no hardcoded hex.
 *
 * Safe DOM throughout — no innerHTML with template strings. The rendered
 * markdown pane sanitises with DOMPurify (RETURN_DOM_FRAGMENT) so the
 * sanitised tree is appended as DOM nodes rather than assigned via
 * innerHTML. */
(function (global) {
  'use strict';

  /* ── Helpers ──────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
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

  /* Normalise a source format string to a coarse media bucket so we can
   * pick the right preview element. The doc-info API gives us a format
   * label like "pdf", "jpg", "mp4", "epub", "docx" etc. */
  function classifyFormat(fmt) {
    var f = (fmt || '').toLowerCase();
    if (f === 'pdf') return 'pdf';
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'tiff', 'tif'].indexOf(f) !== -1) return 'image';
    if (['mp4', 'm4v', 'webm', 'mov', 'mkv', 'avi'].indexOf(f) !== -1) return 'video';
    if (['mp3', 'wav', 'm4a', 'ogg', 'flac', 'opus', 'aac'].indexOf(f) !== -1) return 'audio';
    if (['txt', 'csv', 'html', 'htm', 'md', 'log', 'json', 'xml'].indexOf(f) !== -1) return 'text';
    return 'other';
  }


  /* ── API endpoints ────────────────────────────────────────────────────── */

  var API_DOC_INFO       = function (idx, id) { return '/api/search/doc-info/' + encodeURIComponent(idx) + '/' + encodeURIComponent(id); };
  var API_SOURCE         = function (idx, id) { return '/api/search/source/'   + encodeURIComponent(idx) + '/' + encodeURIComponent(id); };
  var API_VIEW_MD        = function (idx, id) { return '/api/search/view/'     + encodeURIComponent(idx) + '/' + encodeURIComponent(id); };
  var API_DOWNLOAD_SRC   = function (idx, id) { return '/api/search/download/' + encodeURIComponent(idx) + '/' + encodeURIComponent(id); };
  var API_RELATED        = '/api/preview/related';
  var API_FORCE_ACTION   = '/api/preview/force-action';
  var API_FLAG_LOOKUP    = '/api/flags/lookup-source';
  var API_FLAG_CREATE    = '/api/flags';


  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFViewer.mount: root element is required');

    var role        = (opts && opts.role) || 'member';
    var docIndex    = (opts && opts.index) || 'documents';
    var docId       = (opts && opts.id) || '';
    var returnQuery = (opts && opts.returnQuery) || '';
    var isOperator  = role === 'operator' || role === 'admin';

    /* ── State ────────────────────────────────────────────────────────────── */
    var info          = null;   /* doc-info response */
    var mdLoaded      = false;
    var mdText        = '';
    var sidebarOpen   = true;

    /* ── Skeleton ─────────────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-page-wrapper mf-vw');

    /* Header bar ─────────────────────────────────────────── */
    var header = el('div', 'mf-vw__header');

    var headerLeft = el('div', 'mf-vw__header-left');
    var crumb = el('a', 'mf-vw__crumb');
    crumb.href = returnQuery ? ('/search?q=' + encodeURIComponent(returnQuery)) : '/search';
    crumb.textContent = returnQuery ? 'Back to results' : 'Back to search';
    headerLeft.appendChild(crumb);

    var titleWrap = el('div', 'mf-vw__title-wrap');
    var titleEl = el('h1', 'mf-vw__title');
    titleEl.textContent = 'Loading…';
    titleWrap.appendChild(titleEl);
    var subtitleEl = el('div', 'mf-vw__subtitle');
    titleWrap.appendChild(subtitleEl);
    headerLeft.appendChild(titleWrap);

    header.appendChild(headerLeft);

    /* Action buttons */
    var actions = el('div', 'mf-vw__actions');

    var dlMdBtn = el('button', 'mf-btn mf-btn--ghost mf-vw__action');
    dlMdBtn.textContent = 'Download MD';
    dlMdBtn.title = 'Download converted Markdown';
    dlMdBtn.disabled = true;
    actions.appendChild(dlMdBtn);

    var dlOrigBtn = el('button', 'mf-btn mf-btn--ghost mf-vw__action');
    dlOrigBtn.textContent = 'Download original';
    dlOrigBtn.title = 'Download the original source file';
    dlOrigBtn.disabled = true;
    actions.appendChild(dlOrigBtn);

    var reprocessBtn = el('button', 'mf-btn mf-btn--ghost mf-vw__action');
    reprocessBtn.textContent = 'Force re-process';
    reprocessBtn.title = 'Re-run the conversion pipeline on this file';
    reprocessBtn.disabled = true;
    if (!isOperator) reprocessBtn.hidden = true;
    actions.appendChild(reprocessBtn);

    var flagBtn = el('button', 'mf-btn mf-btn--ghost mf-vw__action mf-vw__action--flag');
    flagBtn.textContent = '⚑ Flag for review';
    flagBtn.title = 'Flag this file for review (hides it from search until resolved)';
    flagBtn.disabled = true;
    actions.appendChild(flagBtn);

    var sidebarToggle = el('button', 'mf-btn mf-btn--ghost mf-vw__action mf-vw__sidebar-toggle');
    sidebarToggle.textContent = 'Hide sidebar';
    sidebarToggle.title = 'Toggle metadata sidebar';
    actions.appendChild(sidebarToggle);

    header.appendChild(actions);
    wrapper.appendChild(header);

    /* Body: dual pane + sidebar ─────────────────────────── */
    var body = el('div', 'mf-vw__body');

    /* Loading skeleton */
    var loadingState = el('div', 'mf-vw__loading');
    var loadingShimmer1 = el('div', 'mf-vw__skel mf-vw__skel--title');
    loadingState.appendChild(loadingShimmer1);
    var loadingShimmer2 = el('div', 'mf-vw__skel mf-vw__skel--lines');
    for (var i = 0; i < 6; i++) {
      loadingShimmer2.appendChild(el('div', 'mf-vw__skel-line'));
    }
    loadingState.appendChild(loadingShimmer2);
    body.appendChild(loadingState);

    /* Error state */
    var errorState = el('div', 'mf-vw__error');
    errorState.hidden = true;
    var errorTitle = el('h2', 'mf-vw__error-title');
    errorTitle.textContent = 'Document unavailable';
    errorState.appendChild(errorTitle);
    var errorText = el('p', 'mf-vw__error-text');
    errorState.appendChild(errorText);
    body.appendChild(errorState);

    /* Content (initially hidden until doc-info loads) */
    var content = el('div', 'mf-vw__content');
    content.hidden = true;

    /* Two-pane layout */
    var panes = el('div', 'mf-vw__panes');

    /* Markdown pane (left) */
    var mdPane = el('div', 'mf-vw__pane mf-vw__pane--md');
    var mdHeader = el('div', 'mf-vw__pane-header');
    var mdLabel = el('span', 'mf-vw__pane-label');
    mdLabel.textContent = 'Converted Markdown';
    mdHeader.appendChild(mdLabel);
    var mdToggle = el('div', 'mf-vw__pane-toggle');
    var mdRenderedBtn = el('button', 'mf-vw__pane-toggle-btn mf-vw__pane-toggle-btn--active');
    mdRenderedBtn.textContent = 'Rendered';
    mdRenderedBtn.dataset.view = 'rendered';
    mdToggle.appendChild(mdRenderedBtn);
    var mdRawBtn = el('button', 'mf-vw__pane-toggle-btn');
    mdRawBtn.textContent = 'Raw';
    mdRawBtn.dataset.view = 'raw';
    mdToggle.appendChild(mdRawBtn);
    mdHeader.appendChild(mdToggle);
    mdPane.appendChild(mdHeader);

    var mdBody = el('div', 'mf-vw__pane-body');
    var mdRendered = el('div', 'mf-vw__md-rendered');
    var mdPlaceholder = el('div', 'mf-vw__pane-placeholder');
    mdPlaceholder.textContent = 'Loading markdown…';
    mdRendered.appendChild(mdPlaceholder);
    mdBody.appendChild(mdRendered);
    var mdRaw = el('pre', 'mf-vw__md-raw');
    mdRaw.hidden = true;
    mdBody.appendChild(mdRaw);
    mdPane.appendChild(mdBody);

    panes.appendChild(mdPane);

    /* Original pane (right) */
    var origPane = el('div', 'mf-vw__pane mf-vw__pane--orig');
    var origHeader = el('div', 'mf-vw__pane-header');
    var origLabel = el('span', 'mf-vw__pane-label');
    origLabel.textContent = 'Original file';
    origHeader.appendChild(origLabel);
    var origFmtBadge = el('span', 'mf-vw__pane-fmt-badge');
    origHeader.appendChild(origFmtBadge);
    origPane.appendChild(origHeader);

    var origBody = el('div', 'mf-vw__pane-body mf-vw__pane-body--orig');
    var origPlaceholder = el('div', 'mf-vw__pane-placeholder');
    origPlaceholder.textContent = 'Loading…';
    origBody.appendChild(origPlaceholder);
    origPane.appendChild(origBody);

    panes.appendChild(origPane);

    content.appendChild(panes);

    /* Sidebar (right rail) */
    var sidebar = el('aside', 'mf-vw__sidebar');

    var sbMetaSection = el('section', 'mf-vw__sb-section');
    var sbMetaTitle = el('h3', 'mf-vw__sb-title');
    sbMetaTitle.textContent = 'Metadata';
    sbMetaSection.appendChild(sbMetaTitle);
    var sbMetaTable = el('dl', 'mf-vw__meta-table');
    sbMetaSection.appendChild(sbMetaTable);
    sidebar.appendChild(sbMetaSection);

    var sbFidSection = el('section', 'mf-vw__sb-section mf-vw__sb-section--fidelity');
    var sbFidTitle = el('h3', 'mf-vw__sb-title');
    sbFidTitle.textContent = 'Fidelity';
    sbFidSection.appendChild(sbFidTitle);
    var sbFidBadge = el('div', 'mf-vw__fid-badge');
    sbFidSection.appendChild(sbFidBadge);
    var sbFidNote = el('p', 'mf-vw__fid-note');
    sbFidSection.appendChild(sbFidNote);
    sidebar.appendChild(sbFidSection);

    var sbRelSection = el('section', 'mf-vw__sb-section');
    var sbRelTitle = el('h3', 'mf-vw__sb-title');
    sbRelTitle.textContent = 'Related files';
    sbRelSection.appendChild(sbRelTitle);
    var sbRelList = el('ul', 'mf-vw__rel-list');
    sbRelSection.appendChild(sbRelList);
    var sbRelStatus = el('p', 'mf-vw__rel-status');
    sbRelStatus.textContent = 'Loading related files…';
    sbRelSection.appendChild(sbRelStatus);
    sidebar.appendChild(sbRelSection);

    content.appendChild(sidebar);

    body.appendChild(content);
    wrapper.appendChild(body);
    root.appendChild(wrapper);

    /* ── Flag modal (BEM-prefixed; defines its own backdrop styles) ────────── */
    var flagBackdrop = buildFlagModal();
    document.body.appendChild(flagBackdrop);

    /* ── Sidebar toggle ──────────────────────────────────────────────────── */
    sidebarToggle.addEventListener('click', function () {
      sidebarOpen = !sidebarOpen;
      content.classList.toggle('mf-vw__content--sb-collapsed', !sidebarOpen);
      sidebarToggle.textContent = sidebarOpen ? 'Hide sidebar' : 'Show sidebar';
    });

    /* ── Markdown pane: rendered/raw toggle ──────────────────────────────── */
    function setMdView(view) {
      var rendered = view === 'rendered';
      mdRendered.hidden = !rendered;
      mdRaw.hidden      = rendered;
      mdRenderedBtn.classList.toggle('mf-vw__pane-toggle-btn--active', rendered);
      mdRawBtn.classList.toggle('mf-vw__pane-toggle-btn--active', !rendered);
    }
    mdRenderedBtn.addEventListener('click', function () { setMdView('rendered'); });
    mdRawBtn.addEventListener('click', function () { setMdView('raw'); });

    /* ── Action wiring ───────────────────────────────────────────────────── */

    dlMdBtn.addEventListener('click', function () {
      if (!info || !info.has_markdown) {
        showToast('No converted markdown available.', 'error');
        return;
      }
      /* /view returns text/markdown; trigger a download via a temp anchor. */
      var url = API_VIEW_MD(docIndex, docId);
      fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('Markdown not available');
          return r.blob();
        })
        .then(function (blob) {
          var dl = document.createElement('a');
          dl.href = URL.createObjectURL(blob);
          var base = (info.title || info.source_filename || 'document').replace(/\.[^./\\]+$/, '');
          dl.download = base + '.md';
          document.body.appendChild(dl);
          dl.click();
          document.body.removeChild(dl);
          setTimeout(function () { URL.revokeObjectURL(dl.href); }, 1000);
        })
        .catch(function (e) {
          showToast('Markdown download failed: ' + (e.message || 'unknown'), 'error');
        });
    });

    dlOrigBtn.addEventListener('click', function () {
      if (!info || !info.has_source) {
        showToast('Original file not available.', 'error');
        return;
      }
      window.location.href = API_DOWNLOAD_SRC(docIndex, docId);
    });

    reprocessBtn.addEventListener('click', function () {
      if (!info) return;
      /* doc-info doesn't return absolute source_path; we fall back to the
       * filename. The backend may reject if it can't resolve — handled
       * via the response. */
      var srcPath = info.source_path_resolved || info.source_filename || '';
      if (!srcPath) {
        showToast('Source path unknown — cannot re-process.', 'error');
        return;
      }
      if (!confirm('Re-run the conversion pipeline on this file? Existing output will be overwritten.')) {
        return;
      }
      reprocessBtn.disabled = true;
      reprocessBtn.textContent = 'Re-processing…';
      fetch(API_FORCE_ACTION, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path:   srcPath,
          action: 'reconvert',
        }),
      })
        .then(function (r) {
          if (!r.ok) {
            return r.json().catch(function () { return {}; }).then(function (b) {
              throw new Error(b.detail || ('Re-process failed: HTTP ' + r.status));
            });
          }
          return r.json();
        })
        .then(function () {
          showToast('Re-process queued — refresh in a moment to see updated output.', 'success');
        })
        .catch(function (e) {
          showToast(e.message || 'Re-process failed.', 'error');
        })
        .finally(function () {
          reprocessBtn.disabled = false;
          reprocessBtn.textContent = 'Force re-process';
        });
    });

    flagBtn.addEventListener('click', function () {
      if (!info) return;
      var srcPath = info.source_path_resolved || info.source_filename || docId;
      openFlagModal(srcPath);
    });

    /* ── Initial load ────────────────────────────────────────────────────── */

    if (!docId) {
      showError('No document ID provided in URL.');
      return apiHandle();
    }

    fetch(API_DOC_INFO(docIndex, docId), { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 404) {
          throw Object.assign(new Error('Document not found.'), { status: 404 });
        }
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (b) {
            throw Object.assign(new Error(b.detail || ('HTTP ' + r.status)), { status: r.status });
          });
        }
        return r.json();
      })
      .then(function (data) {
        info = data;
        renderInfo();
        renderMetaTable();
        renderFidelityBadge();
        renderOriginalPane();
        loadMarkdown();
        loadRelatedFiles();
      })
      .catch(function (e) {
        if (e.status === 404) {
          showError('Document not found. It may have been deleted or its index entry removed.');
        } else if (e.status === 403) {
          showError('You do not have permission to view this document.');
        } else {
          showError(e.message || 'Failed to load document.');
        }
      });

    /* ── Renderers ───────────────────────────────────────────────────────── */

    function renderInfo() {
      loadingState.hidden = true;
      content.hidden = false;

      var displayTitle = info.title || info.source_filename || 'Untitled document';
      titleEl.textContent = displayTitle;
      document.title = displayTitle + ' — MarkFlow Viewer';

      var subParts = [];
      var fmtUpper = (info.source_format || '').toUpperCase();
      if (fmtUpper) subParts.push(fmtUpper);
      if (info.source_size) subParts.push(formatSize(info.source_size));
      if (info.date) subParts.push('Converted ' + formatLocalTime(info.date));
      subtitleEl.textContent = subParts.join(' • ');

      origFmtBadge.textContent = fmtUpper || '—';

      /* Enable action buttons based on availability.
       *
       * Note: doc-info does NOT return the absolute source_path (used for
       * security gating). Force re-process and Flag both need the absolute
       * path. We try the operations using `source_filename` as a fallback;
       * the backend lookup-source / force-action will respond 404 if it
       * can't resolve, which we surface as a toast. A follow-up should
       * extend doc-info to include source_path so these features work
       * unconditionally. */
      dlMdBtn.disabled   = !info.has_markdown;
      dlOrigBtn.disabled = !info.has_source;
      flagBtn.disabled   = false;
      reprocessBtn.disabled = !isOperator || !info.has_source;
      if (!info.has_source) {
        reprocessBtn.title = 'Source file not available — cannot re-process.';
      }
    }

    function renderMetaTable() {
      clear(sbMetaTable);

      var rows = [];
      if (info.source_filename) rows.push(['Filename', info.source_filename]);
      if (info.source_format)   rows.push(['Format', String(info.source_format).toUpperCase()]);
      if (info.source_size)     rows.push(['Size', formatSize(info.source_size)]);
      if (info.date)            rows.push(['Converted', formatLocalTime(info.date)]);
      if (info.has_ocr)         rows.push(['OCR', 'Applied']);
      rows.push(['Index', docIndex]);
      rows.push(['Document ID', docId]);

      rows.forEach(function (row) {
        var dt = el('dt', 'mf-vw__meta-key');
        dt.textContent = row[0];
        sbMetaTable.appendChild(dt);
        var dd = el('dd', 'mf-vw__meta-val');
        dd.textContent = row[1];
        dd.title = row[1];
        sbMetaTable.appendChild(dd);
      });
    }

    function renderFidelityBadge() {
      var tier = info.fidelity_tier;
      clear(sbFidBadge);
      sbFidNote.textContent = '';

      if (tier == null || tier === '') {
        sbFidBadge.classList.add('mf-vw__fid-badge--unknown');
        sbFidBadge.textContent = 'Unknown';
        sbFidNote.textContent = 'Fidelity tier not recorded for this document.';
        return;
      }

      var tierStr = String(tier);
      var label = 'Tier ' + tierStr;
      var note  = '';
      if (tierStr === '1') {
        sbFidBadge.classList.add('mf-vw__fid-badge--t1');
        note = 'Plain Markdown — text only, no formatting preserved.';
      } else if (tierStr === '2') {
        sbFidBadge.classList.add('mf-vw__fid-badge--t2');
        note = 'Markdown + style sidecar — formatting preserved separately.';
      } else if (tierStr === '3') {
        sbFidBadge.classList.add('mf-vw__fid-badge--t3');
        note = 'High fidelity — embedded styles and structure preserved.';
      } else {
        sbFidBadge.classList.add('mf-vw__fid-badge--unknown');
      }
      sbFidBadge.textContent = label;
      sbFidNote.textContent  = note;
    }

    function renderOriginalPane() {
      clear(origBody);

      if (!info.has_source) {
        var ns = el('div', 'mf-vw__pane-placeholder mf-vw__pane-placeholder--missing');
        var nsT = el('strong');
        nsT.textContent = 'Original file not available';
        ns.appendChild(nsT);
        var nsP = el('p');
        nsP.textContent = 'The source file could not be located on disk. The conversion is still viewable.';
        ns.appendChild(nsP);
        origBody.appendChild(ns);
        return;
      }

      var bucket = classifyFormat(info.source_format);
      var srcUrl = API_SOURCE(docIndex, docId);

      if (bucket === 'pdf' && info.can_inline) {
        var emb = document.createElement('embed');
        emb.className = 'mf-vw__embed';
        emb.src = srcUrl;
        emb.type = 'application/pdf';
        origBody.appendChild(emb);
        return;
      }
      if (bucket === 'image' && info.can_inline) {
        var img = document.createElement('img');
        img.className = 'mf-vw__img';
        img.src = srcUrl;
        img.alt = info.source_filename || 'Original image';
        origBody.appendChild(img);
        return;
      }
      if (bucket === 'video') {
        var v = document.createElement('video');
        v.className = 'mf-vw__media';
        v.src = srcUrl;
        v.controls = true;
        v.preload = 'metadata';
        origBody.appendChild(v);
        return;
      }
      if (bucket === 'audio') {
        var au = document.createElement('audio');
        au.className = 'mf-vw__media mf-vw__media--audio';
        au.src = srcUrl;
        au.controls = true;
        au.preload = 'metadata';
        origBody.appendChild(au);
        return;
      }
      if (info.can_inline) {
        var ifr = document.createElement('iframe');
        ifr.className = 'mf-vw__iframe';
        ifr.src = srcUrl;
        ifr.title = info.source_filename || 'Original file preview';
        origBody.appendChild(ifr);
        return;
      }

      /* Non-previewable: download-only message. */
      var dl = el('div', 'mf-vw__pane-placeholder mf-vw__pane-placeholder--download');
      var dlIcon = el('div', 'mf-vw__file-icon');
      dlIcon.textContent = (info.source_format || '?').toUpperCase();
      dl.appendChild(dlIcon);
      var dlT = el('strong');
      dlT.textContent = info.source_filename || info.title || 'Original file';
      dl.appendChild(dlT);
      var dlP = el('p');
      dlP.textContent = 'This file format cannot be previewed in the browser.';
      dl.appendChild(dlP);
      var dlBtn = el('button', 'mf-btn mf-btn--primary mf-vw__pane-dl-btn');
      dlBtn.textContent = 'Download original';
      dlBtn.addEventListener('click', function () {
        window.location.href = API_DOWNLOAD_SRC(docIndex, docId);
      });
      dl.appendChild(dlBtn);
      origBody.appendChild(dl);
    }

    function loadMarkdown() {
      if (mdLoaded) return;
      mdLoaded = true;

      if (!info.has_markdown) {
        clear(mdRendered);
        var none = el('div', 'mf-vw__pane-placeholder mf-vw__pane-placeholder--missing');
        var nT = el('strong'); nT.textContent = 'No markdown conversion';
        none.appendChild(nT);
        var nP = el('p');
        nP.textContent = 'This document has no converted markdown output. Try Force re-process to run the pipeline again.';
        none.appendChild(nP);
        mdRendered.appendChild(none);
        mdRaw.textContent = '';
        return;
      }

      fetch(API_VIEW_MD(docIndex, docId), { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('Failed to load markdown (HTTP ' + r.status + ')');
          return r.text();
        })
        .then(function (text) {
          mdText = text;
          mdRaw.textContent = text;

          /* Render via marked + DOMPurify. We use RETURN_DOM_FRAGMENT so the
           * sanitised tree is returned as DocumentFragment nodes that we
           * appendChild directly — no innerHTML assignment, conforming to
           * the project's strict DOM-construction rule. */
          clear(mdRendered);
          if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
            /* Library missing — fall back to plain text */
            var pre = el('pre', 'mf-vw__md-raw');
            pre.textContent = text;
            mdRendered.appendChild(pre);
            return;
          }
          var rawHtml = marked.parse(text);
          var frag = DOMPurify.sanitize(rawHtml, {
            ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','a','ul','ol','li',
              'table','thead','tbody','tr','th','td','pre','code','blockquote',
              'em','strong','del','br','hr','img','span','div','sup','sub','dl','dt','dd'],
            ALLOWED_ATTR: ['href','src','alt','title','class','id','colspan','rowspan'],
            RETURN_DOM_FRAGMENT: true,
          });
          mdRendered.appendChild(frag);
        })
        .catch(function (e) {
          clear(mdRendered);
          var err = el('div', 'mf-vw__pane-placeholder mf-vw__pane-placeholder--error');
          var t = el('strong'); t.textContent = 'Could not load markdown';
          err.appendChild(t);
          var p = el('p'); p.textContent = e.message || 'Unknown error.';
          err.appendChild(p);
          mdRendered.appendChild(err);
        });
    }

    function loadRelatedFiles() {
      /* /api/preview/related is operator-gated; non-operators get 403.
       * Hide the section gracefully rather than show an error.
       *
       * The endpoint requires `path` and a query. doc-info doesn't return an
       * absolute path, so we pass source_filename as both the seed and the
       * query. Backend filters out the seed file from results.  This shows
       * "files with similar names / content" — the closest we can get to
       * 'other versions of the same source' with available API surface. */
      var q = info.title || info.source_filename || '';
      if (!q) {
        sbRelStatus.textContent = 'No context available.';
        return;
      }

      var path = info.source_filename || q;
      var url = API_RELATED +
        '?path=' + encodeURIComponent(path) +
        '&mode=keyword' +
        '&q=' + encodeURIComponent(q) +
        '&limit=8';

      fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
          if (r.status === 403) {
            sbRelSection.hidden = true;
            return null;
          }
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (data) {
          if (!data) return;
          renderRelatedFiles(data.results || [], data.warning);
        })
        .catch(function () {
          sbRelStatus.textContent = 'Related files unavailable.';
        });
    }

    function renderRelatedFiles(results, warning) {
      clear(sbRelList);
      if (warning) {
        sbRelStatus.textContent = warning;
        return;
      }
      if (!results.length) {
        sbRelStatus.textContent = 'No related files found.';
        return;
      }
      sbRelStatus.hidden = true;
      results.forEach(function (r) {
        var li = el('li', 'mf-vw__rel-item');

        var nameEl = el('div', 'mf-vw__rel-name');
        nameEl.textContent = r.name || '(unnamed)';
        nameEl.title = r.name || '';
        li.appendChild(nameEl);

        var metaEl = el('div', 'mf-vw__rel-meta');
        var bits = [];
        if (r.source_format) bits.push(String(r.source_format).toUpperCase());
        if (r.size_bytes)    bits.push(formatSize(r.size_bytes));
        metaEl.textContent = bits.join(' • ');
        li.appendChild(metaEl);

        if (r.doc_id) {
          /* Make the row a link to that document's viewer. */
          li.classList.add('mf-vw__rel-item--linked');
          li.setAttribute('role', 'link');
          li.tabIndex = 0;
          var goto = function () {
            var u = '/viewer?index=documents&id=' + encodeURIComponent(r.doc_id);
            if (returnQuery) u += '&q=' + encodeURIComponent(returnQuery);
            window.location.href = u;
          };
          li.addEventListener('click', goto);
          li.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goto(); }
          });
        }

        sbRelList.appendChild(li);
      });
    }

    function showError(msg) {
      loadingState.hidden = true;
      content.hidden = true;
      errorState.hidden = false;
      errorText.textContent = msg;
    }

    /* ── Flag modal (mirrors search-results pattern, BEM-prefixed) ─────── */

    var flagState = {};

    function buildFlagModal() {
      var backdrop = el('div', 'mf-vw__modal-backdrop');

      var dialog = el('div', 'mf-vw__modal');

      var dlgTitle = el('h3', 'mf-vw__modal-title');
      dlgTitle.textContent = 'Flag File for Review';
      dialog.appendChild(dlgTitle);

      var fnameP = el('p', 'mf-vw__modal-filename');
      fnameP.id = 'mf-vw-flag-filename';
      dialog.appendChild(fnameP);

      var reasonGrp = el('div', 'mf-vw__modal-fg');
      var reasonLabel = el('label');
      reasonLabel.htmlFor = 'mf-vw-flag-reason';
      reasonLabel.textContent = 'Reason';
      reasonGrp.appendChild(reasonLabel);
      var reasonSelect = el('select');
      reasonSelect.id = 'mf-vw-flag-reason';
      [
        ['',             'Select a reason…'],
        ['pii',          'Contains PII'],
        ['confidential', 'Confidential / Privileged'],
        ['unauthorized', 'Not Authorized to Share'],
        ['other',        'Other'],
      ].forEach(function (pair) {
        var opt = document.createElement('option');
        opt.value = pair[0];
        opt.textContent = pair[1];
        reasonSelect.appendChild(opt);
      });
      reasonGrp.appendChild(reasonSelect);
      dialog.appendChild(reasonGrp);

      var noteGrp = el('div', 'mf-vw__modal-fg');
      var noteLabel = el('label');
      noteLabel.htmlFor = 'mf-vw-flag-note';
      noteLabel.textContent = 'Note (optional)';
      noteGrp.appendChild(noteLabel);
      var noteInput = el('input');
      noteInput.type = 'text';
      noteInput.id = 'mf-vw-flag-note';
      noteInput.placeholder = 'Additional context…';
      noteGrp.appendChild(noteInput);
      dialog.appendChild(noteGrp);

      var btnRow = el('div', 'mf-vw__modal-btns');
      var cancelBtn = el('button', 'mf-btn mf-btn--ghost');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', closeFlagModal);
      btnRow.appendChild(cancelBtn);

      var submitBtn = el('button', 'mf-btn mf-btn--danger');
      submitBtn.id = 'mf-vw-flag-submit';
      submitBtn.textContent = 'Flag File';
      submitBtn.addEventListener('click', submitFlag);
      btnRow.appendChild(submitBtn);

      dialog.appendChild(btnRow);
      backdrop.appendChild(dialog);

      /* Click outside to dismiss */
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) closeFlagModal();
      });

      return backdrop;
    }

    function openFlagModal(sourcePath) {
      flagState = { sourcePath: sourcePath };
      var fnameP = document.getElementById('mf-vw-flag-filename');
      if (fnameP) fnameP.textContent = sourcePath;
      var r = document.getElementById('mf-vw-flag-reason');
      if (r) r.value = '';
      var n = document.getElementById('mf-vw-flag-note');
      if (n) n.value = '';
      flagBackdrop.classList.add('mf-vw__modal-backdrop--open');
    }

    function closeFlagModal() {
      flagBackdrop.classList.remove('mf-vw__modal-backdrop--open');
    }

    function submitFlag() {
      var reasonEl = document.getElementById('mf-vw-flag-reason');
      var reason = reasonEl ? reasonEl.value : '';
      if (!reason) { showToast('Please select a reason.', 'error'); return; }

      var noteEl = document.getElementById('mf-vw-flag-note');
      var note   = noteEl ? noteEl.value : '';
      var submitBtn = document.getElementById('mf-vw-flag-submit');
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Flagging…'; }

      var sourcePath = flagState.sourcePath;
      fetch(API_FLAG_LOOKUP + '?source_path=' + encodeURIComponent(sourcePath),
        { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('Could not look up source file.');
          return r.json();
        })
        .then(function (sfResp) {
          return fetch(API_FLAG_CREATE, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              source_file_id: sfResp.source_file_id,
              reason:         reason,
              note:           note,
            }),
          }).then(function (r) {
            if (!r.ok) {
              return r.json().catch(function () { return {}; }).then(function (b) {
                throw new Error(b.detail || ('Flag failed: HTTP ' + r.status));
              });
            }
            return r.json().catch(function () { return {}; });
          });
        })
        .then(function () {
          closeFlagModal();
          showToast('File flagged — hidden from search.', 'success');
        })
        .catch(function (err) {
          showToast((err && err.message) || 'Failed to flag file.', 'error');
        })
        .finally(function () {
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Flag File'; }
        });
    }

    /* ── Esc closes modal ────────────────────────────────────────────────── */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' &&
          flagBackdrop.classList.contains('mf-vw__modal-backdrop--open')) {
        closeFlagModal();
      }
    });

    /* ── Return handle ───────────────────────────────────────────────────── */
    return apiHandle();

    function apiHandle() {
      return {
        destroy: function () {
          if (flagBackdrop && flagBackdrop.parentNode) {
            flagBackdrop.parentNode.removeChild(flagBackdrop);
          }
        },
      };
    }
  }


  /* ── Export ────────────────────────────────────────────────────────────── */

  global.MFViewer = { mount: mount };

})(window);
