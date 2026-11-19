# Supervisor Co-sign

## What it does

Supervisor co-signature workflow. When a supervisee locks a note, this plugin
creates a co-sign task for that provider's supervisor and, for that supervisor
only, replaces the note footer's **Sign** with **Co-sign**. The supervisor picks an attestation template,
edits it if they want, and approves; the attestation lands on the chart as an
`attestation_review` custom command and the task closes. A provider-menu
summary page shows the same work across a whole team, with inline co-signing.

The supervisor for a note is the supervising provider set on the note itself.
When the note has none, it falls back to Canvas's native
`Staff.default_supervising_provider` field on the note's provider, set per-staff
in Canvas admin. The plugin maintains no roster of its own. If neither is set,
the locked note is ignored silently (the skip is logged).

## Problem it solves

Canvas records a second signature on a note, but a signature alone does not say
what the supervisor attested to, and nothing tells a supervisor which of their
supervisees' notes still need review. This plugin gives each supervisor a
worklist of notes owed a co-sign, puts a single **Co-sign** action where they
would otherwise click **Sign**, and saves a written attestation on the chart
with who signed it and when.

## Who it's for

Practices where residents, NPs, PAs, or other supervised clinicians need an
attending attestation on their documentation, and where somebody has to prove
later that the attestation happened.

## How to install

```bash
canvas install supervisor_cosign
```

The plugin stores its records in the `supervisor__cosign` custom data namespace,
so the install needs the namespace access keys (`namespace_read_access_key` and
`namespace_read_write_access_key`). Without them the models fail to load.

Each supervised provider needs a supervisor: either the supervising provider on
the note, or `Default supervising provider` on the provider's Staff record in
Canvas admin. The footer Co-sign button needs Canvas to send
`NOTE_FOOTER__GET_CONFIGURATION` (SDK 0.179.0 and later).

## How it works

1. A supervisee signs their note, which produces a `NOTE_STATE_CHANGE_EVENT`
   with state `LOCKED`.
2. Note-type gate: if `COSIGN_NOTE_TYPE_CODES` is set and this note's type
   isn't on it, the handler stops. Unset means every type passes.
3. `NoteLockHandler` reads the note's `supervising_provider`, falling back to
   the note provider's `default_supervising_provider`. No supervisor, no work.
4. If the note already has a pending `CoSignRecord`, the handler stops. If
   its latest record is approved, the handler stops unless
   `COSIGN_REOPEN_ON_AMEND` is on and the supervisee is the one locking it,
   meaning they amended and re-signed a co-signed note; that reopens the
   co-sign with a new pending record and a task titled "Co-sign review
   (amended)". Re-locks by anyone else, including the one this plugin causes
   when it writes the attestation and a billing plugin adding a charge, leave
   the note approved. With the setting off (the default), a co-signed note
   stays approved through any amendment.
5. Sampling gate: `SAMPLE_PERCENTAGE` decides whether this note gets picked.
   At `100` every eligible note is selected. A reopened note skips the draw,
   since it was already selected once.
6. The handler writes a `CoSignRecord` with status `pending` and a 3-day due
   date, then emits an `AddTask` assigned to the supervisor, labeled
   `cosign`, titled with the note date and patient name, plus a comment
   linking the note itself (see below). With `COSIGN_CREATE_TASKS` set to
   `false` the record is written and no task or comment is emitted.
7. The supervisor on a pending record sees **Co-sign** in the note footer in
   place of **Sign** (see below). Nobody else sees it, and it goes away once
   the co-sign is approved.
8. Clicking it opens a modal listing prior attestations for that note plus
   the template picker and two text areas. The same attestation
   form is available inline on the summary page.
9. `POST /cosign/<note_id>/` verifies the caller is the supervisor named on
   the record, writes the attestation to the chart, flips the record to
   `approved`, comments on the task and completes it, appends a
   `CoSignAddendum` row, and reloads the note's buttons so the open chart
   gets its native footer back.

Only the supervisor on the record can submit. Anyone else gets a 403, logged
with both ids so the mismatch is diagnosable.

## Co-sign replaces Sign in the footer

A supervisor viewing a locked or signed note that has a pending record naming
them doesn't get Canvas's native footer state buttons. `CoSignFooterConfiguration` answers
`NOTE_FOOTER__GET_CONFIGURATION` with `hide_default_state_buttons`, and two
plugin footer buttons take their place:

