import { h } from 'https://esm.sh/preact@10.25.4';
import htm from 'https://esm.sh/htm@3.1.1';

import { FieldConditionEditor, emptyFieldCondition } from '/plugin-io/api/report_builder/static/condition-editor.js?v={{ cache_bust }}';

const html = htm.bind(h);

const AGG_FNS = ['count', 'min', 'max', 'sum', 'avg'];

export function ColumnPicker({ entity, columns, onChange }) {
  if (!entity) return null;
  const toggle = (name) => {
    if (columns.includes(name)) {
      onChange(columns.filter((c) => c !== name));
    } else {
      onChange([...columns, name]);
    }
  };
  return html`
    <div class="rb-column-picker">
      ${entity.fields.filter((f) => f.selectable_column).map((f) => html`
        <label key=${f.name} class="rb-column-checkbox">
          <input
            type="checkbox"
            checked=${columns.includes(f.name)}
            onChange=${() => toggle(f.name)}
          />
          <span>${f.label}</span>
        </label>
      `)}
    </div>
  `;
}

export function AggregateColumnEditor({ rootEntity, entities, column, onChange, onRemove }) {
  const rel = rootEntity?.relationships?.find((r) => r.name === column.relationship);
  const targetEntity = entities?.find((e) => e.key === rel?.target_entity);

  const updateSubFilter = (i, next) => {
    const sub = column.sub_filters.slice();
    sub[i] = next;
    onChange({ ...column, sub_filters: sub });
  };
  const removeSubFilter = (i) => {
    const sub = column.sub_filters.slice();
    sub.splice(i, 1);
    onChange({ ...column, sub_filters: sub });
  };
  const addSubFilter = () => {
    if (!targetEntity) return;
    onChange({
      ...column,
      sub_filters: [...column.sub_filters, emptyFieldCondition(targetEntity)],
    });
  };

  return html`
    <div class="rb-aggregate-column">
      <div class="rb-aggregate-column-header">
        <input
          type="text"
          placeholder="Column label"
          value=${column.label}
          onInput=${(e) => onChange({ ...column, label: e.target.value })}
          class="rb-aggregate-column-label"
        />
        <select
          value=${column.relationship}
          onChange=${(e) => onChange({ ...column, relationship: e.target.value, aggregate_field: null, sub_filters: [] })}
        >
          ${rootEntity.relationships.map((r) => html`
            <option value=${r.name}>${r.label}</option>
          `)}
        </select>
        <select
          value=${column.fn}
          onChange=${(e) => {
            const fn = e.target.value;
            onChange({ ...column, fn, aggregate_field: fn === 'count' ? null : column.aggregate_field });
          }}
        >
          ${AGG_FNS.map((fn) => html`<option value=${fn}>${fn}</option>`)}
        </select>
        ${column.fn !== 'count' && targetEntity ? html`
          <select
            value=${column.aggregate_field || ''}
            onChange=${(e) => onChange({ ...column, aggregate_field: e.target.value || null })}
          >
            <option value="">(field)</option>
            ${targetEntity.fields.map((f) => html`
              <option value=${f.name}>${f.label}</option>
            `)}
          </select>
        ` : null}
        ${onRemove ? html`<button class="rb-btn-icon" onClick=${onRemove} title="Remove">×</button>` : null}
      </div>
      ${targetEntity ? html`
        <div class="rb-aggregate-subfilters">
          <div class="rb-aggregate-subfilters-label">Where ${targetEntity.label}:</div>
          ${column.sub_filters.map((sub, i) => html`
            <${FieldConditionEditor}
              key=${i}
              entity=${targetEntity}
              condition=${sub}
              onChange=${(next) => updateSubFilter(i, next)}
              onRemove=${() => removeSubFilter(i)}
            />
          `)}
          <button class="rb-btn rb-btn-link" onClick=${addSubFilter}>+ Sub-filter</button>
        </div>
      ` : null}
    </div>
  `;
}

export function emptyAggregateColumn(rootEntity) {
  const rel = rootEntity?.relationships?.[0];
  return {
    label: 'Computed',
    relationship: rel?.name || '',
    fn: 'count',
    aggregate_field: null,
    sub_filters: [],
  };
}
