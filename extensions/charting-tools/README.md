# Charting Tools

One builder for three things, each made of pre-filled commands:

| Kind | Holds | Reaches a note through |
|---|---|---|
| **Note template** | Any commands | The "/" menu, and automatic insertion for chosen note types |
| **Quickpick** | One Plan or Procedures command | The "/" menu, and the panel on Assess and Diagnose commands |
| **Order set** | Assessment, Plan, and Procedures commands | The "/" menu, and the panel on Assess and Diagnose commands |

Sections are Canvas's own note sections for each command (home-app's `noteSection`), so "Plan" means what the note's Plan section shows. POC lab test is an Assessment command in Canvas, so quickpicks don't offer it.

A note template reaches a note in either or both of two ways:

- **The "/" menu**: the template appears by name in the note body "/" menu ([note body automations](https://docs.canvasmedical.com/sdk/handlers-action-buttons/#note-body-automations)). Picking it inserts its commands on the line where the clinician typed "/".
- **Note types**: when an appointment of an assigned note type is booked, or a note of that type is created directly, the template's commands are appended to the note automatically.

## Features

- **Template builder**: a global app where admins name a template and pick its commands in order. The template name is the "/" menu entry.
- **Empty commands**: by default each command is inserted empty, ready to document.
- **Questionnaire choice**: Questionnaire, Review of systems, Physical exam, and Structured assessment commands require picking which questionnaire to insert. The builder lists active questionnaires for that command type.
- **Carry forward from last encounter**: a per-command toggle. When it is on, the command is prefilled from the most recent committed command of the same type in one of the patient's earlier notes. If no such command exists, the command is inserted empty.
- **Scribe prompts**: when `SCRIBE_ENABLED` is on, each command in a template can carry a prompt. The prompt is stored on the inserted command as command metadata, where a scribe can read it.

## How to install

```sh
canvas install charting_tools
```

After install, **Charting Admin** appears in the provider menu.

## Panel filters

The panel's **Filter** sits above both tabs, and appears only when there is something to filter by:

- **Condition**: the diagnoses charted on the note that at least one quickpick (or order set, on that tab) is tagged for, starting with the one this command is charting. A diagnosis nothing is tagged for isn't offered, and with none tagged the row doesn't appear, so every item shows.
- **Tags**: admin-defined labels. Quickpicks and order sets carry **Filter tags** set in the builder (the picker searches existing tags first, with how often each is used, and offers to create a new one only when nothing matches exactly). Choosing tags lists only items with at least one of them.
- **Lab** (quickpicks): see below.

## Lab quickpicks across lab partners

A lab quickpick's lab order lists every lab partner set up on the instance (for example a generic lab, LabCorp, Quest), each with its own tests, so one "CBC" quickpick works with whichever lab the clinician uses. A lab left without tests isn't offered for that quickpick.

The panel's **Filter** has a **Condition** row and a **Lab** choice. The Lab choice starts on the patient's preferred lab when their patient metadata `preferred_lab` names one of the labs the lab quickpicks are set up for, matched to the lab's name ignoring capitals and surrounding spaces (for example `labcorp` matches "LabCorp"); otherwise it starts as "Choose a lab", and the clinician can change it either way. Lab quickpicks are hidden until a lab is chosen; then only those with tests for that lab show, and **Add orders** uses that lab's tests. Note templates and order sets keep one lab partner per lab order, since the "/" menu has no lab choice. Lab orders saved with a single partner keep working.

## The patient's preferred lab

Lab Orders this plugin creates are created with their lab already set:

- **Panel quickpicks and order sets:** the lab in the panel's **Lab** choice. That choice starts on the patient's preferred lab when patient metadata `preferred_lab` names one of the labs the lab quickpicks are set up for, and the clinician can change it.
- **The panel's + Lab button, and note templates, order sets, and rules** added by the "/" menu, a note type, or a rule: the patient's preferred lab, when `preferred_lab` names an active lab partner (matched to its name, ignoring capitals and surrounding spaces). With no match, the Lab Order is added with no lab.

A lab order set up with tests for several labs uses the chosen lab's tests when it has some for it; one with no lab set up gets just the lab.

Setting the lab when the command is created, rather than by an edit afterward, is deliberate. A lab set by an edit right after a command is added can be overwritten in the open note by a copy of the command from before the edit, so the lab shows empty until the page is reloaded.

## Moving between environments

Charting Admin's **Download all** saves every note template, quickpick, order set, and rule to a JSON file, and **Upload** brings such a file into another environment (for example from a test instance to production). Both are admin-only.

An upload first shows a preview, and nothing is saved until **Upload** is clicked there:

- Each item is matched to one already here **by name and kind**. A match is replaced by the uploaded version; anything else is added. An item whose name is already used here by a different kind isn't uploaded.
- Each item keeps the on/off state it had where it was downloaded.
- References that differ per environment are matched on arrival, keeping the id when this environment has it and otherwise matching by name: **note types** (template note types, Follow-up note types, rule note-type conditions), **lab partners** (whose tests must exist at the matched lab), and **task assignees** (staff and teams). Questionnaires (by code), ICD-10 picks, and instruction, imaging, medication, pharmacy, and referral codings carry over as they are.
- An item with a note type or lab that doesn't exist here, a lab test the matched lab doesn't offer, a questionnaire that isn't active here, or a note type another template here already uses, is listed under **Can't be uploaded** with the reason, and the rest upload. A task assignee that can't be matched is left unset, with a warning.
- Expanded diagnosis lists travel in the file, so an upload doesn't need UMLS unless a pick changed.

## Ordering provider and prescriber

Lab, Imaging, and DME orders the plugin creates take the note's provider as their ordering provider, and Prescribe, Refill, and Adjust Prescription take the note's provider as their prescriber, wherever they come from: the panel's quick adds, quickpicks, order sets, note templates, and rules. A note with no provider leaves them for the clinician to fill in. (Without this, the order shows the plugin's own user, "Canvas Bot", as the ordering provider.)

## Send-to search (Refer, Imaging, DME)

The **Refer to**, **Imaging center**, and **Send to** fields search the instance's own directory first, its active customer-managed service providers, by name, practice, or specialty. They then search Canvas Science contacts the way home-app does: limited to the service-area zip codes of the admin's primary practice location, and to radiology contacts for imaging orders. A Science contact that's already in the directory is listed once. If Science can't be reached, the directory results still show.

## Command forms

Plan, Instruct, Lab order, Imaging order, DME order, Refer, Follow up, Task, and Prescribe commands have a **Fill in details** form, so a command can be inserted partly filled. Every field is optional; what is left blank is left for the clinician. Coded fields search Canvas's own catalogs (SNOMED instructions, Canvas Science imaging studies and contacts, FDB medications, pharmacies, the instance's lab partners and tests). Follow-up and task dates are relative ("in 90 days") and count from the note's date of service. When carry forward is on and the patient has a prior command, the carried-forward values win over the form.

