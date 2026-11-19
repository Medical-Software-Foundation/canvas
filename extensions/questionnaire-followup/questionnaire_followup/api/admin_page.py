"""Form-based admin page for the questionnaire pairings (served by GET /admin/ui).

An EMR admin builds the rules entirely through form controls. Each rule reads as
a sentence - when this short form scores at least N, present that long one - so
the person configuring it can check it against what they meant without knowing
anything about the storage format. The JSON config document is the storage format
only; it is never shown to or edited by a user.

The rule cap and the comparator vocabulary are substituted in from
``services.config_store`` rather than repeated here, so the page cannot offer a
score rule the server would refuse, or a limit it would not enforce.

The page loads the rules from GET /admin/config, the questionnaire list from
GET /admin/questionnaires, and saves via POST /admin/config.
"""

import json

from questionnaire_followup.services.config_store import (
    COMPARATOR_BETWEEN,
    COMPARATOR_COMPLETED,
    COMPARATOR_LABELS,
    DEFAULT_COMPARATOR,
    MAX_RULES,
)


def build_admin_html() -> str:
    """Return the full HTML page for the pairing editor, with the server's limits filled in."""
    return (
        _ADMIN_HTML.replace("__MAX_RULES__", str(MAX_RULES))
        .replace("__COMPARATOR_LABELS__", json.dumps(COMPARATOR_LABELS))
        .replace("__CMP_BETWEEN__", COMPARATOR_BETWEEN)
        .replace("__CMP_COMPLETED__", COMPARATOR_COMPLETED)
        .replace("__CMP_DEFAULT__", DEFAULT_COMPARATOR)
    )


