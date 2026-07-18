# Canvas Reporting — Phase 2 (Builder + Persistence + Library) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the static Phase-1 page into the real product: a saved-report **library**, an interactive **4-step builder** with live preview and the five visualizations, and **persistence** so reports are saved, shared within the org, and reloaded.

**Architecture:** Build on the Phase-1 foundation (`Application`, `ReportingAPI` SimpleAPI, the `datasets`/`query` engine). Add a `Report` `CustomModel` (Canvas-provisioned Postgres table via a `custom_data` namespace) with an `owner` FK to a `StaffProxy`. Extend `ReportingAPI` with CRUD endpoints. Replace the single-report SPA with a small vanilla-JS app (library → builder/viewer) that reuses the existing `/run` endpoint for live preview and reads `/datasets` for builder options. A saved report's `definition` JSON is exactly the `/run` request body, so rendering a saved report reuses Phase 1 verbatim.

**Tech Stack:** Python 3.11+/3.13 runtime, Canvas SDK (`CustomModel`, `ModelExtension`, `SimpleAPI`, `StaffSessionAuthMixin`), Django ORM (sandbox-restricted), vanilla HTML/CSS/JS, `pytest` via `uv` (SDK stubbed).

**Scope (Phase 2):** persistence (`Report` model), CRUD endpoints with owner + private/shared visibility, the library view, the 4-step builder, the five visualizations (grouped bar, compare table, trend line, KPI, plain table), save/load. **Out of scope (Phase 3+):** dashboards (the Weekly-Ops grid), CSV/PDF export, scheduled email, customer-defined datasets, additional datasets.

---

## Reference Facts (verified — do not re-derive)

- **Persistence pattern** (copy `extensions/sticky_note/`):
  - Proxy module `models/proxy.py`: `from canvas_sdk.v1.data import ModelExtension, Staff` then `class StaffProxy(Staff, ModelExtension): pass`.
  - Model: `from canvas_sdk.v1.data.base import CustomModel` + fields from `django.db.models`. FK uses `to_field="dbid", on_delete=DO_NOTHING, related_name="%(app_label)s__reports"`. **No `unique=True` on plain fields** — use `Meta.constraints`. 1 MB per-field cap (JSON definition is tiny, fine).
  - **Models are NOT declared in the manifest.** Canvas auto-discovers `CustomModel`s in the package. The manifest only needs `"custom_data": {"namespace": "<vendor>__reporting", "access": "read_write"}` and `"secrets": ["namespace_read_write_access_key"]`.
  - CRUD is plain Django ORM: `Report.objects.create(...)`, `.filter(...).update(...)` (optimistic lock via a `version` filter), `.filter(...).values(...)`.
- **Sandbox gotchas (Phase-1 hard lessons — the guard tests in `tests/test_sandbox_imports.py` enforce these):**
  1. A module defining `@dataclass` must NOT use `from __future__ import annotations` (crashes in-sandbox).
  2. No self-package imports (`from reporting.datasets import X` inside that package); use full submodule paths. The sandbox re-evaluates modules with no `sys.modules` caching, so no cross-module mutable singletons either.
  3. Aggregation: only `Count, Case, When, Q, F, Value` importable from `django.db.models`. (Model field classes `ForeignKey, TextField, JSONField, IntegerField, DateTimeField, CharField`, `DO_NOTHING`, `UniqueConstraint` ARE importable — proven by the deployed `sticky_note` extension.)
  - **pytest cannot catch sandbox failures.** Every task that changes importable modules ends by deploying to `training` and checking logs for `Error importing module 'reporting`.
- **Current staff:** resolve from request header `canvas-logged-in-user-id` (a Staff UUID) → `Staff.objects.get(id=<uuid>)` → `.dbid`.
- **Reuse:** the `/run` endpoint and `_build_query` already validate and execute a report definition. A saved report's `definition` JSON == the `/run` body (`dataset_key`, `measure_key`, `group_by`, `filters`, `period`).
- **Deploy:** `canvas install extensions/reporting/reporting --host training` (run from repo root). Logs: `canvas logs --host training --since 3m --no-follow`.
- **Test command:** from `extensions/reporting`, `uv run --with pytest pytest tests/ -q`.

