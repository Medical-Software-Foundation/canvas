# Canvas plugin context

This repo contains Canvas plugins. Reviews and code-edit sessions should follow the patterns below, drawn from real issues found in past PRs. Behavior-tuning rules for Claude Code Review live in `REVIEW.md`; this file is the longer-form context that both human and AI reviewers benefit from.

## Reference codebases

Consult these for correct patterns:

- **canvas-plugins** (`canvas_sdk/`) — the plugin SDK. Authoritative source for how plugins should be built.
  - `canvas_sdk/handlers/` — `BaseHandler`, `ActionButton`, `Application`, `CronTask`, `SimpleAPIRoute`
  - `canvas_sdk/effects/` — all available effects (banner alerts, tasks, notes, billing, etc.)
  - `canvas_sdk/v1/data/` — ORM-style data access (`Patient`, `Note`, `Condition`, etc.)
  - `canvas_sdk/commands/` — command effects (`GoalCommand`, `DiagnoseCommand`, etc.)
  - `canvas_sdk/utils/http.py` — the SDK's HTTP client with metrics and timeout enforcement
  - `canvas_sdk/caching/` — `Cache` wrapper with `get_or_set()`, TTLs
- **canvas-plugins/example-plugins/** — 40+ reference implementations
- **Medical-Software-Foundation/canvas** (`protocols/`, `extensions/`) — production-quality open-source plugins

## Critical anti-patterns

### All-patient batch ops on plugin or patient lifecycle events

The single most dangerous pattern. A handler that subscribes to `PLUGIN_CREATED` or `PLUGIN_UPDATED` and iterates every patient turns any plugin reinstall — even an unrelated config tweak — into a potentially instance-killing batch. `PATIENT_UPDATED` is similarly broad: it fires on every attribute change.

Use a global-scope `Application` with a `SimpleAPI` endpoint to let a user intentionally trigger the batch. See `vineyard/vineyard-note-automations/` for the pattern: a global app provides a button, clicking it calls an API that starts the work.

### Fail closed, never fail open

When a secret or config value is missing, deny access. Common fail-open patterns to reject:

- Origin validation returning `True` when `CANVAS_INSTANCE_ORIGIN` is unset
- Admin checks returning `True` when `ADMIN_STAFF_IDS` is empty
- Authentication bypass when a required secret is absent

```python
# BAD: fails open
def is_admin(self, staff_id: str) -> bool:
    admin_ids = self.secrets.get("ADMIN_STAFF_IDS", "")
    if not admin_ids.strip():
        return True

# GOOD: fails closed
def is_admin(self, staff_id: str) -> bool:
    admin_ids = self.secrets.get("ADMIN_STAFF_IDS", "")
    if not admin_ids.strip():
        log.warning("ADMIN_STAFF_IDS not configured, denying access")
        return False
```

### Don't swallow exceptions

Bare `try/except Exception` around handler logic hides bugs from Sentry and monitoring. Catch only the specific exception you expect from an external call.

```python
# BAD: hides bugs
try:
    result = process_patient(patient)
except Exception:
    log.error("Something went wrong")
    return []

# GOOD: let unexpected errors raise, catch only expected ones
try:
    pdf_bytes = docusign.get_signed_document(envelope_id)
except RuntimeError as exc:
    log.error("DocuSign error: %s", exc)
    return [JSONResponse({"error": "Unable to retrieve document"}, status_code=503)]
```

### Filter `entered_in_error` on clinical data

Any query against `Condition`, `Medication`, `LabReport`, etc. must filter retracted records:

```python
conditions = Condition.objects.filter(
    patient_id=patient_id,
    entered_in_error__isnull=True,
)
```

### Fail explicitly on missing required data

Never write `"unknown"` / `"N/A"` / `""` into the database for an authenticated user, patient, or note ID. Return an error instead.

```python
# BAD: silently corrupts data
sender_id = request.headers.get("X-Staff-Id", "unknown")

# GOOD: explicit failure
sender_id = request.headers.get("X-Staff-Id")
if not sender_id:
    return [JSONResponse({"error": "Missing X-Staff-Id header"}, status_code=400)]
```

## Important patterns

### N+1 queries

The most common performance issue. Watch for:

- Iterating patients and querying per-patient inside the loop — use a bulk `.filter()` instead
- `.exists()` + `.last()` (two queries) when `.last()` + None check suffices
- Fetching related objects in a loop — use `select_related()` / `prefetch_related()`
- `.filter()` on a prefetched relationship inside a loop (negates the prefetch) — use `Prefetch` or filter in Python

```python
# BAD: N+1
for patient in Patient.objects.all():
    conditions = Condition.objects.filter(patient=patient)

# GOOD: bulk query
patients = Patient.objects.prefetch_related("conditions").all()
for patient in patients:
    conditions = patient.conditions.all()
```

### Use SDK data models, not FHIR API calls

When data is available through `canvas_sdk.v1.data` (`Patient`, `Condition`, `LabReport`, `StaffRole`, etc.), use it directly. SDK access is faster, type-safe, and doesn't consume API rate limits.

### Use the SDK's HTTP client, not raw `requests`

`canvas_sdk.utils.http.Http` enforces a 30s timeout, validates URLs, and tracks metrics. Don't import `requests` or `httpx`.

```python
from canvas_sdk.utils.http import Http

http = Http(base_url="https://api.example.com")
response = http.post("/endpoint", json=payload)
```

### Use questionnaire codes, not names or IDs

Codes are stable across installations. Names break when versioned (`(v2)` suffix). Database IDs vary per environment. Look up by coding system + code.

### Separate admin/config into global-scope apps

Admin operations (configuration, batch jobs, settings) belong in a global-scope `Application`, not patient-specific apps or handlers. Patient-scoped apps are for patient-level workflows only.

### Subscribe to specific events

Don't use `PATIENT_UPDATED` when you only care about address changes — that fires on every attribute update. Pick the most specific event in `canvas_sdk/events/`.

## Style and quality

### Tests must verify behavior

Asserting that `compute()` returns a list proves nothing. Tests should verify the right effects are returned for given inputs and edge cases.

```python
# BAD: proves nothing
def test_handler():
    handler = MyHandler(event=mock_event)
    result = handler.compute()
    assert isinstance(result, list)

# GOOD: verifies behavior
def test_handler_creates_task_for_overdue_patient():
    event = make_event(patient_id=overdue_patient.id)
    handler = MyHandler(event=event)
    result = handler.compute()
    assert len(result) == 1
    assert result[0].type == EffectType.ADD_TASK
```

### Clean up `canvas init` boilerplate

Remove unused auto-generated files, placeholder descriptions ("A protocol that does xyz..."), empty unused component arrays, and generic test stubs.

### Guard against `None` in templates

When rendering patient data, handle `None`. "None oz" or "None mg" is a poor user experience.

## Plugin architecture checklist

### Structure
- Plugin has a `CANVAS_MANIFEST.json` with accurate `components`, `secrets`, and `description`
- Description is not the boilerplate "Edit the description in CANVAS_MANIFEST.json"
- Handler classes listed in the manifest match actual class paths
- `data_access.event`, `read`, `write` populated correctly
- `README.md` includes a demo video link ([video drive](https://drive.google.com/drive/folders/1YaFaXr5x47_t2J_xtSViKeoNwm14vucX))
- `pyproject.toml` declares `canvas[test-utils]` and test config
- Tests in `tests/` are meaningful (not just stubs)
- No leftover `canvas init` boilerplate

### Handler patterns
- Inherits from the correct base class:
  - `BaseHandler` — responding to specific events
  - `CronTask` — scheduled work (set `SCHEDULE` as a cron expression)
  - `ActionButton` — chart/note buttons (set `BUTTON_TITLE`, `BUTTON_KEY`, `BUTTON_LOCATION`)
  - `Application` — embeddable apps (implement `on_open()`, global scope for admin)
  - `SimpleAPIRoute` — custom API endpoints (set `PATH`, implement HTTP methods)
- `RESPONDS_TO` is the most specific event that does the job
- `compute()` returns `list[Effect]` (not a single Effect, not None)
- Early returns with `[]` for events the handler should ignore
- No side effects outside of the returned `Effect` list (don't write to the DB directly from `compute()`)
- No batch operations triggered by `PLUGIN_CREATED` / `PLUGIN_UPDATED`

### Data access
- Uses `canvas_sdk.v1.data` models, not FHIR API calls or raw SQL
- QuerySets use `select_related()` / `prefetch_related()`, no N+1
- `.get()` calls are wrapped in try/except for `DoesNotExist`
- Clinical queries filter `entered_in_error`
- Questionnaire lookups use codes

### Secrets and configuration
- All secrets declared in `CANVAS_MANIFEST.json` `secrets` array
- Accessed via `self.secrets["KEY"]`, never hardcoded
- Missing secrets cause a clear error, not silent misbehavior

### Effects
- Created via SDK classes; `.apply()` is called
- Command effects use `.originate()` or `.edit()` as appropriate
- API endpoints return `JSONResponse` (from `canvas_sdk.effects.simple_api`)
- External HTTP uses `canvas_sdk.utils.http.Http`, not raw `requests`/`httpx`
