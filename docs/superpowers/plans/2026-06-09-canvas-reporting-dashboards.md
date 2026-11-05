# Canvas Reporting — Phase 3 (Dashboards) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let users compose saved reports into **dashboards** — a flexible grid of widgets, each referencing a saved report, with a dashboard-level period the widgets inherit. Create/edit/view/save/share dashboards, persisted like reports.

**Architecture:** Mirror the proven Phase-2 persistence + CRUD pattern. Add a `Dashboard` `CustomModel` (owner FK via the existing `StaffProxy`, JSON `layout` + `default_period`, private/shared visibility, version lock). Add `/dashboards` CRUD endpoints on `ReportingAPI`. In the SPA, add a Reports/Dashboards switch to the Library, a dashboard **viewer** (grid; each widget fetches its report's definition, applies the dashboard's default period, runs via `/run`, and renders), and a dashboard **editor** (add/remove/reorder widgets, set per-widget column span, set name/visibility/period). Widgets lazy-load as they scroll into view.

**Tech Stack:** Same as Phase 2 — Canvas SDK `CustomModel`/`SimpleAPI`, Django ORM (sandbox-restricted), vanilla JS, `pytest` via `uv`.

**Scope (Phase 3):** dashboard persistence + CRUD + sharing, the grid viewer with period inheritance + lazy-load, the editor (add/remove/reorder/span). **Out of scope (Phase 4+):** CSV/PDF export, scheduled email delivery, cross-widget cascading filters (only a default-period inherit), drag-and-drop reordering (use up/down + span controls in v1).

---

## Reference Facts (proven in Phases 1–2 — obey these)

- **Persistence pattern:** copy `reporting/models/report.py` + `reporting/services/reports.py` + the `/reports` routes. `Dashboard` is auto-discovered (no manifest change — `custom_data` namespace already declared).
- **THREE sandbox rules (enforced by `tests/test_sandbox_imports.py`; all three already cost us a live failure):**
  1. A `@dataclass` module must NOT `from __future__ import annotations`. (Models use plain classes, fine.)
  2. **Import functions/classes by name and call them bare.** NEVER `from reporting.services import dashboards as d; d.create()` — accessing attributes on a plugin module object raises `AttributeError(... not in ALLOWED_MODULES)` at request time. Use `from reporting.services.dashboards import create`.
  3. No self-package imports; full submodule paths only; no cross-module mutable singletons. ORM aggregation names limited to `Count, Case, When, Q, F, Value` — but model field classes (`ForeignKey, TextField, JSONField, IntegerField, DateTimeField`) and queryset methods (`.values()/.filter()/.distinct()/.order_by()/.update()/.create()`) are fine at module level.
- **pytest cannot catch sandbox failures** — Task at the end deploys to `training` and greps logs for `Error importing module 'reporting` and `not in ALLOWED_MODULES`.
- **Current staff:** `_current_staff_dbid(self)` already exists in the routes module.
- **Reuse:** the SPA already has `api()`, `renderVisualization()`, the five renderers, `escapeHtml()`, `categoryTagClass()`, `setTopbarActions()`, `showLibrary()`. The dashboard viewer renders each widget by POSTing a report definition to `/run` and calling `renderVisualization(vizType, result)`.
- **Deploy:** `canvas install extensions/reporting/reporting --host training` (repo root). Tests: from `extensions/reporting`, `uv run --with pytest pytest tests/ -q` (58 passing at Phase-2 end).

---

## Data shapes

- **Dashboard.layout** (JSON): `{ "widgets": [ { "report_id": int, "span": 1|2|3|4, "viz": "bar"|"compare_table"|"trend"|"kpi"|"table"|null } ] }` — order in the list IS the grid order. `viz: null` -> use the report's own default.
- **Dashboard.default_period** (JSON, optional): `{ granularity, count, include_rolling_12 }` — when set, each widget's report definition has its `period` replaced by this before `/run` (period inheritance). When absent, each widget uses its report's own period.
- **CRUD bodies** mirror reports: create `{ name, visibility, layout, default_period }`; summary serialization `{ id, name, visibility, owner_id, widget_count }`; detail adds `layout`, `default_period`.

---

## File Structure (this phase)