_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Questionnaire Follow-Up</title>
<style>
  :root {
    --bg-page:#f5f6f8; --bg-3:#e8edf3; --card:#ffffff;
    --text-heading:#111827; --text-body:#1f2933; --text-muted:#6b7280; --text-label:#475569;
    --primary:#2185D0; --primary-hover:#1a6aae; --teal:#4a9fe0;
    --warn-bg:#fff8e6; --warn-line:#f0d9a0; --warn-text:#8a6100;
    --danger:#c0392b; --ok:#1a7f4b;
    --line:#e5e7eb; --radius-lg:14px; --radius-md:10px; --radius-full:9999px;
    --shadow-card:0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06);
    --font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  }
  * { margin:0; padding:0; box-sizing:border-box; -webkit-font-smoothing:antialiased; }
  body { font-family:var(--font); color:var(--text-body); font-size:14px; line-height:1.5; min-height:100vh;
         background:radial-gradient(1100px 520px at 88% -8%, var(--bg-3), rgba(232,237,243,0) 60%), var(--bg-page); }
  .wrap { max-width:1000px; margin:0 auto; padding:3rem 2rem 7rem; }
  h1 { font-weight:900; font-size:26px; color:var(--text-heading); letter-spacing:-.02em; }
  .sub { color:var(--text-muted); margin-bottom:1.5rem; max-width:70ch; }
  .banner { display:flex; gap:12px; align-items:flex-start; background:var(--warn-bg); border:1px solid var(--warn-line);
            color:var(--warn-text); border-radius:var(--radius-md); padding:14px 16px; margin-bottom:22px; }
  .banner p { font-size:13px; }
  .banner strong { font-weight:900; }
  .rule { background:var(--card); border:1px solid var(--line); border-radius:var(--radius-lg);
          box-shadow:var(--shadow-card); margin-bottom:16px; overflow:hidden; }
  .rule.off { opacity:.62; }
  .rule-head { display:flex; align-items:center; gap:12px; padding:14px 18px; background:#fafbfc; border-bottom:1px solid var(--line); }
  .rule-head .name { flex:1; font-weight:700; font-size:15px; border:1px solid transparent; background:transparent;
                     border-radius:8px; padding:6px 8px; font-family:var(--font); color:var(--text-heading); }
  .rule-head .name:hover { border-color:#e2e8f0; background:#fff; }
  .rule-head .name:focus { outline:none; border-color:var(--teal); background:#fff; box-shadow:0 0 0 3px rgba(33,133,208,.15); }
  .sentence { padding:18px; display:flex; flex-wrap:wrap; align-items:center; gap:8px 10px; font-size:14px; }
  .sentence .txt { color:var(--text-label); }
  select, input { font-family:var(--font); font-size:14px; color:var(--text-body); }
  .sel { background:#fff; border:1px solid #e2e8f0; border-radius:var(--radius-md); padding:8px 10px; max-width:290px; }
  .num { background:#fff; border:1px solid #e2e8f0; border-radius:var(--radius-md); padding:8px 10px; width:74px; text-align:center; }
  .sel:focus, .num:focus { outline:none; border-color:var(--teal); box-shadow:0 0 0 3px rgba(33,133,208,.15); }
  .cmp { max-width:180px; }
  .sel.bad, .num.bad { border-color:#e0b4b4; background:#fff8f8; }
  .flag { display:inline-flex; align-items:center; gap:5px; font-size:12px; font-weight:700; color:var(--danger); }
  .note { padding:0 18px 16px; font-size:12px; color:var(--text-muted); }
  .toggle { display:inline-flex; align-items:center; gap:7px; font-size:12px; font-weight:700; text-transform:uppercase;
            letter-spacing:.06em; color:var(--text-label); cursor:pointer; user-select:none; white-space:nowrap; }
  .toggle input { width:16px; height:16px; accent-color:var(--primary); cursor:pointer; }
  .ic { flex-shrink:0; vertical-align:middle; }
  .icon-btn { background:none; border:none; color:var(--text-muted); cursor:pointer; padding:5px; border-radius:6px; display:inline-flex; }
  .icon-btn:hover { background:#eef2f6; color:var(--primary); }
  .icon-btn.danger:hover { background:#fdecec; color:var(--danger); }
  .btn { padding:9px 16px; border-radius:10px; font-weight:800; font-size:13px; cursor:pointer; border:none; font-family:var(--font); }
  .btn-primary { background:var(--primary); color:#fff; }
  .btn-primary:hover { background:var(--primary-hover); }
  .btn-link { background:none; border:none; color:var(--warn-text); font-weight:800; font-size:12px; cursor:pointer;
              text-decoration:underline; font-family:var(--font); white-space:nowrap; }
  .btn-ghost { background:#fff; color:var(--primary); border:1px dashed #bcd6ee; width:100%; padding:12px; border-radius:10px;
               font-weight:800; font-size:13px; cursor:pointer; font-family:var(--font); }
  .btn-ghost:hover { background:#eef5fc; }
  .empty { background:var(--card); border:1px dashed var(--line); border-radius:var(--radius-lg); padding:36px;
           text-align:center; color:var(--text-muted); margin-bottom:16px; }
  /* Controls sit bottom-LEFT so they clear the Canvas chat widget (bottom-right). */
  .footer { position:fixed; bottom:0; left:0; right:0; background:#fff; border-top:1px solid var(--line);
            padding:14px 2rem; display:flex; justify-content:flex-start; gap:14px; align-items:center; z-index:60; }
  .saved { color:var(--ok); font-weight:700; font-size:13px; }
  .muted { color:var(--text-muted); font-size:12px; }
  .err { color:var(--danger); font-weight:700; font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Questionnaire Follow-Up</h1>
  <p class="sub">When a patient&#39;s answers to a short questionnaire meet a rule you set here, the paired
     long one is presented to them in the patient portal. Rules are checked each time the patient opens the
     portal, and a form stops being offered as soon as it is answered.</p>

  <div class="banner" id="defaults-banner" hidden>
    <svg class="ic" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
    <p><strong>These pairings are shipped defaults</strong>, current as of <span id="defaults-date"></span>.
       They use national-standard LOINC codes and standard cutoffs, and they are switched off until you review
       them. Check that each one points at the questionnaire your instance actually uses before enabling it.</p>
    <button class="btn-link" onclick="dismissBanner()">Reviewed</button>
  </div>

  <div id="rules"></div>
  <button class="btn-ghost" onclick="addRule()">
    <svg class="ic" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg> Add pairing
  </button>
</div>

<div class="footer">
  <button class="btn btn-primary" onclick="save()">Save pairings</button>
  <span class="muted" id="status"></span>
</div>

<script>
const BASE = '/plugin-io/api/questionnaire_followup';
const MAX_RULES = __MAX_RULES__;
const COMPARATOR_LABELS = __COMPARATOR_LABELS__;
const COMPARATORS = Object.keys(COMPARATOR_LABELS);
const CMP_BETWEEN = '__CMP_BETWEEN__';
const CMP_COMPLETED = '__CMP_COMPLETED__';
const CMP_DEFAULT = '__CMP_DEFAULT__';
let config = { rules: [], defaults_reviewed: false, defaults_current_as_of: '' };
let QLIST = [];
let QBYCODE = {};

function esc(s) {
  return (s == null ? '' : String(s))
    .split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;')
    .split('"').join('&quot;').split("'").join('&#39;');
}
function setStatus(text, kind) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.className = kind === 'ok' ? 'saved' : (kind === 'err' ? 'err' : 'muted');
}

async function load() {
  try {
    const res = await (await fetch(BASE + '/admin/config')).json();
    if (res.config) config = res.config;
  } catch (e) { setStatus('Could not load the saved pairings.', 'err'); }
  try {
    const res = await (await fetch(BASE + '/admin/questionnaires')).json();
    QLIST = res.questionnaires || [];
  } catch (e) { setStatus('Could not load this instance\\u2019s questionnaires.', 'err'); }

  QBYCODE = {};
  QLIST.forEach(q => { QBYCODE[q.code] = q; });
  if (!Array.isArray(config.rules)) config.rules = [];

  const banner = document.getElementById('defaults-banner');
  banner.hidden = !!config.defaults_reviewed;
  document.getElementById('defaults-date').textContent = config.defaults_current_as_of || 'an unknown date';
  render();
}
document.addEventListener('DOMContentLoaded', load);

function dismissBanner() {
  config.defaults_reviewed = true;
  document.getElementById('defaults-banner').hidden = true;
}

function addRule() {
  if (config.rules.length >= MAX_RULES) {
    setStatus('At most ' + MAX_RULES + ' pairings can be configured.', 'err');
    return;
  }
  config.rules.push({
    id: 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
    enabled: false, name: 'New pairing', trigger_code: '', followup_code: '',
    comparator: CMP_DEFAULT, threshold: 3, threshold_max: 3,
    trigger_lookback_days: 30, suppression_days: 90
  });
  render();
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}
function removeRule(i) { config.rules.splice(i, 1); render(); }
function setField(i, field, value, rerender) {
  const rule = config.rules[i];
  if (field === 'enabled') rule.enabled = !!value;
  else if (field === 'name' || field === 'trigger_code' || field === 'followup_code' || field === 'comparator') rule[field] = value;
  else {
    const n = parseInt(value, 10);
    rule[field] = isNaN(n) ? 0 : n;
  }
  if (rerender) render();
}

// A code the instance does not have is the failure mode that matters most here:
// the rule looks configured and never fires. Keep it selected and label it.
function options(selected) {
  let html = '<option value="">Select a questionnaire\\u2026</option>';
  if (selected && !QBYCODE[selected]) {
    html += '<option value="' + esc(selected) + '" selected>Not in this instance (' + esc(selected) + ')</option>';
  }
  QLIST.forEach(q => {
    const label = q.name + ' (' + q.code + ')';
    html += '<option value="' + esc(q.code) + '"' + (q.code === selected ? ' selected' : '') + '>' + esc(label) + '</option>';
  });
  return html;
}

function comparatorOptions(selected) {
  let html = '';
  // A comparator this version does not know (a config saved by a newer one) stays
  // selected and labelled, exactly like a code the instance does not have.
  if (selected && !COMPARATOR_LABELS[selected]) {
    html += '<option value="' + esc(selected) + '" selected>Unrecognized (' + esc(selected) + ')</option>';
  }
  COMPARATORS.forEach(c => {
    html += '<option value="' + esc(c) + '"' + (c === selected ? ' selected' : '') + '>' + esc(COMPARATOR_LABELS[c]) + '</option>';
  });
  return html;
}

// "is completed" pairs on the patient having answered at all, so it shows no number.
function readsScore(rule) { return rule.comparator !== CMP_COMPLETED; }
// A backwards range is left inert and flagged rather than silently swapped: the
// swap would point the pairing at a severity band nobody chose.
function rangeBackwards(rule) {
  return rule.comparator === CMP_BETWEEN && Number(rule.threshold) > Number(rule.threshold_max);
}
function rangeClass(rule) { return rangeBackwards(rule) ? ' bad' : ''; }

function ruleWarnings(rule) {
  const out = [];
  if (rule.trigger_code && !QBYCODE[rule.trigger_code]) out.push('The short questionnaire is not loaded in this instance, so this pairing never fires.');
  if (rule.followup_code && !QBYCODE[rule.followup_code]) out.push('The follow-up questionnaire is not loaded in this instance, so this pairing never fires.');
  if (rule.enabled && (!rule.trigger_code || !rule.followup_code)) out.push('Both questionnaires must be chosen before this pairing does anything.');
  const followup = QBYCODE[rule.followup_code];
  if (followup && !followup.can_originate_in_charting) out.push('The follow-up is not enabled to originate in charting, so the patient\\u2019s answer may not commit into a note.');
  if (rule.trigger_code && rule.trigger_code === rule.followup_code) out.push('The short and follow-up questionnaires are the same, so this pairing re-asks the same form.');
  if (rangeBackwards(rule)) out.push('The score range runs backwards \\u2014 the low end is above the high end \\u2014 so this pairing never fires. Correct the two numbers.');
  if (rule.comparator && !COMPARATOR_LABELS[rule.comparator]) out.push('This pairing uses a score rule this version does not recognize, so it never fires.');
  return out;
}

function render() {
  const host = document.getElementById('rules');
  if (!config.rules.length) {
    host.innerHTML = '<div class="empty">No pairings yet. Add one to start presenting a follow-up questionnaire after a positive screen.</div>';
    return;
  }
  host.innerHTML = config.rules.map((rule, i) => {
    const warnings = ruleWarnings(rule);
    const badClass = c => (c && !QBYCODE[c]) ? ' bad' : '';
    return '' +
      '<div class="rule' + (rule.enabled ? '' : ' off') + '">' +
        '<div class="rule-head">' +
          '<label class="toggle"><input type="checkbox"' + (rule.enabled ? ' checked' : '') +
            ' onchange="setField(' + i + ',\\'enabled\\',this.checked,true)">' + (rule.enabled ? 'On' : 'Off') + '</label>' +
          '<input class="name" value="' + esc(rule.name) + '" oninput="setField(' + i + ',\\'name\\',this.value)" aria-label="Pairing name">' +
          '<button class="icon-btn danger" title="Remove pairing" onclick="removeRule(' + i + ')">' +
            '<svg class="ic" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg></button>' +
        '</div>' +
        '<div class="sentence">' +
          '<span class="txt">When</span>' +
          '<select class="sel' + badClass(rule.trigger_code) + '" onchange="setField(' + i + ',\\'trigger_code\\',this.value,true)">' + options(rule.trigger_code) + '</select>' +
          '<select class="sel cmp" onchange="setField(' + i + ',\\'comparator\\',this.value,true)">' + comparatorOptions(rule.comparator) + '</select>' +
          (readsScore(rule) ?
            '<input class="num' + rangeClass(rule) + '" type="number" min="0" value="' + esc(rule.threshold) + '" onchange="setField(' + i + ',\\'threshold\\',this.value)">' : '') +
          (rule.comparator === CMP_BETWEEN ?
            '<span class="txt">and</span>' +
            '<input class="num' + rangeClass(rule) + '" type="number" min="0" value="' + esc(rule.threshold_max) + '" onchange="setField(' + i + ',\\'threshold_max\\',this.value)">' : '') +
          '<span class="txt">within the last</span>' +
          '<input class="num" type="number" min="1" value="' + esc(rule.trigger_lookback_days) + '" onchange="setField(' + i + ',\\'trigger_lookback_days\\',this.value)">' +
          '<span class="txt">days, present</span>' +
          '<select class="sel' + badClass(rule.followup_code) + '" onchange="setField(' + i + ',\\'followup_code\\',this.value,true)">' + options(rule.followup_code) + '</select>' +
          '<span class="txt">in the portal \\u2014 unless it was completed in the last</span>' +
          '<input class="num" type="number" min="0" value="' + esc(rule.suppression_days) + '" onchange="setField(' + i + ',\\'suppression_days\\',this.value)">' +
          '<span class="txt">days.</span>' +
        '</div>' +
        (warnings.length ? '<div class="note">' + warnings.map(w =>
          '<div class="flag"><svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11 15h2v2h-2zm0-8h2v6h-2zm.99-5C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"/></svg>' + esc(w) + '</div>').join('') + '</div>' : '') +
      '</div>';
  }).join('');
}

async function save() {
  setStatus('Saving\\u2026');
  try {
    const res = await fetch(BASE + '/admin/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config })
    });
    const data = await res.json();
    if (data.success) { setStatus('Saved', 'ok'); }
    else { setStatus(data.error || 'Could not save', 'err'); }
  } catch (e) { setStatus('Could not save', 'err'); }
}
</script>
</body>
</html>"""


ACCESS_DENIED_HTML = (
    "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
    "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,"
    "sans-serif;background:#f5f6f8;color:#1f2933;"
    "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;}"
    ".card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:40px 48px;max-width:440px;"
    "box-shadow:0 8px 24px rgba(0,0,0,0.06);}h1{color:#111827;font-size:20px;margin:0 0 8px;}"
    "p{color:#6b7280;font-size:14px;margin:0;}</style></head>"
    "<body><div class='card'><h1>Access restricted</h1>"
    "<p>You do not have access to Questionnaire Follow-Up. Ask an administrator to add "
    "your staff key to the plugin's ADMIN_STAFF_KEYS setting.</p>"
    "</div></body></html>"
)
