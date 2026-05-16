# Plugin Specification: Clinical Pathways

Version: 0.1.0  
Status: Draft — awaiting implementation

---

## 1. Plugin Overview

Clinical Pathways is a Canvas plugin that lets staff build structured, branching clinical questionnaires ("pathways") through an in-Canvas builder UI, and lets providers run those pathways against a patient during a note encounter. At completion, the provider's Q&A trail and the pathway's free-text recommendation are each originated as separate `CustomCommand` blocks in the open note.

**Scope summary.** The plugin covers two distinct surfaces:

- A **pathway builder** accessible from the provider menu (`provider_menu_item` scope), where any authenticated Canvas staff user creates and edits pathways in-place. No versioning; edits are live immediately.
- A **chart runner** accessible as a note tab (`NoteApplication` scope), where any authenticated provider working a note can search pathways by title, step through branching segments, and persist the Q&A + recommendation to the note.

---

## 2. Manifest Summary

```json
{
  "sdk_version": "0.1.4",
  "plugin_version": "0.1.0",
  "name": "clinical_pathways",
  "description": "Build structured branching questionnaires and run them against a patient note, originating a Q&A trail and recommendation as custom commands.",
  "url_permissions": [],
  "components": {
    "applications": [
      {
        "class": "clinical_pathways.applications.builder_app:PathwayBuilderApp",
        "name": "Pathway Builder",
        "description": "Create and edit clinical pathways (branching questionnaires).",
        "scope": "provider_menu_item",
        "icon": "assets/icon.png"
      },
      {
        "class": "clinical_pathways.applications.runner_app:PathwayRunnerApp",
        "name": "Clinical Pathways",
        "description": "Run a clinical pathway during a note encounter.",
        "scope": "note_application"
      }
    ],
    "protocols": [
      {
        "class": "clinical_pathways.handlers.builder_api:BuilderAPI",
        "description": "CRUD endpoints for pathway builder UI."
      },
      {
        "class": "clinical_pathways.handlers.runner_api:RunnerAPI",
        "description": "Search/fetch and segment-step endpoints for the note runner."
      }
    ],
    "commands": [
      {
        "name": "PathwayQA",
        "label": "Pathway Q&A",
        "schema_key": "pathwayQA",
        "section": "plan"
      },
      {
        "name": "PathwayRecommendation",
        "label": "Pathway Recommendation",
        "schema_key": "pathwayRecommendation",
        "section": "plan"
      }
    ],
    "content": [],
    "effects": [],
    "views": []
  },
  "custom_data": {
    "namespace": "canvas__clinical_pathways",
    "access": "read_write"
  },
  "secrets": [],
  "tags": {},
  "references": [],
  "license": "MIT",
  "diagram": false,
  "readme": "./README.md"
}
```

**Event subscriptions:** None. Both surfaces are launched on demand (menu item click / note tab click). No background event listeners are needed.

**Effects emitted:**

| Effect | When | How |
|---|---|---|
| `LaunchModalEffect(target=TargetType.PAGE)` | `PathwayBuilderApp.on_open()` | Opens builder SPA in provider menu |
| `LaunchModalEffect(target=TargetType.NOTE)` | `PathwayRunnerApp.on_open()` | Opens runner SPA as note tab |
| `CustomCommand(...).originate()` x2 | Runner API `/complete` POST | Q&A trail + recommendation into note |

**Permissions:** Any authenticated staff Canvas session may call the builder API (enforced via `StaffSessionAuthMixin`). Any authenticated staff Canvas session may call the runner API (same mixin). No patient-facing surfaces.

---

## 3. CustomModel Data Model

### 3.1 File layout

All models live under `clinical_pathways/models/` (not a flat `models.py`), so that migrations are discovered correctly by the plugin runner.

```
clinical_pathways/models/
    __init__.py          # re-exports all models
    pathway.py
    segment.py
    question.py
    option.py
    branch.py
```

### 3.2 Model definitions

```python
# models/pathway.py
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import BooleanField, DateTimeField, Index, TextField

class Pathway(CustomModel):
    """A named clinical pathway (top-level container)."""
    title = TextField()
    description = TextField(default="")
    recommendation = TextField(default="")
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["title"]),
            Index(fields=["is_active"]),
        ]
```

