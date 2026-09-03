# Note Protocol Automation

A Canvas plugin that automatically inserts a configured set of blank commands
into a note the moment it is created, based on the note's type and the patient's
clinical parameters. An admin defines the rules once in a global configuration
UI; from then on, every matching note opens pre-populated with the right
commands already staged.

## What it does

When a note is first created, the plugin looks up the note's type, evaluates the
rules an admin has configured for that type against the patient's data
(conditions, age, sex, recent lab values, care-team roles), and inserts the
commands those matching rules call for as blank, staged commands in the note.
The provider then fills them in — they never have to remember which commands a
given visit type requires. Commands are inserted exactly once, at note creation,
and never re-inserted when the note is later signed or edited. If anything goes
wrong, the plugin fails silently and never blocks note creation.

## Problem it solves

Many visit types have an implicit "protocol" — a standard set of commands a
provider is expected to complete (for example, a chronic-disease visit that
always needs a Diagnose, an Assess, a Plan, and a Goal). Today providers add
each of these by hand on every note, which is slow, easy to forget, and
inconsistent from one provider to the next. This plugin turns that implicit
protocol into an explicit, configurable rule so the right commands appear
automatically, and so the protocol can be tuned by patient context (e.g. only
add a lab-order command when a relevant lab value is out of range or stale).

## Who it's for

- **Clinic administrators / clinical informaticists** who want to standardize
  documentation for specific visit types across all providers.
- **Care teams in any specialty** with repeatable, note-type-driven workflows
  (primary care, chronic-care management, specialty visits) where the same set
  of commands is expected on every note of a given type.

## How to install

1. Install the plugin into your Canvas instance:

   ```bash
   canvas install note_protocol_automation
   ```

2. Open the global admin application named **Note Protocols** (it appears as a
   global menu item). This launches the rule-authoring UI as a full page.

3. Create one or more rules (see Configuration options below). Rules take effect
   on the next note created of the matching type — no redeploy needed.

The configuration UI is staff-session authenticated AND admin-gated: only staff
whose ids are listed in the `ADMIN_STAFF_IDS` secret can open or use it (see
below). The plugin requires no external services.

## Configuration options

All configuration is done in the **Note Protocols** admin UI — no code changes
required. Rules are stored durably in the plugin's own custom-data table
(namespace `custom_data__note_protocol_automation`).

### `ADMIN_STAFF_IDS` (required secret)

Because these rules auto-insert commands into every matching note, the entire
config surface is restricted to an explicit allow-list of administrators. Set the
plugin secret `ADMIN_STAFF_IDS` to a comma-separated list of the staff ids
allowed to manage rules (for example `a1b2c3...,d4e5f6...`). Dashed or undashed
UUID forms are both accepted.

This gate is **fail-closed**: if `ADMIN_STAFF_IDS` is unset or empty, the admin
app is denied to everyone — every rules/note-types request returns `403 Forbidden`
and a warning is logged, so the UI loads but can neither read nor write any rules.
You must set this secret before anyone can use the Note Protocols app.

Each rule has:

- **Name** — a human-readable label.
- **Note type** — which note type the rule applies to (chosen from the
  instance's active note types).
- **Enabled** — a toggle to activate or deactivate the rule without deleting it.
- **Priority** — rules are evaluated in priority order; when several rules match,
  their command lists are merged in priority then list order, first occurrence
  wins.
- **Predicate combinator** — how a rule's predicates combine, chosen per rule
  and defaulting to **all**: **all** (AND) fires the rule only when every
  predicate is true, while **any** (OR) fires it when at least one predicate is
  true.
- **Predicates** — zero or more conditions evaluated for the rule, combined via
  the combinator above (all of them, or any of them). Each predicate is a
  `(signal, operator, value)` triple over one of these patient signals:
  - **Condition (ICD-10)** — `starts with` / `equals` / `does not have` a code.
  - **Age** — `>=`, `<=`, `==`, or `between` two bounds (whole years).
  - **Sex** — equals one of Female / Male / Other / Unknown (sex at birth).
  - **Lab value** — a lab chosen from a curated list of common labs (each mapped
    to its LOINC) compared with `<`, `<=`, `>`, `>=`, `==` against a threshold,
    optionally restricted to results within N days. Only final, committed,
    non-junked, non-errored lab reports are considered.
  - **Care team role** — the patient's active care team includes a given role
    code.

  A rule with no predicates and the **all** combinator matches every note of its
  chosen type; with the **any** combinator a no-predicate rule never fires.
- **Commands to insert (in order)** — the ordered list of commands to stage.
  Available commands: Diagnose, Assess, Plan, Goal, HPI, Reason for Visit, Lab
  Order, Medication Statement, Allergy, Immunization.

## Screenshots

> **TODO:** Add screenshots of the config UI and an auto-inserted command set
> before publishing.

## Privacy

The plugin never logs patient data. Signal gathering reads only the minimal
columns it needs and only for the signals a candidate rule actually references.
The configuration UI is a global admin surface and takes no patient parameter.
