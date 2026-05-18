# Plugin Specification: Clinical Pathways

Version: 0.2.0
Status: Implemented — initial UAT cycle

This spec captures the **v0.2** implementation. The user-facing UI of the
builder is governed by the external design brief at
`/Users/sr/src/pathway-builder-ui-design.md`; this document captures only
the implementation choices for *this* plugin (data model, handler topology,
runtime semantics, file layout). When the two disagree, the design brief is
authoritative for UI behavior and this spec is authoritative for code shape.

---

## 1. Purpose

Clinical Pathways lets a configurator declare a **branching pathway over
existing Canvas Questionnaires** through a tree-shaped builder UI, publish
it, and then have a provider start an instance of it from inside a patient
note. As the provider commits each questionnaire, the plugin's runtime
evaluator advances the pathway: it auto-inserts the next questionnaire (or a
terminal `CustomCommand` classification) directly into the same note.

There is no plugin-authored question UI; the plugin **references** Canvas's
native `Questionnaire` / `Question` / `ResponseOptionSet` / `ResponseOption`
records (`canvas_sdk.v1.data.questionnaire`) and lets Canvas render the
questionnaires as it would for any other `QuestionnaireCommand`.

---

## 2. Manifest

```json
{
  "sdk_version": "0.139.0",
  "plugin_version": "0.2.0",
  "name": "clinical_pathways",
  "custom_data": {
    "namespace": "canvas__clinical_pathways",
    "access": "read_write"
  },
  "components": {
    "applications": [
      { "class": "clinical_pathways.applications.builder_app:PathwayBuilderApp",
        "scope": "provider_menu_item" }
    ],
    "protocols": [
      { "class": "clinical_pathways.handlers.builder_api:BuilderAPI" },
      { "class": "clinical_pathways.handlers.picker_api:PickerAPI" },
      { "class": "clinical_pathways.handlers.runner_button:PathwayRunnerButton" },
      { "class": "clinical_pathways.handlers.evaluator:PathwayEvaluator" }
    ],
    "commands": [
      { "name": "PathwayClassification", "schema_key": "pathwayClassification",
        "section": "plan" }
    ]
  }
}
```

Surfaces:

- **Pathway Builder** (`provider_menu_item` Application) — full-page SPA
  for authoring pathways.
- **Picker** (`NOTE_HEADER` `ActionButton` → `DEFAULT_MODAL`) — searchable
  list of published pathways, launched from any editable note. On select,
  emits a `BatchOriginateCommandEffect` that inserts the start questionnaire
  and creates a `PathwayRun`; closes itself via the `INIT_CHANNEL` /
  `CLOSE_MODAL` postMessage handshake.
- **Runtime evaluator** (`BaseProtocol` on `INTERVIEW_UPDATED`) — gates on
  `interview.committer_id` being set, then advances the matching
  `PathwayRun`.
- **Terminal command** (`pathwayClassification`) — the single terminal
  `CustomCommand` schema v0.2 ships; configurable fields are defined in
  `clinical_pathways.terminal_commands.TERMINAL_COMMANDS`.

---

## 3. Data model

```python
# models/pathway.py
class Pathway(CustomModel):
    title = TextField()                  # pathway name
    description = TextField(default="")
    recommendation = TextField(default="")  # v0.1 vestige; not written by v0.2
    is_active = BooleanField(default=True)
    status = TextField(default="draft")     # "draft" | "published"
    definition = JSONField(default=dict)    # the tree document (see §4)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["title"]),
            Index(fields=["is_active"]),
            Index(fields=["status"]),
        ]


# models/pathway_run.py
class PathwayRun(CustomModel):
    note_uuid = TextField()
    pathway = ForeignKey(Pathway, to_field="dbid", on_delete=DO_NOTHING,
                         related_name="runs")
    current_node_id = TextField(default="")
    status = TextField(default="active")     # "active" | "completed"
    captured_responses = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["note_uuid"]),
            Index(fields=["status"]),
            Index(fields=["note_uuid", "status"]),
        ]
```

