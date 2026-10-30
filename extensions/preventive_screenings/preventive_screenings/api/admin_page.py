"""Form-based admin page for the preventive screenings (served by GET /admin/ui).

An EMR admin builds the rules entirely through form controls. Each screening
reads as a sentence - screen these patients, this often, counted as done when
this is on file - so the person configuring it can check it against what they
meant without knowing anything about the storage format. The JSON config
document is the storage format only; it is never shown to or edited by a user.

The page loads everything from GET /admin/config (the stored screenings and the
catalog of code sets to pick from) and saves via POST /admin/config.

Nothing is loaded from outside Canvas: the font stack is the system one and the
icons are inline SVG. A page that reaches a third party on every open is a
patient-data leak waiting to be found, and it fails the security review.
"""

from preventive_screenings.services.config_store import (
    MAX_CODES_PER_SIGNAL,
    MAX_SCREENINGS,
    MAX_SIGNALS_PER_SCREENING,
)


def build_admin_html() -> str:
    """Return the full HTML page for the screening editor."""
    return (
        _ADMIN_HTML.replace("__MAX_SCREENINGS__", str(MAX_SCREENINGS))
        .replace("__MAX_SIGNALS__", str(MAX_SIGNALS_PER_SCREENING))
        .replace("__MAX_CODES__", str(MAX_CODES_PER_SIGNAL))
    )


