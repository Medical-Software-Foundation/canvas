// @ts-check
/**
 * note_protocol_automation — rule-authoring admin UI (Preact).
 *
 * TEMPLATE-SAFE RULE: this file is served via render_to_string (Django template
 * engine) — it must NEVER contain a Django tag opener anywhere (incl. JSDoc):
 * no doubled-open-brace (variable tag) and no open-brace-percent (block tag), or
 * the static route 500s and the app never mounts. Declare types with @typedef +
 * @property and destructured @param forms, never the doubled-brace inline-object
 * JSDoc shorthand. STYLES ARE ALWAYS STRINGS (style=${"..."}), NEVER object
 * literals (an object literal after style=$ is a doubled-open-brace).
 *
 * Imports use RELATIVE paths into ./ui/ (a SIBLING of this file under static/,
 * NOT ../ui/ — app.js is served at /static/app.js, so ../ui would resolve above
 * /static/ and 404). `preact/hooks` is a BARE SPECIFIER resolved by the import
 * map in index.html to this plugin's own same-origin /static/vendor/ copy
 * (SRI-checked) — NOT esm.sh.
 *
 * SURFACE: global admin page (no patient param). Two views:
 *   - Rule list: GET /rules, GET /note-types -> table with edit/delete + New.
 *   - Rule editor: name, note-type dropdown, enabled, a predicate builder
 *     (signal-driven rows), an ordered command picker; Save -> POST/PUT /rules.
 *
 * NUMERIC COERCION: HTML inputs yield STRINGS. The executor's predicate eval is
 * type-strict (isinstance int/float). Age, between-bounds, lab threshold and
 * within_days are coerced with Number() before the predicate JSON is built, or
 * the saved rule would silently never fire.
 */
import { useState, useEffect, useCallback } from "preact/hooks";
import { html } from "./ui/html.js";
import { Card } from "./ui/Card.js";
import { Button } from "./ui/Button.js";
import { Badge } from "./ui/Badge.js";
import { Stack, Row } from "./ui/Layout.js";
import { Spinner } from "./ui/Spinner.js";

/** This plugin's SimpleAPI base (slug MUST match the manifest name). */
const API_BASE = "/plugin-io/api/note_protocol_automation";

// ---------------------------------------------------------------------------
// Vocabularies (mirror lib/catalog.py + the executor's predicate shapes).
// ---------------------------------------------------------------------------

/** Command catalog: key (stored) -> friendly label (shown). Order = display order. */
const COMMANDS = [
  ["diagnose", "Diagnose"],
  ["assess", "Assess"],
  ["plan", "Plan"],
  ["goal", "Goal"],
  ["hpi", "HPI"],
  ["reason_for_visit", "Reason for Visit"],
  ["lab_order", "Lab Order"],
  ["medication_statement", "Medication Statement"],
  ["allergy", "Allergy"],
  ["immunization_statement", "Immunization"],
];

/** Friendly label lookup for a command key. */
const COMMAND_LABEL = Object.fromEntries(COMMANDS);

/** Predicate signals: value (stored) -> friendly label. */
const SIGNALS = [
  ["condition", "Condition (ICD-10)"],
  ["age", "Age"],
  ["sex", "Sex"],
  ["lab_value", "Lab value"],
  ["care_team_role", "Care team role"],
];

/** Operators available per signal (value -> label). */
const CONDITION_OPS = [
  ["has_prefix", "starts with"],
  ["has", "equals"],
  ["not_has", "does not have"],
];
const AGE_OPS = [
  [">=", "at least (>=)"],
  ["<=", "at most (<=)"],
  ["==", "equals (==)"],
  ["between", "between"],
];
const LAB_OPS = [
  ["<", "less than (<)"],
  ["<=", "at most (<=)"],
  [">", "greater than (>)"],
  [">=", "at least (>=)"],
  ["==", "equals (==)"],
];
const SEX_VALUES = [
  ["F", "Female"],
  ["M", "Male"],
  ["O", "Other"],
  ["UNK", "Unknown"],
];