| Button | Replaces | Does |
|---|---|---|
| **Co-sign** (green, first) | native **Sign** | Opens the attestation modal |
| **Amend** / **Unlock** | native **Amend** / **Unlock** | Unlocks the note; reads **Amend** on a signed signature-required note, as native does |

From a locked or signed note the native footer offers only Sign and
Amend/Unlock, so nothing else is lost. Once the record is approved the native
footer returns. An unlocked note keeps the native footer, so whoever is editing
it can still lock or sign it. The supervisee, other staff, and the supervisor on their own
notes keep the native footer throughout.

Hiding is per viewer and per note, so it needs Canvas to send
`NOTE_FOOTER__GET_CONFIGURATION` (SDK 0.179.0 and later).

## Attestation templates

Four choices in the modal, three of which prefill text the supervisor can then
edit freely:

| Key | Text |
|-----|------|
| `teaching` | "I was present for and participated in the critical and key portions of the examination and agree with *{supervisee}*'s findings and treatment plan." |
| `reviewed` | "I have reviewed *{supervisee}*'s documentation and agree with the assessment, findings, and plan as documented." |
| `personally_performed` | "I personally performed the service. I have reviewed and agree with the documentation." |
| `custom` | Empty. Write your own. |

**Reviewed & agree** is pre-selected in both attestation UIs and is the
server-side fallback when a request omits the field. The teaching-physician
attestation claims presence for the key portions of the examination, which
should be a deliberate choice rather than what you get by not choosing. The
menu order stays clinical, so the default is the second entry, not the first.

Whatever text is in the textarea at submit time wins. The server only falls
back to the canonical template string when the textarea came in empty, so an
edited teaching-physician attestation is saved as edited rather than being
quietly reverted to boilerplate. Submitting with nothing in the box returns a
400.

The saved attestation always ends with `Co-signed by <credentialed name> on
<timestamp> UTC`, appended server-side. Supervisors can't remove it.

The manifest puts the `attestation_review` command in the `plan` section. A
custom command declared without a section lands in `internal`, which Canvas's
note printouts never render, so the attestation would show in the chart but be
missing from **Print note** and from the PDF saved when the note is signed.

## Which notes enter the flow

`COSIGN_NOTE_TYPE_CODES` holds a list of `NoteType` codes, either as a JSON
array or comma-separated; these two are equivalent:

```
["office_visit", "follow_up", "new_patient_eval"]
office_visit, follow_up, new_patient_eval
```

Matching is case- and separator-insensitive, so `Office Visit`, `office_visit`
and `officevisit` are the same value, but it is exact after normalizing:
`visit` will not match `officevisit`. A note type with no code is matched on its
name instead.

Leave it unset and every note type is eligible, which is the behavior before
the filter existed. That polarity is the opposite of
`COSIGN_OVERSIGHT_STAFF_IDS`, where unset means nobody.

The check runs before the supervisor lookup, before the dedup query and before
the sampling draw. Type first because it is a string compare against a row
already loaded and it keeps the "provider X has supervisor Y" log line from
firing on a message note; sampling last because it is the only nondeterministic
gate, so "why wasn't this note picked?" stays answerable by elimination.

## Linking the task to its note

The task's comment carries two links:

```
Note type: Encounter Note - 2026-09-20
Open the note: /patient/<patient key>?noteId=<note dbid>
Co-sign from the summary page: /plugin-io/api/supervisor_cosign/summary/view?note=<note uuid>
```

`/patient/<key>?noteId=<dbid>` is the only note deep link known to resolve in
Canvas, and it takes the note's **integer `dbid`, not its UUID** — a UUID there
loads the chart and silently ignores the note. `helpers/note_links.py` owns both
builders, and either returns `""` rather than a half-built URL when an input is
missing, so a note with no patient still produces a task.

The links live in the comment rather than the title on purpose. `AddTask` has no
body field and its `linked_object_type` accepts only `REFERRAL` and `IMAGING`, so
a comment is the only place a URL can go, and a bare identifier with nowhere to
click is hard to act on. The comment names the task id the handler mints itself, which is what lets it
reference a task Canvas has not created yet; effects apply in order.

Canvas's own note↔task relation (`NoteTask`, written by originating a
`TaskCommand` inside the note) was considered and rejected: the note is locked
when the task is created, so it would need an unlock/re-sign round trip on the
supervisee's chart before the supervisor had done anything.

## Summary page