```
reporting/models/dashboard.py            # Dashboard(CustomModel)
reporting/services/dashboards.py         # CRUD + visibility (mirror reports.py)
reporting/routes/reporting_api.py        # + /dashboards endpoints (modify)
reporting/static/js/app.js               # + dashboards tab, viewer, editor (modify)
reporting/static/css/app.css             # + dashboard grid styles (modify)
tests/models/test_dashboard.py
tests/services/test_dashboards.py
tests/routes/test_reporting_api.py       # + dashboard endpoint tests (modify)
```

---

## Task 1: Dashboard model

**Files:** Create `reporting/models/dashboard.py`; create `tests/models/test_dashboard.py`.

- [ ] **Step 1: Failing test** (`tests/models/test_dashboard.py`):

```python
from reporting.models.dashboard import Dashboard


def test_dashboard_is_custom_model():
    from canvas_sdk.v1.data.base import CustomModel
    assert issubclass(Dashboard, CustomModel)


def test_dashboard_holds_layout_and_owner():
    d = Dashboard(name="Weekly Ops", visibility="shared",
                  layout={"widgets": [{"report_id": 1, "span": 2}]},
                  default_period={"granularity": "month", "count": 3},
                  owner_id=5, version=1)
    assert d.name == "Weekly Ops"
    assert d.layout["widgets"][0]["report_id"] == 1
    assert d.owner_id == 5
```

- [ ] **Step 2: Run, expect fail** — `uv run --with pytest pytest tests/models/test_dashboard.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement `reporting/models/dashboard.py`**:

```python
"""Persisted dashboards: an ordered grid of saved-report widgets."""

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


class Dashboard(CustomModel):
    """A named, owned, optionally-shared grid of report widgets.

    layout: {"widgets": [{"report_id": int, "span": 1-4, "viz": str|None}, ...]}
            (list order = grid order)
    default_period: {granularity, count, include_rolling_12} | {} -> widgets inherit
            this period; when empty each widget uses its report's own period.
    """

    owner = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__dashboards",
        null=True,
    )
    name = TextField(default="", blank=True)
    visibility = TextField(default="private")  # "private" | "shared"
    layout = JSONField(default=dict)
    default_period = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    version = IntegerField(default=0)
```

- [ ] **Step 4: Run, expect pass** — 2 passed. Then full suite (expect 60).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/models/dashboard.py extensions/reporting/tests/models/test_dashboard.py
git commit -m "feat(reporting): Dashboard CustomModel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Dashboard CRUD service

**Files:** Create `reporting/services/dashboards.py`; create `tests/services/test_dashboards.py`.

Mirror `reporting/services/reports.py` exactly, swapping `Report`→`Dashboard` and adjusting serialization (summary exposes `widget_count` from `layout`; detail exposes `layout` + `default_period`).

- [ ] **Step 1: Failing tests** (`tests/services/test_dashboards.py`):

```python
from unittest.mock import MagicMock, patch

from reporting.services import dashboards as svc


def test_serialize_summary_has_widget_count():
    row = MagicMock(dbid=2, visibility="shared", owner_id=5,
                    layout={"widgets": [{"report_id": 1}, {"report_id": 2}]})
    row.name = "Ops"
    out = svc.serialize_summary(row)
    assert out == {"id": 2, "name": "Ops", "visibility": "shared",
                   "owner_id": 5, "widget_count": 2}


def test_serialize_detail_has_layout_and_period():
    row = MagicMock(dbid=2, visibility="private", owner_id=5,
                    layout={"widgets": []}, default_period={"granularity": "month"})
    row.name = "Ops"
    out = svc.serialize_detail(row)
    assert out["layout"] == {"widgets": []}
    assert out["default_period"] == {"granularity": "month"}


def test_list_visible_owned_or_shared():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.filter.return_value.order_by.return_value = ["a"]
        assert svc.list_visible(staff_dbid=5) == ["a"]
        assert M.objects.filter.called


def test_create_sets_owner_and_version():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.create.return_value = MagicMock(dbid=7)
        out = svc.create(staff_dbid=5, name="Ops", visibility="shared",
                         layout={"widgets": []}, default_period={})
        kwargs = M.objects.create.call_args.kwargs
        assert kwargs["owner_id"] == 5 and kwargs["version"] == 1
        assert out.dbid == 7