/**
 * Curated labs: friendly name -> LOINC. Both are stored in the predicate value.
 * A broad set of common labs so the dropdown isn't tied to any one specialty.
 * The first entry is the default when a new lab predicate is added — keep eGFR
 * first so that default stays stable. Every LOINC below is a real, standard code.
 */
const LABS = [
  ["eGFR", "33914-3"],
  ["Hemoglobin A1c", "4548-4"],
  ["Creatinine", "2160-0"],
  ["Potassium", "2823-3"],
  ["Urine Albumin/Creatinine Ratio", "9318-7"],
  ["Hemoglobin", "718-7"],
  ["White Blood Cell Count", "6690-2"],
  ["Platelets", "777-3"],
  ["Total Cholesterol", "2093-3"],
  ["LDL Cholesterol", "13457-7"],
  ["HDL Cholesterol", "2085-9"],
  ["Triglycerides", "2571-8"],
  ["TSH", "3016-3"],
  ["Glucose", "2345-7"],
  ["Sodium", "2951-2"],
  ["Calcium", "17861-6"],
  ["ALT", "1742-6"],
  ["AST", "1920-8"],
];

// ---------------------------------------------------------------------------
// Style constants (strings only — see template-safety note).
// ---------------------------------------------------------------------------
const PAGE_STYLE =
  "max-width:880px;margin:0 auto;padding:var(--npa-space-6) var(--npa-space-4);";
const TABLE_STYLE = "width:100%;border-collapse:collapse;";
const TH_STYLE =
  "text-align:left;padding:var(--npa-space-2) var(--npa-space-3);" +
  "font-size:var(--npa-font-size-sm);font-weight:var(--npa-font-weight-semibold);" +
  "color:var(--npa-color-text-secondary);border-bottom:1px solid var(--npa-color-border);";
const TD_STYLE =
  "padding:var(--npa-space-2) var(--npa-space-3);" +
  "border-bottom:1px solid var(--npa-color-border);color:var(--npa-color-text);" +
  "vertical-align:middle;";
const LABEL_STYLE =
  "display:block;font-size:var(--npa-font-size-sm);font-weight:var(--npa-font-weight-semibold);" +
  "color:var(--npa-color-text);margin-bottom:var(--npa-space-1);";
const INPUT_STYLE =
  "width:100%;box-sizing:border-box;padding:var(--npa-space-2) var(--npa-space-3);" +
  "border:1px solid var(--npa-color-border-strong);border-radius:var(--npa-radius-md);" +
  "font-family:var(--npa-font-sans);font-size:var(--npa-font-size-md);" +
  "color:var(--npa-color-text);background:var(--npa-color-surface);";
const SELECT_STYLE = INPUT_STYLE;
const SMALL_INPUT_STYLE = INPUT_STYLE + "max-width:140px;";
const ROW_BOX_STYLE =
  "padding:var(--npa-space-3);border:1px solid var(--npa-color-border);" +
  "border-radius:var(--npa-radius-md);background:var(--npa-color-surface-subtle,transparent);";
const MUTED_STYLE =
  "margin:0;font-size:var(--npa-font-size-sm);color:var(--npa-color-text-secondary);";
const PICKER_ITEM_STYLE =
  "display:flex;align-items:center;justify-content:space-between;gap:var(--npa-space-2);" +
  "padding:var(--npa-space-1) var(--npa-space-2);border:1px solid var(--npa-color-border);" +
  "border-radius:var(--npa-radius-md);";

// ---------------------------------------------------------------------------
// Predicate row defaults + helpers.
// ---------------------------------------------------------------------------

/**
 * Build a default predicate dict for a freshly chosen signal. Each shape matches
 * the executor exactly (see handlers/executor.py + lib/predicates.py).
 * @param {string} signal
 * @returns {Object}
 */
