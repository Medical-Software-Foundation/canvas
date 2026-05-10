# nutrition_charting

A structured ADIME (Assessment, Diagnosis, Intervention, Monitoring/Evaluation) charting workflow for dieticians, plus a printable nutrition note styled like the Canvas home-app print convention.

## What it does

Adds a **Nutrition** tab alongside the standard Commands tab on any note type whose name contains the word "nutrition" (case-insensitive). The tab renders a single-page form organized by ADIME sections; each section's "Save" button writes the captured data to native Canvas commands on the same note (Vitals, StructuredAssessment, Plan, Goal, Refer, Instruct, FollowUp, Task) so it stays structured and queryable.

The Medical Chart Review section auto-populates from the patient's chart (age, sex, anthropometrics, active PMH, allergies, currently-taking nutrition-relevant medications, recent labs). A **Print Nutrition Note** button in the note header opens a printable HTML view styled to match Canvas's home-app print conventions.

## Problem it solves

Dieticians chart in ADIME format, not SOAP. Off-the-shelf tools (and most AI scribes) don't fit ADIME, so dieticians lose visit time fighting the form, lose structure when they fall back to free-text, and end up maintaining a paper or Word print workflow that's disconnected from the EHR.

This plugin gives them a guided, structured, ADIME-shaped charting experience inside Canvas — same place as the rest of the chart — with all the captured data landing as queryable Canvas commands, plus an in-product printable note that replaces the paper / Word workflow.

## Who it's for

- **Primary:** Registered dieticians (or any care-team member) who chart in ADIME format inside Canvas, on note types whose name contains `"nutrition"`.
- **Adjacent:** PA / NP / MD providers on multidisciplinary teams who consume the same notes — referrals, recommended labs, and follow-up scheduling all surface through native Canvas commands and stay visible to the rest of the care team.

## How it's organized

| Component | Type | Purpose |
|-----------|------|---------|
| `NutritionChartingApp` | `NoteApplication` | The "Nutrition" tab. Visible on note types whose name contains `"nutrition"`. |
| `PrintNutritionNoteButton` | `ActionButton` (NOTE_HEADER) | Opens the print modal. |
| `NutritionChartingAPI` | `SimpleAPI` | Form-state + auto-populate + per-section save handler. Staff-session auth only. |
| `PrintNutritionNoteAPI` | `SimpleAPI` | Renders the printable HTML. Staff session preferred; falls back to `simple-api-key` for non-session callers. |
| `NutritionChartingNoteLifecycle` | `BaseHandler` (`NOTE_STATE_CHANGE_EVENT_CREATED`) | Deletes the plugin's per-note `AttributeHub` row when a note transitions to `DELETED`. AttributeHub isn't FK-linked to Note, so without this hook deleted notes leave orphan form-state behind. |

**Custom data namespace:** `canvas__nutrition_charting` (read_write). Stores per-note form state, visit type (Initial / Follow-up), and the originated `command_uuid` map per section so resaves edit existing commands in place instead of duplicating. See `MIGRATIONS.md` for how to rename the namespace safely.

**Sections → emitted commands:**

| Section | Command(s) emitted |
|---------|-------------------|
| Medical Chart Review | `Vitals` (height / weight / BMI). Allergies / PMH / meds / labs render in the form + print but aren't re-emitted as commands. |
| Social and Diet History | `StructuredAssessment` |
| Dietary Intake | `StructuredAssessment` |
| Nutrition Focused Physical Exam (NFPE) | `StructuredAssessment` |
| Estimated Nutrition Requirements | `Plan` (formatted narrative) |
| Nutrition Diagnosis (PES) | `StructuredAssessment` |
| Educational Materials | `Instruct` per material, headed "Diet education" |
| Counseling Narrative | `Plan` |
| Goals | `Goal` per goal |
| Follow-up Appointment | `FollowUp` |
| Referrals | `Refer` per row (with provider, indications, clinical question, priority, etc.) |
| Recommended Labs | `Plan` (formatted bulleted list — see Known limitations below) |
| Recommended Supplementation | `Plan` |
| Monitor at Team Meeting | `Task` (gated by checkbox; deletes when unchecked on resave) |

## How to install

```bash
canvas install nutrition_charting/ --host <instance-name>
```

The plugin auto-detects which note types it applies to by keyword — no admin step required to register it on specific note types. The instance needs at least one note type whose name contains `"nutrition"` (e.g. `Nutrition`, `Nutrition Initial`, `Nutrition Follow-up`); creating those note types is an admin task per Canvas's normal note-type provisioning.

After install, set the practice-info secrets so the print template renders the right header:

```bash
canvas config set nutrition_charting practice-name "Practice Name" --host <instance-name>
canvas config set nutrition_charting practice-address "<street, city, ST zip>" --host <instance-name>
canvas config set nutrition_charting practice-phone "(xxx) xxx-xxxx" --host <instance-name>
canvas config set nutrition_charting practice-fax "(xxx) xxx-xxxx" --host <instance-name>
```

If you want the print API to be reachable outside a logged-in staff session (e.g. a future automation), also set:

```bash
canvas config set nutrition_charting simple-api-key "$(python -c 'import secrets; print(secrets.token_hex(16))')" --host <instance-name>
```

