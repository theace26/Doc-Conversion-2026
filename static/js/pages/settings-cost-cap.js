/* MFCostCapDetail — Cost overview, spend tiles, and daily chart (Plan 7 Task 1).
 *
 * Usage:
 *   MFCostCapDetail.mount(slot, { rateTable, period, period30, staleness, providers, prefs });
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout — no innerHTML anywhere.
 */
(function (global) {
  'use strict';

  var CHART_COLORS = [
    'var(--mf-color-accent)',
    'var(--mf-color-success)',
    'var(--mf-color-warn)',
    'var(--mf-color-error)',
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function elNS(ns, tag, cls) {
    var n = document.createElementNS(ns, tag);
    if (cls) n.setAttribute('class', cls);
    return n;
  }

  function _formatUSD(val) {
    var n = Number(val);
    if (isNaN(n)) return '$0.00';
    return '$' + n.toFixed(2);
  }

  function _formatDate(val) {
    if (!val) return '—';
    if (typeof global.parseUTC === 'function') {
      var d = global.parseUTC(val);
      if (d && !isNaN(d.getTime())) return d.toLocaleDateString();
    }
    return String(val);
  }

  function _pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function _todayDateString() {
    return new Date().toISOString().slice(0, 10); // YYYY-MM-DD in UTC
  }

  function _todayUSD(daily) {
    var today = _todayDateString();
    var entry = null;
    for (var i = 0; i < daily.length; i++) {
      if (daily[i].date === today) { entry = daily[i]; break; }
    }
    return entry ? Number(entry.usd) : 0;
  }

  function _makeSaveBar(onSave, onDiscard) {
    var bar = el('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-top:1.4rem;';

    var saveBtn = el('button', 'mf-btn mf-btn--primary');
    saveBtn.textContent = 'Save changes';
    bar.appendChild(saveBtn);

    var discardBtn = el('button', 'mf-btn mf-btn--ghost');
    discardBtn.textContent = 'Discard';
    bar.appendChild(discardBtn);

    var savedMsg = el('span');
    savedMsg.style.cssText = 'font-size:0.85rem;color:var(--mf-color-success);opacity:0;transition:opacity 0.2s;';
    savedMsg.textContent = 'Saved';
    bar.appendChild(savedMsg);

    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      onSave(saveBtn, savedMsg);
    });

    discardBtn.addEventListener('click', function () {
      onDiscard();
    });

    return { bar: bar, saveBtn: saveBtn, savedMsg: savedMsg };
  }

  function _showSaved(saveBtn, savedMsg) {
    savedMsg.style.opacity = '1';
    setTimeout(function () { savedMsg.style.opacity = '0'; }, 2000);
    saveBtn.disabled = false;
  }

  /* ── Stale banner ── */
  function _buildStaleBanner(staleness) {
    var banner = el('div', 'mf-cost__stale-banner');
    var ageDays = staleness.age_days != null ? staleness.age_days : '?';
    banner.textContent = 'Cost data may be stale — last updated ' + ageDays + ' days ago.';
    return banner;
  }

  /* ── SVG chart (single provider) ── */
  function _buildChartSingle(daily) {
    var wrap = el('div', 'mf-cost__chart-wrap');
    var svgNS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 400 80');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'mf-cost__chart-svg');

    var slice = daily.slice(-14);
    if (slice.length < 2) {
      var noDataText = document.createElementNS(svgNS, 'text');
      noDataText.setAttribute('x', '200');
      noDataText.setAttribute('y', '44');
      noDataText.setAttribute('text-anchor', 'middle');
      noDataText.setAttribute('font-size', '12');
      noDataText.setAttribute('fill', 'var(--mf-color-text-muted)');
      noDataText.textContent = 'No chart data available';
      svg.appendChild(noDataText);
      wrap.appendChild(svg);
      return wrap;
    }

    var maxVal = 0;
    for (var i = 0; i < slice.length; i++) {
      var v = Number(slice[i].usd);
      if (v > maxVal) maxVal = v;
    }
    if (maxVal === 0) maxVal = 1;

    var pts = [];
    for (var j = 0; j < slice.length; j++) {
      var x = (j / (slice.length - 1)) * 400;
      var y = 80 - (Number(slice[j].usd) / maxVal) * 70 - 5;
      pts.push(x + ',' + y);
    }
    var pointsStr = pts.join(' ');

    var line = document.createElementNS(svgNS, 'polyline');
    line.setAttribute('points', pointsStr);
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', 'var(--mf-color-accent)');
    line.setAttribute('stroke-width', '2');
    svg.appendChild(line);

    wrap.appendChild(svg);
    return wrap;
  }

  /* ── SVG chart (multiple providers) ── */
  function _buildChartMulti(daily, providers) {
    var wrap = el('div', 'mf-cost__chart-wrap');
    var svgNS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 400 80');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'mf-cost__chart-svg');

    var slice = daily.slice(-14);
    if (slice.length < 2) {
      var noDataText = document.createElementNS(svgNS, 'text');
      noDataText.setAttribute('x', '200');
      noDataText.setAttribute('y', '44');
      noDataText.setAttribute('text-anchor', 'middle');
      noDataText.setAttribute('font-size', '12');
      noDataText.setAttribute('fill', 'var(--mf-color-text-muted)');
      noDataText.textContent = 'No chart data available';
      svg.appendChild(noDataText);
      wrap.appendChild(svg);
      return wrap;
    }

    var maxVal = 0;
    for (var i = 0; i < slice.length; i++) {
      var dayUSD = Number(slice[i].usd);
      if (dayUSD > maxVal) maxVal = dayUSD;
    }
    if (maxVal === 0) maxVal = 1;

    for (var pi = 0; pi < providers.length; pi++) {
      var provName = providers[pi];
      var color = CHART_COLORS[pi % CHART_COLORS.length];
      var pts = [];
      for (var j = 0; j < slice.length; j++) {
        var x = (j / (slice.length - 1)) * 400;
        var provUSD = 0;
        if (slice[j].by_provider && slice[j].by_provider[provName] != null) {
          provUSD = Number(slice[j].by_provider[provName]);
        }
        var y = 80 - (provUSD / maxVal) * 70 - 5;
        pts.push(x + ',' + y);
      }
      var line = document.createElementNS(svgNS, 'polyline');
      line.setAttribute('points', pts.join(' '));
      line.setAttribute('fill', 'none');
      line.setAttribute('stroke', color);
      line.setAttribute('stroke-width', '2');
      svg.appendChild(line);
    }

    wrap.appendChild(svg);

    var legend = el('div', 'mf-cost__legend');
    for (var li = 0; li < providers.length; li++) {
      var chip = el('span', 'mf-cost__legend-chip');
      chip.textContent = providers[li];
      chip.style.background = CHART_COLORS[li % CHART_COLORS.length];
      chip.style.color = 'var(--mf-surface)';
      legend.appendChild(chip);
    }
    wrap.appendChild(legend);

    return wrap;
  }

  /* ── Spend breakdown table (no provider column) ── */
  function _buildBreakdownTableSingle(byModel) {
    var table = el('table', 'mf-cost__breakdown-table');
    var thead = el('thead');
    var headerRow = el('tr');
    ['Model', 'Input tokens', 'Output tokens', 'Cost'].forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    if (!byModel || byModel.length === 0) {
      var emptyRow = el('tr');
      var emptyTd = el('td');
      emptyTd.setAttribute('colspan', '4');
      emptyTd.style.cssText = 'color:var(--mf-text-muted);font-style:italic;padding:1rem 0.75rem;';
      emptyTd.textContent = 'No spend data.';
      emptyRow.appendChild(emptyTd);
      tbody.appendChild(emptyRow);
    } else {
      byModel.forEach(function (row) {
        var tr = el('tr');
        var tdModel = el('td');
        tdModel.textContent = row.model || '—';
        tr.appendChild(tdModel);
        var tdIn = el('td');
        tdIn.textContent = row.input_tokens != null ? Number(row.input_tokens).toLocaleString() : '—';
        tr.appendChild(tdIn);
        var tdOut = el('td');
        tdOut.textContent = row.output_tokens != null ? Number(row.output_tokens).toLocaleString() : '—';
        tr.appendChild(tdOut);
        var tdCost = el('td');
        tdCost.textContent = _formatUSD(row.usd);
        tr.appendChild(tdCost);
        tbody.appendChild(tr);
      });
    }
    table.appendChild(tbody);
    return table;
  }

  /* ── Spend breakdown table (with provider column and totals row) ── */
  function _buildBreakdownTableMulti(byModel) {
    var table = el('table', 'mf-cost__breakdown-table');
    var thead = el('thead');
    var headerRow = el('tr');
    ['Provider', 'Model', 'Input tokens', 'Output tokens', 'Cost'].forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    var totalUSD = 0;
    var totalIn = 0;
    var totalOut = 0;
    var hasData = byModel && byModel.length > 0;

    if (!hasData) {
      var emptyRow = el('tr');
      var emptyTd = el('td');
      emptyTd.setAttribute('colspan', '5');
      emptyTd.style.cssText = 'color:var(--mf-text-muted);font-style:italic;padding:1rem 0.75rem;';
      emptyTd.textContent = 'No spend data.';
      emptyRow.appendChild(emptyTd);
      tbody.appendChild(emptyRow);
    } else {
      byModel.forEach(function (row) {
        var tr = el('tr');
        var tdProv = el('td');
        tdProv.textContent = row.provider || '—';
        tr.appendChild(tdProv);
        var tdModel = el('td');
        tdModel.textContent = row.model || '—';
        tr.appendChild(tdModel);
        var inToks = row.input_tokens != null ? Number(row.input_tokens) : 0;
        var outToks = row.output_tokens != null ? Number(row.output_tokens) : 0;
        var rowUSD = row.usd != null ? Number(row.usd) : 0;
        totalIn += inToks;
        totalOut += outToks;
        totalUSD += rowUSD;
        var tdIn = el('td');
        tdIn.textContent = inToks.toLocaleString();
        tr.appendChild(tdIn);
        var tdOut = el('td');
        tdOut.textContent = outToks.toLocaleString();
        tr.appendChild(tdOut);
        var tdCost = el('td');
        tdCost.textContent = _formatUSD(rowUSD);
        tr.appendChild(tdCost);
        tbody.appendChild(tr);
      });

      var totalsRow = el('tr');
      totalsRow.style.cssText = 'border-top:2px solid var(--mf-color-accent);font-weight:700;';
      var tProv = el('td');
      tProv.textContent = 'Total';
      totalsRow.appendChild(tProv);
      var tModel = el('td');
      totalsRow.appendChild(tModel);
      var tIn = el('td');
      tIn.textContent = totalIn.toLocaleString();
      totalsRow.appendChild(tIn);
      var tOut = el('td');
      tOut.textContent = totalOut.toLocaleString();
      totalsRow.appendChild(tOut);
      var tCost = el('td');
      tCost.textContent = _formatUSD(totalUSD);
      totalsRow.appendChild(tCost);
      tbody.appendChild(totalsRow);
    }

    table.appendChild(tbody);
    return table;
  }

  /* ── Overview section ── */
  function _renderOverview(contentSlot, opts, setSection) {
    var period = opts.period || { total_usd: 0, by_provider: {}, by_model: [], daily: [] };
    var staleness = opts.staleness || { is_stale: false, age_days: 0 };
    var providers = opts.providers || [];
    var daily = period.daily || [];
    var byModel = period.by_model || [];

    var isSingle = providers.length <= 1;

    /* tiles */
    var tilesDiv = el('div', 'mf-cost__tiles ' + (isSingle ? 'mf-cost__tiles--2up' : 'mf-cost__tiles--3up'));

    var todayUSD = _todayUSD(daily);

    var tile1 = el('div', 'mf-cost__tile');
    var tile1Label = el('div', 'mf-cost__tile-label');
    tile1Label.textContent = 'Spend today';
    tile1.appendChild(tile1Label);
    var tile1Val = el('div', 'mf-cost__tile-value');
    tile1Val.textContent = _formatUSD(todayUSD);
    tile1.appendChild(tile1Val);
    tilesDiv.appendChild(tile1);

    var tile2 = el('div', 'mf-cost__tile');
    var tile2Label = el('div', 'mf-cost__tile-label');
    tile2Label.textContent = 'Spend this month';
    tile2.appendChild(tile2Label);
    var tile2Val = el('div', 'mf-cost__tile-value');
    tile2Val.textContent = _formatUSD(period.total_usd);
    tile2.appendChild(tile2Val);
    tilesDiv.appendChild(tile2);

    if (!isSingle) {
      var tile3 = el('div', 'mf-cost__tile');
      var tile3Label = el('div', 'mf-cost__tile-label');
      tile3Label.textContent = 'Active providers';
      tile3.appendChild(tile3Label);
      var tile3Val = el('div', 'mf-cost__tile-value');
      tile3Val.textContent = String(providers.length);
      tile3Val.title = providers.join(', ');
      tile3.appendChild(tile3Val);
      tilesDiv.appendChild(tile3);
    }

    contentSlot.appendChild(tilesDiv);

    /* stale banner */
    if (staleness.is_stale === true) {
      contentSlot.appendChild(_buildStaleBanner(staleness));
    }

    /* chart */
    if (isSingle) {
      contentSlot.appendChild(_buildChartSingle(daily));
    } else {
      contentSlot.appendChild(_buildChartMulti(daily, providers));
    }

    /* breakdown table */
    var tableHead = el('h3', 'mf-stg__section-subhead');
    tableHead.textContent = 'Spend by model';
    contentSlot.appendChild(tableHead);

    if (isSingle) {
      contentSlot.appendChild(_buildBreakdownTableSingle(byModel));
    } else {
      contentSlot.appendChild(_buildBreakdownTableMulti(byModel));
    }
  }

  /* ── Rates by provider section ── */
  function _renderProviderRates(contentSlot, providerName, rateTable, setSection) {
    var rates = (rateTable || []).filter(function (r) {
      return r.provider === providerName;
    });

    if (rates.length === 0) {
      var stub = el('p');
      stub.style.cssText = 'color:var(--mf-text-muted);font-style:italic;';
      stub.textContent = 'No rates loaded for ' + providerName + '. Import a CSV to add rates.';
      contentSlot.appendChild(stub);
      return;
    }

    var hasCacheWrite = false;
    var hasCacheRead = false;
    for (var i = 0; i < rates.length; i++) {
      if (rates[i].cache_write_per_1m != null) hasCacheWrite = true;
      if (rates[i].cache_read_per_1m != null) hasCacheRead = true;
    }

    var table = el('table', 'mf-cost__breakdown-table');
    var thead = el('thead');
    var headerRow = el('tr');
    var cols = ['Model', 'Input ($/1M)', 'Output ($/1M)'];
    if (hasCacheWrite) cols.push('Cache write');
    if (hasCacheRead) cols.push('Cache read');
    cols.push('Effective date');
    cols.forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    rates.forEach(function (rate) {
      var tr = el('tr');
      var tdModel = el('td');
      tdModel.textContent = rate.model || '—';
      tr.appendChild(tdModel);
      var tdIn = el('td');
      tdIn.textContent = rate.input_per_1m != null ? _formatUSD(rate.input_per_1m) : '—';
      tr.appendChild(tdIn);
      var tdOut = el('td');
      tdOut.textContent = rate.output_per_1m != null ? _formatUSD(rate.output_per_1m) : '—';
      tr.appendChild(tdOut);
      if (hasCacheWrite) {
        var tdCW = el('td');
        tdCW.textContent = rate.cache_write_per_1m != null ? _formatUSD(rate.cache_write_per_1m) : '—';
        tr.appendChild(tdCW);
      }
      if (hasCacheRead) {
        var tdCR = el('td');
        tdCR.textContent = rate.cache_read_per_1m != null ? _formatUSD(rate.cache_read_per_1m) : '—';
        tr.appendChild(tdCR);
      }
      var tdDate = el('td');
      tdDate.textContent = _formatDate(rate.effective_date);
      tr.appendChild(tdDate);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    contentSlot.appendChild(table);

    var note = el('p', 'mf-cost__source-note');
    note.textContent = 'Source: CSV import. Update rates in ';
    var noteLink = el('a');
    noteLink.href = '#sources';
    noteLink.textContent = 'Sources & CSV import';
    noteLink.style.color = 'var(--mf-color-accent)';
    noteLink.addEventListener('click', function (e) {
      e.preventDefault();
      if (typeof setSection === 'function') {
        setSection('sources');
      }
    });
    note.appendChild(noteLink);
    var noteTrail = document.createTextNode(' →.');
    note.appendChild(noteTrail);
    contentSlot.appendChild(note);
  }

  /* ── RFC 4180-compliant CSV line splitter ── */
  function _splitCSVLine(line) {
    var fields = [];
    var i = 0;
    while (i < line.length) {
      if (line[i] === '"') {
        var field = '';
        i++; // skip opening quote
        while (i < line.length) {
          if (line[i] === '"') {
            if (i + 1 < line.length && line[i + 1] === '"') {
              field += '"'; // escaped quote
              i += 2;
            } else {
              i++; // skip closing quote
              break;
            }
          } else {
            field += line[i];
            i++;
          }
        }
        // skip comma after field
        if (i < line.length && line[i] === ',') i++;
        fields.push(field);
      } else {
        var end = line.indexOf(',', i);
        if (end === -1) {
          fields.push(line.slice(i).trim());
          break;
        } else {
          fields.push(line.slice(i, end).trim());
          i = end + 1;
        }
      }
    }
    return fields;
  }

  /* ── CSV parser ── */
  function _parseCSV(text) {
    var REQUIRED = ['provider', 'model', 'input_per_1m', 'output_per_1m'];
    /* intentionally not validated — optional columns are preserved as-is */

    if (text.charCodeAt(0) === 0xFEFF) {
      text = text.slice(1);
    }

    var lines = text.split(/\r?\n/);
    var nonEmpty = [];
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].trim() !== '') nonEmpty.push({ raw: lines[i], lineNum: i + 1 });
    }

    if (nonEmpty.length === 0) {
      return { rows: [], errors: [{ row: 0, message: 'File is empty.' }] };
    }

    var headerLine = nonEmpty[0].raw;
    var headers = _splitCSVLine(headerLine).map(function (h) { return h.toLowerCase(); });

    var errors = [];
    for (var ri = 0; ri < REQUIRED.length; ri++) {
      if (headers.indexOf(REQUIRED[ri]) === -1) {
        errors.push({ row: 0, message: 'Missing required column: ' + REQUIRED[ri] });
      }
    }
    if (errors.length > 0) {
      return { rows: [], errors: errors };
    }

    var rows = [];
    for (var di = 1; di < nonEmpty.length; di++) {
      var lineNum = nonEmpty[di].lineNum;
      var cells = _splitCSVLine(nonEmpty[di].raw);
      var rowObj = {};
      for (var hi = 0; hi < headers.length; hi++) {
        rowObj[headers[hi]] = cells[hi] !== undefined ? cells[hi] : '';
      }
      var rowErrors = false;
      for (var rqi = 0; rqi < REQUIRED.length; rqi++) {
        var colName = REQUIRED[rqi];
        if (!rowObj[colName] || rowObj[colName] === '') {
          errors.push({ row: lineNum, message: 'Empty required cell: ' + colName });
          rowErrors = true;
        }
      }
      if (!rowErrors) {
        rows.push(rowObj);
      }
    }

    return { rows: rows, errors: errors };
  }

  /* ── Format preview (color-coded, no innerHTML) ── */
  function _buildPreview(rows, headers) {
    var block = el('div', 'mf-cost__preview-block');
    block.style.cssText = 'background:#1a1a1a;color:#e6e6e6;font-family:var(--mf-font-mono);font-size:0.78rem;padding:0.75rem;border-radius:var(--mf-radius);overflow-x:auto;white-space:pre;margin-top:1rem;';

    var RATE_COLS = ['input_per_1m', 'output_per_1m', 'cache_write_per_1m', 'cache_read_per_1m', 'vision_per_image', 'batch_discount_pct'];

    var limit = rows.length < 5 ? rows.length : 5;
    for (var ri = 0; ri < limit; ri++) {
      var row = rows[ri];
      var p = el('p');
      p.style.margin = '0';

      for (var hi = 0; hi < headers.length; hi++) {
        var colName = headers[hi];
        var cellVal = row[colName] !== undefined ? row[colName] : '';

        var span = el('span');
        if (colName === 'provider') {
          span.style.color = 'var(--mf-color-accent)';
        } else if (RATE_COLS.indexOf(colName) !== -1) {
          span.style.color = 'var(--mf-color-success)';
        } else {
          span.style.color = '#e6e6e6';
        }
        span.textContent = cellVal;
        p.appendChild(span);

        if (hi < headers.length - 1) {
          var comma = el('span');
          comma.style.color = 'var(--mf-color-text-muted)';
          comma.textContent = ',';
          p.appendChild(comma);
        }
      }
      block.appendChild(p);
    }
    return block;
  }

  /* ── Sources & CSV import ── */
  function _renderCSVImport(contentSlot) {
    var frag = document.createDocumentFragment();

    var lastParseResult = null;
    var reloadBtn = null;
    var previewSlot = null;
    var errorSlot = null;
    var feedbackSlot = null;

    /* Drop zone */
    var dropZone = el('div', 'mf-cost__drop-zone');

    var dropIcon = el('div', 'mf-cost__drop-icon');
    dropIcon.textContent = '↑';
    dropZone.appendChild(dropIcon);

    var dropLabel = el('div');
    dropLabel.textContent = 'Drop a CSV rate file here';
    dropZone.appendChild(dropLabel);

    var dragDepth = 0;

    dropZone.addEventListener('dragenter', function (e) {
      e.preventDefault();
      dragDepth++;
      dropZone.classList.add('mf-cost__drop-zone--active');
    });
    dropZone.addEventListener('dragleave', function () {
      dragDepth--;
      if (dragDepth === 0) {
        dropZone.classList.remove('mf-cost__drop-zone--active');
      }
    });
    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault(); // required to allow drop
    });
    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dragDepth = 0;
      dropZone.classList.remove('mf-cost__drop-zone--active');
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) {
        _readFileAndParse(file);
      }
    });

    frag.appendChild(dropZone);

    /* Button row */
    var btnRow = el('div', 'mf-cost__btn-row');

    var chooseBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    chooseBtn.type = 'button';
    chooseBtn.textContent = 'Choose file';
    chooseBtn.addEventListener('click', function () {
      var fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.accept = '.csv';
      fileInput.addEventListener('change', function () {
        var file = fileInput.files && fileInput.files[0];
        if (file) {
          _readFileAndParse(file);
        }
      });
      fileInput.click();
    });
    btnRow.appendChild(chooseBtn);

    var pasteBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
    pasteBtn.type = 'button';
    pasteBtn.textContent = 'Paste from clipboard';
    pasteBtn.addEventListener('click', function () {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        _showClipboardUnavailable();
        return;
      }
      navigator.clipboard.readText().then(function (text) {
        _applyParse(text);
      }).catch(function () {
        _showClipboardUnavailable();
      });
    });
    btnRow.appendChild(pasteBtn);

    frag.appendChild(btnRow);

    /* Clipboard unavailable inline note slot */
    var clipNote = el('span');
    clipNote.style.cssText = 'font-size:0.85rem;color:var(--mf-color-error);margin-left:0.5rem;display:none;';
    clipNote.textContent = 'Clipboard not available in this browser.';
    btnRow.appendChild(clipNote);

    /* Preview and error slots */
    previewSlot = el('div');
    frag.appendChild(previewSlot);

    errorSlot = el('div');
    frag.appendChild(errorSlot);

    /* Reload button */
    reloadBtn = el('button', 'mf-btn mf-btn--primary');
    reloadBtn.type = 'button';
    reloadBtn.textContent = 'Reload rates';
    reloadBtn.disabled = true;
    reloadBtn.style.marginTop = '1rem';
    frag.appendChild(reloadBtn);

    /* Feedback slot for reload success/error */
    feedbackSlot = el('div');
    frag.appendChild(feedbackSlot);

    reloadBtn.addEventListener('click', function () {
      if (!lastParseResult || lastParseResult.errors.length > 0 || lastParseResult.rows.length === 0) return;
      reloadBtn.disabled = true;
      reloadBtn.textContent = 'Reloading…';
      while (feedbackSlot.firstChild) feedbackSlot.removeChild(feedbackSlot.firstChild);

      fetch('/api/admin/llm-costs/reload', {
        method: 'POST',
        credentials: 'same-origin',
      })
        .then(function (r) {
          if (!r.ok) throw new Error('Server error ' + r.status);
          return r.json();
        })
        .then(function (data) {
          reloadBtn.textContent = 'Reload rates';
          reloadBtn.disabled = false;
          var successMsg = el('div', 'mf-cost__reload-success');
          successMsg.textContent = 'Loaded ' + (data.loaded_count || data.total_rates || 0) + ' rate entries. Refresh the page to see updated rates.';
          feedbackSlot.appendChild(successMsg);
        })
        .catch(function (e) {
          reloadBtn.textContent = 'Reload rates';
          reloadBtn.disabled = false;
          var errMsg = el('div', 'mf-cost__reload-error');
          errMsg.textContent = e.message || 'Reload failed.';
          feedbackSlot.appendChild(errMsg);
        });
    });

    function _readFileAndParse(file) {
      var reader = new FileReader();
      reader.onload = function (evt) {
        _applyParse(evt.target.result);
      };
      reader.onerror = function () {
        var errList = el('ul', 'mf-cost__error-list');
        var li = document.createElement('li');
        li.textContent = 'Could not read the file. Try again or use another file.';
        errList.appendChild(li);
        while (errorSlot.firstChild) errorSlot.removeChild(errorSlot.firstChild);
        errorSlot.appendChild(errList);
      };
      reader.readAsText(file);
    }

    function _applyParse(text) {
      var result = _parseCSV(text);
      lastParseResult = result;

      /* Clear previous state */
      while (previewSlot.firstChild) previewSlot.removeChild(previewSlot.firstChild);
      while (errorSlot.firstChild) errorSlot.removeChild(errorSlot.firstChild);
      while (feedbackSlot.firstChild) feedbackSlot.removeChild(feedbackSlot.firstChild);
      clipNote.style.display = 'none';

      if (result.errors.length > 0) {
        reloadBtn.disabled = true;
        var errList = el('ul', 'mf-cost__error-list');
        for (var i = 0; i < result.errors.length; i++) {
          var li = el('li');
          li.textContent = 'Row ' + result.errors[i].row + ': ' + result.errors[i].message;
          errList.appendChild(li);
        }
        errorSlot.appendChild(errList);
      } else if (result.rows.length > 0) {
        reloadBtn.disabled = false;
        /* Collect headers from first row keys, preserving order */
        var firstRow = result.rows[0];
        var hdrs = [];
        for (var k in firstRow) {
          if (Object.prototype.hasOwnProperty.call(firstRow, k)) hdrs.push(k);
        }
        previewSlot.appendChild(_buildPreview(result.rows, hdrs));
      }
    }

    function _showClipboardUnavailable() {
      clipNote.style.display = '';
    }

    contentSlot.appendChild(frag);
  }

  /* ── Spend history ── */
  function _renderHistory(contentSlot, opts) {
    var period30 = opts.period30 || { total_usd: 0, by_provider: {}, by_model: [], daily: [] };
    var providers = opts.providers || [];
    var byModel = period30.by_model || [];
    var isSingle = providers.length === 1;

    var tableHead = el('h3', 'mf-stg__section-subhead');
    tableHead.textContent = 'Last 30 days — spend by model';
    contentSlot.appendChild(tableHead);

    if (isSingle) {
      contentSlot.appendChild(_buildBreakdownTableSingle(byModel));
    } else {
      contentSlot.appendChild(_buildBreakdownTableMulti(byModel));
    }

    var dlBtn = el('button', 'mf-btn mf-btn--ghost');
    dlBtn.style.marginTop = '1rem';
    dlBtn.textContent = 'Download as CSV';
    dlBtn.addEventListener('click', function () {
      dlBtn.disabled = true;
      fetch('/api/analysis/cost/period?days=30', {
        headers: { 'Accept': 'text/csv' },
        credentials: 'same-origin',
      })
        .then(function (r) {
          var ct = r.headers.get('Content-Type') || '';
          if (!r.ok || ct.indexOf('text/csv') === -1) {
            throw new Error('not-csv');
          }
          return r.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'cost-history-30d.csv';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          dlBtn.disabled = false;
        })
        .catch(function () {
          dlBtn.disabled = false;
          var msg = el('span');
          msg.style.cssText = 'margin-left:0.75rem;font-size:0.85rem;color:var(--mf-text-muted);';
          msg.textContent = 'CSV export not yet available.';
          dlBtn.parentNode.insertBefore(msg, dlBtn.nextSibling);
        });
    });
    contentSlot.appendChild(dlBtn);
  }

  /* ── Alerts & thresholds ── */
  function _renderAlerts(contentSlot, opts) {
    var prefs = opts.prefs || {};
    var alertEnabled = prefs.cost_alert_enabled === true;
    var alertThreshold = prefs.cost_alert_threshold_usd != null
      ? Number(prefs.cost_alert_threshold_usd)
      : 10;

    var currentEnabled = alertEnabled;
    var currentThreshold = alertThreshold;

    /* toggle row */
    var toggleRow = el('div');
    toggleRow.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;';

    var toggleBtn = el('button', 'mf-toggle ' + (currentEnabled ? 'mf-toggle--on' : 'mf-toggle--off'));
    toggleBtn.type = 'button';
    toggleBtn.setAttribute('aria-label', 'Enable cost alerts');
    var knob = el('span', 'mf-toggle__knob');
    toggleBtn.appendChild(knob);
    toggleRow.appendChild(toggleBtn);

    var toggleLabel = el('span');
    toggleLabel.style.cssText = 'font-size:0.92rem;color:var(--mf-color-text);';
    toggleLabel.textContent = 'Enable cost alerts';
    toggleRow.appendChild(toggleLabel);

    contentSlot.appendChild(toggleRow);

    /* threshold input */
    var thresholdLabel = el('label', 'mf-stg__field-label');
    thresholdLabel.textContent = 'Alert threshold (USD)';
    contentSlot.appendChild(thresholdLabel);

    var thresholdInput = el('input', 'mf-stg__field-input');
    thresholdInput.type = 'number';
    thresholdInput.min = '0';
    thresholdInput.step = '0.01';
    thresholdInput.value = String(currentThreshold);
    thresholdInput.disabled = !currentEnabled;
    thresholdInput.style.fontFamily = 'inherit';
    thresholdInput.style.cursor = 'text';
    thresholdInput.style.width = '200px';
    contentSlot.appendChild(thresholdInput);

    /* toggle interaction */
    toggleBtn.addEventListener('click', function () {
      currentEnabled = !currentEnabled;
      if (currentEnabled) {
        toggleBtn.className = 'mf-toggle mf-toggle--on';
      } else {
        toggleBtn.className = 'mf-toggle mf-toggle--off';
      }
      thresholdInput.disabled = !currentEnabled;
    });

    thresholdInput.addEventListener('change', function () {
      currentThreshold = Math.max(0, parseFloat(thresholdInput.value) || 0);
    });

    /* save bar */
    var barObj = _makeSaveBar(
      function (saveBtn, savedMsg) {
        var payload = {
          cost_alert_enabled: currentEnabled,
          cost_alert_threshold_usd: currentThreshold,
        };
        fetch('/api/preferences', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(payload),
        })
          .then(function (r) {
            if (!r.ok) throw new Error('save failed: ' + r.status);
            return r.json();
          })
          .then(function () {
            _showSaved(saveBtn, savedMsg);
          })
          .catch(function (e) {
            console.error('mf: cost alert save failed', e);
            saveBtn.disabled = false;
          });
      },
      function () {
        currentEnabled = alertEnabled;
        currentThreshold = alertThreshold;
        if (currentEnabled) {
          toggleBtn.className = 'mf-toggle mf-toggle--on';
        } else {
          toggleBtn.className = 'mf-toggle mf-toggle--off';
        }
        thresholdInput.value = String(currentThreshold);
        thresholdInput.disabled = !currentEnabled;
      }
    );
    contentSlot.appendChild(barObj.bar);

    var note = el('p');
    note.style.cssText = 'font-size:0.82rem;color:var(--mf-text-muted);margin-top:0.75rem;';
    note.textContent = 'Alert delivery (Slack / email) configured in Notifications → Channels.';
    contentSlot.appendChild(note);
  }

  /* ── _renderContent dispatcher ── */
  function _renderContent(contentSlot, activeSection, opts) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var providers = opts.providers || [];
    var rateTable = opts.rateTable || [];

    var head = el('h2', 'mf-stg__section-head');

    if (activeSection === 'overview') {
      head.textContent = 'Overview';
      contentSlot.appendChild(head);
      _renderOverview(contentSlot, opts);
    } else if (activeSection.indexOf('provider-') === 0) {
      var provName = activeSection.slice('provider-'.length);
      head.textContent = provName;
      contentSlot.appendChild(head);
      _renderProviderRates(contentSlot, provName, rateTable, opts._setSection);
    } else if (activeSection === 'sources') {
      head.textContent = 'Sources & CSV import';
      contentSlot.appendChild(head);
      _renderCSVImport(contentSlot);
    } else if (activeSection === 'history') {
      head.textContent = 'Spend history';
      contentSlot.appendChild(head);
      _renderHistory(contentSlot, opts);
    } else if (activeSection === 'alerts') {
      head.textContent = 'Alerts & thresholds';
      contentSlot.appendChild(head);
      _renderAlerts(contentSlot, opts);
    } else {
      head.textContent = activeSection;
      contentSlot.appendChild(head);
    }
  }

  /* ── mount ── */
  function mount(slot, opts) {
    if (!slot) throw new Error('MFCostCapDetail.mount: slot is required');
    opts = opts || {};

    var rateTable = opts.rateTable || [];
    var providers = opts.providers || [];

    var activeSection = 'overview';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Cost & Spend.';
    body.appendChild(headline);

    var detail = el('div', 'mf-stg__detail');

    var sidebar = el('nav', 'mf-stg__sidebar');

    function _setSection(id) {
      activeSection = id;
      sidebar.querySelectorAll('.mf-stg__sidebar-link').forEach(function (l) {
        l.classList.remove('mf-stg__sidebar-link--active');
      });
      var target = sidebar.querySelector('[data-section="' + id + '"]');
      if (target) target.classList.add('mf-stg__sidebar-link--active');
      opts._setSection = _setSection;
      _renderContent(contentSlot, activeSection, opts);
    }

    opts._setSection = _setSection;

    function _addSidebarGroup(label) {
      var grp = el('div');
      grp.style.cssText = 'font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--mf-color-text-faint);padding:0.85rem 0.85rem 0.3rem;';
      grp.textContent = label;
      sidebar.appendChild(grp);
    }

    function _addSidebarLink(id, label, isExternal, href) {
      var isActive = id === activeSection;
      var link = el('a', 'mf-stg__sidebar-link' + (isActive ? ' mf-stg__sidebar-link--active' : ''));
      link.href = href || ('#' + id);
      link.setAttribute('data-section', id);
      link.textContent = label;
      if (isExternal) {
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      } else {
        link.addEventListener('click', function (e) {
          e.preventDefault();
          _setSection(id);
        });
      }
      sidebar.appendChild(link);
    }

    _addSidebarGroup('COST');
    _addSidebarLink('overview', 'Overview');

    _addSidebarGroup('RATES BY PROVIDER');
    if (providers.length === 0) {
      var noRates = el('div');
      noRates.style.cssText = 'font-size:0.82rem;color:var(--mf-color-text-faint);padding:0.3rem 0.85rem 0.85rem;font-style:italic;';
      noRates.textContent = 'No rates loaded — import a CSV.';
      sidebar.appendChild(noRates);
    } else {
      providers.forEach(function (provName) {
        _addSidebarLink('provider-' + provName, provName);
      });
    }

    _addSidebarGroup('DATA');
    _addSidebarLink('sources', 'Sources & CSV import');
    _addSidebarLink('history', 'Spend history');

    _addSidebarGroup('NOTIFY');
    _addSidebarLink('alerts', 'Alerts & thresholds');

    var extLink = el('a', 'mf-stg__sidebar-link');
    extLink.href = '/help';
    extLink.target = '_blank';
    extLink.rel = 'noopener noreferrer';
    extLink.style.cssText = 'font-size:0.82rem;color:var(--mf-color-text-muted);margin-top:0.75rem;';
    extLink.textContent = 'CSV format reference ↗';
    sidebar.appendChild(extLink);

    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, opts);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFCostCapDetail = { mount: mount };
})(window);