def test_update_optimistic_lock():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.filter.return_value.update.return_value = 1
        assert svc.update(dashboard_id=7, staff_dbid=5, expected_version=1,
                          fields={"name": "X"}) is True
        M.objects.filter.assert_called_with(dbid=7, owner_id=5, version=1)


def test_delete_only_owner():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.filter.return_value.delete.return_value = (1, {})
        assert svc.delete(dashboard_id=7, staff_dbid=5) is True
        M.objects.filter.assert_called_with(dbid=7, owner_id=5)
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement `reporting/services/dashboards.py`**:

```python
"""CRUD + visibility logic for dashboards. Thin wrapper over Dashboard.objects."""

from django.db.models import Q

from reporting.models.dashboard import Dashboard


def serialize_summary(row) -> dict:
    widgets = (row.layout or {}).get("widgets", []) if isinstance(row.layout, dict) else []
    return {
        "id": row.dbid,
        "name": row.name,
        "visibility": row.visibility,
        "owner_id": row.owner_id,
        "widget_count": len(widgets),
    }


def serialize_detail(row) -> dict:
    out = serialize_summary(row)
    out["layout"] = row.layout
    out["default_period"] = row.default_period
    return out


def list_visible(staff_dbid: int):
    return Dashboard.objects.filter(
        Q(owner_id=staff_dbid) | Q(visibility="shared")
    ).order_by("-updated_at")


def get_visible(dashboard_id: int, staff_dbid: int):
    return (
        Dashboard.objects.filter(dbid=dashboard_id)
        .filter(Q(owner_id=staff_dbid) | Q(visibility="shared"))
        .first()
    )


def create(staff_dbid: int, name: str, visibility: str, layout: dict,
           default_period: dict):
    return Dashboard.objects.create(
        owner_id=staff_dbid,
        name=name,
        visibility=visibility if visibility in ("private", "shared") else "private",
        layout=layout,
        default_period=default_period,
        version=1,
    )


def update(dashboard_id: int, staff_dbid: int, expected_version: int,
           fields: dict) -> bool:
    rows = Dashboard.objects.filter(
        dbid=dashboard_id, owner_id=staff_dbid, version=expected_version
    ).update(version=expected_version + 1, **fields)
    return rows == 1


def delete(dashboard_id: int, staff_dbid: int) -> bool:
    deleted, _ = Dashboard.objects.filter(dbid=dashboard_id, owner_id=staff_dbid).delete()
    return deleted >= 1
```

- [ ] **Step 4: Run, expect pass** — 6 passed; full suite 66.

- [ ] **Step 5: Commit**

```bash
git add extensions/reporting/reporting/services/dashboards.py extensions/reporting/tests/services/test_dashboards.py
git commit -m "feat(reporting): dashboard CRUD + visibility service

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Dashboard CRUD endpoints

**Files:** Modify `reporting/routes/reporting_api.py`; modify `tests/routes/test_reporting_api.py`.

**CRITICAL:** import the service functions BY NAME (sandbox rule #2):

```python
from reporting.services.dashboards import (
    create as dash_create,
    delete as dash_delete,
    get_visible as dash_get_visible,
    list_visible as dash_list_visible,
    serialize_detail as dash_detail,
    serialize_summary as dash_summary,
    update as dash_update,
)
```

- [ ] **Step 1: Failing tests** — append to `tests/routes/test_reporting_api.py`:

```python
def test_list_dashboards_returns_summaries():
    from unittest.mock import patch, MagicMock
    h = _handler()
    row = MagicMock(dbid=1, visibility="shared", owner_id=5,
                    layout={"widgets": [{"report_id": 9}]})
    row.name = "Ops"
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_list_visible", return_value=[row]):
        responses = h.list_dashboards()
    assert responses[0].data["dashboards"][0]["widget_count"] == 1


def test_create_dashboard_returns_id():
    from unittest.mock import patch, MagicMock
    body = {"name": "Ops", "visibility": "shared",
            "layout": {"widgets": []}, "default_period": {}}
    h = _handler(body)
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_create", return_value=MagicMock(dbid=7)):
        responses = h.create_dashboard()
    assert responses[0].data["id"] == 7


def test_get_dashboard_404_when_missing():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"dashboard_id": "99"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_get_visible", return_value=None):
        responses = h.get_dashboard()
    assert responses[0].status_code == 404


