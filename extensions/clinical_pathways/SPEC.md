# Plugin Specification: Clinical Pathways

Version: 0.4.7
Status: Implemented — in UAT

This spec captures the **v0.4** implementation: the implementation choices
for this plugin (data model, handler topology, runtime semantics, file
layout).

The companion plugin `imci_questionnaires` (a separate plugin at
`extensions/imci_questionnaires/`, on branch `add-imci-questionnaires`)
ships the IMCI Fever WHO Questionnaire YAML records the pathway examples
reference.

---

## 1. Purpose

Clinical Pathways lets a configurator declare a **per-question branching
flow** over **existing Canvas Questionnaire records**, publish it, and
have a provider start it from inside a patient note. As the provider
commits each questionnaire, the plugin's runtime evaluator advances the
pathway: each step references one Canvas question, evaluates rules
against captured responses, and either advances to the next step (which
may auto-insert a new questionnaire) or terminates by emitting a
recommendation `CustomCommand` on the note.

There is no plugin-authored question UI; the plugin **references**
Canvas's native `Questionnaire` / `Question` / `ResponseOptionSet` /
`ResponseOption` records (`canvas_sdk.v1.data.questionnaire`) and lets
Canvas render the questionnaires as it would for any other
`QuestionnaireCommand`.

---

## 2. Manifest

```json
{
  "sdk_version": "0.139.0",
  "plugin_version": "0.4.7",
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
  for authoring pathways. Three-pane layout: left rail (pathways list),
  center (per-step rule editor with A/B/C… letter labels on step cards),
  right rail (collapsible loaded-questionnaire panels + recommendations).
  Routing dropdowns ("Then go to" / "Otherwise") prefix step targets
  with the matching center-pane letter so the logic flow is visible at
  a glance.
- **Picker** (`NOTE_HEADER` `ActionButton` → `RIGHT_CHART_PANE`) —
  searchable list of published pathways. On select, originates the start
  step's questionnaire as a `QuestionnaireCommand`, creates a `PathwayRun`
  pre-populated with `current_step_id` and `inserted_questionnaires`, and
  closes the side pane via the `INIT_CHANNEL` / `CLOSE_MODAL` postMessage
  handshake.
- **Runtime evaluator** (`BaseProtocol` on `INTERVIEW_UPDATED`) — gates on
  `interview.committer_id`, atomically claims the event via a per-run
  `last_processed_event_token`, walks the step list forward, and emits
  follow-on `QuestionnaireCommand` inserts (via
  `BatchOriginateCommandEffect`) or a terminal `CustomCommand`
  recommendation (via `cmd.originate()`).
- **Terminal command** (`pathwayClassification`) — the single
  `CustomCommand` schema v0.4 ships; field shape is defined in
  `clinical_pathways.terminal_commands.TERMINAL_COMMANDS`.

---

## 3. Data model

```python
# models/pathway.py
class Pathway(CustomModel):
    title = TextField()
    description = TextField(default="")
    recommendation = TextField(default="")   # v0.1 vestige; unused.
    is_active = BooleanField(default=True)
    status = TextField(default="draft")      # "draft" | "published"
    definition = JSONField(default=dict)     # see §4
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
    pathway = ForeignKey(
        Pathway, to_field="dbid", on_delete=DO_NOTHING, related_name="runs",
    )
    current_node_id = TextField(default="")          # v0.3 vestige; unused.
    current_step_id = TextField(default="")          # v0.4 active.
    inserted_questionnaires = JSONField(default=list)
    committed_questionnaires = JSONField(default=list)
    last_processed_event_token = TextField(default="")
    status = TextField(default="active")             # "active" | "completed"
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

**Migration history**:

