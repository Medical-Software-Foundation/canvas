// Render the plugin's real templates/picker.html into a standalone HTML file with
// mock data, so we can screenshot every picker state locally (pixel-accurate, no login,
// no PHI). We reuse picker.html VERBATIM and only substitute the Django template
// variables it declares:
//   {{ patient_id|escapejs }}  {{ patient_name|escapejs }}  {{ consents_json|escapejs }}
//   {{ records_json|escapejs }} {{ method_options_json|escapejs }}  {{ settings_url }}
//   {% if is_admin %} ... {% endif %}  (the Settings gear)
//
// The JSON shapes mirror service.py: picker_items() -> CONSENTS, consent_records() -> RECORDS.
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
const PICKER = resolve(REPO, 'consent_capture', 'templates', 'picker.html');

// ---- Mock data (representative, no PHI) ---------------------------------------
const METHOD_OPTIONS = ['Verbal', 'Electronic', 'Written', 'Other'];

const QUESTIONS = [
  { id: 'q1', prompt: 'Do you consent to treatment as described above?', type: 'yes_no', required: true, affirm: true },
  { id: 'q2', prompt: 'Have your questions been answered to your satisfaction?', type: 'yes_no', required: true, affirm: false },
  { id: 'q3', prompt: 'I confirm the above was reviewed with me.', type: 'acknowledge', required: true, affirm: true },
];

const PARAGRAPHS = [
  'I authorize my care team to provide the treatment, services, and procedures they determine to be reasonable and necessary for my care.',
  'I understand that no guarantee has been made to me about the results of any treatment or examination, and that I may withdraw this consent at any time.',
  'I have had the opportunity to ask questions, and my questions have been answered to my satisfaction.',
];

// CONSENTS drives the Required / Optional action rows + the wizard.
const CONSENTS = [
  {
    code: 'TREAT', system: 'INTERNAL', display: 'Treatment Consent',
    paragraphs: PARAGRAPHS, method_enabled: true, obtained_by_enabled: true, capacity_enabled: true,
    method_options: METHOD_OPTIONS, questions: QUESTIONS,
    required: true, active: true, on_file: false, status: 'needed',
    effective_date: '', expiration_date: '',
  },
  {
    code: 'RPM', system: 'INTERNAL', display: 'Remote Patient Monitoring Consent',
    paragraphs: PARAGRAPHS.slice(0, 2), method_enabled: true, obtained_by_enabled: true, capacity_enabled: false,
    method_options: METHOD_OPTIONS, questions: QUESTIONS.slice(0, 1),
    required: true, active: true, on_file: false, status: 'expired',
    effective_date: '2024-06-01', expiration_date: '2025-06-01',
  },
  {
    code: 'TELE', system: 'INTERNAL', display: 'Telehealth Consent',
    paragraphs: PARAGRAPHS.slice(0, 2), method_enabled: true, obtained_by_enabled: false, capacity_enabled: false,
    method_options: METHOD_OPTIONS, questions: [],
    required: false, active: true, on_file: false, status: 'needed',
    effective_date: '', expiration_date: '',
  },
  {
    code: 'WRITTEN', system: 'INTERNAL', display: 'Financial Responsibility (Signed Form)',
    paragraphs: PARAGRAPHS.slice(0, 1), method_enabled: true, obtained_by_enabled: true, capacity_enabled: false,
    method_options: ['Written'], questions: [],
    required: false, active: true, on_file: false, status: 'needed',
    effective_date: '', expiration_date: '',
  },
];

// RECORDS drives the On File history (one row per recording, newest first).
const RECORDS = [
  {
    id: '1001', code: 'HIPAA', system: 'INTERNAL', display: 'Notice of Privacy Practices',
    status: 'active', on_file: true, effective_date: '2025-03-12', expiration_date: '',
  },
  {
    id: '1002', code: 'RPM', system: 'INTERNAL', display: 'Remote Patient Monitoring Consent',
    status: 'expired', on_file: false, effective_date: '2024-06-01', expiration_date: '2025-06-01',
  },
];

function fill(html, vars) {
  // Replace {% if is_admin %}...{% endif %} — keep the inner content (show the gear).
  html = html.replace(/\{%\s*if\s+is_admin\s*%\}/g, '').replace(/\{%\s*endif\s*%\}/g, '');
  // Replace {{ name|filter }} / {{ name }} tokens with the mapped value.
  html = html.replace(/\{\{\s*([a-z_]+)(?:\|[a-z]+)?\s*\}\}/gi, (m, name) => {
    if (name in vars) return vars[name];
    return '';
  });
  return html;
}

export function renderPickerHtml(outPath) {
  const raw = readFileSync(PICKER, 'utf8');
  const vars = {
    patient_id: 'demo-patient',
    patient_name: 'Jordan Rivera',
    // These feed JSON.parse("...") after escapejs, so we JSON-encode then escape quotes/backslashes.
    consents_json: jsEscape(JSON.stringify(CONSENTS)),
    records_json: jsEscape(JSON.stringify(RECORDS)),
    method_options_json: jsEscape(JSON.stringify(METHOD_OPTIONS)),
    settings_url: '#settings',
  };
  const html = fill(raw, vars);
  writeFileSync(outPath, html, 'utf8');
  return outPath;
}

// Mimic Django's |escapejs for a value placed inside a double-quoted JS string literal.
function jsEscape(s) {
  return s
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\u0022')
    .replace(/'/g, '\\u0027')
    .replace(/</g, '\\u003C')
    .replace(/>/g, '\\u003E')
    .replace(/&/g, '\\u0026')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r');
}

export { CONSENTS, RECORDS, METHOD_OPTIONS };