function defaultPredicate(signal) {
  if (signal === "condition") {
    return { signal: "condition", operator: "has_prefix", value: "" };
  }
  if (signal === "age") {
    return { signal: "age", operator: ">=", value: 18 };
  }
  if (signal === "sex") {
    return { signal: "sex", operator: "==", value: "F" };
  }
  if (signal === "lab_value") {
    return {
      signal: "lab_value",
      operator: "<",
      value: { loinc: LABS[0][1], label: LABS[0][0], threshold: 0, within_days: 180 },
    };
  }
  if (signal === "care_team_role") {
    return { signal: "care_team_role", operator: "has_role", value: "" };
  }
  return { signal: "condition", operator: "has_prefix", value: "" };
}

/**
 * Coerce a predicate's input strings into the strict numeric shapes the executor
 * expects, immediately before save. Returns a fresh, JSON-ready predicate dict.
 * @param {Object} p
 * @returns {Object}
 */
function normalizePredicate(p) {
  if (p.signal === "age") {
    if (p.operator === "between") {
      const lo = Number(Array.isArray(p.value) ? p.value[0] : 0);
      const hi = Number(Array.isArray(p.value) ? p.value[1] : 0);
      return { signal: "age", operator: "between", value: [lo, hi] };
    }
    return { signal: "age", operator: p.operator, value: Number(p.value) };
  }
  if (p.signal === "lab_value") {
    const v = p.value || {};
    return {
      signal: "lab_value",
      operator: p.operator,
      value: {
        loinc: v.loinc,
        label: v.label,
        threshold: Number(v.threshold),
        within_days: Number(v.within_days),
      },
    };
  }
  // condition / sex / care_team_role: value is a plain string already.
  return { signal: p.signal, operator: p.operator, value: p.value };
}

// ---------------------------------------------------------------------------
// Rule list view.
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} RuleListProps
 * @property {Array<Object>} rules Rules from GET /rules.
 * @property {Object<string,string>} noteTypeNames Map note_type_id -> name.
 * @property {() => void} onNew Start a new rule.
 * @property {(rule: Object) => void} onEdit Edit an existing rule.
 * @property {(dbid: number) => void} onDelete Delete a rule by dbid.
 */

/**
 * The rule list: a table of configured rules with per-row edit/delete.
 * @param {RuleListProps} props
 */