## Configuration options

All configurable without code changes. Two paths:

- **CLI** — `canvas config set <plugin_name> <key>=<value> --host <instance-name>`. Examples in the install section above.
- **Canvas admin UI** — `https://<your-canvas-instance>/admin/plugin_io/plugin/<plugin_id>/change/`. Each secret declared in `CANVAS_MANIFEST.json` shows up as an input field on the plugin's detail page.

Admin-UI access to plugin secrets is governed per-plugin by a **Managing users** list on the plugin's detail page. Users on that list can view and modify the plugin's secrets; users not on the list can still see basic plugin info and enable / disable the plugin but cannot read or write secret values. Add the dietetics admin (or whoever owns the practice's print branding) to the Managing users list so they can update the practice-info secrets without involving Canvas Root / Support.

| Secret | What it does |
|--------|--------------|
| `practice-name` | Practice name shown in the print header + signature block. |
| `practice-address` | Practice address line in the print header (right side). |
| `practice-phone` | "P:" entry in the print header / footer. |
| `practice-fax` | "F:" entry in the print header / footer. |
| `simple-api-key` | Auth fallback for `PrintNutritionNoteAPI` outside a staff session. Optional. |

If any practice secret is unset, that line renders empty in the print header rather than failing.

## Known limitations

These are deliberate trade-offs in the current build, called out so operators know what to expect:

- **Scribe / LLM integration is not wired up.** The architecture is Scribe-compatible — everything lands as queryable Canvas commands, and the free-text-heavy sections are backed by Canvas questionnaires — but no LLM agent fills the form today. A future plugin can drive the same save endpoints to pre-populate sections.
- **Note types are not provisioned by the plugin.** It detects nutrition note types by name-substring match. The practice's admin team (or the Canvas implementation team) creates the actual note types in admin.
- **Recommended Labs emit as a `Plan` command, not `LabOrder`.** `LabOrderCommand` validates that `lab_partner` and `tests_order_codes` match a real configured partner; recommendations to the team aren't tied to one. A formatted `Plan` titled "Recommended Labs" keeps the data structured and queryable without per-instance lab-partner config. See Roadmap below.
- **Referrals support a ServiceProvider typeahead with a free-text fallback.** The "Refer to" field on a referral row searches the instance's `ServiceProvider` directory (first name, last name, or practice name) and resolves to a real `ServiceProvider` record when the dietician picks a result. If the target isn't in the directory, the dietician can use the "add manually" affordance to fill four free-text fields (first name, last name, specialty, practice name) instead. The emitted `Refer` command carries the resolved record when one was selected; otherwise it carries the manual fields.
- **Indications on referrals come from the patient's active PMH only.** Codes outside the patient's active conditions list have to be added in Canvas's command UI after save.
- **Educational materials list is hardcoded** to five canonical handouts (DASH, Mediterranean, Low-FODMAP, Diabetic carb counting, Weight management) plus an "Add other" free-text affordance. The canonical keys are part of the public contract — see `MIGRATIONS.md` for the rename procedure if a future release adds or renames materials.
- **`DELETE_*_COMMAND` effects don't refresh the host's Commands tab live.** Canvas core live-updates the Commands tab for `ORIGINATE_*` and `EDIT_*` effects but not deletes. The plugin surfaces a "↻ Refresh to see changes" link inline whenever a save included a delete; the dietician clicks it to reload the page (form-state survives the reload). Resolving this properly requires a Canvas core platform fix.
- **`AttributeHub` cleanup is handled for note deletes only.** `NutritionChartingNoteLifecycle` removes the per-note row when a note transitions to `DELETED`. Patient deletes, namespace renames, and other lifecycle events are not currently swept — see `MIGRATIONS.md` for guidance.

## Roadmap

Possible future work, roughly in the order it would make the most product-impact difference:

1. **Scribe integration.** Wire an LLM agent to the existing save endpoints so a transcript-driven flow can pre-populate sections. The structured-command output already supports this.
2. **Native `LabOrder` emission once a default lab partner is configurable.** The Recommended Labs section emits as `Plan` today; with a configurable `lab_partner` secret, the section can switch to one `LabOrder` command per lab.
3. **Educational-materials content management.** Replace the hardcoded canonical list with a admin-editable library (probably a separate `nutrition_education_library` plugin). The `material:<key>` row-id contract documented in `MIGRATIONS.md` is designed to survive that move.
4. **Real-time delete propagation in the Commands tab.** Canvas core platform fix — file with the platform team. The plugin's "↻ Refresh" link is the workaround.
5. **Cron-driven AttributeHub orphan sweeper.** The `NutritionChartingNoteLifecycle` handler covers the common case (note delete). A periodic sweeper would catch any rows orphaned by lifecycle events the handler doesn't subscribe to.

## Screenshots

> Drop UAT screenshots into a `screenshots/` directory next to this README before publication. Suggested coverage:
>
> - The Nutrition tab on a fresh Initial visit (top-of-form view)
> - The auto-populated Medical Chart Review section
> - A multi-row section after add / edit / remove (Goals or Referrals)
> - The Indications PMH multiselect on a Referral row
> - The print modal on an Initial visit, fully populated
> - The print modal on a Follow-up showing the tighter follow-up layout
