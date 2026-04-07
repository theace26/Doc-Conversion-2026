/**
 * MarkFlow AI-Assisted Search
 *
 * Manages the toggle, side drawer, SSE streaming, and source expansion.
 * Requires: no framework, plain fetch + ReadableStream.
 *
 * Public API (called from search.html inline JS):
 *   AIAssist.init()              — call once on DOMContentLoaded
 *   AIAssist.onResults(query, hits) — call after Meilisearch results render
 */

var AIAssist = (function() {
  var STORAGE_KEY = 'markflow_ai_assist_enabled';

  var _enabled = localStorage.getItem(STORAGE_KEY) === 'true';
  var _currentQuery = '';
  var _currentResults = [];
  var _currentSources = [];
  var _streaming = false;
  var _abortController = null;
  var _cachedResponseText = '';

  // Server-side status: { key_configured, org_enabled, enabled }.
  // Determined by /api/ai-assist/status during init().
  var _serverStatus = null;

  // DOM refs (set in init)
  var toggleBtn, drawer, drawerBody, drawerQueryBadge;

  // ── Toggle ────────────────────────────────────────────────────────────────

  function setEnabled(val) {
    _enabled = val;
    localStorage.setItem(STORAGE_KEY, val ? 'true' : 'false');
    _updateToggleUI();
    if (!val) closeDrawer();
  }

  function _updateToggleUI() {
    if (!toggleBtn) return;
    toggleBtn.classList.toggle('active', _enabled);
    var dot = toggleBtn.querySelector('.toggle-dot');
    if (dot) dot.title = _enabled ? 'AI Assist on' : 'AI Assist off';
    toggleBtn.setAttribute('aria-pressed', String(_enabled));
  }

  // ── Drawer open/close ─────────────────────────────────────────────────────

  function openDrawer() {
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
  }

  function closeDrawer() {
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    _cancelStream();
  }

  // ── Entry point called by search.html ─────────────────────────────────────

  function onResults(query, hits) {
    _currentQuery = query;
    _currentResults = hits || [];
    _currentSources = [];

    if (!_enabled || !_currentResults.length || !query.trim()) return;

    openDrawer();
    _renderLoading(query);
    _startSearchStream(query, hits);
  }

  // ── Stream: search synthesis ──────────────────────────────────────────────

  function _startSearchStream(query, results) {
    _cancelStream();
    _streaming = true;
    _abortController = new AbortController();

    var responseText = '';
    var textEl = _getOrCreateTextEl();
    var cursor = document.createElement('span');
    cursor.className = 'ai-cursor';
    textEl.appendChild(cursor);

    fetch('/api/ai-assist/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query, results: results }),
      signal: _abortController.signal,
    })
      .then(function(resp) {
        if (!resp.ok) throw new Error('Server error ' + resp.status);
        return _consumeStream(resp, function(event) {
          if (event.type === 'chunk') {
            responseText += event.text;
            textEl.textContent = responseText;
            textEl.appendChild(cursor);
          } else if (event.type === 'sources') {
            _currentSources = event.sources || [];
          } else if (event.type === 'done') {
            cursor.remove();
            _streaming = false;
            _cachedResponseText = responseText;
            _renderSources(_currentSources);
          } else if (event.type === 'error') {
            cursor.remove();
            _streaming = false;
            _renderError(event.message || 'Unknown error');
          }
        });
      })
      .catch(function(err) {
        if (err.name === 'AbortError') return;
        cursor.remove();
        _streaming = false;
        _renderError('Connection error. Check that the service is running.');
      });
  }

  // ── Stream: expand single document ────────────────────────────────────────

  function _startExpandStream(query, source) {
    _cancelStream();
    _streaming = true;
    _abortController = new AbortController();

    drawerBody.textContent = '';

    var heading = document.createElement('div');
    heading.className = 'ai-expand-heading';

    var backBtn = document.createElement('button');
    backBtn.className = 'ai-back-btn';
    backBtn.textContent = '\u2190 Back';
    backBtn.addEventListener('click', function() {
      _cancelStream();
      _renderSynthesisResults(_currentQuery, _cachedResponseText, _currentSources);
    });
    heading.appendChild(backBtn);

    var headingText = document.createElement('span');
    headingText.textContent = 'Deep read: ' + (source.title || 'Document');
    heading.appendChild(headingText);

    drawerBody.appendChild(heading);

    var loadEl = _buildLoadingEl();
    drawerBody.appendChild(loadEl);

    var expandText = '';
    var textEl = document.createElement('div');
    textEl.className = 'ai-response-text';
    var cursor = document.createElement('span');
    cursor.className = 'ai-cursor';

    fetch('/api/ai-assist/expand', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query, doc_id: source.doc_id }),
      signal: _abortController.signal,
    })
      .then(function(resp) {
        if (!resp.ok) throw new Error('Server error ' + resp.status);
        loadEl.remove();
        textEl.appendChild(cursor);
        drawerBody.appendChild(textEl);

        return _consumeStream(resp, function(event) {
          if (event.type === 'chunk') {
            expandText += event.text;
            textEl.textContent = expandText;
            textEl.appendChild(cursor);
          } else if (event.type === 'done') {
            cursor.remove();
            _streaming = false;
          } else if (event.type === 'error') {
            cursor.remove();
            _streaming = false;
            _renderError(event.message);
          }
        });
      })
      .catch(function(err) {
        if (err.name === 'AbortError') return;
        loadEl.remove();
        _streaming = false;
        _renderError('Failed to load document analysis.');
      });
  }

  // ── SSE consumer ──────────────────────────────────────────────────────────

  function _consumeStream(resp, onEvent) {
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';

    function pump() {
      return reader.read().then(function(result) {
        if (result.done) return;
        buffer += decoder.decode(result.value, { stream: true });

        var lines = buffer.split('\n');
        buffer = lines.pop(); // last item may be incomplete

        for (var i = 0; i < lines.length; i++) {
          var trimmed = lines[i].trim();
          if (trimmed.indexOf('data:') !== 0) continue;
          var raw = trimmed.slice(5).trim();
          if (!raw) continue;
          try {
            var event = JSON.parse(raw);
            onEvent(event);
          } catch(e) {
            // malformed event, skip
          }
        }

        return pump();
      });
    }

    return pump();
  }

  function _cancelStream() {
    if (_abortController) {
      _abortController.abort();
      _abortController = null;
    }
    _streaming = false;
  }

  // ── Render helpers ────────────────────────────────────────────────────────

  function _renderLoading(query) {
    if (drawerQueryBadge) drawerQueryBadge.textContent = query;
    drawerBody.textContent = '';
    drawerBody.appendChild(_buildLoadingEl());
  }

  function _buildLoadingEl() {
    var el = document.createElement('div');
    el.className = 'ai-drawer-loading';

    var dots = document.createElement('div');
    dots.className = 'ai-loading-dots';
    for (var i = 0; i < 3; i++) dots.appendChild(document.createElement('span'));
    el.appendChild(dots);

    var label = document.createElement('span');
    label.textContent = 'Synthesizing answer\u2026';
    el.appendChild(label);

    return el;
  }

  function _getOrCreateTextEl() {
    drawerBody.textContent = '';
    var el = document.createElement('div');
    el.className = 'ai-response-text';
    el.id = 'ai-response-text';
    drawerBody.appendChild(el);
    return el;
  }

  function _renderSynthesisResults(query, text, sources) {
    if (drawerQueryBadge) drawerQueryBadge.textContent = query;
    drawerBody.textContent = '';

    if (text) {
      var textEl = document.createElement('div');
      textEl.className = 'ai-response-text';
      textEl.id = 'ai-response-text';
      textEl.textContent = text;
      drawerBody.appendChild(textEl);
    }

    if (sources && sources.length) {
      _renderSources(sources);
    }
  }

  function _renderSources(sources) {
    if (!sources.length) return;

    // Cache the current text for "back" navigation
    var textEl = document.getElementById('ai-response-text');
    if (textEl) _cachedResponseText = textEl.textContent;

    var section = document.createElement('div');
    section.className = 'ai-sources-section';

    var label = document.createElement('div');
    label.className = 'ai-sources-label';
    label.textContent = 'Sources';
    section.appendChild(label);

    sources.forEach(function(src) {
      var item = document.createElement('div');
      item.className = 'ai-source-item';

      var meta = document.createElement('div');
      meta.className = 'ai-source-meta';

      var indexSpan = document.createElement('span');
      indexSpan.className = 'ai-source-index';
      indexSpan.textContent = src.index;
      meta.appendChild(indexSpan);

      var titleSpan = document.createElement('span');
      titleSpan.className = 'ai-source-title';
      titleSpan.title = src.path || '';
      titleSpan.textContent = src.title || 'Untitled';
      meta.appendChild(titleSpan);

      var typeSpan = document.createElement('span');
      typeSpan.className = 'ai-source-type';
      typeSpan.textContent = src.file_type || '';
      meta.appendChild(typeSpan);

      var expandBtn = document.createElement('button');
      expandBtn.className = 'ai-expand-btn';
      expandBtn.textContent = 'Read full doc';
      expandBtn.disabled = !src.doc_id;
      expandBtn.title = src.doc_id ? 'Deep analysis of this document' : 'No converted doc available';
      expandBtn.addEventListener('click', (function(s) {
        return function() { _startExpandStream(_currentQuery, s); };
      })(src));

      item.appendChild(meta);
      item.appendChild(expandBtn);
      section.appendChild(item);
    });

    drawerBody.appendChild(section);
  }

  function _renderError(message) {
    drawerBody.textContent = '';
    var el = document.createElement('div');
    el.className = 'ai-drawer-error';
    el.textContent = 'AI Assist error: ' + message;
    drawerBody.appendChild(el);
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    toggleBtn = document.getElementById('ai-assist-toggle');
    drawer = document.getElementById('ai-assist-drawer');
    drawerBody = document.getElementById('ai-drawer-body');
    drawerQueryBadge = document.getElementById('ai-drawer-query-badge');

    if (!toggleBtn || !drawer || !drawerBody) {
      console.warn('AIAssist: required DOM elements not found');
      return;
    }

    _updateToggleUI();

    toggleBtn.addEventListener('click', function() {
      // Gating: if the server says we're not configured / not enabled, do
      // NOT toggle the local enabled flag — instead surface a clear notice.
      if (_serverStatus && !_serverStatus.key_configured) {
        _showNotConfiguredNotice('missing_key');
        return;
      }
      if (_serverStatus && _serverStatus.key_configured && !_serverStatus.org_enabled) {
        _showNotConfiguredNotice('org_disabled');
        return;
      }
      setEnabled(!_enabled);
    });

    var closeBtn = document.getElementById('ai-drawer-close');
    if (closeBtn) closeBtn.addEventListener('click', function() { closeDrawer(); });

    // Keyboard: Escape closes drawer
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
    });

    // Check the server status and reflect it on the toggle button without
    // hiding it. The button remains visible so the user knows the feature
    // exists; click handler above shows a clear notice when misconfigured.
    fetch('/api/ai-assist/status')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        _serverStatus = data || {};
        _applyServerStatusToButton();
      })
      .catch(function() {
        _serverStatus = { key_configured: false, org_enabled: false, enabled: false };
        _applyServerStatusToButton();
      });
  }

  function _applyServerStatusToButton() {
    if (!toggleBtn || !_serverStatus) return;
    if (!_serverStatus.key_configured) {
      toggleBtn.classList.add('needs-config');
      toggleBtn.title = 'AI Assist not configured \u2014 click for setup instructions';
    } else if (!_serverStatus.org_enabled) {
      toggleBtn.classList.add('needs-config');
      toggleBtn.title = 'AI Assist is disabled by an administrator \u2014 click for details';
    } else {
      toggleBtn.classList.remove('needs-config');
      toggleBtn.title = 'Toggle AI-assisted synthesis of search results';
    }
  }

  function _showNotConfiguredNotice(reason) {
    if (!drawer || !drawerBody) {
      alert(
        reason === 'missing_key'
          ? 'AI Assist requires an active Anthropic provider on the Providers page.'
          : 'AI Assist is currently disabled by an administrator. Enable it on the Settings page.'
      );
      return;
    }
    openDrawer();
    drawerBody.textContent = '';

    var box = document.createElement('div');
    box.className = 'ai-drawer-error';
    box.style.padding = '1rem';

    var h = document.createElement('strong');
    h.textContent = 'AI Assist is not available';
    box.appendChild(h);

    var p = document.createElement('p');
    p.style.marginTop = '0.5rem';

    if (reason === 'missing_key') {
      // Server-provided error message (e.g. "Active LLM provider is 'openai'.
      // AI Assist currently requires an Anthropic provider...") is preferred
      // when present. Otherwise fall back to the generic instructions.
      var msg = (_serverStatus && _serverStatus.provider_error)
        || 'AI Assist uses the same LLM provider as the image scanner. Add an Anthropic provider with a valid API key on the Providers page and mark it as Active.';
      p.appendChild(document.createTextNode(msg + ' '));
      p.appendChild(document.createTextNode('Open the '));
      var providersLink = document.createElement('a');
      providersLink.href = '/providers.html';
      providersLink.textContent = 'Providers page';
      p.appendChild(providersLink);
      p.appendChild(document.createTextNode(' to configure it.'));
      box.appendChild(p);
    } else {
      p.appendChild(document.createTextNode('An administrator must enable AI Assist on the '));
      var a = document.createElement('a');
      a.href = '/settings.html#ai-assist-settings';
      a.textContent = 'Settings page';
      p.appendChild(a);
      p.appendChild(document.createTextNode('.'));
      box.appendChild(p);
    }

    drawerBody.appendChild(box);
  }

  return { init: init, onResults: onResults };
})();
