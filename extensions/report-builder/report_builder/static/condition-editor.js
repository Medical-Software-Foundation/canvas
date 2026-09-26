import { h } from 'https://esm.sh/preact@10.25.4';
import { useMemo } from 'https://esm.sh/preact@10.25.4/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

const OPS_BY_TYPE = {
  string: ['eq', 'ne', 'contains', 'starts_with', 'in', 'not_in', 'is_null'],
  integer: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'not_in', 'is_null'],
  decimal: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'is_null'],
  boolean: ['eq', 'ne', 'is_null'],
  date: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'is_null'],
  datetime: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'is_null'],
  choice: ['eq', 'ne', 'in', 'not_in', 'is_null'],
};

const OP_LABELS = {
  eq: '=',
  ne: '≠',
  lt: '<',
  lte: '≤',
  gt: '>',
  gte: '≥',
  in: 'in',
  not_in: 'not in',
  contains: 'contains',
  starts_with: 'starts with',
  is_null: 'is null',
};

const AGG_FNS = ['count', 'min', 'max', 'sum', 'avg'];
const COMPARE_OPS = ['eq', 'ne', 'lt', 'lte', 'gt', 'gte'];

function defaultValueForField(field) {
  if (!field) return '';
  if (field.type === 'boolean') return true;
  if (field.type === 'integer' || field.type === 'decimal') return 0;
  return '';
}

function emptyFieldCondition(entity) {
  const field = entity?.fields?.find((f) => f.filterable) || entity?.fields?.[0];
  return {
    kind: 'field',
    field: field?.name || '',
    op: 'eq',
    value: defaultValueForField(field),
  };
}

function emptyAggregateCondition(entity) {
  const rel = entity?.relationships?.[0];
  return {
    kind: 'aggregate',
    relationship: rel?.name || '',
    fn: 'count',
    aggregate_field: null,
    sub_filters: [],
    compare_op: 'gte',
    compare_value: 1,
  };
}

function ValueInput({ field, op, value, onChange }) {
  if (op === 'is_null') {
    return html`
      <select value=${String(value)} onChange=${(e) => onChange(e.target.value === 'true')}>
        <option value="true">is null</option>
        <option value="false">is not null</option>
      </select>
    `;
  }

  if (op === 'in' || op === 'not_in') {
    const text = Array.isArray(value) ? value.join(', ') : '';
    return html`
      <input
        type="text"
        placeholder="comma-separated values"
        value=${text}
        onInput=${(e) => onChange(e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
      />
    `;
  }

  if (!field) {
    return html`<input type="text" value=${value || ''} onInput=${(e) => onChange(e.target.value)} />`;
  }

  if (field.type === 'boolean') {
    return html`
      <select value=${String(value)} onChange=${(e) => onChange(e.target.value === 'true')}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    `;
  }

  if (field.type === 'choice') {
    return html`
      <select value=${value || ''} onChange=${(e) => onChange(e.target.value)}>
        <option value="">(select)</option>
        ${(field.choices || []).map((c) => html`
          <option value=${c.value}>${c.label}</option>
        `)}
      </select>
    `;
  }

  if (field.type === 'date' || field.type === 'datetime') {
    const isRelative = value && typeof value === 'object' && value._type === 'relative_date';
    const magnitude = isRelative ? Math.abs(value.offset_days) : 0;
    const direction = isRelative && value.offset_days > 0 ? 'after' : 'before';
    return html`
      <div class="rb-date-input">
        <select
          value=${isRelative ? 'relative' : 'absolute'}
          onChange=${(e) => {
            if (e.target.value === 'relative') {
              onChange({ _type: 'relative_date', offset_days: 0 });
            } else {
              onChange('');
            }
          }}
        >
          <option value="absolute">Absolute</option>
          <option value="relative">Relative to as-of</option>
        </select>
        ${isRelative ? html`
          <input
            type="number"
            min="0"
            value=${magnitude}
            onInput=${(e) => {
              const m = Math.abs(parseInt(e.target.value, 10) || 0);
              const signed = direction === 'before' ? -m : m;
              onChange({ _type: 'relative_date', offset_days: signed });
            }}
          />
          <span>days</span>
          <select
            value=${direction}
            onChange=${(e) => {
              const signed = e.target.value === 'before' ? -magnitude : magnitude;
              onChange({ _type: 'relative_date', offset_days: signed });
            }}
          >
            <option value="before">before as-of</option>
            <option value="after">after as-of</option>
          </select>
        ` : html`
          <input
            type=${field.type === 'date' ? 'date' : 'datetime-local'}
            value=${value || ''}
            onInput=${(e) => onChange(e.target.value)}
          />
        `}
      </div>
    `;
  }

  if (field.type === 'integer' || field.type === 'decimal') {
    return html`
      <input
        type="number"
        value=${value ?? ''}
        onInput=${(e) => onChange(field.type === 'integer' ? (parseInt(e.target.value, 10) || 0) : (parseFloat(e.target.value) || 0))}
      />
    `;
  }

  return html`
    <input
      type="text"
      value=${value || ''}
      onInput=${(e) => onChange(e.target.value)}
    />
  `;
}