A provider-menu item, **Co-sign Summary**, opens a page listing co-sign status
across a supervisor's team, with per-supervisee compliance percentages along the
top. Clicking **Co-sign** on a row expands an attestation form underneath it and
posts to the same endpoint the footer modal uses, so a supervisor can clear
a backlog without opening each chart.

Two views, switched by the **View** control:

- **Co-sign records** — the `CoSignRecord` rows, i.e. exactly what needs
  attesting and what is already done.
- **All supervisee notes** — the notes themselves, so you can see the
  denominator. Drafts, unlocked, locked and signed all appear; deleted notes
  never do; cancelled and no-show bookings are behind a checkbox, as are
  non-clinical note types. A Canvas `Note` is also the row behind appointments,
  messages and data imports, so without those exclusions the list is mostly
  appointment stubs.

The list pages 50 at a time, with Prev/Next and a `Showing 51-100 of 243`
count. The compliance percentages across the top are computed over the whole
filtered set, not the visible page, so they do not move as you page; in the
all-notes view the approved/pending split is capped at the first 2,000 notes
and says so when the cap bites, because `CoSignRecord.note_id` is a TextField
with no ForeignKey and the split cannot be done in SQL.

Each row's date links straight into that note in the chart. Opening the page
with `?note=<uuid>` — which is what the task comment links to — expands that
note's attestation form on load, and says so plainly if the note falls outside
the current date window or filters rather than showing a list that quietly
omits it.

The two views range over different date fields — a record's `selected_at`
against a note's `datetime_of_service` — so the date label changes with the
view. The same range gives different row sets, by design.

Who sees it:

| Viewer | Gets |
|---|---|
| Supervises at least one active staff member | The page, scoped to their own supervisees |
| Listed in `COSIGN_OVERSIGHT_STAFF_IDS` | The page, all supervisors, with supervisor and supervisee filters |
| Neither | A neutral placeholder page; the JSON routes return 403 |

"Supervises somebody" is derived from `Staff.default_supervising_provider`, or
from being the supervisor on any `CoSignRecord` (a note-level supervising
provider), not configured, so it stays correct as admin changes pairings. A
`provider_menu_item` application has no `visible()` hook, so the menu entry
itself cannot be hidden — every staff member sees the label and some will click
it. The placeholder is the courtesy; the 403 on `/summary/data` is the boundary.

Oversight viewers can read everything and co-sign nothing. Attestation is tied
to the named supervisor on the record, and `POST /cosign/<note_id>/` enforces
that independently of the page.

## Why the note gets unlocked and re-signed

A locked note won't accept a new command, so `submit_cosign` emits a chain of
four effects: `NoteEffect.unlock()`, then `CustomCommand.originate()`, then
raw `LOCK_NOTE` and `SIGN_NOTE` effects.

The last two are constructed by hand rather than through the SDK builders on
purpose. SDK builders validate against current DB state at construct time, but
effects only apply in order at runtime, so the builders reject a lock on a note
that is (at construct time) still locked. Building the `Effect` directly
sidesteps a check that's asking the wrong question.

`CustomCommand` supports originate only. There's no
`COMMIT_CUSTOM_COMMAND_COMMAND` effect type in the proto, so origination is
final for this command and there's no separate commit step.

All four effects are constructed inside a `try` **before** any database write.
If construction raises (an instance with "only the provider can sign/unlock"
enabled will do it), the endpoint returns 500 with nothing persisted. Get that
ordering backwards and you'd strand a record at `approved` with an OPEN task
and no retry path, since the retry filters on `status="pending"`.

## Configuration options

| Secret | Default | Meaning |
|--------|---------|---------|
| `SAMPLE_PERCENTAGE` | `100` | Percent of eligible locked notes selected for co-sign. Clamped to 0–100; unparseable values fall back to 100. |
| `COSIGN_NOTE_TYPE_CODES` | unset | `NoteType` codes, as a JSON array or comma-separated, that may enter the flow. **Unset means every note type is eligible**, so installing this plugin changes nothing until you set it. |
| `COSIGN_REOPEN_ON_AMEND` | unset | `true`, `yes`, `on` or `1` reopens a co-signed note when its supervisee amends and re-signs it, with a new pending record and a "Co-sign review (amended)" task. Unset or any other value keeps a co-signed note approved through amendments. Whether an amendment needs a new co-sign is the practice's policy (for example, its prescriptive authority agreements), so it is off until the practice turns it on. |
| `COSIGN_CREATE_TASKS` | unset | `false`, `no`, `off` or `0` records eligible notes without creating a supervisor task. Those notes still appear on the summary page, and approving one clears it. Unset or any other value creates tasks. |
| `COSIGN_OVERSIGHT_STAFF_IDS` | unset | Staff ids that get the cross-team view on the summary page. Unset means nobody; `*` means everybody. |
| `namespace_read_access_key`, `namespace_read_write_access_key` | — | Required by any `custom_data` plugin. Without them `CustomModel` writes no-op silently. |