| Version | Definition shape | PathwayRun state shape |
|---|---|---|
| v0.1.x | Five tables (Pathway / Segment / Question / Option / BranchRule) | n/a |
| v0.2.x | `definition.version = 1` (nested tree of questionnaires + terminal nodes) | `current_node_id` |
| v0.3.x | `definition.version = 2` (flat `nodes[]`, recommendations top-level) | `current_node_id` |
| v0.4.0–v0.4.3 | `definition.version = 3` (flat `steps[]`, per-step rules + Otherwise; rule-level `combinator: "all"\|"any"`) | `current_step_id`, `inserted_questionnaires`, `committed_questionnaires`, `last_processed_event_token` |
| v0.4.4+ | Same `version = 3`, but rules carry per-condition `connector: "and"\|"or"` with AND-tighter-than-OR precedence; legacy `combinator` auto-migrated on load. | (unchanged) |
| v0.4.5+ | Recommendations: `params.recommended_action` dropped (folded into `params.body`); builder uses `params.title` as the rail label (mirrors `rec.name`). | (unchanged) |

Older definition shapes are *not* migrated — opening a v0.1/0.2/0.3
pathway in the v0.4 builder yields a blank v3 definition that the user
re-authors. v0.1's Segment/Question/Option/BranchRule tables remain in
postgres but are orphaned (SDK does not permit drops).

**Critical SDK quirk**: `CustomModel` reverse-relation managers
(`pw.runs`, `pw.segments`, etc.) do **not** expose a working Django
`RelatedManager`. Always query through `Model.objects.filter(parent__dbid=...)`
or `Model.objects.filter(parent_id=parent.dbid)`. This was a real runtime
crash in v0.1.3.

---

## 4. Pathway definition (`Pathway.definition`, v3 JSON shape)

```json
{
  "version": 3,
  "start_step_id": "s_...",
  "loaded_questionnaires": [
    { "questionnaire_id": "<canvas-uuid>",
      "questionnaire_name_snapshot": "..." }
  ],
  "steps": [
    {
      "step_id": "s_...",
      "questionnaire_id": "<canvas-uuid>",
      "questionnaire_name_snapshot": "...",
      "question_id": "<canvas-uuid>",
      "question_name_snapshot": "...",
      "rules": [
        {
          "rule_id": "r_...",
          "conditions": [
            {
              "question_id": "<canvas-uuid>",
              "operator": "eq" | "neq" | "contains" | "contains_any" |
                          "contains_all" | "contains_none" |
                          "lt" | "lte" | "gt" | "gte" |
                          "any_answer" | "no_answer",
              "value_option_id": "<dbid as string>",
              "value_option_ids": ["<dbid as string>", ...],
              "value_text": "...",
              "value_number": 0,
              "connector": "and" | "or"
            }
          ],
          "then": {
            "type": "step" | "recommendation",
            "target_id": "s_..." | "rec_..."
          }
        }
      ],
      "otherwise": {
        "type": "step" | "recommendation",
        "target_id": "s_..." | "rec_..."
      }
    }
  ],
  "recommendations": [
    {
      "recommendation_id": "rec_...",
      "name": "Severe febrile illness",
      "command_key": "pathway_classification",
      "params": {
        "title": "...",
        "severity": "minor" | "moderate" | "severe" | "critical",
        "body": "..."
      }
    }
  ]
}
```

**Step semantics**:

- Each step references exactly one Canvas (questionnaire, question)
  pair. The first step in the array is the start (`start_step_id` is
  kept in sync with `steps[0].step_id` on every save).
- Each step has **exactly one rule** (auto-created with one empty
  condition when the step is added). The builder UI does not surface
  add/delete-rule affordances.
- Conditions in a rule are joined by **per-pair `connector` values**
  (`"and"` | `"or"`, default `"and"`) carried on each non-first
  condition. The evaluator splits the list on `or` boundaries and
  matches if any AND-group is fully satisfied — i.e. AND binds tighter
  than OR, so `A and B or C and D` evaluates as `(A and B) or (C and
  D)`. Arbitrary parenthesization beyond this precedence is not
  supported.
- v0.4.0–v0.4.3 used a rule-level `combinator` field (`"all"`/`"any"`)
  instead. The evaluator still honors it as a back-compat fallback when
  no per-condition connectors are present; the builder migrates pathways
  to the new shape on first load (`combinator: "any"` → every non-first
  condition gets `connector: "or"`, `"all"` → `"and"`, then the field is
  removed).