```python
# models/segment.py
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING, BooleanField, ForeignKey, Index, IntegerField, TextField,
)
from clinical_pathways.models.pathway import Pathway

class Segment(CustomModel):
    """An ordered block of questions within a pathway.

    A pathway has one entry segment (is_entry=True). Branching rules on
    the preceding segment's responses determine which segment comes next.
    The last segment in a branch has no outgoing branch rules; the runner
    presents the pathway recommendation on reaching such a segment after
    all its questions are answered.
    """
    pathway = ForeignKey(
        Pathway, to_field="dbid", on_delete=DO_NOTHING, related_name="segments",
    )
    title = TextField()
    order = IntegerField(default=0)
    is_entry = BooleanField(default=False)

    class Meta:
        indexes = [
            Index(fields=["pathway", "order"]),
            Index(fields=["is_entry"]),
        ]
```

```python
# models/question.py
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING, BooleanField, ForeignKey, Index, IntegerField, TextField,
)
from clinical_pathways.models.segment import Segment

class ResponseType:
    """Allowed answer-input types for a Question. Stored as the raw string."""
    YES_NO       = "yes_no"
    MULTI_CHOICE = "multi"
    FREE_TEXT    = "free_text"
    NUMERIC      = "numeric"
    ALL = (YES_NO, MULTI_CHOICE, FREE_TEXT, NUMERIC)

class Question(CustomModel):
    """A single question within a segment."""
    segment = ForeignKey(
        Segment, to_field="dbid", on_delete=DO_NOTHING, related_name="questions",
    )
    text = TextField()
    response_type = TextField(default=ResponseType.FREE_TEXT)
    order = IntegerField(default=0)
    required = BooleanField(default=True)

    class Meta:
        indexes = [
            Index(fields=["segment", "order"]),
        ]
```

```python
# models/option.py
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING, ForeignKey, Index, IntegerField, TextField,
)
from clinical_pathways.models.question import Question

class Option(CustomModel):
    """A selectable answer choice for MULTI_CHOICE or YES_NO questions.

    YES_NO questions always have exactly two Option rows: "Yes" and "No".
    MULTI_CHOICE questions have one row per choice.
    FREE_TEXT and NUMERIC questions have no Option rows.
    """
    question = ForeignKey(
        Question, to_field="dbid", on_delete=DO_NOTHING, related_name="options",
    )
    label = TextField()
    order = IntegerField(default=0)

    class Meta:
        indexes = [
            Index(fields=["question", "order"]),
        ]
```

```python
# models/branch.py
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING, ForeignKey, Index, IntegerField, JSONField, TextField,
)
from clinical_pathways.models.segment import Segment

class BranchRule(CustomModel):
    """Determines which segment follows a given segment.

    Evaluation model:
      - A segment may have zero or more BranchRule rows.
      - Each rule carries a `conditions` JSON blob (see §6 for schema).
      - Rules are evaluated in `priority` order (ascending); the first
        rule whose conditions are fully satisfied wins.
      - If no rule matches (or the segment has no rules), the pathway
        is considered complete and the runner presents the recommendation.
    """
    from_segment = ForeignKey(
        Segment, to_field="dbid", on_delete=DO_NOTHING, related_name="outgoing_rules",
    )
    to_segment = ForeignKey(
        Segment, to_field="dbid", on_delete=DO_NOTHING, related_name="incoming_rules",
    )
    # JSON: list of {question_dbid: int, operator: "eq"|"contains"|"gte"|"lte"|"in", value: str|list}
    conditions = JSONField(default=list)
    priority = IntegerField(default=0)
    label = TextField(default="")

    class Meta:
        indexes = [
            Index(fields=["from_segment", "priority"]),
        ]
```

### 3.3 Data notes