---

## File Structure (this phase)

```
extensions/reporting/reporting/
├── CANVAS_MANIFEST.json            # + custom_data namespace, + secret, + read_write
├── models/
│   ├── __init__.py
│   ├── proxy.py                    # StaffProxy(Staff, ModelExtension)
│   └── report.py                   # Report(CustomModel)
├── services/
│   ├── __init__.py
│   └── reports.py                  # pure-ish CRUD + visibility logic over Report
├── routes/reporting_api.py         # + /reports CRUD endpoints (modify)
├── templates/app.html              # replace: library + builder shell (modify)
└── static/
    ├── css/app.css                 # expand styling (modify)
    └── js/app.js                    # replace: router, library, builder, viz (modify)
tests/
├── conftest.py                     # extend: CustomModel/ModelExtension/field stubs (modify)
├── models/{__init__.py,test_report.py}
├── services/{__init__.py,test_reports.py}
└── routes/test_reporting_api.py    # + CRUD endpoint tests (modify)
```

---

## Task 1: Extend test stubs for CustomModel + Django fields

**Files:** Modify `extensions/reporting/tests/conftest.py`

The Phase-1 conftest stubs `django.db.models` with only `Q/Count/Case/When/Value/F`. Add the model-definition names and `canvas_sdk.v1.data.base.CustomModel` / `ModelExtension` so `models/` imports cleanly.

- [ ] **Step 1: Add Django field stubs** — in `_install_django_stubs`, after the existing aggregation classes, add field/constraint stubs and `DO_NOTHING`:

```python
    class _FieldStub:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    for _name in (
        "ForeignKey", "TextField", "JSONField", "IntegerField",
        "DateTimeField", "CharField", "BooleanField", "UniqueConstraint",
    ):
        setattr(m, _name, type(_name, (_FieldStub,), {}))
    m.DO_NOTHING = "DO_NOTHING"
```

- [ ] **Step 2: Stub CustomModel + ModelExtension + Staff** — in `_install_canvas_sdk_stubs`, add:

```python
    base_mod = _ensure_module("canvas_sdk.v1.data.base")

    class CustomModel:
        objects = MagicMock()

        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ModelExtension:
        pass

    class Staff:
        objects = MagicMock()

    base_mod.CustomModel = CustomModel
    data.CustomModel = CustomModel
    data.ModelExtension = ModelExtension
    data.Staff = Staff
```

- [ ] **Step 3: Verify collection still clean** — from `extensions/reporting`: `uv run --with pytest pytest tests/ -q`. Expected: 41 passed (unchanged; no new tests yet).

- [ ] **Step 4: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/tests/conftest.py
git commit -m "test(reporting): stub CustomModel + Django field classes for persistence

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Report persistence model

**Files:**
- Create: `extensions/reporting/reporting/models/__init__.py` (empty)
- Create: `extensions/reporting/reporting/models/proxy.py`
- Create: `extensions/reporting/reporting/models/report.py`
- Create: `extensions/reporting/tests/models/__init__.py` (empty), `extensions/reporting/tests/models/test_report.py`

- [ ] **Step 1: Write the failing test** — `tests/models/test_report.py`:

```python
from reporting.models.report import Report


def test_report_is_custom_model():
    from canvas_sdk.v1.data.base import CustomModel
    assert issubclass(Report, CustomModel)


def test_report_instance_holds_definition_and_owner():
    r = Report(name="No-shows", category="Operations", visibility="shared",
               definition={"dataset_key": "appointments"}, owner_id=7, version=1)
    assert r.name == "No-shows"
    assert r.visibility == "shared"
    assert r.definition["dataset_key"] == "appointments"
    assert r.owner_id == 7
```