- The rule's `then` (if any condition matches) and the step's
  `otherwise` (if no rule matches) each route to either another step or
  a recommendation.
- Conditions can reference any question from any loaded questionnaire,
  not just the step's own question.

**Operator semantics**:

| `ResponseOptionSet.type` | Allowed operators |
|---|---|
| `SING` (radio) | `eq`, `neq`, `any_answer`, `no_answer` |
| `MULT` (checkbox) | `contains_any`, `contains_all`, `contains_none`, `any_answer`, `no_answer` |
| `INT` (integer) | `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `any_answer`, `no_answer` |
| `TXT` (free text) | `eq`, `neq`, `contains`, `any_answer`, `no_answer` |

Question identifiers in definition JSON are Canvas Question UUIDs.
ResponseOption identifiers are the option's integer `dbid` stringified,
**not** a UUID — Canvas's `ResponseOption` model has no `id` field, only
`dbid` (a discovery from v0.2.6).

**Recommendation shape** (v0.4.5+):

- The builder no longer surfaces a separate "Name" input. `params.title`
  drives both the rail label and the classification card heading;
  `rec.name` is mirrored from `params.title` on every keystroke and on
  load (legacy records with `name` set and `title` blank are backfilled
  in the JS migration).
- The `recommended_action` parameter is gone. The renamed "Recommendation"
  textarea writes `params.body` only. Legacy records' `recommended_action`
  text is folded into `params.body` with a `Recommended action: …`
  prefix on first load, and the field is dropped from the params dict.
- The `pathway_classification.html` and `pathway_classification_print.html`
  templates no longer render a "Recommended action" callout.

---

## 5. Handler topology

```
clinical_pathways/
├── CANVAS_MANIFEST.json
├── __init__.py
├── applications/
│   └── builder_app.py              # PathwayBuilderApp (provider_menu_item)
├── handlers/
│   ├── builder_api.py              # SimpleAPI — builder SPA + JSON CRUD + catalog
│   ├── picker_api.py               # SimpleAPI — picker SPA + /start endpoint
│   ├── runner_button.py            # ActionButton — note-header launcher
│   └── evaluator.py                # BaseProtocol — advances PathwayRuns
├── models/
│   ├── __init__.py
│   ├── pathway.py
│   └── pathway_run.py
├── terminal_commands.py            # TERMINAL_COMMANDS schema registry
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
| GET | `/pathways` | List active pathways (summary). |
| POST | `/pathways` | Create a draft pathway with an empty v3 definition. |
| GET | `/pathways/<dbid>` | Get a single pathway including its definition. |
| PUT | `/pathways/<dbid>` | Replace title/description/definition. |
| DELETE | `/pathways/<dbid>` | Soft-delete (`is_active=False`, force unpublish). |
| POST | `/pathways/<dbid>/publish` | Validate, flip status to `published` on success; 400 with `issues` on errors. |
| POST | `/pathways/<dbid>/unpublish` | Flip status to `draft`. |
| POST | `/pathways/<dbid>/validate` | Return `issues` without changing status. |
| GET | `/catalog/questionnaires?q=...` | Typeahead — active Canvas questionnaires with `can_originate_in_charting=True`. |
| GET | `/catalog/questionnaires/<id>` | Full questionnaire detail incl. questions + response options. |
| GET | `/catalog/terminal-commands` | Return the `TERMINAL_COMMANDS` registry. |

Auth: `StaffSessionAuthMixin`. Persistence is full-document via `PUT` —
the SPA mutates a local copy of the definition and debounces a save
after every change. The save does **not** assign the server response
back to `state.pathway`; doing so would detach DOM closures that hold
references into the definition tree and silently lose subsequent edits
(real bug from v0.2.1).