function RuleList({ rules, noteTypeNames, onNew, onEdit, onDelete }) {
  return html`
    <${Card}
      title="Note protocols"
      actions=${html`<${Button} variant="primary" size="sm" onClick=${onNew}>New rule<//>`}
    >
      ${rules.length === 0
        ? html`<p style=${MUTED_STYLE}>
            No rules yet. Create one to auto-insert a protocol's commands when a
            matching note is created.
          </p>`
        : html`
            <table style=${TABLE_STYLE}>
              <thead>
                <tr>
                  <th style=${TH_STYLE}>Name</th>
                  <th style=${TH_STYLE}>Note type</th>
                  <th style=${TH_STYLE}>Enabled</th>
                  <th style=${TH_STYLE}>Commands</th>
                  <th style=${TH_STYLE}></th>
                </tr>
              </thead>
              <tbody>
                ${rules.map(
                  (r) => html`
                    <tr key=${r.dbid}>
                      <td style=${TD_STYLE}>${r.name || "(unnamed)"}</td>
                      <td style=${TD_STYLE}>
                        ${noteTypeNames[r.note_type_id] || r.note_type_id || "(any)"}
                      </td>
                      <td style=${TD_STYLE}>
                        ${r.enabled
                          ? html`<${Badge} tone="success">Enabled<//>`
                          : html`<${Badge} tone="neutral">Disabled<//>`}
                      </td>
                      <td style=${TD_STYLE}>${(r.commands || []).length}</td>
                      <td style=${TD_STYLE}>
                        <${Row} gap=${2} justify="end">
                          <${Button} variant="secondary" size="sm" onClick=${() => onEdit(r)}>
                            Edit
                          <//>
                          <${Button} variant="danger" size="sm" onClick=${() => onDelete(r.dbid)}>
                            Delete
                          <//>
                        <//>
                      </td>
                    </tr>
                  `
                )}
              </tbody>
            </table>
          `}
    <//>
  `;
}

// ---------------------------------------------------------------------------
// Predicate builder.
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} PredicateRowProps
 * @property {Object} predicate The predicate dict being edited.
 * @property {(next: Object) => void} onChange Replace this predicate.
 * @property {() => void} onRemove Remove this predicate row.
 */

/**
 * A single predicate row whose inputs are driven by the chosen signal.
 * @param {PredicateRowProps} props
 */
function PredicateRow({ predicate, onChange, onRemove }) {
  const signal = predicate.signal;

  const setSignal = (next) => onChange(defaultPredicate(next));
  const setOperator = (op) => {
    if (signal === "age" && op === "between") {
      onChange({ signal: "age", operator: "between", value: [60, 70] });
      return;
    }
    if (signal === "age") {
      const cur = Array.isArray(predicate.value) ? predicate.value[0] : predicate.value;
      onChange({ signal: "age", operator: op, value: cur });
      return;
    }
    onChange({ ...predicate, operator: op });
  };

  const signalSelect = html`
    <select
      style=${SELECT_STYLE}
      value=${signal}
      onChange=${(e) => setSignal(e.target.value)}
    >
      ${SIGNALS.map(([v, label]) => html`<option value=${v}>${label}</option>`)}
    </select>
  `;

  let inputs = null;

  if (signal === "condition") {
    inputs = html`
      <select style=${SELECT_STYLE} value=${predicate.operator} onChange=${(e) => setOperator(e.target.value)}>
        ${CONDITION_OPS.map(([v, label]) => html`<option value=${v}>${label}</option>`)}
      </select>
      <input
        style=${INPUT_STYLE}
        type="text"
        placeholder="e.g. I10"
        value=${predicate.value || ""}
        onInput=${(e) => onChange({ ...predicate, value: e.target.value })}
      />
    `;
  } else if (signal === "age") {
    inputs = html`
      <select style=${SELECT_STYLE} value=${predicate.operator} onChange=${(e) => setOperator(e.target.value)}>
        ${AGE_OPS.map(([v, label]) => html`<option value=${v}>${label}</option>`)}
      </select>
      ${predicate.operator === "between"
        ? html`
            <input
              style=${SMALL_INPUT_STYLE}
              type="number"
              value=${Array.isArray(predicate.value) ? predicate.value[0] : ""}
              onInput=${(e) =>
                onChange({
                  ...predicate,
                  value: [e.target.value, Array.isArray(predicate.value) ? predicate.value[1] : ""],
                })}
            />
            <span style=${MUTED_STYLE}>and</span>
            <input
              style=${SMALL_INPUT_STYLE}
              type="number"
              value=${Array.isArray(predicate.value) ? predicate.value[1] : ""}
              onInput=${(e) =>
                onChange({
                  ...predicate,
                  value: [Array.isArray(predicate.value) ? predicate.value[0] : "", e.target.value],
                })}
            />
          `
        : html`
            <input
              style=${SMALL_INPUT_STYLE}
              type="number"
              value=${predicate.value}
              onInput=${(e) => onChange({ ...predicate, value: e.target.value })}
            />
          `}
    `;
  } else if (signal === "sex") {
    inputs = html`
      <span style=${MUTED_STYLE}>is</span>
      <select
        style=${SELECT_STYLE}
        value=${predicate.value}
        onChange=${(e) => onChange({ signal: "sex", operator: "==", value: e.target.value })}
      >
        ${SEX_VALUES.map(([v, label]) => html`<option value=${v}>${label}</option>`)}
      </select>
    `;
  } else if (signal === "lab_value") {
    const v = predicate.value || {};
    const onLab = (loinc) => {
      const match = LABS.find(([, code]) => code === loinc);
      onChange({
        ...predicate,
        value: { ...v, loinc, label: match ? match[0] : v.label },
      });
    };
    inputs = html`
      <select style=${SELECT_STYLE} value=${v.loinc} onChange=${(e) => onLab(e.target.value)}>
        ${LABS.map(([label, code]) => html`<option value=${code}>${label}</option>`)}
      </select>
      <select style=${SELECT_STYLE} value=${predicate.operator} onChange=${(e) => setOperator(e.target.value)}>
        ${LAB_OPS.map(([op, label]) => html`<option value=${op}>${label}</option>`)}
      </select>
      <input
        style=${SMALL_INPUT_STYLE}
        type="number"
        placeholder="threshold"
        value=${v.threshold}
        onInput=${(e) => onChange({ ...predicate, value: { ...v, threshold: e.target.value } })}
      />
      <span style=${MUTED_STYLE}>within</span>
      <input
        style=${SMALL_INPUT_STYLE}
        type="number"
        placeholder="days"
        value=${v.within_days}
        onInput=${(e) => onChange({ ...predicate, value: { ...v, within_days: e.target.value } })}
      />
      <span style=${MUTED_STYLE}>days</span>
    `;
  } else if (signal === "care_team_role") {
    inputs = html`
      <span style=${MUTED_STYLE}>has role</span>
      <input
        style=${INPUT_STYLE}
        type="text"
        placeholder="role code"
        value=${predicate.value || ""}
        onInput=${(e) => onChange({ signal: "care_team_role", operator: "has_role", value: e.target.value })}
      />
    `;
  }

  return html`
    <div style=${ROW_BOX_STYLE}>
      <${Row} gap=${2} align="center" wrap=${true}>
        ${signalSelect} ${inputs}
        <${Button} variant="ghost" size="sm" onClick=${onRemove}>Remove<//>
      <//>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Command picker (ordered multi-select with up/down reordering).
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} CommandPickerProps
 * @property {Array<string>} selected Ordered selected command keys.
 * @property {(next: Array<string>) => void} onChange Replace the ordered selection.
 */

