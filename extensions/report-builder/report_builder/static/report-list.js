import { h } from 'https://esm.sh/preact@10.25.4';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

export function ReportList({ reports, selectedId, onSelect }) {
  if (!reports.length) {
    return html`
      <div class="rb-report-list rb-report-list-empty">
        <p>No saved reports yet.</p>
      </div>
    `;
  }
  return html`
    <ul class="rb-report-list">
      ${reports.map((r) => html`
        <li
          key=${r.id}
          class=${'rb-report-list-item' + (r.id === selectedId ? ' rb-selected' : '')}
          onClick=${() => onSelect(r.id)}
        >
          <div class="rb-report-list-name">${r.name}</div>
          <div class="rb-report-list-meta">${r.root_entity}</div>
        </li>
      `)}
    </ul>
  `;
}
