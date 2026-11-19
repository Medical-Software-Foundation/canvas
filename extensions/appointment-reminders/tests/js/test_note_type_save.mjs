// Executes the real enabled-flag logic from gatherNoteTypeReminders, extracted
// from the admin page. String-matching the template would not have caught the
// original bug: the shape was there, the values were wrong.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(
  new URL("../../appointment_reminders/handlers/notification_api.py", import.meta.url),
  "utf8",
);

// Pull the decision out of the page so the test tracks the shipped source.
const m = src.match(
  /var priorSaved = \(savedNoteTypeReminders\[nt\.id\] \|\| \{\}\)\[enabledKey\];\s*\n\s*var optedOut = ([^\n]+);\s*\n\s*if \(optedOut\) entry\[enabledKey\] = false;/,
);
assert.ok(m, "could not locate the enabled-flag logic — did the save path change?");
const optedOutExpr = m[1];

function save({ globalEnabled, checked, priorSaved }) {
  const savedNoteTypeReminders = { "nt-1": priorSaved === undefined ? {} : { reminders_enabled: priorSaved } };
  const nt = { id: "nt-1" };
  const enabledKey = "reminders_enabled";
  const enabledEl = { checked };
  const entry = {};
  const priorSavedVal = (savedNoteTypeReminders[nt.id] || {})[enabledKey];
  const optedOut = eval(optedOutExpr.replace(/priorSaved/g, "priorSavedVal"));
  if (optedOut) entry[enabledKey] = false;
  return entry;
}

// Global on, per-type on → inherit, so nothing is written.
assert.deepEqual(save({ globalEnabled: true, checked: true, priorSaved: undefined }), {},
  "an enabled visit type must write no key — absent means inherit");
assert.deepEqual(save({ globalEnabled: true, checked: true, priorSaved: true }), {},
  "a legacy explicit true must not be rewritten");

// Global on, per-type off → the one case that persists.
assert.deepEqual(save({ globalEnabled: true, checked: false, priorSaved: undefined }),
  { reminders_enabled: false }, "an opt-out must persist as exactly false");

// Global off: toggles are forced off in the UI, so read the stored value, not the DOM.
assert.deepEqual(save({ globalEnabled: false, checked: false, priorSaved: undefined }), {},
  "a globally-off campaign must not convert every visit type into an opt-out");
assert.deepEqual(save({ globalEnabled: false, checked: false, priorSaved: false }),
  { reminders_enabled: false }, "an existing opt-out survives a global-off save");

// The regression that matters: a Save that touches nothing changes nothing.
const before = { reminders_enabled: false };
const after = save({ globalEnabled: true, checked: false, priorSaved: false });
assert.deepEqual(after, before, "an untouched visit type must round-trip byte-identically");

// And nothing anywhere writes a hard true.
for (const g of [true, false]) for (const c of [true, false]) for (const p of [undefined, true, false]) {
  const out = save({ globalEnabled: g, checked: c, priorSaved: p });
  assert.notEqual(out.reminders_enabled, true,
    `wrote a hard true for global=${g} checked=${c} prior=${p}`);
}

console.log("all note-type save assertions passed");