/**
 * Ordered command picker: a catalog of "Add" buttons plus the ordered list of
 * chosen commands with up/down/remove controls. Order is stored as-is.
 * @param {CommandPickerProps} props
 */
function CommandPicker({ selected, onChange }) {
  const add = (key) => {
    if (!selected.includes(key)) onChange([...selected, key]);
  };
  const remove = (key) => onChange(selected.filter((k) => k !== key));
  const move = (i, delta) => {
    const j = i + delta;
    if (j < 0 || j >= selected.length) return;
    const next = selected.slice();
    const tmp = next[i];
    next[i] = next[j];
    next[j] = tmp;
    onChange(next);
  };

  const available = COMMANDS.filter(([key]) => !selected.includes(key));

  return html`
    <${Stack} gap=${3}>
      <div>
        <span style=${LABEL_STYLE}>Add a command</span>
        <${Row} gap=${2} wrap=${true}>
          ${available.length === 0
            ? html`<span style=${MUTED_STYLE}>All commands added.</span>`
            : available.map(
                ([key, label]) => html`
                  <${Button} variant="secondary" size="sm" onClick=${() => add(key)}>
                    + ${label}
                  <//>
                `
              )}
        <//>
      </div>
      ${selected.length === 0
        ? html`<p style=${MUTED_STYLE}>No commands selected yet.</p>`
        : html`
            <${Stack} gap=${2}>
              ${selected.map(
                (key, i) => html`
                  <div key=${key} style=${PICKER_ITEM_STYLE}>
                    <span>${i + 1}. ${COMMAND_LABEL[key] || key}</span>
                    <${Row} gap=${1}>
                      <${Button}
                        variant="ghost"
                        size="sm"
                        disabled=${i === 0}
                        onClick=${() => move(i, -1)}
                      >
                        Up
                      <//>
                      <${Button}
                        variant="ghost"
                        size="sm"
                        disabled=${i === selected.length - 1}
                        onClick=${() => move(i, 1)}
                      >
                        Down
                      <//>
                      <${Button} variant="ghost" size="sm" onClick=${() => remove(key)}>Remove<//>
                    <//>
                  </div>
                `
              )}
            <//>
          `}
    <//>
  `;
}