export function FieldConditionEditor({ entity, condition, onChange, onRemove }) {
  const field = entity?.fields?.find((f) => f.name === condition.field);
  const ops = useMemo(() => OPS_BY_TYPE[field?.type || 'string'], [field]);

  return html`
    <div class="rb-condition rb-condition-field">
      <select
        value=${condition.field}
        onChange=${(e) => {
          const next = entity.fields.find((f) => f.name === e.target.value);
          onChange({ ...condition, field: e.target.value, op: 'eq', value: defaultValueForField(next) });
        }}
      >
        ${entity?.fields?.filter((f) => f.filterable).map((f) => html`
          <option value=${f.name}>${f.label}</option>
        `)}
      </select>
      <select
        value=${condition.op}
        onChange=${(e) => onChange({ ...condition, op: e.target.value })}
      >
        ${ops.map((op) => html`<option value=${op}>${OP_LABELS[op]}</option>`)}
      </select>
      <${ValueInput}
        field=${field}
        op=${condition.op}
        value=${condition.value}
        onChange=${(value) => onChange({ ...condition, value })}
      />
      ${onRemove ? html`<button class="rb-btn-icon" onClick=${onRemove} title="Remove">×</button>` : null}
    </div>
  `;
}

export function AggregateConditionEditor({
  rootEntity,
  entities,
  condition,
  onChange,
  onRemove,
}) {
  const rel = rootEntity?.relationships?.find((r) => r.name === condition.relationship);
  const targetEntity = entities?.find((e) => e.key === rel?.target_entity);

  const updateSubFilter = (i, next) => {
    const sub = condition.sub_filters.slice();
    sub[i] = next;
    onChange({ ...condition, sub_filters: sub });
  };

  const removeSubFilter = (i) => {
    const sub = condition.sub_filters.slice();
    sub.splice(i, 1);
    onChange({ ...condition, sub_filters: sub });
  };

  const addSubFilter = () => {
    if (!targetEntity) return;
    onChange({
      ...condition,
      sub_filters: [...condition.sub_filters, emptyFieldCondition(targetEntity)],
    });
  };

  return html`
    <div class="rb-condition rb-condition-aggregate">
      <div class="rb-aggregate-header">
        <select
          value=${condition.relationship}
          onChange=${(e) => onChange({ ...condition, relationship: e.target.value, sub_filters: [], aggregate_field: null })}
        >
          ${rootEntity?.relationships?.map((r) => html`
            <option value=${r.name}>${r.label}</option>
          `)}
        </select>
        <select
          value=${condition.fn}
          onChange=${(e) => {
            const fn = e.target.value;
            onChange({ ...condition, fn, aggregate_field: fn === 'count' ? null : condition.aggregate_field });
          }}
        >
          ${AGG_FNS.map((fn) => html`<option value=${fn}>${fn}</option>`)}
        </select>
        ${condition.fn !== 'count' && targetEntity ? html`
          <select
            value=${condition.aggregate_field || ''}
            onChange=${(e) => onChange({ ...condition, aggregate_field: e.target.value || null })}
          >
            <option value="">(field)</option>
            ${targetEntity.fields.map((f) => html`
              <option value=${f.name}>${f.label}</option>
            `)}
          </select>
        ` : null}
        <select
          value=${condition.compare_op}
          onChange=${(e) => onChange({ ...condition, compare_op: e.target.value })}
        >
          ${COMPARE_OPS.map((op) => html`<option value=${op}>${OP_LABELS[op]}</option>`)}
        </select>
        <input
          type="number"
          value=${condition.compare_value}
          onInput=${(e) => onChange({ ...condition, compare_value: parseFloat(e.target.value) || 0 })}
        />
        ${onRemove ? html`<button class="rb-btn-icon" onClick=${onRemove} title="Remove">×</button>` : null}
      </div>
      ${targetEntity ? html`
        <div class="rb-aggregate-subfilters">
          <div class="rb-aggregate-subfilters-label">Where ${targetEntity.label}:</div>
          ${condition.sub_filters.map((sub, i) => html`
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

export { emptyFieldCondition, emptyAggregateCondition };