_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Preventive Screenings</title>
<style>
  :root {
    --bg-page:#f5f6f8; --bg-3:#e8edf3; --card:#ffffff;
    --text-heading:#111827; --text-body:#1f2933; --text-muted:#6b7280; --text-label:#475569;
    --primary:#2185D0; --primary-hover:#1a6aae; --teal:#4a9fe0;
    --warn-bg:#fff8e6; --warn-line:#f0d9a0; --warn-text:#8a6100;
    --danger:#c0392b; --ok:#1a7f4b;
    --line:#e5e7eb; --radius-lg:14px; --radius-md:10px;
    --shadow-card:0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06);
    --font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  }
  * { margin:0; padding:0; box-sizing:border-box; -webkit-font-smoothing:antialiased; }
  body { font-family:var(--font); color:var(--text-body); font-size:14px; line-height:1.5; min-height:100vh;
         background:radial-gradient(1100px 520px at 88% -8%, var(--bg-3), rgba(232,237,243,0) 60%), var(--bg-page); }
  .wrap { max-width:1040px; margin:0 auto; padding:3rem 2rem 7rem; }
  h1 { font-weight:900; font-size:26px; color:var(--text-heading); letter-spacing:-.02em; }
  .sub { color:var(--text-muted); margin-bottom:1.5rem; max-width:72ch; }
  .banner { display:flex; gap:12px; align-items:flex-start; background:var(--warn-bg); border:1px solid var(--warn-line);
            color:var(--warn-text); border-radius:var(--radius-md); padding:14px 16px; margin-bottom:22px; }
  .banner p { font-size:13px; }
  .banner strong { font-weight:900; }
  .scr { background:var(--card); border:1px solid var(--line); border-radius:var(--radius-lg);
         box-shadow:var(--shadow-card); margin-bottom:16px; overflow:hidden; }
  .scr.off { opacity:.62; }
  .scr-head { display:flex; align-items:center; gap:12px; padding:14px 18px; background:#fafbfc; border-bottom:1px solid var(--line); }
  .scr-head .name { flex:1; font-weight:700; font-size:15px; border:1px solid transparent; background:transparent;
                    border-radius:8px; padding:6px 8px; font-family:var(--font); color:var(--text-heading); }
  .scr-head .name:hover { border-color:#e2e8f0; background:#fff; }
  .scr-head .name:focus { outline:none; border-color:var(--teal); background:#fff; box-shadow:0 0 0 3px rgba(33,133,208,.15); }
  .grp { padding:14px 18px; border-bottom:1px solid #f1f4f7; }
  .grp:last-child { border-bottom:none; }
  .grp-label { font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.07em;
               color:var(--text-muted); margin-bottom:9px; }
  .row { display:flex; flex-wrap:wrap; align-items:center; gap:7px 9px; margin-bottom:7px; }
  .row:last-child { margin-bottom:0; }
  .txt { color:var(--text-label); }
  select, input { font-family:var(--font); font-size:14px; color:var(--text-body); }
  .sel { background:#fff; border:1px solid #e2e8f0; border-radius:var(--radius-md); padding:7px 9px; max-width:280px; }
  .num { background:#fff; border:1px solid #e2e8f0; border-radius:var(--radius-md); padding:7px 9px; width:72px; text-align:center; }
  .txtin { background:#fff; border:1px solid #e2e8f0; border-radius:var(--radius-md); padding:7px 9px; min-width:170px; flex:1; max-width:320px; }
  .sel:focus, .num:focus, .txtin:focus { outline:none; border-color:var(--teal); box-shadow:0 0 0 3px rgba(33,133,208,.15); }
  .flag { display:flex; align-items:flex-start; gap:5px; font-size:12px; font-weight:700; color:var(--danger); margin-top:6px; }
  .ic { flex-shrink:0; vertical-align:middle; }
  .toggle { display:inline-flex; align-items:center; gap:7px; font-size:12px; font-weight:700; text-transform:uppercase;
            letter-spacing:.06em; color:var(--text-label); cursor:pointer; user-select:none; white-space:nowrap; }
  .toggle input { width:16px; height:16px; accent-color:var(--primary); cursor:pointer; }
  .icon-btn { background:none; border:none; color:var(--text-muted); cursor:pointer; padding:5px; border-radius:6px; display:inline-flex; }
  .icon-btn:hover { background:#eef2f6; color:var(--primary); }
  .icon-btn.danger:hover { background:#fdecec; color:var(--danger); }
  .btn { padding:9px 16px; border-radius:10px; font-weight:800; font-size:13px; cursor:pointer; border:none; font-family:var(--font); }
  .btn-primary { background:var(--primary); color:#fff; }
  .btn-primary:hover { background:var(--primary-hover); }
  .btn-link { background:none; border:none; color:var(--warn-text); font-weight:800; font-size:12px; cursor:pointer;
              text-decoration:underline; font-family:var(--font); white-space:nowrap; }
  .btn-add { background:#fff; color:var(--primary); border:1px dashed #bcd6ee; border-radius:9px; padding:6px 11px;
             font-weight:800; font-size:12px; cursor:pointer; font-family:var(--font); }
  .btn-add:hover { background:#eef5fc; }
  .btn-ghost { background:#fff; color:var(--primary); border:1px dashed #bcd6ee; width:100%; padding:12px; border-radius:10px;
               font-weight:800; font-size:13px; cursor:pointer; font-family:var(--font); }
  .btn-ghost:hover { background:#eef5fc; }
  .empty { background:var(--card); border:1px dashed var(--line); border-radius:var(--radius-lg); padding:36px;
           text-align:center; color:var(--text-muted); margin-bottom:16px; }
  .footer { position:fixed; bottom:0; left:0; right:0; background:#fff; border-top:1px solid var(--line);
            padding:14px 2rem; display:flex; justify-content:flex-start; gap:14px; align-items:center; z-index:60; }
  .saved { color:var(--ok); font-weight:700; font-size:13px; }
  .muted { color:var(--text-muted); font-size:12px; }
  .err { color:var(--danger); font-weight:700; font-size:13px; }
  .summary { font-size:12px; color:var(--text-muted); padding:10px 18px 14px; font-style:italic; }
  /* What a catalog entry actually matches. Collapsed by default - it is the
     answer to "why did that not count", not something to read every time. */
  .vswhat { flex-basis:100%; margin:4px 0 2px 2px; font-size:12px; }
  .vswhat > summary { color:var(--text-muted); cursor:pointer; list-style:revert; }
  .vswhat > summary:hover { color:var(--primary); }
  .vscodes { margin-top:6px; padding:8px 10px; background:#f7f9fb; border:1px solid var(--line);
             border-radius:8px; max-height:150px; overflow:auto; }
  .vscodes div { margin-bottom:5px; }
  .vscodes div:last-child { margin-bottom:0; }
  .vscodes b { color:var(--text); font-size:11px; letter-spacing:.03em; }
  .vscodes span { color:var(--text-muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
                  font-size:11px; word-break:break-all; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Preventive Screenings</h1>
  <p class="sub">Each screening below is checked against the patient's chart. A screening shows as due when its
     interval runs out, and as overdue once it has been due longer than its grace period. Every screening you
     switch on appears in the <strong>screening record</strong> beside the chart, where a provider can also mark
     one complete or not applicable. Tick <strong>Chart card</strong> as well to push it onto the chart summary
     as a protocol card. Nothing is ordered automatically &mdash; a provider clicks the button and signs the order.</p>

  <div class="banner" id="defaults-banner" hidden>
    <svg class="ic" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
    <p><strong>These screenings are shipped defaults</strong>, current as of <span id="defaults-date"></span>.
       They follow published national guidance, which your practice may not follow, and they are switched off
       until you review them. Check the ages, intervals and what counts as done against your own protocol
       before enabling each one.</p>
    <button class="btn-link" data-act="dismiss">Reviewed</button>
  </div>

  <div id="screenings"></div>
  <button class="btn-ghost" data-act="add-screening">
    <svg class="ic" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg> Add screening
  </button>
</div>

<div class="footer">
  <button class="btn btn-primary" data-act="save">Save screenings</button>
  <span class="muted" id="status"></span>
</div>

<script>
const BASE = '/plugin-io/api/preventive_screenings';
const MAX_SCREENINGS = __MAX_SCREENINGS__;
const MAX_SIGNALS = __MAX_SIGNALS__;
const MAX_CODES = __MAX_CODES__;
const CUSTOM = '__custom__';

let config = { screenings: [], defaults_reviewed: false, defaults_current_as_of: '' };
let CATALOG = { sources: [], value_sets: [], order_commands: [] };
// Order codes this practice's own catalogs do not carry. An unresolvable
// code stages an order with every field empty, and it does it silently.
let UNRESOLVABLE = [];
let VSBYKEY = {};

const ICON_TRASH = '<svg class="ic" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
const ICON_WARN = '<svg class="ic" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11 15h2v2h-2zm0-8h2v6h-2zm.99-5C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"/></svg>';

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
function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
// "a imaging report" reads as a bug in a page whose whole job is to let a
// non-developer check the rule says what they meant.
function article(word) { return /^[aeiou]/i.test(word) ? 'an ' : 'a '; }

async function load() {
  try {
    const res = await (await fetch(BASE + '/admin/config')).json();
    if (res.config) config = res.config;
    if (res.catalog) CATALOG = res.catalog;
    UNRESOLVABLE = res.unresolvable_order_codes || [];
  } catch (e) { setStatus('Could not load the saved screenings.', 'err'); }

  VSBYKEY = {};
  (CATALOG.value_sets || []).forEach(v => { VSBYKEY[v.key] = v; });
  if (!Array.isArray(config.screenings)) config.screenings = [];

  const banner = document.getElementById('defaults-banner');
  banner.hidden = !!config.defaults_reviewed;
  document.getElementById('defaults-date').textContent = config.defaults_current_as_of || 'an unknown date';
  render();
}
document.addEventListener('DOMContentLoaded', load);

function newSignal() {
  return { value_set_key: '', source: 'procedure', codes: [], label: '',
           interval_quantity: 1, interval_unit: 'years' };
}
function newScreening() {
  return {
    id: 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
    enabled: false, protocol_card: false, name: 'New screening', sex: 'any', min_age: 18, max_age: 0,
    grace_days: 90, completions: [newSignal()], exclusions: [],
    order_command: '', order_button: '', order_code: '', order_comment: '', guidance: ''
  };
}

// --- option builders ---------------------------------------------------------

function vsOptions(selected, forCustom) {
  let html = '';
  (CATALOG.value_sets || []).forEach(v => {
    html += '<option value="' + esc(v.key) + '"' + (v.key === selected ? ' selected' : '') + '>' + esc(v.label) + '</option>';
  });
  html += '<option value="' + CUSTOM + '"' + (forCustom ? ' selected' : '') + '>Custom codes\\u2026</option>';
  return html;
}
function srcOptions(selected) {
  return (CATALOG.sources || []).map(s =>
    '<option value="' + esc(s.key) + '"' + (s.key === selected ? ' selected' : '') + '>' + esc(s.label) + '</option>'
  ).join('');
}
function cmdOptions(selected) {
  let html = '<option value="">No order button</option>';
  (CATALOG.order_commands || []).forEach(c => {
    html += '<option value="' + esc(c.key) + '"' + (c.key === selected ? ' selected' : '') + '>' + esc(c.label) + '</option>';
  });
  return html;
}
function unitOptions(selected) {
  return ['months', 'years'].map(u =>
    '<option value="' + u + '"' + (u === selected ? ' selected' : '') + '>' + u + '</option>'
  ).join('');
}
function sexOptions(selected) {
  return [['any', 'all patients'], ['female', 'women'], ['male', 'men']].map(p =>
    '<option value="' + p[0] + '"' + (p[0] === selected ? ' selected' : '') + '>' + p[1] + '</option>'
  ).join('');
}

// --- rendering ---------------------------------------------------------------

function signalRow(i, j, sig, kind) {
  const isCustom = !sig.value_set_key;
  const interval = kind === 'completions'
    ? '<span class="txt">for</span>' +
      '<input class="num" type="number" min="1" value="' + esc(sig.interval_quantity) + '" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '" data-field="interval_quantity">' +
      '<select class="sel" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '" data-field="interval_unit">' + unitOptions(sig.interval_unit) + '</select>' +
      '<span class="txt">after</span>'
    : '';
  let html = '<div class="row">' + interval +
    '<select class="sel" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '" data-field="value_set_key">' +
      vsOptions(sig.value_set_key, isCustom) + '</select>';
  if (isCustom) {
    html += '<input class="txtin" placeholder="What to call it" value="' + esc(sig.label) + '" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '" data-field="label">' +
      '<span class="txt">found in a</span>' +
      '<select class="sel" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '" data-field="source">' + srcOptions(sig.source) + '</select>' +
      '<input class="txtin" placeholder="Codes, comma separated" value="' + esc((sig.codes || []).join(', ')) + '" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '" data-field="codes">';
  }
  html += '<button class="icon-btn danger" title="Remove" data-act="del-signal" data-i="' + i + '" data-j="' + j + '" data-kind="' + kind + '">' + ICON_TRASH + '</button>';
  if (!isCustom) html += vsWhat(sig.value_set_key);
  return html + '</div>';
}

// What a catalog entry actually matches: which codes, and which chart records
// they are looked for in. Until 2026-09-22 none of this reached the page, so a
// mammogram recorded as a procedure silently failed to count and the only way
// to find out was to record one and watch the card not move.
function vsWhat(key) {
  const v = VSBYKEY[key];
  if (!v) return '';
  const systems = v.systems || {};
  const names = Object.keys(systems);
  if (!names.length) return '';
  const total = names.reduce((n, sys) => n + systems[sys].length, 0);
  const where = (v.sources || [v.source]).map(sk => {
    const src = (CATALOG.sources || []).find(x => x.key === sk);
    return src ? src.label : sk;
  });
  const whereText = where.length === 1 ? where[0]
    : where.slice(0, -1).join(', ') + ' or ' + where[where.length - 1];
  let body = '';
  names.forEach(sys => {
    body += '<div><b>' + esc(sys) + '</b> <span>' + esc(systems[sys].join(', ')) + '</span></div>';
  });
  return '<details class="vswhat"><summary>Counts when any of ' + plural(total, 'code') +
    ' appears in ' + article(whereText) + esc(whereText) + '</summary>' +
    '<div class="vscodes">' + body + '</div></details>';
}

function summarize(s) {
  const who = { female: 'Women', male: 'Men' }[s.sex] || 'Patients';
  const ages = s.max_age ? 'aged ' + s.min_age + ' to ' + s.max_age : 'aged ' + s.min_age + ' and over';
  const parts = (s.completions || []).map(sig => {
    const label = sig.value_set_key ? (VSBYKEY[sig.value_set_key] || {}).label : (sig.label || 'a recorded result');
    return plural(sig.interval_quantity, sig.interval_unit.replace(/s$/, '')) + ' after ' + String(label).toLowerCase();
  });
  if (!parts.length) return who + ' ' + ages + ' \\u2014 no completion signal set, so this can never read as done.';
  const covers = parts.length === 1 ? parts[0] : parts.slice(0, -1).join(', ') + ', or ' + parts[parts.length - 1];
  // Say where it shows up, because that is the thing the Chart card box
  // changes and it is not obvious from the box alone.
  const where = s.protocol_card
    ? ' Shown as a protocol card on the chart and in the screening record beside it.'
    : ' Shown in the screening record beside the chart, not as a protocol card.';
  return who + ' ' + ages + ' \\u2014 due ' + covers + '; overdue after a further ' +
    plural(s.grace_days, 'day') + '.' + (s.enabled ? where : '');
}

function warnings(s) {
  const out = [];
  if (!(s.completions || []).length) out.push('Nothing counts as done, so this screening would show as due forever. Add a completion signal.');
  (s.completions || []).forEach(sig => {
    if (!sig.value_set_key && !(sig.codes || []).length) out.push('A completion signal has no value set and no codes, so it matches nothing and will be dropped on save.');
    if (sig.value_set_key && !VSBYKEY[sig.value_set_key]) out.push('A completion signal points at "' + sig.value_set_key + '", which this version does not ship.');
  });
  (s.exclusions || []).forEach(sig => {
    if (!sig.value_set_key && !(sig.codes || []).length) out.push('An exclusion has no value set and no codes, so it excludes nobody and will be dropped on save.');
  });
  if (s.max_age && s.max_age < s.min_age) out.push('The upper age is below the lower age, so this screening applies to nobody.');
  // Only when the card is on: the one-click order button lives on the card,
  // so a tracked screening without one is a complete configuration.
  if (s.protocol_card && !s.order_command) out.push('No order command is set, so the card will show the recommendation without a button to act on it.');
  if (s.order_code && UNRESOLVABLE.indexOf(s.order_code) !== -1) {
    out.push('The order code "' + s.order_code + '" matches nothing in this practice\u2019s order catalog, so the button will open an order with every field blank. Check it against what the picker offers for this command \u2014 an imaging or Perform order resolves against CPT, not LOINC.');
  }
  return out;
}

function render() {
  const host = document.getElementById('screenings');
  if (!config.screenings.length) {
    host.innerHTML = '<div class="empty">No screenings yet. Add one to start showing protocol cards when a chart opens.</div>';
    return;
  }
  host.innerHTML = config.screenings.map((s, i) => {
    const cmd = (CATALOG.order_commands || []).find(c => c.key === s.order_command);
    const warn = warnings(s);
    return '' +
    '<div class="scr' + (s.enabled ? '' : ' off') + '">' +
      '<div class="scr-head">' +
        '<label class="toggle"><input type="checkbox"' + (s.enabled ? ' checked' : '') +
          ' data-i="' + i + '" data-field="enabled">' + (s.enabled ? 'On' : 'Off') + '</label>' +
        '<input class="name" value="' + esc(s.name) + '" data-i="' + i + '" data-field="name" aria-label="Screening name">' +
        // Separate from On/Off, because they answer different questions: On
        // decides whether the practice tracks the screening at all, this
        // decides whether it also pushes a card onto the chart summary. The
        // record app beside the chart shows a tracked screening either way.
        '<label class="toggle" title="Also show this screening as a protocol card on the chart summary">' +
          '<input type="checkbox"' + (s.protocol_card ? ' checked' : '') + (s.enabled ? '' : ' disabled') +
          ' data-i="' + i + '" data-field="protocol_card">Chart card</label>' +
        '<button class="icon-btn danger" title="Remove screening" data-act="del-screening" data-i="' + i + '">' + ICON_TRASH + '</button>' +
      '</div>' +

      '<div class="grp"><div class="grp-label">Who it applies to</div><div class="row">' +
        '<span class="txt">Screen</span>' +
        '<select class="sel" data-i="' + i + '" data-field="sex">' + sexOptions(s.sex) + '</select>' +
        '<span class="txt">aged</span>' +
        '<input class="num" type="number" min="0" value="' + esc(s.min_age) + '" data-i="' + i + '" data-field="min_age">' +
        '<span class="txt">up to and including</span>' +
        '<input class="num" type="number" min="0" value="' + esc(s.max_age) + '" data-i="' + i + '" data-field="max_age">' +
        '<span class="txt">(0 = no upper limit).</span>' +
      '</div></div>' +

      '<div class="grp"><div class="grp-label">Counts as done</div>' +
        (s.completions || []).map((sig, j) => signalRow(i, j, sig, 'completions')).join('') +
        ((s.completions || []).length < MAX_SIGNALS
          ? '<button class="btn-add" data-act="add-signal" data-i="' + i + '" data-kind="completions">+ Another way this can be done</button>' : '') +
      '</div>' +

      '<div class="grp"><div class="grp-label">Overdue</div><div class="row">' +
        '<span class="txt">Reads as overdue once it has been due for</span>' +
        '<input class="num" type="number" min="0" value="' + esc(s.grace_days) + '" data-i="' + i + '" data-field="grace_days">' +
        '<span class="txt">days.</span>' +
      '</div></div>' +

      '<div class="grp"><div class="grp-label">Never show if the patient has</div>' +
        (s.exclusions || []).map((sig, j) => signalRow(i, j, sig, 'exclusions')).join('') +
        ((s.exclusions || []).length < MAX_SIGNALS
          ? '<button class="btn-add" data-act="add-signal" data-i="' + i + '" data-kind="exclusions">+ Add an exclusion</button>' : '') +
      '</div>' +

      '<div class="grp"><div class="grp-label">One-click order</div><div class="row">' +
        '<span class="txt">Offer</span>' +
        '<select class="sel" data-i="' + i + '" data-field="order_command">' + cmdOptions(s.order_command) + '</select>' +
        (cmd && cmd.takes_code
          ? '<span class="txt">pre-filled with code</span><input class="txtin" placeholder="e.g. 24606-6" value="' + esc(s.order_code) + '" data-i="' + i + '" data-field="order_code">'
          : '') +
        (s.order_command
          ? '<span class="txt">labelled</span><input class="txtin" placeholder="Button text" value="' + esc(s.order_button) + '" data-i="' + i + '" data-field="order_button">'
          : '') +
      '</div></div>' +

      '<div class="summary">' + esc(summarize(s)) + '</div>' +
      (warn.length ? '<div class="grp">' + warn.map(w => '<div class="flag">' + ICON_WARN + esc(w) + '</div>').join('') + '</div>' : '') +
    '</div>';
  }).join('');
}

// --- events ------------------------------------------------------------------

function setField(target) {
  const i = parseInt(target.dataset.i, 10);
  const field = target.dataset.field;
  if (isNaN(i) || !field) return false;
  const kind = target.dataset.kind;
  const j = parseInt(target.dataset.j, 10);
  const owner = kind ? config.screenings[i][kind][j] : config.screenings[i];
  let rerender = false;

  if (field === 'enabled') {
    owner.enabled = target.checked;
    // A screening that is off cannot be carded. Leaving a stale checked box
    // behind would save a document saying "do not track this, and put it on
    // every chart", which carded_screenings would read as off anyway - so the
    // form would be describing something the plugin does not do.
    if (!owner.enabled) owner.protocol_card = false;
    rerender = true;
  }
  else if (field === 'protocol_card') { owner.protocol_card = target.checked; rerender = true; }
  else if (field === 'codes') { owner.codes = target.value.split(',').map(c => c.trim()).filter(Boolean).slice(0, MAX_CODES); }
  else if (field === 'value_set_key') {
    owner.value_set_key = target.value === CUSTOM ? '' : target.value;
    // Picking a catalog entry adopts its source, so the two can never disagree.
    if (owner.value_set_key && VSBYKEY[owner.value_set_key]) owner.source = VSBYKEY[owner.value_set_key].source;
    rerender = true;
  }
  else if (['name', 'sex', 'source', 'label', 'order_command', 'order_button', 'order_code'].indexOf(field) !== -1) {
    owner[field] = target.value;
    rerender = (field === 'sex' || field === 'order_command');
  }
  else {
    const n = parseInt(target.value, 10);
    owner[field] = isNaN(n) ? 0 : n;
  }
  return rerender;
}

document.addEventListener('change', e => {
  const t = e.target;
  if (!t.dataset || !t.dataset.field) return;
  if (setField(t)) render(); else refreshSummary(t);
});
document.addEventListener('input', e => {
  const t = e.target;
  if (!t.dataset || !t.dataset.field) return;
  if (t.tagName === 'SELECT' || t.type === 'checkbox') return;
  setField(t);
  refreshSummary(t);
});

// Keep the plain-English summary live without re-rendering the whole card,
// which would steal focus from the field being typed in.
function refreshSummary(target) {
  const i = parseInt(target.dataset.i, 10);
  if (isNaN(i)) return;
  const card = document.querySelectorAll('#screenings .scr')[i];
  if (!card) return;
  const el = card.querySelector('.summary');
  if (el) el.textContent = summarize(config.screenings[i]);
}

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  const i = parseInt(btn.dataset.i, 10);
  const j = parseInt(btn.dataset.j, 10);
  const kind = btn.dataset.kind;

  if (act === 'save') { save(); return; }
  if (act === 'dismiss') {
    config.defaults_reviewed = true;
    document.getElementById('defaults-banner').hidden = true;
    return;
  }
  if (act === 'add-screening') {
    if (config.screenings.length >= MAX_SCREENINGS) {
      setStatus('At most ' + MAX_SCREENINGS + ' screenings can be configured.', 'err');
      return;
    }
    config.screenings.push(newScreening());
    render();
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    return;
  }
  if (act === 'del-screening') { config.screenings.splice(i, 1); render(); return; }
  if (act === 'add-signal') {
    const list = config.screenings[i][kind];
    if (list.length < MAX_SIGNALS) { list.push(newSignal()); render(); }
    return;
  }
  if (act === 'del-signal') { config.screenings[i][kind].splice(j, 1); render(); return; }
});

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
    "<p>You do not have access to Preventive Screenings. Ask an administrator to add "
    "your staff key to the plugin's ADMIN_STAFF_KEYS setting.</p>"
    "</div></body></html>"
)
