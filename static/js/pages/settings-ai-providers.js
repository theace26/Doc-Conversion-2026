/* MFAIProvidersDetail — AI providers settings detail page (Plan 6 Task 2).
 *
 * Usage:
 *   MFAIProvidersDetail.mount(slot, { providers, registry });
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout — no innerHTML anywhere.
 */
(function (global) {
  'use strict';

  var FIXED_SECTIONS = [
    { id: 'chain',  label: 'Active provider chain' },
    { id: 'image',  label: 'Image analysis routing' },
    { id: 'vector', label: 'Vector indexing' },
    { id: 'cost',   label: 'Cost cap & alerts' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _capitalize(str) {
    if (!str) return str;
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  function _buildSections(providers, registry) {
    var registryByType = {};
    (registry || []).forEach(function (r) {
      if (r.type) registryByType[r.type] = r;
    });

    var seenTypes = [];
    var typeSet = {};
    (providers || []).forEach(function (p) {
      if (p.provider_type && !typeSet[p.provider_type]) {
        typeSet[p.provider_type] = true;
        seenTypes.push(p.provider_type);
      }
    });

    var sections = [FIXED_SECTIONS[0]];

    seenTypes.forEach(function (type) {
      var displayName = registryByType[type]
        ? registryByType[type].display_name
        : _capitalize(type);
      sections.push({ id: 'provider-' + type, label: displayName, providerType: type });
    });

    sections.push(FIXED_SECTIONS[1]);
    sections.push(FIXED_SECTIONS[2]);
    sections.push(FIXED_SECTIONS[3]);

    return sections;
  }

  function _postAction(url, btn, resultEl, successText) {
    btn.disabled = true;
    btn.textContent = '…';
    resultEl.textContent = '';
    resultEl.className = 'mf-ai__action-result';

    return fetch(url, { method: 'POST', credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (text) {
            var body = text ? JSON.parse(text) : {};
            throw new Error(body.detail || ('HTTP ' + r.status));
          }).catch(function (e) { throw e; });
        }
        return r.text().then(function (text) {
          return text ? JSON.parse(text) : { ok: true };
        });
      })
      .then(function (data) {
        resultEl.classList.add('mf-ai__action-result--ok');
        resultEl.textContent = successText || '✓ OK';
        return data;
      })
      .catch(function (e) {
        resultEl.classList.add('mf-ai__action-result--error');
        resultEl.textContent = '✗ Error: ' + e.message;
        btn.disabled = false;
      });
  }

  function _makeVerifyBtn(provider) {
    var wrap = el('span');
    var btn = el('button', 'mf-ai__action-btn');
    btn.type = 'button';
    btn.textContent = 'Verify';
    var result = el('span', 'mf-ai__action-result');
    wrap.appendChild(btn);
    wrap.appendChild(result);

    btn.addEventListener('click', function () {
      var savedText = btn.textContent;
      _postAction('/api/llm-providers/' + provider.id + '/verify', btn, result, '✓ OK')
        .then(function () {
          btn.textContent = savedText;
          btn.disabled = false;
        });
    });

    return wrap;
  }

  function _makeActivateBtn(provider) {
    var wrap = el('span');
    var btn = el('button', 'mf-ai__action-btn');
    btn.type = 'button';
    var result = el('span', 'mf-ai__action-result');

    if (provider.is_active) {
      btn.textContent = 'Active ✓';
      btn.disabled = true;
    } else {
      btn.textContent = 'Set active';
    }

    wrap.appendChild(btn);
    wrap.appendChild(result);

    btn.addEventListener('click', function () {
      var savedText = btn.textContent;
      _postAction('/api/llm-providers/' + provider.id + '/activate', btn, result, '')
        .then(function (data) {
          if (data !== undefined) {
            btn.textContent = 'Active ✓';
            btn.disabled = true;
            result.textContent = '';
          } else {
            btn.textContent = savedText;
          }
        });
    });

    return wrap;
  }

  function _renderChain(contentSlot, opts) {
    var providers = opts.providers || [];

    if (providers.length === 0) {
      var stub = el('div', 'mf-stg__stub');
      var stubP = el('p');
      stubP.textContent = 'No providers configured. Add providers via Settings → AI Providers in the legacy settings page.';
      stub.appendChild(stubP);
      contentSlot.appendChild(stub);
      return;
    }

    var table = el('table', 'mf-ai__provider-table');

    var thead = el('thead');
    var headerRow = el('tr');
    ['Name', 'Type', 'Active', 'AI Assist', 'Model', 'Actions'].forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    providers.forEach(function (provider) {
      var row = el('tr');

      var tdName = el('td');
      var nameB = el('b');
      nameB.textContent = provider.name || '';
      tdName.appendChild(nameB);
      row.appendChild(tdName);

      var tdType = el('td');
      var typeBadge = el('span', 'mf-ai__type-badge');
      typeBadge.textContent = provider.provider_type || '';
      tdType.appendChild(typeBadge);
      row.appendChild(tdType);

      var tdActive = el('td');
      if (provider.is_active) {
        var activeBadge = el('span', 'mf-ai__active-badge');
        activeBadge.textContent = 'Active';
        tdActive.appendChild(activeBadge);
      }
      row.appendChild(tdActive);

      var tdAssist = el('td');
      if (provider.is_ai_assist) {
        var assistBadge = el('span', 'mf-ai__active-badge');
        assistBadge.textContent = 'AI Assist';
        tdAssist.appendChild(assistBadge);
      }
      row.appendChild(tdAssist);

      var tdModel = el('td');
      var modelCode = el('code');
      modelCode.style.fontFamily = 'var(--mf-font-mono, monospace)';
      modelCode.textContent = provider.model || '';
      tdModel.appendChild(modelCode);
      row.appendChild(tdModel);

      var tdActions = el('td');
      var verifyWrap = _makeVerifyBtn(provider);
      tdActions.appendChild(verifyWrap);
      tdActions.appendChild(document.createTextNode(' '));
      var activateWrap = _makeActivateBtn(provider);
      tdActions.appendChild(activateWrap);
      row.appendChild(tdActions);

      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    contentSlot.appendChild(table);
  }

  function _renderProviderType(contentSlot, type, opts, displayName) {
    var providers = (opts.providers || []).filter(function (p) {
      return p.provider_type === type;
    });

    providers.forEach(function (provider) {
      var fields = [
        { label: 'Name',          value: provider.name || '' },
        { label: 'API key',       value: provider.api_key_masked || '••••••••' },
        { label: 'Model',         value: provider.model || '' },
        { label: 'Provider type', value: provider.provider_type || '' },
      ];

      fields.forEach(function (f) {
        var label = el('label', 'mf-stg__field-label');
        label.textContent = f.label;
        contentSlot.appendChild(label);

        var input = el('input', 'mf-stg__field-input');
        input.type = 'text';
        input.readOnly = true;
        input.value = f.value;
        input.style.fontFamily = f.label === 'Model' || f.label === 'API key'
          ? 'var(--mf-font-mono, monospace)'
          : 'inherit';
        contentSlot.appendChild(input);
      });

      var actionsRow = el('div');
      actionsRow.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-top:1rem;';

      var verifyWrap = _makeVerifyBtn(provider);
      actionsRow.appendChild(verifyWrap);

      var activateWrap = _makeActivateBtn(provider);
      actionsRow.appendChild(activateWrap);

      contentSlot.appendChild(actionsRow);
    });

    var note = el('p', 'mf-ai__provider-note');
    note.textContent = 'To add or edit providers, use the legacy Settings page.';
    contentSlot.appendChild(note);
  }

  function _renderImage(contentSlot, opts) {
    var providers = opts.providers || [];
    var aiAssistProviders = providers.filter(function (p) { return p.is_ai_assist; });

    var label = el('label', 'mf-stg__field-label');
    label.textContent = 'Images are processed by';
    contentSlot.appendChild(label);

    var input = el('input', 'mf-stg__field-input');
    input.type = 'text';
    input.readOnly = true;
    input.value = aiAssistProviders.length > 0
      ? aiAssistProviders.map(function (p) { return p.name; }).join(', ')
      : 'Not configured';
    contentSlot.appendChild(input);

    var note = el('p', 'mf-ai__provider-note');
    note.textContent = 'Configure in AI Assist settings.';
    contentSlot.appendChild(note);
  }

  function _renderVector(contentSlot, opts) {
    var prefs = opts.prefs || {};

    var label = el('label', 'mf-stg__field-label');
    label.textContent = 'Qdrant endpoint';
    contentSlot.appendChild(label);

    var input = el('input', 'mf-stg__field-input');
    input.type = 'text';
    input.readOnly = true;
    input.value = prefs.vector_indexer_url || 'Not configured';
    input.style.fontFamily = 'var(--mf-font-mono, monospace)';
    contentSlot.appendChild(input);

    var statusLabel = el('label', 'mf-stg__field-label');
    statusLabel.textContent = 'Status';
    contentSlot.appendChild(statusLabel);

    var statusInput = el('input', 'mf-stg__field-input');
    statusInput.type = 'text';
    statusInput.readOnly = true;
    statusInput.value = 'Unknown (check server logs)';
    contentSlot.appendChild(statusInput);
  }

  function _renderCost(contentSlot) {
    var card = el('div', 'mf-ai__cost-card');

    var textDiv = el('div', 'mf-ai__cost-card-text');
    var textP = el('p');
    textP.textContent = 'Configure cost caps, rate tables, and spend alerts.';
    var noteP = el('p');
    noteP.style.marginTop = '0.4rem';
    noteP.style.fontSize = '0.8rem';
    noteP.textContent = 'Tracks API spend across all configured providers.';
    textDiv.appendChild(textP);
    textDiv.appendChild(noteP);
    card.appendChild(textDiv);

    var link = el('a', 'mf-ai__cost-link');
    link.href = '/settings/ai-providers/cost';
    link.textContent = 'Open Cost Cap settings →';
    card.appendChild(link);

    contentSlot.appendChild(card);
  }

  function _renderContent(contentSlot, activeSection, sections, opts) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var sectionDef = null;
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].id === activeSection) { sectionDef = sections[i]; break; }
    }

    var head = el('h2', 'mf-stg__section-head');
    head.textContent = sectionDef ? sectionDef.label : activeSection;
    contentSlot.appendChild(head);

    if (activeSection === 'chain') {
      _renderChain(contentSlot, opts);
    } else if (activeSection === 'image') {
      _renderImage(contentSlot, opts);
    } else if (activeSection === 'vector') {
      _renderVector(contentSlot, opts);
    } else if (activeSection === 'cost') {
      _renderCost(contentSlot);
    } else if (activeSection.indexOf('provider-') === 0) {
      var type = activeSection.slice('provider-'.length);
      var displayName = sectionDef ? sectionDef.label : _capitalize(type);
      _renderProviderType(contentSlot, type, opts, displayName);
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFAIProvidersDetail.mount: slot is required');
    opts = opts || {};

    var sections = _buildSections(opts.providers, opts.registry);
    var activeSection = opts.activeSection || 'chain';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'AI Providers.';
    body.appendChild(headline);

    var detail = el('div', 'mf-stg__detail');

    var sidebar = el('nav', 'mf-stg__sidebar');

    sections.forEach(function (sec) {
      var isActive = sec.id === activeSection;
      var link = el('a', 'mf-stg__sidebar-link' + (isActive ? ' mf-stg__sidebar-link--active' : ''));
      link.href = '#' + sec.id;
      link.textContent = sec.label;
      link.addEventListener('click', function (e) {
        e.preventDefault();
        activeSection = sec.id;
        sidebar.querySelectorAll('.mf-stg__sidebar-link').forEach(function (l) {
          l.classList.remove('mf-stg__sidebar-link--active');
        });
        link.classList.add('mf-stg__sidebar-link--active');
        _renderContent(contentSlot, activeSection, sections, opts);
      });
      sidebar.appendChild(link);
    });

    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, sections, opts);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFAIProvidersDetail = { mount: mount };
})(window);