- `CustomModel` auto-provides `dbid` (auto-increment integer primary key). Models do not declare their own `id` / UUID field. FKs reference parents via `to_field="dbid"`.
- Public JSON (API request/response payloads and condition clauses) uses `dbid` as the identifier (e.g., `pathway_dbid`, `segment_dbid`, `question_dbid`).
- `ResponseType` is a plain string-constant class, not a `TextChoices` enum. `Question.response_type` is a `TextField` whose values are validated in the handler against `ResponseType.ALL` — the SDK's CustomModel runner does not enforce `choices=` constraints.
- `null=True` / `blank=True` and `max_length` are intentionally absent (unsupported by the plugin runner per SDK guidance).
- `JSONField` is used for `conditions` and for in-flight responses (see runner design below). No `TextField` with serialized JSON.
- Index `fields` use Django field names (`pathway`, `segment`, `from_segment`) — the SDK resolves them to the underlying `*_id` columns.
- No `UniqueConstraint` on this initial deploy — add only after verifying no duplicate data exists.

---

## 4. Builder UI

### 4.1 Entry point

The builder is registered as a `provider_menu_item` Application. When the provider taps the "Pathway Builder" item in the Canvas provider menu, `PathwayBuilderApp.on_open()` emits:

```python
LaunchModalEffect(
    url="/plugin-io/api/clinical_pathways/builder/",
    target=LaunchModalEffect.TargetType.PAGE,
)
```

`TargetType.PAGE` renders the iframe at full-page width — appropriate for a content-management tool.

### 4.2 Handler

`BuilderAPI(StaffSessionAuthMixin, SimpleAPI)` with `PREFIX = "/builder"`.

Routes:

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve `index.html` (pathway list + edit shell) |
| GET | `/main.js` | Serve `static/builder/main.js` |
| GET | `/styles.css` | Serve `static/builder/styles.css` |
| GET | `/pathways` | JSON list of all active pathways (dbid, title, is_active) |
| POST | `/pathways` | Create a new pathway; body: `{title, description, recommendation}` |
| GET | `/pathways/<pathway_dbid>` | Full pathway detail: segments + questions + options + branch rules |
| PATCH | `/pathways/<pathway_dbid>` | Update pathway top-level fields |
| DELETE | `/pathways/<pathway_dbid>` | Soft-delete (`is_active=False`) |
| POST | `/pathways/<pathway_dbid>/segments` | Add a segment |
| PATCH | `/segments/<segment_dbid>` | Update segment title / order / is_entry |
| DELETE | `/segments/<segment_dbid>` | Delete segment and its questions + rules |
| POST | `/segments/<segment_dbid>/questions` | Add a question (with response_type) |
| PATCH | `/questions/<question_dbid>` | Update question text / response_type / order / required |
| DELETE | `/questions/<question_dbid>` | Delete question and its options |
| POST | `/questions/<question_dbid>/options` | Add an answer option |
| PATCH | `/options/<option_dbid>` | Update option label/order |
| DELETE | `/options/<option_dbid>` | Delete option |
| GET | `/segments/<segment_dbid>/branches` | List outgoing branch rules for a segment |
| POST | `/segments/<segment_dbid>/branches` | Create a branch rule |
| PATCH | `/branches/<branch_dbid>` | Update branch conditions / to_segment / priority |
| DELETE | `/branches/<branch_dbid>` | Delete branch rule |

All mutation routes receive and return JSON. No Django form processing.

**Important:** All writes go through direct CustomModel `save()` / `delete()` calls in the SimpleAPI handler. This is correct — `CustomModel` rows are plugin-owned data, not Canvas-owned data, so the sandbox restriction on `.save()` does not apply to them.

### 4.3 Static assets (builder)

```
clinical_pathways/static/builder/
    index.html      # SPA shell — no Django placeholders
    main.js         # vanilla JS, no framework; reads data-* attrs from body
    styles.css      # Material-style cards, mobile-first layout
```

`index.html` is served by the GET `/` route via `render_to_string("static/builder/index.html", {"cache_bust": _CACHE_BUST})`. All `<script src>` and `<link href>` references append `?v={{ cache_bust }}`.

`main.js` is fully static — no `{{ ... }}` placeholders. Any per-request values (e.g., base API prefix) are set on `<body data-api-prefix="/plugin-io/api/clinical_pathways/builder">` and read via `document.body.dataset`.

### 4.4 Builder form flow

