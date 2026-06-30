import { h } from 'https://esm.sh/preact@10.25.4';
import { useState, useMemo } from 'https://esm.sh/preact@10.25.4/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

import {
  FieldConditionEditor,
  AggregateConditionEditor,
  emptyFieldCondition,
  emptyAggregateCondition,
} from '/plugin-io/api/report_builder/static/condition-editor.js?v={{ cache_bust }}';
import { ColumnPicker, AggregateColumnEditor, emptyAggregateColumn } from '/plugin-io/api/report_builder/static/column-picker.js?v={{ cache_bust }}';
import { ResultsTable } from '/plugin-io/api/report_builder/static/results-table.js?v={{ cache_bust }}';
import { api } from '/plugin-io/api/report_builder/static/api.js?v={{ cache_bust }}';

const html = htm.bind(h);

export function Builder({ entities, report, onChange, onSave, onDelete, showToast }) {
  const rootEntity = useMemo(
    () => entities.find((e) => e.key === report.root_entity),
    [entities, report.root_entity]
  );

  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const updateField = (key, value) => onChange({ ...report, [key]: value });

  const updateCondition = (i, next) => {
    const cs = report.conditions.slice();
    cs[i] = next;
    updateField('conditions', cs);
  };
  const removeCondition = (i) => {
    const cs = report.conditions.slice();
    cs.splice(i, 1);
    updateField('conditions', cs);
  };
  const addFieldCondition = () => {
    if (!rootEntity) return;
    updateField('conditions', [...report.conditions, emptyFieldCondition(rootEntity)]);
  };
  const addAggregateCondition = () => {
    if (!rootEntity) return;
    updateField('conditions', [...report.conditions, emptyAggregateCondition(rootEntity)]);
  };

  const updateAggregateColumn = (i, next) => {
    const cols = report.aggregate_columns.slice();
    cols[i] = next;
    updateField('aggregate_columns', cols);
  };
  const removeAggregateColumn = (i) => {
    const cols = report.aggregate_columns.slice();
    cols.splice(i, 1);
    updateField('aggregate_columns', cols);
  };
  const addAggregateColumn = () => {
    if (!rootEntity) return;
    updateField('aggregate_columns', [...report.aggregate_columns, emptyAggregateColumn(rootEntity)]);
  };

  const runPreview = async () => {
    setPreviewing(true);
    setPreview(null);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const result = await api.previewReport(report, today, 1, 25);
      setPreview(result);
    } catch (err) {
      showToast(`Preview failed: ${err.message}`, 'error');
    } finally {
      setPreviewing(false);
    }
  };

  return html`
    <div class="rb-builder">
      <div class="rb-form-row">
        <label>Name</label>
        <input
          type="text"
          value=${report.name}
          onInput=${(e) => updateField('name', e.target.value)}
          placeholder="e.g. Patients with no completed visit in 90 days"
        />
      </div>
      <div class="rb-form-row">
        <label>Description</label>
        <input
          type="text"
          value=${report.description}
          onInput=${(e) => updateField('description', e.target.value)}
          placeholder="Optional"
        />
      </div>
      <div class="rb-form-row">
        <label>Root entity</label>
        <select
          value=${report.root_entity}
          onChange=${(e) => onChange({
            ...report,
            root_entity: e.target.value,
            conditions: [],
            columns: [],
            aggregate_columns: [],
          })}
        >
          ${entities.map((e) => html`
            <option value=${e.key}>${e.plural_label}</option>
          `)}
        </select>
      </div>

      <section class="rb-section">
        <h3>Filters</h3>
        ${report.conditions.length === 0 ? html`
          <p class="rb-empty-line">No filters — every ${rootEntity?.plural_label?.toLowerCase()} will be returned.</p>
        ` : null}
        ${report.conditions.map((c, i) => c.kind === 'field'
          ? html`<${FieldConditionEditor}
              key=${i}
              entity=${rootEntity}
              condition=${c}
              onChange=${(next) => updateCondition(i, next)}
              onRemove=${() => removeCondition(i)}
            />`
          : html`<${AggregateConditionEditor}
              key=${i}
              rootEntity=${rootEntity}
              entities=${entities}
              condition=${c}
              onChange=${(next) => updateCondition(i, next)}
              onRemove=${() => removeCondition(i)}
            />`
        )}
        <div class="rb-add-row">
          <button class="rb-btn rb-btn-link" onClick=${addFieldCondition}>+ Field filter</button>
          <button class="rb-btn rb-btn-link" onClick=${addAggregateCondition}>+ Aggregate filter</button>
        </div>
      </section>

      <section class="rb-section">
        <h3>Columns</h3>
        <${ColumnPicker}
          entity=${rootEntity}
          columns=${report.columns}
          onChange=${(cols) => updateField('columns', cols)}
        />

        <h4>Computed columns</h4>
        ${report.aggregate_columns.map((c, i) => html`
          <${AggregateColumnEditor}
            key=${i}
            rootEntity=${rootEntity}
            entities=${entities}
            column=${c}
            onChange=${(next) => updateAggregateColumn(i, next)}
            onRemove=${() => removeAggregateColumn(i)}
          />
        `)}
        <button class="rb-btn rb-btn-link" onClick=${addAggregateColumn}>+ Computed column</button>
      </section>

      <div class="rb-actions">
        <button class="rb-btn rb-btn-primary" onClick=${onSave}>Save</button>
        <button class="rb-btn" onClick=${runPreview} disabled=${previewing}>
          ${previewing ? 'Previewing…' : 'Preview run →'}
        </button>
        ${onDelete ? html`
          <button class="rb-btn rb-btn-danger" onClick=${onDelete}>Delete</button>
        ` : null}
      </div>

      ${preview ? html`
        <section class="rb-section">
          <h3>Preview</h3>
          <${ResultsTable}
            result=${preview}
            columns=${report.columns}
            aggregateLabels=${report.aggregate_columns.map((c) => c.label)}
          />
        </section>
      ` : null}
    </div>
  `;
}