// ---------------------------------------------------------------------------
// Rule editor view.
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} RuleEditorProps
 * @property {Object|null} rule The rule being edited, or null for a new rule.
 * @property {Array<Object>} noteTypes Note types from GET /note-types.
 * @property {(payload: Object, dbid: (number|null)) => void} onSave Persist the rule.
 * @property {() => void} onCancel Discard and return to the list.
 */

/**
 * The rule editor form: name, note type, enabled, predicate builder, command
 * picker. Save coerces numeric predicate fields and emits the exact rule JSON.
 * @param {RuleEditorProps} props
 */
function RuleEditor({ rule, noteTypes, onSave, onCancel }) {
  const [name, setName] = useState(rule ? rule.name || "" : "");
  const [noteTypeId, setNoteTypeId] = useState(
    rule ? rule.note_type_id || "" : noteTypes.length ? noteTypes[0].id : ""
  );
  const [enabled, setEnabled] = useState(rule ? rule.enabled !== false : true);
  const [matchMode, setMatchMode] = useState(rule ? rule.match || "all" : "all");
  const [predicates, setPredicates] = useState(
    rule && Array.isArray(rule.predicates) ? rule.predicates.slice() : []
  );
  const [commands, setCommands] = useState(
    rule && Array.isArray(rule.commands) ? rule.commands.slice() : []
  );

  const setPredicateAt = (i, next) =>
    setPredicates(predicates.map((p, idx) => (idx === i ? next : p)));
  const removePredicateAt = (i) => setPredicates(predicates.filter((_, idx) => idx !== i));
  const addPredicate = () => setPredicates([...predicates, defaultPredicate("age")]);

  const save = () => {
    const payload = {
      name: name,
      note_type_id: noteTypeId,
      enabled: enabled,
      match: matchMode,
      priority: rule && typeof rule.priority === "number" ? rule.priority : 0,
      predicates: predicates.map(normalizePredicate),
      commands: commands,
    };
    onSave(payload, rule ? rule.dbid : null);
  };

  return html`
    <${Card}
      title=${rule ? "Edit rule" : "New rule"}
      actions=${html`
        <${Row} gap=${2}>
          <${Button} variant="ghost" size="sm" onClick=${onCancel}>Cancel<//>
          <${Button} variant="primary" size="sm" onClick=${save}>Save<//>
        <//>
      `}
    >
      <${Stack} gap=${5}>
        <div>
          <label style=${LABEL_STYLE}>Name</label>
          <input
            style=${INPUT_STYLE}
            type="text"
            placeholder="e.g. Annual physical protocol"
            value=${name}
            onInput=${(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label style=${LABEL_STYLE}>Note type</label>
          <select style=${SELECT_STYLE} value=${noteTypeId} onChange=${(e) => setNoteTypeId(e.target.value)}>
            ${noteTypes.length === 0
              ? html`<option value="">(no note types found)</option>`
              : noteTypes.map((nt) => html`<option value=${nt.id}>${nt.name}</option>`)}
          </select>
        </div>

        <div>
          <label style=${LABEL_STYLE}>
            <input
              type="checkbox"
              checked=${enabled}
              onChange=${(e) => setEnabled(e.target.checked)}
            />
            Enabled
          </label>
        </div>

        <div>
          <label style=${LABEL_STYLE}>Predicate combinator</label>
          <select
            style=${SELECT_STYLE}
            value=${matchMode}
            onChange=${(e) => setMatchMode(e.target.value)}
          >
            <option value="all">All predicates must match (AND)</option>
            <option value="any">Any predicate can match (OR)</option>
          </select>
        </div>

        <div>
          <span style=${LABEL_STYLE}>
            Predicates (${matchMode === "any" ? "any can match" : "all must match"})
          </span>
          <${Stack} gap=${2}>
            ${predicates.length === 0
              ? html`<p style=${MUTED_STYLE}>
                  ${matchMode === "any"
                    ? "No predicates — with the Any combinator this rule never fires."
                    : "No predicates — this rule matches every note of the chosen type."}
                </p>`
              : predicates.map(
                  (p, i) => html`
                    <${PredicateRow}
                      key=${i}
                      predicate=${p}
                      onChange=${(next) => setPredicateAt(i, next)}
                      onRemove=${() => removePredicateAt(i)}
                    />
                  `
                )}
            <div>
              <${Button} variant="secondary" size="sm" onClick=${addPredicate}>+ Add predicate<//>
            </div>
          <//>
        </div>

        <div>
          <span style=${LABEL_STYLE}>Commands to insert (in order)</span>
          <${CommandPicker} selected=${commands} onChange=${setCommands} />
        </div>
      <//>
    <//>
  `;
}