1. **Pathway list view** — cards showing all pathways (title, active/inactive badge). "New Pathway" button opens the edit view for a blank pathway.
2. **Pathway edit view** — top-level fields: title (required), description (optional textarea), recommendation (required textarea for completion text). Save button calls `PATCH /pathways/<pathway_dbid>`.
3. **Segment list** — ordered list of segments within the pathway. Drag-to-reorder updates `order` via `PATCH /segments/<segment_dbid>`. "Add Segment" appends a new segment.
4. **Segment edit** — segment title field. Inline question list below.
5. **Question list** — within a segment, ordered list of questions. Each question shows: question text, response type badge, reorder handle, delete button.
6. **Add / edit question** — inline form: question text textarea, response type picker (Yes/No, Multi-choice, Free text, Numeric), required toggle. For Multi-choice and Yes/No types, an additional option list appears below with "Add option" and per-option delete.
7. **Branch rules panel** — accordion below each segment's question list. Shows existing branch rules as cards: `IF [conditions] → go to [segment title]`. "Add Rule" opens a rule editor.
8. **Rule editor** — condition builder: select question (from this segment), select operator (equals / contains / ≥ / ≤ / is one of), enter value(s). Multiple conditions on a rule are ANDed. Target segment dropdown lists all other segments in the pathway. Priority field (integer, lower fires first). Save calls `POST /segments/<segment_dbid>/branches` or `PATCH /branches/<branch_dbid>`.

---

## 5. Runtime — Launch from Chart

### 5.1 Entry point

The runner is registered as a `NoteApplication`. It appears as a tab inside the open note named "Clinical Pathways". `PathwayRunnerApp` inherits from `NoteApplication` with:

```python
NAME = "Clinical Pathways"
IDENTIFIER = "clinical_pathways__runner"
PRIORITY = 50
```

`on_open()` reads the external note UUID from `self.event.context["note"]["id"]` and the patient UUID from `self.event.context["patient"]["id"]`, then emits:

```python
note_uuid = self.event.context["note"]["id"]
patient_id = self.event.context["patient"]["id"]
LaunchModalEffect(
    url=f"/plugin-io/api/clinical_pathways/runner/?note_uuid={note_uuid}&patient_id={patient_id}",
    target=LaunchModalEffect.TargetType.NOTE,
)
```

`self.event.context["note_id"]` is the integer database ID and **must not** be used here — `CustomCommand.note_uuid` requires the external UUID string available at `context["note"]["id"]` (see SDK docs, Note Applications "Context and Event Data" table).

`TargetType.NOTE` renders the iframe in the note tab area — the correct surface for in-note content.

### 5.2 Handler

`RunnerAPI(StaffSessionAuthMixin, SimpleAPI)` with `PREFIX = "/runner"`.

Routes:

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve `index.html` (runner SPA shell) |
| GET | `/main.js` | Serve `static/runner/main.js` |
| GET | `/styles.css` | Serve `static/runner/styles.css` |
| GET | `/pathways` | Search pathways by title; query param `q=<search_term>`; returns `[{dbid, title, description}]` (up to 50, active only) |
| GET | `/pathways/<pathway_dbid>/entry` | Return first segment (questions + options) for selected pathway |
| POST | `/segments/<segment_dbid>/next` | Body: `{responses: [{question_dbid, answer}]}`. Evaluate branch rules, return next segment or `{done: true, recommendation}` |
| POST | `/complete` | Body: `{pathway_dbid, note_uuid, responses_trail: [...], recommendation}`. Originates two `CustomCommand`s into the note. Returns `[qa_cmd.originate(), rec_cmd.originate(), JSONResponse({"status": "ok"})]`. |

### 5.3 Static assets (runner)

```
clinical_pathways/static/runner/
    index.html      # SPA shell
    main.js         # vanilla JS, reads data-* attrs
    styles.css
```

Same cache-busting and static-JS discipline as the builder.

### 5.4 Runner interaction flow