### 5.2 `PickerAPI` (`PREFIX = "/picker"`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/`, `/main.js`, `/styles.css` | Picker SPA assets. |
| GET | `/pathways?q=...` | Search published, active pathways by title. |
| POST | `/start` | Body `{pathway_dbid, note_uuid}`; finds `start_step_id`, originates the start step's `QuestionnaireCommand`, creates a `PathwayRun` with `current_step_id` + `inserted_questionnaires=[start_questionnaire_id]`. |

`PathwayRunnerButton` (`NOTE_HEADER` ActionButton, only on editable note
states) emits
`LaunchModalEffect(url=/picker/...&note_uuid=...&patient_id=..., target=RIGHT_CHART_PANE)`.
The picker SPA closes itself via the `INIT_CHANNEL` / `CLOSE_MODAL`
postMessage handshake after a successful `/start`.

### 5.3 `PathwayEvaluator` (`BaseProtocol` on `INTERVIEW_UPDATED`)

Per-event processing for each active `PathwayRun` whose `note_uuid`
matches the event's interview:

1. Compute an `event_token = <interview_id>:<modified_iso>`.
2. Atomically claim the event via
   `PathwayRun.objects.filter(dbid=..., last_processed_event_token=prior).update(last_processed_event_token=token)`
   — only one worker per event's update changes a row; the others skip.
   (Canvas dispatches each event to all worker processes; this gate
   prevents duplicate inserts.)
3. Merge the interview's responses into `run.captured_responses` and add
   the event's questionnaire IDs to `committed_questionnaires`.
4. Walk forward from `current_step_id`:
   - If the step's question is captured (or its questionnaire is in
     `committed_questionnaires`), evaluate the step's rules — each
     rule's conditions are joined by the per-pair `connector` values
     with AND-tighter-than-OR precedence. First rule whose conditions
     are satisfied wins. If no rule matches, fall through to the step's
     `otherwise`.
   - If the routing target is a step, advance `current_step_id` and
     continue the walk.
   - If the routing target is a recommendation, resolve the recommendation
     from `definition.recommendations`, build a `CustomCommand` with
     the rendered `pathway_classification` template content, emit it via
     `cmd.originate()` (not `BatchOriginateCommandEffect` —
     `CustomCommand`s in a batch envelope crash the Canvas note UI), and
     mark the run `completed`.
   - If the step's questionnaire has never been committed, emit a
     `BatchOriginateCommandEffect` with a fresh `QuestionnaireCommand`
     for that questionnaire (unless it's already in
     `inserted_questionnaires`), record the insertion, and pause.

A safety counter (`256`) on the walk loop prevents runaway routing in a
malformed pathway.

---

## 6. Validation (Publish gate)

Implemented in `builder_api._validate_pathway`. Errors block publish;
warnings inform the configurator but allow publish.

| Severity | Check |
|---|---|
| error | `definition.version == 3`. |
| error | At least one step exists. |
| error | `start_step_id` resolves to a step. |
| error | Each step references a `questionnaire_id` and `question_id`. |
| warning | Referenced questionnaire still exists in Canvas. |
| warning | Step has no rules and no `otherwise` — the arm dead-ends. |
| error | Rule has at least one condition. |
| error | Each non-first condition's `connector`, if set, is `"and"` or `"or"`. |
| error | Rule's `then` and step's `otherwise` resolve to a step or recommendation in this pathway. |
| error | Every recommendation references a known `command_key`. |
| error | Every recommendation's required parameters are non-empty. |

---

## 7. Out of scope for v0.4

- **Cross-step "Otherwise" auto-defaults.** Each step's `otherwise` is
  null by default; the user explicitly sets it.
- **Drag-to-reorder steps.** Reordering is via up/down arrow buttons on
  each step card.
- **Multiple rules per step.** A step has exactly one implicit rule;
  alternate routing is modelled by adding another step.
- **Arbitrary parenthesization of condition groups.** v0.4.4 introduced
  per-pair AND/OR connectors with AND-tighter-than-OR precedence; the
  user cannot author `A and (B or C)`-style explicit groupings.
