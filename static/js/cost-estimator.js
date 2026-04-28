/**
 * static/js/cost-estimator.js — v0.33.2
 *
 * Shared formatting + render helpers for the LLM cost-estimation
 * subsystem. Used by:
 *   - static/batch-management.html (per-batch cost panel)
 *   - static/admin.html (Provider Spend monthly running total)
 *
 * All DOM is built via createElement + textContent (XSS-safe per the
 * project gotcha). No innerHTML, no template strings injected as HTML.
 *
 * Public surface (attached to window.CostEstimator):
 *   formatUsd(amount)             -> "$1.23" / "$1,234.56" / "$0.00" / "—"
 *   formatTokens(n)               -> "34,021 tokens" / "12.6M tokens"
 *   formatRate(rate)              -> "anthropic/claude-opus-4-7 ($45/1M blended)"
 *   renderBatchCostPanel(el, c)   -> populates `el` with the per-batch panel
 *   renderPeriodCostCard(el, p)   -> populates `el` with the Provider Spend card
 */
(function () {
  'use strict';

  // ── Formatters ─────────────────────────────────────────────────────────

  function formatUsd(amount) {
    if (amount === null || amount === undefined) return '—';
    if (typeof amount !== 'number' || !isFinite(amount)) return '—';
    if (amount === 0) return '$0.00';
    if (amount < 0.01 && amount > 0) {
      return '$' + amount.toFixed(4);
    }
    return '$' + amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatTokens(n) {
    if (n === null || n === undefined) return '—';
    n = Number(n);
    if (!isFinite(n)) return '—';
    if (n >= 1_000_000) {
      return (n / 1_000_000).toFixed(1) + 'M tokens';
    }
    if (n >= 1_000) {
      return n.toLocaleString() + ' tokens';
    }
    return n.toLocaleString() + ' tokens';
  }

  function formatRate(rate) {
    if (!rate) return '—';
    var input = rate.input_per_million_usd;
    var output = rate.output_per_million_usd;
    var blended = (input + output) / 2;
    return rate.provider + '/' + rate.model +
      ' ($' + input.toFixed(2) + ' in / $' + output.toFixed(2) +
      ' out per 1M, blended $' + blended.toFixed(2) + ')';
  }

  function pct(part, whole) {
    if (!whole) return 0;
    return Math.round((part / whole) * 100);
  }

  // ── DOM helpers ────────────────────────────────────────────────────────

  function el(tag, opts) {
    var node = document.createElement(tag);
    if (opts) {
      if (opts.cls) node.className = opts.cls;
      if (opts.text !== undefined) node.textContent = opts.text;
      if (opts.style) node.setAttribute('style', opts.style);
      if (opts.attrs) {
        Object.keys(opts.attrs).forEach(function (k) {
          node.setAttribute(k, opts.attrs[k]);
        });
      }
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function dlRow(dl, label, value, opts) {
    opts = opts || {};
    var dt = el('dt', { text: label });
    dt.style.color = 'var(--text-muted)';
    dt.style.fontSize = '0.85rem';
    dl.appendChild(dt);
    var dd = el('dd', { text: value });
    dd.style.margin = '0';
    dd.style.fontWeight = opts.bold ? '700' : '500';
    if (opts.color) dd.style.color = opts.color;
    if (opts.title) dd.title = opts.title;
    dl.appendChild(dd);
  }

  // ── Render: per-batch cost panel ───────────────────────────────────────

  function renderBatchCostPanel(container, summary) {
    clear(container);
    if (!summary) {
      container.appendChild(el('p', {
        cls: 'text-muted text-sm',
        text: 'Cost estimate unavailable.',
      }));
      return;
    }

    var wrap = el('div', { cls: 'cost-panel' });
    wrap.style.cssText = 'margin:0.75rem 0;padding:0.85rem 1rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-alt)';

    // Heading
    var head = el('div');
    head.style.cssText = 'display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin-bottom:0.5rem';
    var title = el('strong', { text: 'Cost Estimate' });
    title.style.fontSize = '0.95rem';
    head.appendChild(title);
    var subtitle = el('span', {
      cls: 'text-muted text-sm',
      text: summary.total_files + ' files · ' +
            summary.files_with_tokens + ' analyzed (actual) · ' +
            summary.files_estimated + ' estimated',
    });
    head.appendChild(subtitle);
    wrap.appendChild(head);

    // Two-column layout: Tokens (left) + Cost (right)
    var grid = el('div');
    grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:0.4rem';

    // Tokens column
    var tokDl = el('dl');
    tokDl.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:0.25rem 0.75rem;margin:0';
    dlRow(tokDl, 'Actual:', formatTokens(summary.actual_tokens));
    dlRow(tokDl, 'Estimated:', formatTokens(summary.estimated_tokens));
    dlRow(tokDl, 'Total:', formatTokens(summary.actual_tokens + summary.estimated_tokens), { bold: true });
    var tokCol = el('div');
    tokCol.appendChild(el('div', { cls: 'text-sm', text: 'TOKENS', style: 'font-weight:600;color:var(--text-muted);margin-bottom:0.3rem' }));
    tokCol.appendChild(tokDl);
    grid.appendChild(tokCol);

    // Cost column
    var costDl = el('dl');
    costDl.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:0.25rem 0.75rem;margin:0';
    dlRow(costDl, 'Actual:', formatUsd(summary.actual_cost_usd));
    dlRow(costDl, 'Estimated:', formatUsd(summary.estimated_cost_usd));
    dlRow(costDl, 'Total:', formatUsd(summary.total_cost_usd), { bold: true, color: 'var(--accent)' });
    var costCol = el('div');
    var costHead = el('div', { cls: 'text-sm', text: 'COST (USD)', style: 'font-weight:600;color:var(--text-muted);margin-bottom:0.3rem' });
    costCol.appendChild(costHead);
    costCol.appendChild(costDl);
    grid.appendChild(costCol);

    wrap.appendChild(grid);

    // Per-file averages
    var avg = el('p', { cls: 'text-sm text-muted' });
    avg.style.marginTop = '0.6rem';
    avg.textContent = 'Per-file average: ' +
      formatTokens(Math.round(summary.per_file_avg_tokens)) + ' · ' +
      formatUsd(summary.per_file_avg_cost_usd);
    wrap.appendChild(avg);

    // Rate(s) used
    if (summary.rates_used && summary.rates_used.length) {
      var rateLine = el('p', { cls: 'text-sm text-muted' });
      rateLine.style.cssText = 'margin-top:0.25rem;font-family:ui-monospace,monospace;font-size:0.78rem';
      var label = el('span', { text: 'Rate' + (summary.rates_used.length > 1 ? 's' : '') + ' used: ' });
      rateLine.appendChild(label);
      summary.rates_used.forEach(function (r, i) {
        if (i > 0) rateLine.appendChild(el('span', { text: ', ' }));
        rateLine.appendChild(el('span', { text: formatRate(r) }));
      });
      wrap.appendChild(rateLine);
    } else if (summary.files_with_tokens === 0) {
      var msg = el('p', { cls: 'text-sm text-muted', text: 'Estimate unavailable until at least 1 file is analyzed.' });
      msg.style.marginTop = '0.4rem';
      wrap.appendChild(msg);
    }

    // Per-file breakdown disclosure
    if (summary.files && summary.files.length) {
      var details = el('details');
      details.style.marginTop = '0.6rem';
      var sum = el('summary', { text: 'Show per-file breakdown' });
      sum.style.cssText = 'cursor:pointer;font-size:0.85rem;color:var(--accent)';
      details.appendChild(sum);

      var table = el('table');
      table.style.cssText = 'width:100%;border-collapse:collapse;margin-top:0.5rem;font-size:0.8rem';
      var thead = el('thead');
      var hr = el('tr');
      ['File', 'Provider/Model', 'Tokens', 'Cost', ''].forEach(function (h) {
        var th = el('th', { text: h });
        th.style.cssText = 'text-align:left;padding:0.25rem 0.4rem;border-bottom:1px solid var(--border);color:var(--text-muted);font-weight:600';
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      table.appendChild(thead);

      var tbody = el('tbody');
      summary.files.forEach(function (f) {
        var tr = el('tr');
        var name = (f.source_path || '').split(/[\\/]/).pop() || f.file_id;
        var nameTd = el('td', { text: name, style: 'padding:0.2rem 0.4rem;font-family:ui-monospace,monospace;font-size:0.78rem' });
        nameTd.title = f.source_path || '';
        tr.appendChild(nameTd);
        var pmTd = el('td', {
          text: (f.provider || '?') + (f.model ? '/' + f.model : ''),
          style: 'padding:0.2rem 0.4rem;font-size:0.78rem',
        });
        tr.appendChild(pmTd);
        tr.appendChild(el('td', { text: formatTokens(f.tokens_used), style: 'padding:0.2rem 0.4rem;font-size:0.78rem' }));
        tr.appendChild(el('td', { text: formatUsd(f.cost_usd), style: 'padding:0.2rem 0.4rem;font-size:0.78rem;font-weight:500' }));
        var tag = el('td', { style: 'padding:0.2rem 0.4rem;font-size:0.7rem' });
        if (f.estimated) {
          var pill = el('span', { text: 'estimated', cls: 'pill' });
          pill.style.cssText = 'background:var(--surface-alt);color:var(--text-muted);padding:0.1rem 0.4rem;border-radius:3px;border:1px solid var(--border)';
          tag.appendChild(pill);
        }
        tr.appendChild(tag);
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      details.appendChild(table);
      wrap.appendChild(details);
    }

    container.appendChild(wrap);
  }

  // ── Render: Provider Spend card (Admin) ─────────────────────────────────

  function renderPeriodCostCard(container, period, opts) {
    opts = opts || {};
    clear(container);
    if (!period) {
      container.appendChild(el('p', { cls: 'text-muted', text: 'Cost data unavailable.' }));
      return;
    }

    // Hero — total cost
    var hero = el('div');
    hero.style.cssText = 'display:flex;align-items:baseline;gap:0.6rem;margin-bottom:0.3rem';
    var dollar = el('strong', { text: formatUsd(period.total_cost_usd) });
    dollar.style.cssText = 'font-size:1.6rem;color:var(--accent)';
    hero.appendChild(dollar);
    var cap = el('span', { text: 'total this cycle', cls: 'text-muted text-sm' });
    hero.appendChild(cap);
    container.appendChild(hero);

    var subline = el('p', { cls: 'text-sm text-muted' });
    subline.style.margin = '0 0 0.6rem';
    subline.textContent = formatTokens(period.total_tokens) + ' · ' +
      period.file_count.toLocaleString() + ' files analyzed';
    container.appendChild(subline);

    // By-provider breakdown
    if (period.by_provider && Object.keys(period.by_provider).length) {
      var bpHead = el('div', { cls: 'text-sm', text: 'By provider', style: 'font-weight:600;color:var(--text-muted);margin-bottom:0.25rem' });
      container.appendChild(bpHead);
      var bpTable = el('div');
      bpTable.style.cssText = 'display:grid;grid-template-columns:auto 1fr auto;gap:0.15rem 0.6rem;margin-bottom:0.6rem;font-size:0.85rem';
      var entries = Object.entries(period.by_provider).sort(function (a, b) { return b[1] - a[1]; });
      var totalUsd = period.total_cost_usd || 0;
      entries.forEach(function (kv) {
        var prov = kv[0];
        var amt = kv[1];
        bpTable.appendChild(el('span', { text: prov + ':', style: 'font-family:ui-monospace,monospace' }));
        bpTable.appendChild(el('span', { text: formatUsd(amt) }));
        bpTable.appendChild(el('span', { text: '(' + pct(amt, totalUsd) + '%)', cls: 'text-muted' }));
      });
      container.appendChild(bpTable);
    }

    // Cycle progress + projection
    var cycleLine = el('p', { cls: 'text-sm text-muted', style: 'margin:0' });
    cycleLine.textContent = period.cycle_label + ' · day ' +
      period.days_into_cycle + ' of ' + period.days_total + ' · ' +
      period.days_remaining + ' days remaining';
    container.appendChild(cycleLine);

    var projLine = el('p', { style: 'margin:0.3rem 0 0.6rem;font-size:0.9rem' });
    var projLabel = el('span', { text: 'Projected at current pace: ', cls: 'text-muted' });
    projLine.appendChild(projLabel);
    var projVal = el('strong', { text: formatUsd(period.projected_full_cycle_cost_usd) });
    projVal.style.color = 'var(--accent)';
    projLine.appendChild(projVal);
    var projSuffix = el('span', { text: ' by cycle end', cls: 'text-muted' });
    projLine.appendChild(projSuffix);
    container.appendChild(projLine);

    // Stale-rate warning + raw-data link footer
    var footer = el('div', { cls: 'text-sm text-muted', style: 'margin-top:0.6rem;display:flex;gap:0.6rem;flex-wrap:wrap' });
    var settingsLink = el('a', { text: 'Set cycle start day →', attrs: { href: '/settings.html#billing-section' } });
    settingsLink.style.color = 'var(--accent)';
    footer.appendChild(settingsLink);
    var ratesLink = el('a', { text: 'Edit rate table →', attrs: { href: '/api/admin/llm-costs', target: '_blank', rel: 'noopener' } });
    ratesLink.style.color = 'var(--accent)';
    footer.appendChild(ratesLink);
    // v0.33.3: CSV export for finance.
    var csvLink = el('a', {
      text: '↓ Export CSV',
      attrs: { href: '/api/analysis/cost/period.csv', download: '' },
    });
    csvLink.style.color = 'var(--accent)';
    footer.appendChild(csvLink);
    container.appendChild(footer);

    if (opts.staleness && opts.staleness.is_stale) {
      var warn = el('p', {
        cls: 'text-sm',
        text: '⚠ Rate data is ' + (opts.staleness.age_days || '?') +
              ' days old (threshold ' + (opts.staleness.threshold_days || 90) +
              '). Check provider pricing pages and update llm_costs.json.',
      });
      warn.style.cssText = 'margin-top:0.5rem;padding:0.4rem 0.6rem;background:#7a4f00;color:#fff;border-radius:4px';
      container.appendChild(warn);
    }
  }

  // ── Public surface ─────────────────────────────────────────────────────

  window.CostEstimator = {
    formatUsd: formatUsd,
    formatTokens: formatTokens,
    formatRate: formatRate,
    renderBatchCostPanel: renderBatchCostPanel,
    renderPeriodCostCard: renderPeriodCostCard,
  };
})();