1. **Pathway search** — text input at top of panel. On each keystroke (debounced 300 ms), calls `GET /runner/pathways?q=<term>`. Displays matching pathway title cards. Searching is title-only (per scope).
2. **Pathway selection** — tapping a card fetches `GET /runner/pathways/<pathway_dbid>/entry` and renders the first segment.
3. **Segment view** — shows segment title, then questions in order. Each question renders the appropriate input:
   - `yes_no` / `multi`: radio or checkbox group from option labels
   - `free_text`: `<textarea>`
   - `numeric`: `<input type="number">`
4. **"Next" button** — posts current segment's responses to `POST /segments/<segment_dbid>/next`. If `done: true`, moves to completion view. Otherwise renders the returned segment.
5. **Completion view** — shows the pathway recommendation text. "Commit to note" button calls `POST /runner/complete` with the full accumulated `responses_trail`.
6. **Note origination** — the `/complete` endpoint constructs two `CustomCommand` objects:
   - **Q&A trail**: HTML grouped by segment (question text → answer), rendered via `render_to_string("templates/qa_trail.html", {...})` with a matching `templates/qa_trail_print.html` for the print version. Originated with `schema_key="pathwayQA"`.
   - **Recommendation**: free-text recommendation wrapped in minimal HTML, rendered via `templates/recommendation.html` (+ `recommendation_print.html`). Originated with `schema_key="pathwayRecommendation"`.
   - Both commands are originated using `command.originate()` with `note_uuid` set to the note's external UUID passed from the runner SPA, and a fresh `command_uuid` per command (`str(uuid4())`).
   - The effects are returned from the POST response alongside the `JSONResponse` so the Canvas platform materializes them in the note.

### 5.5 In-session response storage

The runner is stateless server-side within a session. The SPA accumulates `responses_trail` (an array of `{segment_dbid, segment_title, question_dbid, question_text, answer}` objects) in JS memory and submits the full trail on `/complete`. No server-side session state or CustomModel rows are needed for in-progress runs. Completed runs are captured only as `CustomCommand` blocks in the note (no separate CustomModel for run history in v0.1.0).

---

## 6. Branching Evaluation

### 6.1 Condition schema (stored in `BranchRule.conditions` JSONField)

```json
[
  {
    "question_dbid": 42,
    "operator": "eq" | "contains" | "gte" | "lte" | "in",
    "value": "<string>" | ["<string>", ...]
  }
]
```

- All conditions within a rule are **ANDed**.
- `eq`: answer equals value (string comparison, case-insensitive for free text).
- `contains`: answer string contains value (free text questions).
- `gte` / `lte`: numeric comparison (numeric questions only); value is a string-encoded number.
- `in`: answer is one of the values list (multi-choice questions).

### 6.2 Evaluation order

The server evaluates `BranchRule` rows for a `from_segment` in ascending `priority` order. The first rule where **all conditions pass** determines `to_segment`. If no rule matches, the pathway is complete (`done: true`).

### 6.3 Permissions

Any authenticated Canvas staff user (verified by `StaffSessionAuthMixin`) may create, edit, and delete pathways and run them in notes. No role-based restrictions in v0.1.0.

---

## 7. Out of Scope (Explicit Non-Goals)

- **Pathway versioning** — edits are live and in-place; there is no history or rollback.
- **Role-based edit restrictions** — any staff user can edit any pathway.
- **Structured recommendation fields** — recommendation is a single free-text block; no ICD codes, order fields, or structured sections.
- **ICD/order linkage** — no diagnostic coding or ordering surfaces.
- **Patient-facing surfaces** — no portal or patient portal entry points.
- **Search beyond title** — the runner search matches only pathway title; no full-text search of segment or question content.
- **Run history / audit log** — completed runs are stored only as note commands; there is no separate CustomModel for run history.
- **Multi-language / localization** — English only.
- **Concurrent edit conflict resolution** — last write wins.

---

## 8. Validated SDK Assumptions

The three implementation assumptions originally listed here have been verified against the Canvas SDK reference (`coding_agent_context.txt`, bundled with the `cpa:canvas-sdk` skill).

### V1 — NoteApplication context key for the external note UUID — **resolved**

For `NoteApplication` handlers, the SDK's "Context and Event Data" table documents:

- `self.event.context["note_id"]` → integer **database ID**
- `self.event.context["note"]["id"]` → **external UUID** string (e.g., `"rk786p"`)