- [ ] **Step 2: Run to verify it fails**

From `extensions/reporting`: `uv run --with pytest pytest tests/models/test_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.models.report'`.

- [ ] **Step 3: Implement `models/proxy.py`**

```python
"""Proxy models enabling ForeignKeys from CustomModels to built-in Canvas models."""

from canvas_sdk.v1.data import ModelExtension, Staff


class StaffProxy(Staff, ModelExtension):
    """Proxy so a CustomModel can ForeignKey to Staff."""

    pass
```

- [ ] **Step 4: Implement `models/report.py`**

```python
"""Persisted saved-report definitions (Canvas-provisioned custom data table)."""

from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    IntegerField,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel
from reporting.models.proxy import StaffProxy


class Report(CustomModel):
    """A saved report: a named, owned, optionally-shared query definition.

    visibility: "private" (owner only) or "shared" (whole org).
    definition: the JSON report spec consumed by the /run endpoint
        (dataset_key, measure_key, group_by, filters, period).
    """

    owner = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__reports",
        null=True,
    )
    name = TextField(default="", blank=True)
    category = TextField(default="", blank=True)
    visibility = TextField(default="private")  # "private" | "shared"
    definition = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    version = IntegerField(default=0)  # optimistic-lock counter
```

- [ ] **Step 5: Run to verify pass**

`uv run --with pytest pytest tests/models/test_report.py -q` — Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/models extensions/reporting/tests/models
git commit -m "feat(reporting): Report CustomModel + StaffProxy for persistence

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Report CRUD + visibility service

**Files:**
- Create: `extensions/reporting/reporting/services/__init__.py` (empty)
- Create: `extensions/reporting/reporting/services/reports.py`
- Create: `extensions/reporting/tests/services/__init__.py` (empty), `extensions/reporting/tests/services/test_reports.py`

Pure-ish functions over `Report.objects`, unit-tested by patching `Report.objects`. Encapsulates the visibility rule (own OR shared) and serialization so route handlers stay thin.

- [ ] **Step 1: Write the failing tests** — `tests/services/test_reports.py`:

```python
from unittest.mock import MagicMock, patch

from reporting.services import reports as svc


def test_serialize_summary_omits_definition():
    row = MagicMock(dbid=3, name="X", category="Operations",
                    visibility="shared", owner_id=5)
    out = svc.serialize_summary(row)
    assert out == {"id": 3, "name": "X", "category": "Operations",
                   "visibility": "shared", "owner_id": 5}
    assert "definition" not in out


def test_serialize_detail_includes_definition():
    row = MagicMock(dbid=3, name="X", category="Operations",
                    visibility="private", owner_id=5,
                    definition={"dataset_key": "appointments"})
    out = svc.serialize_detail(row)
    assert out["id"] == 3
    assert out["definition"] == {"dataset_key": "appointments"}


def test_list_visible_returns_owned_and_shared():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.order_by.return_value = ["a", "b"]
        result = svc.list_visible(staff_dbid=5)
        # Q(owner_id=5) | Q(visibility="shared")
        assert M.objects.filter.called
        assert result == ["a", "b"]


def test_create_persists_and_returns_instance():
    with patch("reporting.services.reports.Report") as M:
        M.objects.create.return_value = MagicMock(dbid=9)
        out = svc.create(staff_dbid=5, name="N", category="Operations",
                         visibility="private", definition={"x": 1})
        M.objects.create.assert_called_once()
        kwargs = M.objects.create.call_args.kwargs
        assert kwargs["owner_id"] == 5 and kwargs["version"] == 1
        assert out.dbid == 9


def test_update_uses_version_optimistic_lock():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.update.return_value = 1  # rows updated
        ok = svc.update(report_id=9, staff_dbid=5, expected_version=1,
                        fields={"name": "New"})
        assert ok is True
        M.objects.filter.assert_called_with(dbid=9, owner_id=5, version=1)


def test_update_returns_false_on_version_conflict():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.update.return_value = 0
        ok = svc.update(report_id=9, staff_dbid=5, expected_version=1,
                        fields={"name": "New"})
        assert ok is False


def test_delete_only_owner():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.delete.return_value = (1, {})
        ok = svc.delete(report_id=9, staff_dbid=5)
        assert ok is True
        M.objects.filter.assert_called_with(dbid=9, owner_id=5)
```