### Questionnaire answers

Questionnaire, Review of systems, Physical exam, and Structured assessment commands get a form of their chosen questionnaire's questions (text, number, date, single and multiple choice). Answers are stored by question code and option code, the identifiers Canvas's own questionnaire carry forward matches on, because question and option ids change with each questionnaire version. At insert they are mapped onto the newest active version; a question or option that version no longer has is skipped.

Sending any answer makes Canvas skip the questionnaire's own carry forward for that command (home-app sets `skip_carry_forward` on a plugin command that arrives with answers). A command with no pre-filled answers still carries forward per the questionnaire's setting.

Order sets offer Structured assessment only, the one questionnaire command in the Assessment section; quickpicks offer none.

## Diagnoses and the command panel

Quickpicks and order sets carry a list of ICD-10-CM diagnoses, searched through NLM's UMLS. Each pick is one code (`E11.9`) or a heading and everything under it (`N18`). On save the picks are expanded and stored, so the panel never waits on UMLS; re-saving picks up a yearly ICD-10-CM update.

With **On Assess and Diagnose** turned on, the item is offered in a panel attached to those commands while they are charted. The panel shows a tab only for a kind that has at least one active item turned on for it. A tab whose items are all removed later hides itself the next time the panel loads. The panel stays on the Assess or Diagnose after it's committed, for as long as the note is open; once the note is locked or signed it shows nothing. (Canvas keeps a committed command's custom HTML but won't change it, so the plugin writes the panel one last time, with a fresh 4-hour token, just before commit. When that token runs out the panel hides too.)