Set it below 100 for audit-style sampling rather than universal review. The
draw is per note, using `random.uniform`, so the actual rate on a small
number of notes will wander from the configured one.

Custom data namespace is `supervisor__cosign` with `read_write` access. Install
needs the namespace access keys or the models silently fail to load.

## Components

| Component | Purpose |
|-----------|---------|
| `protocols/note_lock_handler.py` | `NOTE_STATE_CHANGE_EVENT_CREATED` — selects locked notes, creates the record and the supervisor's task |
| `protocols/cosign_button.py` | `SHOW_NOTE_FOOTER_BUTTON` — the footer Co-sign button for the supervisor who owes the co-sign; launches the modal |
| `protocols/cosign_footer.py` | `NOTE_FOOTER__GET_CONFIGURATION` and `SHOW_NOTE_FOOTER_BUTTON` — hides the native footer and adds Amend/Unlock for that supervisor |
| `helpers/viewer_cosign.py` | Whether the viewing user is the supervisor on a pending record |
| `api/handlers.py` | `SimpleAPI`: co-sign submission and the compliance report |
| `templates/cosign_modal.html` | Modal UI: attestation history, template picker, submit |
| `applications/cosign_summary_app.py` | Provider-menu entry that opens the summary page |
| `api/summary.py` | `SimpleAPI`: the summary page, its CSS/JS, and its scoped JSON feed |
| `templates/cosign_summary.*` | The summary page shell, styles, and behavior |
| `helpers/note_type_codes.py` | Which note types enter the flow |
| `helpers/supervision.py` | Supervisor and supervisee resolution off the native pairing |
| `helpers/cosign_access.py`, `helpers/staff_allowlist.py` | Who may see the summary page |
| `helpers/summary_queries.py` | The two summary views, batched to a fixed query count |
| `helpers/note_links.py` | Chart and summary-page URLs for a note |
| `helpers/attestation_templates.py` | The attestation prose, single-sourced |
| `models/cosign_record.py` | `CoSignRecord` — one row per selected note |
| `models/cosign_addendum.py` | `CoSignAddendum` — append-only attestation log |

Both models store ids as `TextField`, not `ForeignKey`. FK `to_field="dbid"`
combined with `filter(fk__id=uuid)` is broken in `CustomModel`.

## API

Routes live under `/plugin-io/api/supervisor_cosign/`. Authentication requires
a logged-in Staff session.

**`POST /cosign/<note_id>/`** — body `{template, attestation_text,
additional_comments}`. Returns `{"status": "approved", "count": N}`. 404 when
no pending record exists for the note, 403 when the caller isn't the recorded
supervisor, 400 on empty attestation text.

**`GET /report/?start=YYYY-MM-DD&end=YYYY-MM-DD`** — returns per-supervisee
totals (`total`, `approved`, `pending`, `pct_cosigned`) plus the underlying
records. Scoped to the calling supervisor's own records; the date bounds use
`__date` lookups so an `end` of the 31st includes all of the 31st instead of
cutting off at midnight.

**`GET /summary/view`** — the summary page. Also serves `/summary/styles.css`
and `/summary/app.js`.

**`GET /summary/data?mode=records|notes&start=&end=&supervisor=&supervisee=`** —
the rows behind the page. Scope is applied from the caller before any parameter
is read: a plain supervisor is pinned to their own records and a `supervisor`
parameter naming somebody else is discarded. Results are bounded
to a 30-day default window and 200 rows (500 max), with `has_more` rather than a
`COUNT`.

**`GET /summary/filters`** — dropdown options, scoped the same way.

## Roadmap

- **Reassignment.** Only the named supervisor can co-sign. If one is on leave,
  there is no way to hand their queue to somebody else.
- **Aggregate-only oversight.** Oversight staff currently see individual rows,
  including patient names. A non-clinical compliance role arguably only needs the
  percentages.

## CANVAS_MANIFEST

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename file or class names.

The manifest's class paths are all `supervisor_cosign.*`, and the SimpleAPI
routes resolve under the plugin name too, so the directory has to stay named
`supervisor_cosign`.