**v0.1 → v0.2 migration:** the four v0.1 models (`Segment` / `Question` /
`Option` / `BranchRule`) and the four custom commands (`pathwayQA`,
`pathwayRecommendation`) are gone from Python. Their database tables remain
in `canvas__clinical_pathways` (the SDK doesn't permit drops); they're
unreferenced and inert. v0.1 test pathways were wiped by user direction
during the v0.2 cutover.

**Why FKs use `to_field="dbid"`:** that's the auto-provided integer PK on
`CustomModel`. Reverse-relation managers (`pw.runs`, `pw.segments`) are not
real Django `RelatedManager`s under the SDK; **always query via
`Model.objects.filter(parent__dbid=...)`** (lesson from v0.1.3 where
`pw.segments.filter(...)` returned `None` and crashed every request).

---

## 4. Pathway definition (`Pathway.definition` JSON shape)

```json
{
  "version": 1,
  "root": {
    "node_id": "n_...",
    "type": "questionnaire",
    "questionnaire_id": "<canvas-questionnaire-uuid>",
    "questionnaire_name_snapshot": "Fever Gate",
    "match_mode": "first",
    "branches": [
      {
        "branch_id": "b_...",
        "label": "",
        "when": {
          "kind": "group",
          "combinator": "all",
          "children": [
            {
              "kind": "comparison",
              "questionnaire_id": "...",
              "question_id": "...",
              "operator": "eq",
              "value_option_id": "...",
              "value_text": "",
              "value_number": null
            },
            { "kind": "group", "combinator": "any", "children": [ ... ] }
          ]
        },
        "then": {
          "node_id": "n_...",
          "type": "questionnaire" | "terminal",
          "...node-type-specific...": "..."
        }
      }
    ]
  }
}
```

Terminal node:

```json
{
  "node_id": "n_...",
  "type": "terminal",
  "command_key": "pathway_classification",
  "params": {
    "title": "Possible bacterial pneumonia",
    "severity": "severe",
    "body": "Recommend chest X-ray …",
    "recommended_action": "Refer to ED if SpO2 < 92%"
  }
}
```

`params` values may contain `{{question_id}}` template references; the
runtime evaluator resolves them against `captured_responses` at the time
the terminal lands. v0.2 references questions by their Canvas UUID; the
builder shows the question name for legibility but persists the id.

**Operators (v0.2):**

| Question response type (`ResponseOptionSet.type`) | Allowed operators |
|---|---|
| `SING` (radio) | `eq`, `neq`, `any_answer`, `no_answer` |
| `MULT` (checkbox) | `contains_any`, `contains_all`, `contains_none`, `any_answer`, `no_answer` |
| `INT` (integer) | `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `any_answer`, `no_answer` |
| `TXT` (free text) | `eq`, `neq`, `contains`, `any_answer`, `no_answer` |

**Combinators (v0.2):** `all`, `any`, `none` — nested arbitrarily.

**Match mode (v0.2):** `first` (default). `all` (concurrent terminals,
required by IMCI-style pathways) is acknowledged in the data shape but not
yet exposed in the v0.2 builder UI.

**Cross-questionnaire conditions:** allowed. The condition builder's
question dropdown lets the configurator pick from any ancestor
questionnaire (the current node + every questionnaire above it in the tree).

---

## 5. Handler topology

```
clinical_pathways/
├── CANVAS_MANIFEST.json
├── __init__.py
├── applications/
│   └── builder_app.py           # PathwayBuilderApp (provider_menu_item)
├── handlers/
│   ├── builder_api.py           # SimpleAPI — builder SPA + JSON CRUD + catalog
│   ├── picker_api.py            # SimpleAPI — picker SPA + /start endpoint
│   ├── runner_button.py         # ActionButton — note-header launcher
│   └── evaluator.py             # BaseProtocol — advances PathwayRuns
├── models/
│   ├── __init__.py
│   ├── pathway.py
│   └── pathway_run.py
├── terminal_commands.py         # TERMINAL_COMMANDS schema registry
├── static/
│   ├── builder/{index.html,main.js,styles.css}
│   └── picker/{index.html,main.js,styles.css}
├── templates/
│   ├── pathway_classification.html
│   └── pathway_classification_print.html
└── assets/{icon.svg,icon.png}
```

### 5.1 `BuilderAPI` (`PREFIX = "/builder"`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/`, `/main.js`, `/styles.css` | Serve the SPA assets. |
| GET | `/pathways` | List active pathways (dbid, title, status, updated_at). |
| POST | `/pathways` | Create a draft pathway with an empty definition. |
| GET | `/pathways/<dbid>` | Get a single pathway including its definition. |
| PUT | `/pathways/<dbid>` | Replace title/description/definition. |
| DELETE | `/pathways/<dbid>` | Soft-delete (`is_active=False`, force unpublish). |
| POST | `/pathways/<dbid>/publish` | Validate, flip status to `published` on success; 400 with `issues` on errors. |
| POST | `/pathways/<dbid>/unpublish` | Flip status to `draft`. |
| POST | `/pathways/<dbid>/validate` | Return `issues` without changing status. |
| GET | `/catalog/questionnaires?q=...` | Typeahead — active Canvas questionnaires with `can_originate_in_charting=True`. |
| GET | `/catalog/questionnaires/<id>` | Full questionnaire detail incl. questions + response options. |
| GET | `/catalog/terminal-commands` | Return the `TERMINAL_COMMANDS` registry. |

Auth: `StaffSessionAuthMixin`. Persistence is full-document via PUT — the
SPA mutates a local copy of the definition and debounces a save after every
change.

### 5.2 `PickerAPI` (`PREFIX = "/picker"`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/`, `/main.js`, `/styles.css` | Picker modal SPA assets. |
| GET | `/pathways?q=...` | Search published, active pathways. |
| POST | `/start` | Body `{pathway_dbid, note_uuid}`; creates a `PathwayRun`, emits `BatchOriginateCommandEffect([start_questionnaire])`, returns `{status: "started"}`. |

`PathwayRunnerButton` (`NOTE_HEADER` ActionButton) emits
`LaunchModalEffect(url=/picker/...&note_uuid=...&patient_id=...,
target=DEFAULT_MODAL)`. The picker SPA closes itself via the
`INIT_CHANNEL` / `CLOSE_MODAL` postMessage handshake after a successful
`/start`.

### 5.3 `PathwayEvaluator` (`BaseProtocol` on `INTERVIEW_UPDATED`)

1. Look up the interview by `event.target.id`.
2. Skip unless `interview.committer_id` is set and
   `interview.entered_in_error_id` is null (commit gate).
3. Resolve the note's external UUID via `Note.objects.get(dbid=interview.note_id).id`.
4. For each active `PathwayRun` whose `note_uuid` matches and whose
   `current_node_id`'s questionnaire matches one of the interview's
   `questionnaires`:
   - Build `captured` (question_id → bucket of text + option_ids).
   - Merge into the run's persisted `captured_responses` for template
     interpolation across nodes.
   - Evaluate branches in order under `match_mode` (`first` or `all`).
   - For each match's `then`:
     - `questionnaire` → emit `QuestionnaireCommand(note_uuid, questionnaire_id)`; advance run.
     - `terminal` → resolve `params` (interpolating `{{...}}`), render
       `templates/pathway_classification.html`, emit a `CustomCommand`;
       mark run `completed`.
   - All resulting commands are batched into a single
     `BatchOriginateCommandEffect`.

The evaluator is idempotent w.r.t. duplicate `INTERVIEW_UPDATED` events for
the same commit, because once the run advances past a node, subsequent
events for the prior questionnaire no longer match its `current_node_id`.

---

## 6. Validation (Publish gate)

Implemented in `builder_api._validate_pathway`. Errors block publish;
warnings inform the configurator but still allow publish.

| Severity | Check |
|---|---|
| error | A root node is selected. |
| warning | The referenced questionnaire still exists in Canvas. |
| error | Every `questionnaire` node has at least one branch. |
| error | Every branch has a `then` target. |
| error | Every `terminal` node references a known `command_key`. |
| error | Every `terminal`'s required parameters are non-empty. |

Not yet enforced (deferred to v0.3): condition references only ancestor
questions, `{{...}}` references resolve, cycle detection (impossible to
introduce via the tree-building UI but worth a defensive check).

---

## 7. Out of scope for v0.2

Aligned with the design brief's "Decisions still open" — recommendations
made during scoping, not yet built:

1. **Pathway variables** (location, patient attributes, instance settings)
   as condition sources. v0.2 conditions are response-only.
2. **Severity rollup** across concurrent terminals. v0.2 ships the data
   shape for `match_mode=all` but no rollup synthesizer.
3. **All-matches UI toggle** in the builder. The data model supports it;
   the builder defaults every node to `first`.
4. **Versioning** — pathway definitions are mutated in place. No history,
   no draft/published divergence beyond the simple status flip.
5. **`{{...}}` autocomplete** in the terminal editor. The configurator
   types references manually for now.
6. **Stale-reference badges** on the editor cards. Validation surfaces
   warnings at publish time but doesn't decorate the tree inline.
7. **Drag-to-reorder** branches. Branch priority is positional (index
   within the array); reordering today requires deleting and re-adding.
8. **Custom-command catalog beyond `pathway_classification`.** Adding
   commands is a code change in `terminal_commands.py` + manifest.

---

## 8. Validated SDK assumptions

| # | Assumption | Verified via |
|---|---|---|
| V1 | `NoteApplication.on_open()` reads the external note UUID at `event.context["note"]["id"]` (the integer `note_id` key is the DB ID). | SDK docs `data-questionnaire` table. |
| V2 | A SimpleAPI POST may return a mixed `list[Response | Effect]`; effects are applied. | SDK docs `commands-api-examples`, `CommandAPI.add_precharting_commands`. |
| V3 | `provider_menu_item` Applications support `LaunchModalEffect(target=TargetType.PAGE)`. | SDK docs `layout-effect/#modals`. |
| V4 | Custom commands support `originate()` only (no `commit()` action). | SDK command table — `*_CUSTOM_COMMAND_COMMAND | ORIGINATE only`. |
| V5 | CustomModel reverse-relation managers do **not** expose Django's filter/order_by; query through `Model.objects.filter(parent__dbid=...)`. | Reproduced as a runtime crash in v0.1.3; staff_directory plugin uses the direct-query pattern. |
| V6 | `BatchOriginateCommandEffect([cmd1, cmd2]).apply()` materializes multiple commands in a single note update. | SDK docs `effect-batch-originate`. |
| V7 | `INTERVIEW_UPDATED` fires for both in-progress edits and commits; the commit signal is `interview.committer_id` being set. | SDK docs `events` reference + CCM plugin's interview-query pattern. |
| V8 | The `INIT_CHANNEL` → `CLOSE_MODAL` postMessage handshake closes a `DEFAULT_MODAL`-target modal. | Companion-app patterns skill, rule 14. |
