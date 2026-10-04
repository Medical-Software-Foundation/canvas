import { h } from 'https://esm.sh/preact@10.25.4';
import { useState } from 'https://esm.sh/preact@10.25.4/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

import { api } from '/plugin-io/api/report_builder/static/api.js?v={{ cache_bust }}';
import { ResultsTable } from '/plugin-io/api/report_builder/static/results-table.js?v={{ cache_bust }}';

const html = htm.bind(h);

export function Runner({ report, today, showToast }) {
  const [asOf, setAsOf] = useState(today || new Date().toISOString().slice(0, 10));
  const [page, setPage] = useState(1);
  const [perPage] = useState(100);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);

  const run = async (nextPage = page) => {
    setRunning(true);
    try {
      const r = await api.runReport(report.id, asOf, nextPage, perPage);
      setResult(r);
      setPage(nextPage);
    } catch (err) {
      showToast(`Run failed: ${err.message}`, 'error');
    } finally {
      setRunning(false);
    }
  };

  const totalPages = result ? Math.max(1, Math.ceil((result.total || 0) / perPage)) : 1;

  return html`
    <div class="rb-runner">
      <div class="rb-runner-controls">
        <label>As of date</label>
        <input type="date" value=${asOf} onChange=${(e) => setAsOf(e.target.value)} />
        <button class="rb-btn rb-btn-primary" onClick=${() => run(1)} disabled=${running}>
          ${running ? 'Running…' : 'Run'}
        </button>
        ${result && !result.too_large ? html`
          <a class="rb-btn" href=${api.exportUrl(report.id, asOf)} target="_blank" rel="noopener">Export CSV</a>
        ` : null}
      </div>
      ${result ? html`
        <${ResultsTable}
          result=${result}
          columns=${report.columns}
          aggregateLabels=${report.aggregate_columns.map((c) => c.label)}
          rootEntity=${report.root_entity}
        />
        ${!result.too_large && result.total > perPage ? html`
          <div class="rb-pagination">
            <button class="rb-btn" disabled=${page === 1 || running} onClick=${() => run(page - 1)}>← Prev</button>
            <span>Page ${page} of ${totalPages}</span>
            <button class="rb-btn" disabled=${page >= totalPages || running} onClick=${() => run(page + 1)}>Next →</button>
          </div>
        ` : null}
      ` : html`
        <p class="rb-empty-line">Pick an as-of date and click <em>Run</em>.</p>
      `}
    </div>
  `;
}