- [ ] **Step 2: Run to verify fail**

`uv run --with pytest pytest tests/services/test_reports.py -q` — Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `services/reports.py`**

```python
"""CRUD + visibility logic for saved reports. Thin wrapper over Report.objects."""

from django.db.models import Q

from reporting.models.report import Report


def serialize_summary(row) -> dict:
    return {
        "id": row.dbid,
        "name": row.name,
        "category": row.category,
        "visibility": row.visibility,
        "owner_id": row.owner_id,
    }


def serialize_detail(row) -> dict:
    out = serialize_summary(row)
    out["definition"] = row.definition
    return out


def list_visible(staff_dbid: int):
    """Reports owned by the staff member OR shared with the org."""
    return Report.objects.filter(
        Q(owner_id=staff_dbid) | Q(visibility="shared")
    ).order_by("-updated_at")


def get_visible(report_id: int, staff_dbid: int):
    return (
        Report.objects.filter(dbid=report_id)
        .filter(Q(owner_id=staff_dbid) | Q(visibility="shared"))
        .first()
    )


def create(staff_dbid: int, name: str, category: str, visibility: str,
           definition: dict):
    return Report.objects.create(
        owner_id=staff_dbid,
        name=name,
        category=category,
        visibility=visibility if visibility in ("private", "shared") else "private",
        definition=definition,
        version=1,
    )


def update(report_id: int, staff_dbid: int, expected_version: int,
           fields: dict) -> bool:
    """Owner-only, optimistic-locked update. Returns False on conflict/not-owner."""
    rows = Report.objects.filter(
        dbid=report_id, owner_id=staff_dbid, version=expected_version
    ).update(version=expected_version + 1, **fields)
    return rows == 1


def delete(report_id: int, staff_dbid: int) -> bool:
    deleted, _ = Report.objects.filter(dbid=report_id, owner_id=staff_dbid).delete()
    return deleted >= 1
```

- [ ] **Step 4: Run to verify pass**

`uv run --with pytest pytest tests/services/test_reports.py -q` — Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/services extensions/reporting/tests/services
git commit -m "feat(reporting): saved-report CRUD + visibility service

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: CRUD endpoints on ReportingAPI

**Files:** Modify `extensions/reporting/reporting/routes/reporting_api.py`; modify `extensions/reporting/tests/routes/test_reporting_api.py`.

Add staff resolution and five routes that delegate to the service. Reuse the existing `StaffSessionAuthMixin`.

- [ ] **Step 1: Write failing tests** — append to `tests/routes/test_reporting_api.py`:

```python
def test_create_report_returns_id():
    from unittest.mock import patch
    body = {"name": "No-shows", "category": "Operations", "visibility": "shared",
            "definition": {"dataset_key": "appointments", "measure_key": "no_show_rate"}}
    h = _handler(body)
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.report_service.create") as mock_create:
        from unittest.mock import MagicMock
        mock_create.return_value = MagicMock(dbid=42)
        responses = h.create_report()
    assert responses[0].data["id"] == 42


def test_list_reports_returns_summaries():
    from unittest.mock import patch, MagicMock
    h = _handler()
    row = MagicMock(dbid=1, name="X", category="Operations", visibility="shared", owner_id=5)
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.report_service.list_visible", return_value=[row]):
        responses = h.list_reports()
    assert responses[0].data["reports"][0]["id"] == 1
    assert "definition" not in responses[0].data["reports"][0]


def test_get_report_404_when_missing():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"report_id": "99"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.report_service.get_visible", return_value=None):
        responses = h.get_report()
    assert responses[0].status_code == 404


def test_delete_report_conflict_returns_404():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"report_id": "9"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.report_service.delete", return_value=False):
        responses = h.delete_report()
    assert responses[0].status_code == 404
```