def test_delete_dashboard_404_when_not_owner():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"dashboard_id": "7"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_delete", return_value=False):
        responses = h.delete_dashboard()
    assert responses[0].status_code == 404
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** — add the import block above (with the other imports), and these methods to `ReportingAPI` (mirror the report endpoints exactly, using path param `<dashboard_id>`):

```python
    @api.get("/dashboards")
    def list_dashboards(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        rows = dash_list_visible(staff_dbid)
        return [JSONResponse({"dashboards": [dash_summary(r) for r in rows]})]

    @api.post("/dashboards")
    def create_dashboard(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        try:
            row = dash_create(
                staff_dbid=staff_dbid,
                name=body["name"],
                visibility=body.get("visibility", "private"),
                layout=body.get("layout", {"widgets": []}),
                default_period=body.get("default_period", {}),
            )
        except KeyError as exc:
            return [JSONResponse({"error": f"missing field: {exc}"},
                                 status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"id": row.dbid}, status_code=HTTPStatus.CREATED)]

    @api.get("/dashboards/<dashboard_id>")
    def get_dashboard(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        row = dash_get_visible(int(self.request.path_params["dashboard_id"]), staff_dbid)
        if row is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(dash_detail(row))]

    @api.patch("/dashboards/<dashboard_id>")
    def update_dashboard(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        fields = {k: body[k] for k in ("name", "visibility", "layout", "default_period") if k in body}
        ok = dash_update(
            dashboard_id=int(self.request.path_params["dashboard_id"]),
            staff_dbid=staff_dbid, expected_version=int(body.get("version", 0)), fields=fields,
        )
        if not ok:
            return [JSONResponse({"error": "conflict or not owner"},
                                 status_code=HTTPStatus.CONFLICT)]
        return [JSONResponse({"ok": True})]

    @api.delete("/dashboards/<dashboard_id>")
    def delete_dashboard(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        ok = dash_delete(int(self.request.path_params["dashboard_id"]), staff_dbid)
        if not ok:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"ok": True})]
```

- [ ] **Step 4: Run, expect pass** — full suite 70.

- [ ] **Step 5: Commit**

```bash
git add extensions/reporting/reporting/routes/reporting_api.py extensions/reporting/tests/routes/test_reporting_api.py
git commit -m "feat(reporting): dashboard CRUD endpoints

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: SPA — dashboards tab, viewer, editor

**Files:** Modify `reporting/static/js/app.js` and `reporting/static/css/app.css`. (Static; validated by training smoke test.)

Add named functions; do NOT rewrite existing report functions. Reuse `api()`, `renderVisualization()`, `escapeHtml()`, `categoryTagClass()`, `setTopbarActions()`.

- [ ] **Step 1: Library tab switch.** Modify `showLibrary()` to render a segmented switch **Reports | Dashboards** at the top. Reports tab = existing card grid. Dashboards tab = `GET /dashboards` → dashboard cards (name, "N widgets", Shared/Private). Header gains a "＋ New dashboard" button when on the Dashboards tab. Track the active tab in a module global (default Reports). Clicking a dashboard card → `showDashboardViewer(id)`.

- [ ] **Step 2: Dashboard viewer** (`showDashboardViewer(id)` / `renderDashboardViewer(dashboard, reportsById)`):
  - `GET /dashboards/<id>` → the dashboard with `layout.widgets` + `default_period`.
  - Render a CSS-grid (4 columns) container; for each widget create a tile spanning `widget.span` columns, with the referenced report's name as a header and a `data-report-id`/`data-viz` placeholder body ("Loading…").
  - **Lazy-load:** use an `IntersectionObserver`; when a tile scrolls into view, `GET /reports/<report_id>` (cache by id), take its `definition`, and if the dashboard has a non-empty `default_period`, override `definition.period` with it; POST to `/run`; render with `renderVisualization(widget.viz || defaultVizFor(definition), result)` into the tile body. Handle a deleted/missing referenced report gracefully (show "Report unavailable").
  - Header: dashboard name + a **Period** control (granularity + count) reflecting `default_period`; changing it re-runs all widgets with the new inherited period (no save unless they save). Buttons: **Edit**, **Delete** (confirm → `DELETE` → back to Library).

- [ ] **Step 3: Dashboard editor** (`showDashboardEditor(id|null)` / `renderDashboardEditor(dashboard, allReports)`):
  - Load `GET /reports` (the user's saved reports, to choose from) and (if editing) `GET /dashboards/<id>`.
  - Controls: dashboard **name**, **visibility** (Private/Shared), **default period** (granularity + count + rolling-12 checkbox, month-only rule like the builder).
  - **Widgets editor:** an ordered list; each row = a saved-report `<select>` (the report for that widget), a **span** `<select>` (1–4 columns), a **viz** `<select>` (Auto / Bar / Compare / Trend / KPI / Table), **↑/↓** reorder buttons, and a **remove** (✕). "＋ Add widget" appends a row defaulting to the first report. (Drag-and-drop is a later polish; up/down is sufficient.)
  - A live **preview grid** beside/below the editor that renders the current widget set (reuse the viewer's render path).
  - **Save:** `collectDashboard()` builds `{ name, visibility, layout:{widgets:[{report_id,span,viz}]}, default_period }` → `POST /dashboards` (new) or `PATCH /dashboards/<id>` with `version` → back to Library (Dashboards tab).

- [ ] **Step 4: CSS** — add a `.dash-grid` (CSS `display:grid; grid-template-columns:repeat(4,1fr); gap:16px`), `.dash-tile` (spanning via `grid-column: span N`), tile header/body, the library tab switch, and the widget-editor rows. Reuse the Canvas palette variables.

- [ ] **Step 5: Full unit suite still green** (JS not unit-tested): `uv run --with pytest pytest tests/ -q` → 70.

- [ ] **Step 6: Commit**

```bash
git add extensions/reporting/reporting/static
git commit -m "feat(reporting): dashboards tab, grid viewer with period inheritance, editor

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Deploy to training + verify