- **Cross-pathway recommendation library.** Recommendations are
  per-pathway.
- **`{{question_id}}` autocomplete** in the recommendation editor. Manual
  typing of UUIDs for now.
- **All-matches mode** (concurrent terminal classifications, IMCI-style).
  Data shape allows it, builder does not expose it.
- **In-note `enabled_conditions` rendering**: Canvas's questionnaire UI
  in the note context appears to display every question regardless of
  `enabled_conditions` declared in the questionnaire YAML. Per-question
  skipping inside a single questionnaire currently isn't available at
  runtime through this code path. The workaround (not pursued) is to
  decompose multi-question questionnaires into single-question
  questionnaires so the pathway evaluator handles skipping at the
  step boundary.

---

## 8. Validated SDK assumptions / hard-won facts

| # | Fact | How we found it |
|---|---|---|
| V1 | `NoteApplication.on_open()` reads the external note UUID at `event.context["note"]["id"]` (the integer `note_id` key is the DB ID). | SDK docs `data-questionnaire` table. |
| V2 | A SimpleAPI POST may return a mixed `list[Response \| Effect]`; effects are applied. | SDK docs `commands-api-examples`, `CommandAPI.add_precharting_commands`. |
| V3 | `provider_menu_item` Applications support `LaunchModalEffect(target=TargetType.PAGE)`. | SDK docs `layout-effect/#modals`. |
| V4 | `CustomCommand` supports `originate()` only (no `commit()` action). | SDK command table — `*_CUSTOM_COMMAND_COMMAND \| ORIGINATE only`. |
| V5 | `CustomModel` reverse-relation managers do **not** expose Django's filter/order_by; query through `Model.objects.filter(parent__dbid=...)`. | Reproduced as a runtime crash in v0.1.3; staff_directory plugin uses the direct-query pattern. |
| V6 | `BatchOriginateCommandEffect([cmd1, cmd2]).apply()` materializes multiple SDK-defined commands in a single note update — but does **not** safely handle `CustomCommand` in the same envelope (Canvas's note UI crashes with `Cannot read properties of undefined (reading 'key')` on render). Use `cmd.originate()` for `CustomCommand` instead. | SDK docs + UAT crash in v0.4.2. |
| V7 | `INTERVIEW_UPDATED` fires for both in-progress edits and commits; the commit signal is `interview.committer_id` being set. | SDK events reference + CCM plugin's interview-query pattern. |
| V8 | The `INIT_CHANNEL` → `CLOSE_MODAL` postMessage handshake closes a `DEFAULT_MODAL`-target modal AND a `RIGHT_CHART_PANE`-target side pane. | Companion-app patterns skill, rule 14 + UAT. |
| V9 | `Note.id` is a `UUID` object, not a `str`. `QuestionnaireCommand.note_uuid` is a pydantic-validated `str` field. Stringify with `str(note.id)` before assigning. | Pydantic `ValidationError` crash in v0.4.0. |
| V10 | Canvas dispatches each `INTERVIEW_UPDATED` event to every worker process running the plugin. Duplicate effects without an application-level dedup gate. | UAT — observed 3 evaluator runs per event on a 3-worker instance. Mitigated with a `last_processed_event_token` atomic-swap gate on `PathwayRun`. |
| V11 | `ResponseOption` has no `id` field — only `dbid`. `str(opt.id)` returns `'None'` and collapses every option onto the same identifier. Use `str(opt.dbid)` for stable, distinct option identifiers. | UAT logs + repro in v0.2.5/0.2.6. |
| V12 | Declarative questionnaire YAML rejects responses without a `value` field, despite the SDK docs marking it "optional". | UAT install 500 in `imci_questionnaires` 0.1.0. |
| V13 | Canvas SDK `Question` and `Questionnaire` models have both `id` (UUID) and `dbid` (integer PK). FK columns on `InterviewQuestionResponse` reference `dbid`. To match the builder's UUID-keyed condition dict, resolve `r.question.id` for each response. | UAT — "no rule matched" log line in v0.2.7. |
