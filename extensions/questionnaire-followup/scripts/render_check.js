// Render the pairing editor's rule list in Node against a stubbed DOM, and assert the
// markup is well formed, every server-supplied value is escaped, and each score rule
// draws the sentence it should.
//
// Run it through the driver, which extracts the page's <script> for you:
//     uv run python scripts/check_admin_page.py
// Or directly, against an already-extracted script:
//     node scripts/render_check.js /tmp/admin_page.js
//
// Exits non-zero if any check fails. The page is a Python string served by SimpleAPI,
// so pytest only ever sees it as text; this is the only check of what it renders.

const fs = require('fs');

// Minimal DOM: the page only ever calls getElementById and sets innerHTML/textContent.
const els = {};
const el = (id) => (els[id] ||= { id, innerHTML: '', textContent: '', className: '', hidden: false });
global.document = { getElementById: el, addEventListener() {}, body: { scrollHeight: 0 } };
global.window = { scrollTo() {} };

eval(
  fs.readFileSync(process.argv[2], 'utf8') +
    `
QLIST = [{name: 'PHQ-9', code: '44249-1', can_originate_in_charting: false},
         {name: 'PHQ-2 <b>x</b>', code: '55758-7', can_originate_in_charting: true}];
QLIST.forEach(q => { QBYCODE[q.code] = q; });

const base = {
  id: 'x', enabled: true, name: 'Rule', trigger_code: '55758-7', followup_code: '44249-1',
  comparator: 'at_least', threshold: 3, threshold_max: 3,
  trigger_lookback_days: 30, suppression_days: 90
};
const renderOne = (extra) => {
  config.rules = [Object.assign({}, base, extra)];
  render();
  return els.rules.innerHTML;
};

globalThis.__out = {};

// Two rules at once: hostile names, a code the instance does not have, and a
// follow-up that cannot originate in charting.
config.rules = [
  Object.assign({}, base, {id: 'a', name: 'Dep "quoted" <img src=x onerror=alert(1)>'}),
  Object.assign({}, base, {id: 'b', name: 'Missing', trigger_code: '00000-0', followup_code: ''}),
];
render();
__out.escaping = els.rules.innerHTML;

// One render per score rule.
__out.atLeast   = renderOne({comparator: 'at_least', threshold: 3});
__out.atMost    = renderOne({comparator: 'at_most', threshold: 2});
__out.between   = renderOne({comparator: 'between', threshold: 10, threshold_max: 14});
__out.backwards = renderOne({comparator: 'between', threshold: 14, threshold_max: 10});
__out.completed = renderOne({comparator: 'completed'});
__out.unknown   = renderOne({comparator: 'sometime_soon'});
__out.vocabulary = COMPARATORS;
`
);

const out = globalThis.__out;
const html = out.escaping;
const count = (s, re) => (s.match(re) || []).length;
// Every rule draws a lookback and a suppression box; the rest are score boxes.
const nums = (s) => count(s, /<input class="num/g);

const checks = {
  'svg open == close': count(html, /<svg\b/g) === count(html, /<\/svg>/g),
  'div open == close': count(html, /<div\b/g) === count(html, /<\/div>/g),
  'delete icons (2 rules)': count(html, /M6 19c0 1\.1/g) === 2,
  'warning icons present': count(html, /M11 15h2v2h-2z/g) >= 3,
  // No icon font is loaded, so a leftover ligature span would render as a bare word.
  'no icon-font spans': !html.includes('material-icons'),
  'rule name escaped': !html.includes('<img') && html.includes('&lt;img src=x onerror=alert(1)&gt;'),
  'questionnaire name escaped': !html.includes('<b>x</b>') && html.includes('&lt;b&gt;x&lt;/b&gt;'),

  // The four score rules, and only those four.
  'vocabulary matches the server':
    JSON.stringify(out.vocabulary) === JSON.stringify(['at_least', 'at_most', 'between', 'completed']),
  'at least: one score box': nums(out.atLeast) === 3,
  'at most: one score box': nums(out.atMost) === 3,
  'at most is offered': out.atMost.includes('scores at most'),
  'between: two score boxes': nums(out.between) === 4,
  'between shows both ends': out.between.includes('value="10"') && out.between.includes('value="14"'),
  'completed: no score box': nums(out.completed) === 2,
  'completed reads as a sentence':
    out.completed.includes('is completed') && out.completed.includes('within the last'),

  // A backwards range is flagged and left inert, never silently swapped.
  'valid range is not flagged': !out.between.includes('runs backwards'),
  'backwards range flagged': out.backwards.includes('runs backwards'),
  'backwards range marks both boxes': count(out.backwards, /class="num bad"/g) === 2,
  'backwards range keeps the numbers as typed':
    out.backwards.includes('value="14"') && out.backwards.includes('value="10"'),

  // A score rule from a newer version stays selected, labelled and flagged.
  'unknown rule flagged': out.unknown.includes('does not recognize'),
  'unknown rule kept visible': out.unknown.includes('Unrecognized (sometime_soon)'),

  'stale wording gone': !out.atLeast.includes('on a screen from the last'),
};

console.log(checks);
process.exit(Object.values(checks).every(Boolean) ? 0 : 1);