(Ensure `_handler` in this file sets `h.request.path_params = {}` by default — it already creates a MagicMock request; add `h.request.path_params = {}` in `_handler` if not present.)

- [ ] **Step 2: Run to verify fail**

`uv run --with pytest pytest tests/routes/test_reporting_api.py -q` — Expected: FAIL (methods/`report_service` not defined).

- [ ] **Step 3: Implement** — in `routes/reporting_api.py`, add imports and a staff helper near the top (after existing imports):

```python
from http import HTTPStatus

from canvas_sdk.v1.data import Staff

from reporting.services import reports as report_service
```

Add module-level helper:

```python
def _current_staff_dbid(handler) -> int:
    uuid = handler.request.headers.get("canvas-logged-in-user-id", "")
    return Staff.objects.get(id=uuid).dbid
```

Add these methods to `ReportingAPI` (delegating to the service):

```python
    @api.get("/reports")
    def list_reports(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        rows = report_service.list_visible(staff_dbid)
        return [JSONResponse({"reports": [report_service.serialize_summary(r) for r in rows]})]

    @api.post("/reports")
    def create_report(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        try:
            row = report_service.create(
                staff_dbid=staff_dbid,
                name=body["name"],
                category=body.get("category", ""),
                visibility=body.get("visibility", "private"),
                definition=body.get("definition", {}),
            )
        except KeyError as exc:
            return [JSONResponse({"error": f"missing field: {exc}"},
                                 status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"id": row.dbid}, status_code=HTTPStatus.CREATED)]

    @api.get("/reports/<report_id>")
    def get_report(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        row = report_service.get_visible(report_id, staff_dbid)
        if row is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(report_service.serialize_detail(row))]

    @api.patch("/reports/<report_id>")
    def update_report(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        fields = {k: body[k] for k in ("name", "category", "visibility", "definition") if k in body}
        ok = report_service.update(
            report_id=report_id, staff_dbid=staff_dbid,
            expected_version=int(body.get("version", 0)), fields=fields,
        )
        if not ok:
            return [JSONResponse({"error": "conflict or not owner"},
                                 status_code=HTTPStatus.CONFLICT)]
        return [JSONResponse({"ok": True})]

    @api.delete("/reports/<report_id>")
    def delete_report(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        ok = report_service.delete(report_id, staff_dbid)
        if not ok:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"ok": True})]
```