**+ Plan** has a caret with **Carry forward the last plan for this diagnosis**: it adds a Plan holding the narrative of the patient's most recent committed Plan from an earlier note that was linked to an Assess of a condition with the same ICD-10 code (the code this Assess or Diagnose is charting), linked to this assessment like any + Plan. If this assessment already has a blank, uncommitted Plan linked to it, that Plan is filled in instead of adding another. If there's no such earlier plan, nothing is added and the button says so.

The bar also has quick-add buttons, always shown: **+ Plan**, **+ Refer**, **+ Lab**, **+ Image**, **+ DME**, **+ Prescribe**, **+ Instruct**, and **+ Procedure**. **+ DME** (the Order DME command, SDK 0.254.0 and later) gets the charted code as its indication but no assessment link, since Order DME doesn't take one. DME orders can also go in note templates, quickpicks, order sets, and rules, with a form for the item, quantity, length of need, and send-to (from the referral directory). The item is either a product from the instance's DME formulary (searched by name or code; only active products) or free text, chosen with the **From the formulary / Free text** switch. A product taken off the formulary since is left out when the order is inserted. On upload to another environment, products are matched by code system and code. Each adds one empty command of that type on the line below the Assess or Diagnose (at the end of the note if that line can't be found). Refer, Lab, and Image get the ICD-10 the command is charting as their diagnosis, and Prescribe gets it as its indication; Plan, Instruct, and Procedure have no indication field. On an Assess, that code comes from the assessed condition, or from the code itself when the Assess diagnoses a new condition. Each click adds another command. Every command the panel adds (Plan, Instruct, Procedure, Lab, Image, Refer, Prescribe, Follow-up, Task, and the rest) is linked to the Assessment behind the Assess or Diagnose it was added from, whether from a quick-add button, a quickpick, or an order set. Orders and prescriptions take the link from Canvas SDK 0.247.0 on, which this plugin requires. An Assess command's own Assessment is used; for Diagnose, the Assessment its condition has in this note. The tabs are:

- **Quickpicks** are multi-select pills: click one to select it, again to clear it, and a quickpick already on the note is grayed out, whichever diagnosis or "/" menu it was added from. The list refreshes each time the panel is opened or the page regains focus. **Filter by condition** offers the diagnoses charted on the note (Diagnose and Assess commands), starting with the one this command is charting; with conditions chosen, only quickpicks made for one of them are listed. Quickpicks are grouped by order type. **Add orders** stages everything selected in one batch: lab quickpicks for the same lab partner merge into one lab order (tests combined, fasting if any test needs it, comments joined), and each order takes the chosen conditions it matches as its indication, or the charted code when none match.
- **Order sets** adds one order set at a time, with the charted code as the indication. Its Assessment commands are left out, because the command the panel sits in is the diagnosis.

Each command a quickpick adds, from the panel or the "/" menu, carries command metadata `charting_tools:quickpick:<id>`, so the panel shows that quickpick as **Already added** for the rest of the note, whichever diagnosis it was added under. Entering the command in error frees it again. From the "/" menu, an order set inserts all of its commands and no indication is set.

The panel is custom HTML on the Assess and Diagnose commands. Only one plugin can set a command's custom HTML, so don't install another plugin that attaches its own panel to those commands.

## Rules

A rule acts on the note when it meets the rule's conditions: **When** (all or any of the conditions) → **Then** (one or more actions, run in order):

| Action | What it does |
|---|---|
| Add commands | Adds its own commands, built with the same command picker and forms as a note template, either suggested on a protocol card or added automatically. Carry forward is off for rule commands, as for quickpicks and order sets. |
| Update a command on the note | Edits uncommitted commands of a chosen type (and questionnaire, for questionnaire types) with the fields or answers the action sets. Only those fields are sent, so the rest of the command stays as the clinician left it. |
| Remove a command from the note | Deletes uncommitted commands of a chosen type (and questionnaire). |

Update and remove never touch committed commands, and always run automatically, since a protocol card can only add. Automatic actions run once per note.

| Condition | True when |
|---|---|
| The note has a diagnosis | A Diagnose, Assess, Change Diagnosis (its new diagnosis), or Assess Coding Gap (unless refuted) command on the note carries one of the picked codes (a heading like N18 can include everything under it; expanded through UMLS when the rule is saved) |
| The patient has an active condition | The patient's problem list has an active, non-surgical condition with one of the picked codes, charted on any note (a heading like N18 can include everything under it; expanded through UMLS when the rule is saved). Resolved conditions don't count. Checked when the note is created or its visit booked, and again when the patient's conditions are added, changed, or resolved (`CONDITION_CREATED`, `CONDITION_UPDATED`, `CONDITION_RESOLVED`), which re-checks the patient's notes still open or booked, the 10 most recent. A diagnosis charted on this note joins the problem list when it is committed. |
| The note type | The note is one of the chosen note types. A note booked for a visit counts as the appointment's note type from the moment it's booked (until check-in Canvas gives it the generic Appointment type), and a note started directly counts as its own type. Checked when the note is created or its visit booked, and again when the visit type changes (`APPOINTMENT_UPDATED`, the note's latest appointment only, so the appointment a reschedule replaced is ignored). |
| A questionnaire score | A questionnaire on the note scores at least / more than / exactly / at most / less than a number. The score adds up the `value` of each chosen answer option, plus numeric answers |
| A questionnaire answer | A multiple-choice question on the note is answered with one of the picked options |
| Patient, appointment, or note information | A metadata field on the patient, the note's most recent appointment, or the note itself is a value, is any of several values, has any value, or isn't set. Values compare ignoring case and surrounding spaces. Appointment metadata includes the scheduling form's additional fields |

Rules that check metadata are evaluated when a note is created (`NOTE_CREATED`) or its visit is booked (`APPOINTMENT_CREATED`), and again whenever that kind of metadata is saved later, by a person or another plugin (`PATIENT_METADATA_*`, `APPOINTMENT_METADATA_*`, `NOTE_METADATA_*`, created and updated). Booking saves the scheduling form's fields in the same transaction, so they are there at booking. Appointment and note metadata re-check that appointment's note; patient metadata re-checks the patient's notes still open for charting or booked, the 10 most recent. Locked, signed, and deleted notes are left alone, and note metadata this plugin writes (keys starting `charting_tools:`) never re-runs rules. An automatic action still runs once per note. All rules are also evaluated while the note is charted, on the update events of the commands they read (`QUESTIONNAIRE_COMMAND__POST_UPDATE`, `ROS_COMMAND__POST_UPDATE`, `PHYSICAL_EXAM_COMMAND__POST_UPDATE`, `STRUCTURED_ASSESSMENT_COMMAND__POST_UPDATE`, `DIAGNOSE_COMMAND__POST_UPDATE`, `ASSESS_COMMAND__POST_UPDATE`, `ASSESS_COMMAND__CONDITION_SELECTED`, `UPDATE_DIAGNOSIS_COMMAND__POST_UPDATE`, `ASSESS_CODING_GAP_COMMAND__POST_UPDATE`). Diagnosis commands are also checked as they are added (`*_COMMAND__POST_ORIGINATE` and `*_COMMAND__POST_INSERTED_INTO_NOTE`), since one started from the chart, such as the Assess button on a condition in the patient summary, arrives with its diagnosis filled in and may never be edited; the diagnosis in the event itself counts even before the command can be read from the note. Adding a command sends several of these at once, so an automatic action claims the rule for the note in the plugin cache before acting, and only the first event acts. Answers are read from each questionnaire command's own data rather than from its Interview, which Canvas creates only on commit. Questionnaires, questions, and options are matched by code, so a rule keeps working across questionnaire versions. One handler serves every rule and skips rules that don't read the command that changed.

| Then | What happens |
|---|---|
| Suggest it on a protocol card | A Protocol Card on the patient's chart recommends the rule's commands with an **Add** button. It is withdrawn when the conditions stop holding, and isn't re-sent while nothing changes. |
| Add it to the note automatically | The rule's commands are added to the note once (note metadata `charting_tools:rule:<rule id>`), as soon as the conditions are met. |

Commands a rule added are never removed when its conditions stop holding, since the clinician may have edited them.

## Configuration

Both settings go in the plugin's secrets.

| Setting | Values | Effect |
|---|---|---|
| `TEMPLATE_ADMIN_ROLES` | Comma-separated staff roles, matched by internal code, abbreviation, or name (case-insensitive) | Staff holding one of these roles can create, edit, and delete templates. When it is empty, no one can manage templates. Every staff member can use existing templates from the "/" menu either way. |
| `SCRIBE_ENABLED` | `true` / `false` | Shows the per-command prompt field in the builder and writes prompts as command metadata when a template is used. Defaults to off. |
| `UMLS_API_KEY` | The practice's UMLS API key (uts.nlm.nih.gov, My Profile) | Needed to search diagnoses and to expand "everything under it" picks. Exact codes match without it. |
| `PANEL_TOKEN_SIGNING_KEY` | A long random string | Signs the tokens the command panel uses to call the plugin. The panel is not shown until this is set. A token is sent in the body of each call (never the URL), lasts 4 hours (the panel is re-signed on an edit after 3), stops working once its Assess or Diagnose is committed, and can't add commands to a note that is no longer open. |
| `CANVAS_INSTANCE_URL` | This instance's address, e.g. `https://example.canvasmedical.com` | Where the panel's calls go. The panel is not shown until this is set. |

## Usage

1. Open **Charting Admin** from the provider menu.
2. Click **New template**, enter a name, and add commands.
3. For each command, choose whether to carry it forward and, when scribe is enabled, enter a prompt.
4. Save. In any note, type `/` and pick the template by name.

The "/" menu is built when a note loads, so a new or renamed template shows up the next time a note is opened.

## Note types

A template can be assigned to any active encounter, inpatient, or chart review note type. Each note type can belong to only one active template, so a new note never receives two templates. The builder shows a type already used by another template as disabled, and saving a conflicting assignment is rejected.

Templates store a note type by the identifier its versions share (`unique_identifier`), so editing a note type in Canvas settings does not break the assignment.

Two handlers do the automatic insert:

- **Appointment booking** (`APPOINTMENT_CREATED`). Booking creates the visit's note with Canvas's generic Appointment note type, which changes to the appointment's note type at check-in. So the match is on the appointment's note type, and the commands go into the note at booking, after the Reason for visit Canvas adds. Carry forward is evaluated at booking.
- **Direct note creation** (`NOTE_CREATED`), for notes created with the note type itself, such as a note started from the chart, the API, or a data import.

Each note gets an automatic template once. The first insert writes note metadata `charting_tools:applied_template` (the template id), and both handlers skip a note that has it, so a reschedule to the same visit type changes nothing. Picking a template from the "/" menu is always allowed and ignores the marker.

### When the visit type changes

Each command an automatic template inserts carries command metadata `charting_tools:from_template` (the template id). When a visit's type changes, the note is brought in line with the new type's template:

- **Triggers.** A reschedule creates a new appointment on the same note (`APPOINTMENT_CREATED`), and editing the visit type on the appointment sends `APPOINTMENT_UPDATED`. Only the note's latest appointment counts, so the appointment a reschedule replaced is ignored, as are canceled and no-showed appointments.
- **Shared commands stay.** A command is shared when both templates have it: the same command type and, for Questionnaire, ROS, Physical Exam, and Structured Assessment, the same questionnaire by code. When a template has the same command more than once, each copy is matched separately.
- **The old template's other commands are removed** only while they are uncommitted and unchanged since they were inserted, meaning saved no more than 5 seconds after creation. A command anyone has changed, a person or another plugin, stays. Where only some copies of a command are shared, edited copies keep their place and an unchanged copy is removed.
- **The new template's other commands are added**, tagged the same way. A visit type with no template removes the old template's unchanged commands and adds nothing.
- **A visit booked as a type with no template** is marked with `charting_tools:applied_template` = `none` at booking, so changing it later to a type that has a template brings that template in. Notes booked before version 0.14.1 have no such mark and aren't switched.
- **Never touched:** committed commands, commands a person added, and anything from the "/" menu, the panel, or a rule.
- **Left as is:** notes that are locked, signed, or deleted, and notes whose template went in before version 0.8.0, whose commands aren't tagged.

## Carry forward

Carry forward is a note template feature. Quickpicks and order sets always insert what they were built with.

Carry forward is available for these commands:

- Reason for visit
- History of present illness
- Plan
- Instruct
- Assess (skips a condition that has been entered in error)
- Follow up (keeps the reason, note type, and comment; the requested date is left blank)
- Task (keeps the title, assignee, comment, and labels; the due date is left blank)
- Lab order
- Perform

Questionnaire, Review of systems, Physical exam, and Structured assessment commands carry forward the same way they do when inserted natively in Canvas: the questionnaire's own carry-forward setting decides. When it is "Carry forward all encounters", Canvas prefills the inserted command from the patient's most recent committed answers, matched by question code. The plugin inserts these commands with no answers so that Canvas applies the setting; a command that arrives with answers skips it. The builder shows each chosen questionnaire's setting read-only. Change it on the questionnaire in Canvas settings.

For any other command the toggle is disabled and the command is inserted empty. The source is the most recent committed, non-entered-in-error command of the same type from a note with an earlier date of service for the same patient. If that command's stored data can't be read, the command is inserted empty and a warning is logged.

## Questionnaires

A template stores its questionnaire by coding system and code, not by database ID, so templates survive questionnaire versioning and match across instances. When the template is used, the code resolves to the newest active questionnaire with that code for the command type (`QUES`, `ROS`, `EXAM`, or `SA`). Questionnaires without a code can't be picked.

Saving a template fails if a chosen questionnaire is no longer active. If a questionnaire is retired after the template was saved, the command is inserted without one, a warning is logged, and the builder marks the choice "(no longer active)".

## Scribe prompt metadata

| Key | Value |
|---|---|
| `charting_tools:scribe_prompt` | The prompt text entered for that command in the template |

The key is written only when `SCRIBE_ENABLED` is on and the prompt is not blank. Read it with `CommandMetadata.objects.filter(command__id=<command uuid>, key="charting_tools:scribe_prompt")`.

## Architecture

- `handlers/template_automation.py`: a `NOTE_BODY_AUTOMATION` action button that emits one "/" entry per active template (key `CHARTING_TOOLS__<template id>`). On click it originates the template's commands in one `BatchOriginateCommandEffect` with `replace_line=True`, followed by the metadata upserts.
- `api/templates_api.py`: a SimpleAPI serving the builder page and CRUD endpoints, gated by `TEMPLATE_ADMIN_ROLES`.
- `applications/admin_app.py`: a provider menu item that opens the builder. Canvas shows plugin menu items to every staff member; non-admins who open it see the access notice.
- `models/note_template.py`: the `NoteTemplate` custom table in the `canvas__charting_tools` namespace.
- `templates/static/semantic.min.css`: Semantic UI 2.4.0 (MIT), copied from home-app's `app/static/css/semantic.min.css` so the builder uses the same build as Canvas. `canvas-overrides.css` ports Canvas's global overrides from home-app's `static/styles/semantic-overrides.scss` and `app.scss`. The builder uses no Semantic icon classes, because the icon font files are not bundled.

## Running tests

```sh
uv run pytest
```