- [ ] **Step 1: Deploy** — `canvas install extensions/reporting/reporting --host training` (repo root).
- [ ] **Step 2: Logs** — `canvas logs --host training --since 3m --no-follow | grep -c "Error importing module 'reporting"` → 0; also grep `not in ALLOWED_MODULES` → 0. Confirm `Loading handler "...ReportingAPI"`.
- [ ] **Step 3: Browser smoke test:**
  1. Library → **Dashboards** tab → **＋ New dashboard**.
  2. Add 2–3 widgets from saved reports, set spans, reorder, set a default period → preview renders each widget.
  3. Save (Shared) → appears as a dashboard card.
  4. Open it → grid renders; widgets lazy-load on scroll; changing the header Period re-runs widgets.
  5. Edit → change a span / remove a widget → save → re-render. Delete a referenced report elsewhere, reopen dashboard → that tile shows "Report unavailable" (graceful).
  6. Reload app → dashboard persists.
- [ ] **Step 4: Push** — `git push origin add-reporting-plugin`.

---

## Definition of Done (Phase 3)

- [ ] `uv run pytest tests/` green (~70).
- [ ] Plugin loads on training, zero import/ALLOWED_MODULES errors.
- [ ] A user can build a dashboard from saved reports (add/remove/reorder/span), set an inherited period, save (private/shared), view it (widgets lazy-load and render), edit, delete; missing referenced reports degrade gracefully; dashboards persist across reload.
- [ ] Committed + pushed on `add-reporting-plugin`.

---

## Self-Review (plan author)

**Spec coverage (Phase-3 scope):** dashboard persistence — Task 1; CRUD + sharing — Tasks 2–3; grid viewer + period inheritance + lazy-load — Task 4 Step 2; editor (add/remove/reorder/span) — Task 4 Step 3; graceful missing-report handling — Task 4 Step 2. Export/scheduling/cascading-filters correctly deferred to Phase 4. Drag-and-drop explicitly downgraded to up/down for v1 (noted).

**Placeholder scan:** backend Tasks 1–3 carry complete code and tests. Task 4 (SPA) is specified by named functions + contracts (consistent with Phase-2's SPA task) and validated by the Task-5 training smoke test — flagged as the judgment-heavy task.

**Consistency:** `layout.widgets[*] = {report_id, span, viz}` is identical across model docstring, service `widget_count`, endpoint bodies, and the SPA `collectDashboard()`. Service/endpoint names match the route tests (`dash_create`, `dash_list_visible`, etc., imported by name per sandbox rule #2). `default_period` shape == the `/run` period shape, so period inheritance is a direct field swap. CRUD/visibility/optimistic-lock logic mirrors the proven `reports` service exactly.
