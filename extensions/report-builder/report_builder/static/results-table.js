import { h } from 'https://esm.sh/preact@10.25.4';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

function patientUrl(row, rootEntity) {
  if (rootEntity === 'patient' && row.id) {
    return `/patient/${row.id}`;
  }
  return null;
}

export function ResultsTable({ result, columns, aggregateLabels, rootEntity }) {
  if (!result) return null;
  if (result.too_large) {
    return html`
      <div class="rb-result-warning">
        <strong>Result too large.</strong> ${result.total.toLocaleString()} rows would be returned; the cap is ${result.max_rows.toLocaleString()}. Refine your filters.
      </div>
    `;
  }
  const allColumns = ['id', ...(columns || []), ...((aggregateLabels) || [])];
  return html`
    <div class="rb-results">
      <div class="rb-results-meta">
        Showing ${result.rows.length} of ${result.total.toLocaleString()} rows (page ${result.page})
      </div>
      <table class="rb-table">
        <thead>
          <tr>${allColumns.map((c) => html`<th>${c}</th>`)}</tr>
        </thead>
        <tbody>
          ${result.rows.map((row) => {
            const href = patientUrl(row, rootEntity);
            return html`<tr key=${row.id || row.dbid}>
              ${allColumns.map((c) => html`<td>${
                c === 'id' && href
                  ? html`<a href=${href} target="_top">${row[c]}</a>`
                  : (row[c] !== null && row[c] !== undefined ? String(row[c]) : '')
              }</td>`)}
            </tr>`;
          })}
        </tbody>
      </table>
    </div>
  `;
}
