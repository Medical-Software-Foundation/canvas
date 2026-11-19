// Assert the pairing editor stops adding rules at MAX_RULES and says so.
//
// Run it through the driver, which extracts the page's <script> for you:
//     uv run python scripts/check_admin_page.py
// Or directly, against an already-extracted script:
//     node scripts/cap_check.js /tmp/admin_page.js
//
// The limit is read from the page itself (services/config_store.py substitutes it), so
// this stays correct when MAX_RULES changes. Exits non-zero if the cap does not hold.

const fs = require('fs');

// Minimal DOM: the page only ever calls getElementById and sets innerHTML/textContent.
const els = {};
const el = (id) => (els[id] ||= { id, innerHTML: '', textContent: '', className: '', hidden: false });
global.document = { getElementById: el, addEventListener() {}, body: { scrollHeight: 0 } };
global.window = { scrollTo() {} };

eval(
  fs.readFileSync(process.argv[2], 'utf8') +
    `
globalThis.__cap = MAX_RULES;
for (let i = 0; i < MAX_RULES + 10; i++) addRule();
globalThis.__count = config.rules.length;
globalThis.__comparator = config.rules[0].comparator;
globalThis.__known = COMPARATORS;
`
);

const cap = globalThis.__cap;
const expected = 'At most ' + cap + ' pairings can be configured.';
const result = {
  cap,
  rules: globalThis.__count,
  status: els.status.textContent,
  className: els.status.className,
  newRuleComparator: globalThis.__comparator,
};
const ok =
  Number.isInteger(cap) &&
  result.rules === cap &&
  result.status === expected &&
  result.className === 'err' &&
  // A rule the editor creates must carry a score rule the server will accept.
  globalThis.__known.includes(result.newRuleComparator);

console.log(result);
process.exit(ok ? 0 : 1);