// ---------------------------------------------------------------------------
// Root app: orchestrates list <-> editor, owns data fetching.
// ---------------------------------------------------------------------------

export function App() {
  const [status, setStatus] = useState(/** @type {"loading"|"ok"|"error"} */ ("loading"));
  const [rules, setRules] = useState(/** @type {Array<Object>} */ ([]));
  const [noteTypes, setNoteTypes] = useState(/** @type {Array<Object>} */ ([]));
  const [view, setView] = useState(/** @type {"list"|"editor"} */ ("list"));
  const [editing, setEditing] = useState(/** @type {Object|null} */ (null));

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [rulesRes, typesRes] = await Promise.all([
        fetch(`${API_BASE}/rules`, { headers: { Accept: "application/json" } }),
        fetch(`${API_BASE}/note-types`, { headers: { Accept: "application/json" } }),
      ]);
      if (!rulesRes.ok || !typesRes.ok) {
        setStatus("error");
        return;
      }
      const rulesData = await rulesRes.json();
      const typesData = await typesRes.json();
      setRules(Array.isArray(rulesData) ? rulesData : []);
      setNoteTypes(Array.isArray(typesData) ? typesData : []);
      setStatus("ok");
    } catch (_e) {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const noteTypeNames = Object.fromEntries(noteTypes.map((nt) => [nt.id, nt.name]));

  const onNew = () => {
    setEditing(null);
    setView("editor");
  };
  const onEdit = (rule) => {
    setEditing(rule);
    setView("editor");
  };
  const onCancel = () => {
    setEditing(null);
    setView("list");
  };

  const onDelete = useCallback(
    async (dbid) => {
      try {
        await fetch(`${API_BASE}/rules/${dbid}`, {
          method: "DELETE",
          headers: { Accept: "application/json" },
        });
      } catch (_e) {
        // fall through to refetch; the list reflects server truth.
      }
      load();
    },
    [load]
  );

  const onSave = useCallback(
    async (payload, dbid) => {
      const isEdit = dbid != null;
      try {
        const res = await fetch(`${API_BASE}/rules${isEdit ? `/${dbid}` : ""}`, {
          method: isEdit ? "PUT" : "POST",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          setStatus("error");
          return;
        }
      } catch (_e) {
        setStatus("error");
        return;
      }
      setEditing(null);
      setView("list");
      load();
    },
    [load]
  );

  if (status === "loading") {
    return html`<div style=${PAGE_STYLE}>
      <${Spinner} center=${true} label="Loading rules" />
    </div>`;
  }

  if (status === "error") {
    return html`
      <div style=${PAGE_STYLE}>
        <${Card} title="Could not load configuration">
          <${Stack} gap=${3}>
            <${Badge} tone="danger">Request failed<//>
            <p style=${MUTED_STYLE}>
              We couldn't reach the rules service. No changes were made.
            </p>
            <div>
              <${Button} variant="secondary" onClick=${load}>Try again<//>
            </div>
          <//>
        <//>
      </div>
    `;
  }

  return html`
    <div style=${PAGE_STYLE}>
      ${view === "list"
        ? html`<${RuleList}
            rules=${rules}
            noteTypeNames=${noteTypeNames}
            onNew=${onNew}
            onEdit=${onEdit}
            onDelete=${onDelete}
          />`
        : html`<${RuleEditor}
            rule=${editing}
            noteTypes=${noteTypes}
            onSave=${onSave}
            onCancel=${onCancel}
          />`}
    </div>
  `;
}