(If `HTTPStatus` is already imported in the file, don't duplicate it.)

- [ ] **Step 4: Run to verify pass**

`uv run --with pytest pytest tests/routes/test_reporting_api.py -q` — Expected: all pass (prior 7 + 4 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/routes/reporting_api.py extensions/reporting/tests/routes/test_reporting_api.py
git commit -m "feat(reporting): saved-report CRUD endpoints (list/create/get/update/delete)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Manifest — enable custom-data persistence

**Files:** Modify `extensions/reporting/reporting/CANVAS_MANIFEST.json`.

- [ ] **Step 1: Add custom_data + secret + read perms.** Insert a top-level `"custom_data"` block and add the secret; add `Staff` to the protocol's read access:

```json
    "custom_data": {
        "namespace": "canvas_medical__reporting",
        "access": "read_write"
    },
    "secrets": ["namespace_read_write_access_key"],
```
And in the `protocols[0].data_access.read` array, ensure `"Staff"` is present (it already is) — no `write` entries needed (custom-data writes are governed by the namespace key, not data_access).

- [ ] **Step 2: Validate JSON + manifest schema**

`python3 -c "import json; json.load(open('extensions/reporting/reporting/CANVAS_MANIFEST.json'))"` (valid), and confirm `custom_data.access == "read_write"`.

- [ ] **Step 3: Full test suite green**

From `extensions/reporting`: `uv run --with pytest pytest tests/ -q` — Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/CANVAS_MANIFEST.json
git commit -m "feat(reporting): declare custom-data namespace for report persistence

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: SPA — library + 4-step builder + visualizations

**Files:** Replace `templates/app.html`, `static/css/app.css`, `static/js/app.js`. Add static-serving routes for any new JS if split. (Static assets — validated by training smoke test, not unit tests.)

This is the largest UI task. Build the SPA as three views switched client-side: **Library** (default), **Builder**, **Viewer**. All data comes from the existing endpoints: `GET /datasets`, `POST /run`, and the `/reports` CRUD from Task 4.

- [ ] **Step 1: Replace `templates/app.html`** with a shell hosting a header, a `#view` container, and the script. Keep `{{ api_base }}`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Reporting</title>
  <link rel="stylesheet" href="{{ api_base }}/app.css" />
</head>
<body>
  <header class="topbar">
    <div><h1>Reporting</h1><p class="sub">Build dashboards and reports — no SQL required</p></div>
    <div id="header-actions"></div>
  </header>
  <main id="view"></main>
  <script>window.API_BASE = "{{ api_base }}";</script>
  <script src="{{ api_base }}/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Replace `static/js/app.js`** with a small framework-free app. It must:
  - `escapeHtml()` helper (reuse Phase-1 pattern) for ALL data-derived strings.
  - `api(path, opts)` fetch helper (JSON), prefixed with `window.API_BASE`.
  - **Library view:** `GET /reports` → grid of cards (name, category tag, visibility, owner). A "＋ New report" button → Builder. Clicking a card → Viewer.
  - **Builder view:** loads `GET /datasets`; renders the 4 steps:
    1. Data: `<select>` of datasets.
    2. Filter: dynamic rows (field `<select>` from the dataset's fields → operator `<select>` constrained to that field's `operators` → value input; "+ Add filter"/remove).
    3. Summarize: measure `<select>` (dataset measures), group-by `<select>` (dataset dimensions, plus "None"), and a "Compare over time" block (granularity select Month/Week/Quarter, "Last N periods" number, "rolling 12-month" checkbox enabled only for Month).
    4. Visualize: a toggle of the five types (Bar, Compare table, Trend, KPI, Table).
  - A **live preview** panel that, on any change, POSTs the assembled definition to `/run` and renders the result with the chosen visualization (debounce ~300ms).
  - **Save:** name + category + visibility inputs → `POST /reports` (or `PATCH` when editing an existing one) → go to Library.
  - **Viewer view:** `GET /reports/<id>` → POST its `definition` to `/run` → render; buttons Edit (→ Builder pre-filled) and Delete (`DELETE /reports/<id>`).
  - **Visualization renderers** (pure functions from a `/run` result `{periods, rows:[{group_label, values}], measure}`):
    - `renderTable` — group rows × period columns (the Phase-1 table, generalized).
    - `renderCompareTable` — same plus a Δ-vs-prior column.
    - `renderBar` — grouped horizontal bars; when >1 period, shade oldest→newest.
    - `renderTrend` — one line per group across periods (SVG polyline).
    - `renderKpi` — when no group_by: the latest period value as a big number with Δ vs prior.
  Keep each renderer a small named function returning an HTML string; the builder picks the renderer by the Step-4 selection. Reuse Canvas dark-theme classes from `app.css`.

(Full JS is ~250–350 lines; write it in focused, named functions — `renderLibrary`, `renderBuilder`, `collectDefinition`, `runPreview`, and the five `render*` viz functions — so each is independently understandable. Do NOT inline everything in one closure.)

- [ ] **Step 3: Expand `static/css/app.css`** with classes for: cards grid, builder two-column layout (steps left, preview right), filter pill rows, segmented toggles, the bar/table/KPI styles. Reuse the Canvas palette variables already defined.

- [ ] **Step 4: Full unit suite still green** (these files aren't imported by tests): `uv run --with pytest pytest tests/ -q` — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/templates extensions/reporting/reporting/static
git commit -m "feat(reporting): SPA library + 4-step builder + five visualizations

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Deploy to training + verify persistence end-to-end

pytest cannot exercise the sandbox or the real custom-data table. Validate live.

- [ ] **Step 1: Deploy** — from repo root: `canvas install extensions/reporting/reporting --host training`.

- [ ] **Step 2: Check logs for import/sandbox errors**

`canvas logs --host training --since 3m --no-follow --limit 600 | grep -c "Error importing module 'reporting"` → expect `0`. Also confirm `Loading handler "...ReportingAPI"`. If `Report` model import fails (e.g. a field class not on the allowlist), capture the exact name and report it.

- [ ] **Step 3: Browser smoke test** on training:
  1. Open app drawer → Reporting → lands on the **Library** (empty or with prior reports).
  2. New report → build "No-show rate by provider, last 3 months, bar" → preview renders.
  3. Save (shared) → returns to Library showing the card.
  4. Reopen the saved report (Viewer) → renders. Edit → change to "Compare table" → save → re-render.
  5. Reload the whole app → the saved report persists (confirms the custom-data table).
  6. Delete → card disappears.

- [ ] **Step 4: Confirm no `NamespaceWriteDenied`** in logs during save (would mean the `custom_data.access` / secret isn't configured on the instance — the operator must set `namespace_read_write_access_key`). Report if so.

- [ ] **Step 5: Commit any fixes; push branch**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git push origin add-reporting-plugin
```

---

## Definition of Done (Phase 2)

- [ ] `uv run pytest tests/` green (model, service, route, sandbox-guard, plus Phase-1 suite).
- [ ] Plugin loads on training with zero import errors.
- [ ] A user can build a report in the 4-step builder with live preview, switch among the five visualizations, save it (private or shared), see it in the Library, reopen/edit/delete it, and it survives an app reload (persisted).
- [ ] All work committed on `add-reporting-plugin` and pushed.

---

## Self-Review (plan author)

**Spec coverage (Phase-2 scope):** persistence — Task 2 (`Report` CustomModel) + Task 5 (manifest) ✓; CRUD + sharing — Task 3 (service) + Task 4 (endpoints) ✓; builder UI + live preview — Task 6 ✓; five visualizations — Task 6 ✓; save/library/load — Task 4 + Task 6 ✓; period comparison — reuses Phase-1 engine via the definition body ✓. Dashboards/export/scheduling correctly deferred to Phase 3+.

**Placeholder scan:** Backend tasks (1–5) carry complete code. Task 6 (the SPA) intentionally specifies the JS by responsibility + per-function contracts rather than 350 lines of literal JS — flagged as the one judgment-heavy task; the implementer writes it against the named-function spec and it is validated by the Task-7 training smoke test (consistent with how Phase-1's SPA task was handled).

**Type/contract consistency:** the saved `definition` JSON is exactly the `/run` body (`dataset_key`, `measure_key`, `group_by`, `filters`, `period`) — one shape across model, service, endpoints, and SPA. `serialize_summary`/`serialize_detail` field names match the route tests and the SPA's expected keys (`id`, `name`, `category`, `visibility`, `owner_id`, `definition`). `_current_staff_dbid`, `report_service.*` names match between routes and their tests.

**Sandbox check:** new modules (`models/`, `services/`) use real annotations (no `@dataclass`, so future-annotations is irrelevant but none added), full-path imports only, and the model-field imports are proven-safe by the deployed `sticky_note` extension. The Task-1 conftest additions keep the guard tests valid. Task 7 is the real sandbox gate.