`CustomCommand.note_uuid` requires the external UUID, so `PathwayRunnerApp.on_open()` reads `context["note"]["id"]` and passes it to the RunnerAPI as the `note_uuid` query parameter (see §5.1).

### V2 — Returning `CustomCommand.originate()` effects from a SimpleAPI POST — **resolved**

The SDK explicitly supports returning a mixed list of effects and a `Response` from a `SimpleAPI` endpoint. The endpoint return type is `list[Response | Effect]`, and the SDK includes a worked example originating multiple commands alongside a `JSONResponse` from a single POST handler (the `CommandAPI` reference plugin, `add_precharting_commands` route). The runner's `/complete` POST will follow the same pattern:

```python
return [
    qa_trail_command.originate(),
    recommendation_command.originate(),
    JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK),
]
```

### V3 — `provider_menu_item` scope + `TargetType.PAGE` — **resolved**

The SDK's `LaunchModalEffect` reference (Layout Effects > Modals) lists `PAGE` as a general-purpose target with no scope restriction:

> `PAGE`: Opens the content as a full page.

Application `scope` controls where the launcher appears (provider menu, portal menu, chart, global) and `target` controls where the URL opens. The two are orthogonal, with the practical rules that `RIGHT_CHART_PANE*` requires a patient-chart context and `NOTE` requires a `NoteApplication`. `PAGE` works from any Application scope, including `provider_menu_item`, so the builder's `LaunchModalEffect(target=TargetType.PAGE)` (see §4.1) is correct.

---

## 9. Suggested File Layout

```
clinical_pathways/                          # container (kebab: clinical-pathways → snake: clinical_pathways)
├── pyproject.toml
├── tests/
│   ├── conftest.py
│   ├── applications/
│   │   ├── test_builder_app.py
│   │   └── test_runner_app.py
│   ├── handlers/
│   │   ├── test_builder_api.py
│   │   └── test_runner_api.py
│   └── models/
│       └── test_models.py
└── clinical_pathways/                      # inner package (snake_case)
    ├── CANVAS_MANIFEST.json
    ├── README.md
    ├── LICENSE
    ├── __init__.py
    ├── applications/
    │   ├── __init__.py
    │   ├── builder_app.py                  # PathwayBuilderApp(Application)
    │   └── runner_app.py                   # PathwayRunnerApp(NoteApplication)
    ├── handlers/
    │   ├── __init__.py
    │   ├── builder_api.py                  # BuilderAPI(StaffSessionAuthMixin, SimpleAPI)
    │   └── runner_api.py                   # RunnerAPI(StaffSessionAuthMixin, SimpleAPI)
    ├── models/
    │   ├── __init__.py                     # re-exports Pathway, Segment, Question, Option, BranchRule
    │   ├── pathway.py
    │   ├── segment.py
    │   ├── question.py
    │   ├── option.py
    │   └── branch.py
    ├── templates/
    │   ├── qa_trail.html                   # CustomCommand display content (Q&A)
    │   ├── qa_trail_print.html             # CustomCommand print_content (Q&A)
    │   ├── recommendation.html             # CustomCommand display content (recommendation)
    │   └── recommendation_print.html       # CustomCommand print_content (recommendation)
    ├── static/
    │   ├── builder/
    │   │   ├── index.html
    │   │   ├── main.js
    │   │   └── styles.css
    │   └── runner/
    │       ├── index.html
    │       ├── main.js
    │       └── styles.css
    └── assets/
        ├── icon.svg                        # source SVG
        └── icon.png                        # 48×48 PNG for manifest
```

**Notes on layout decisions:**

- `templates/` holds the HTML used by `CustomCommand` (rendered with `render_to_string` at note-origination time). These are not static assets served by HTTP — they are server-rendered HTML strings passed as the `content` parameter to `CustomCommand`.
- `static/builder/` and `static/runner/` are separate subdirectories so each SPA's assets can be routed independently (`/builder/main.js` vs `/runner/main.js`).
- The scaffold has been written directly (no `canvas init` step). The spec file (`SPEC.md`) lives at the container root and is not committed as part of the inner package.
