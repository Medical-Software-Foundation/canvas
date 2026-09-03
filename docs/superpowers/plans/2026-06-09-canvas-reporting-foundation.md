# Canvas Reporting — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Reporting plugin so it launches full-page from the Canvas app drawer, loads an SPA shell, and returns a live "no-show rate by provider" result from the Appointments dataset end-to-end — built on a declarative dataset layer and a sandbox-safe query engine.

**Architecture:** A Canvas plugin (`extensions/reporting/`) modeled on the existing `staff_directory` extension. A global `Application` launches a full-page modal pointing at a `SimpleAPI` HTML route that serves the SPA shell; JSON routes return query results. A pure-Python query engine (no Django `Sum`/`Avg`/`Trunc` — those are sandbox-blocked) translates declarative dataset + report definitions into `Count(filter=Q(...))` grouped queries and computes rates/periods in Python.

**Tech Stack:** Python 3.11+, Canvas SDK (`Application`, `SimpleAPI`, `StaffSessionAuthMixin`, `render_to_string`, `canvas_sdk.v1.data` ORM models), Django ORM (sandbox-restricted), vanilla HTML/CSS/JS for the SPA, `pytest` via `uv`, SDK stubbed in tests.

**Scope (Phase 1 only):** plugin scaffold + manifest, global Application + full-page launch, SPA shell, the declarative dataset format, the Appointments dataset, the query engine (filters + measures + period comparison), a JSON results endpoint, and a minimal SPA that renders one result. **Out of scope this phase:** the 4-step builder UI, saving/persisting reports (`CustomModel`), dashboards, exports, scheduling, and additional datasets. Those are later phases.

---

## Reference Facts (verified against the codebase — do not re-derive)

- **Template extension:** `extensions/staff_directory/` (global app + SimpleAPI HTML/JSON + `services/` + stubbed tests). Mirror its layout.
- **Directory layout:** outer `extensions/reporting/` holds `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`, `tests/`, and the inner package `reporting/`. The inner package holds `CANVAS_MANIFEST.json`, `__init__.py`, `applications/`, `routes/`, `services/`, `query/`, `datasets/`, `templates/`, `static/css|js/`, `assets/`.
- **Manifest `name`** must equal the inner package dir name: `reporting`. `class` paths are `reporting.<module>:<Class>`.
- **App scope** for a global (non-patient) app: `"scope": "global"`. `icon` is **required** (relative path, e.g. `assets/icon.png`). Optional `"menu_position": "top"`.
- **Launch:** `LaunchModalEffect(url="/plugin-io/api/reporting/app/home", target=LaunchModalEffect.TargetType.PAGE, title="Reporting").apply()`.
- **SimpleAPI URL shape:** `/plugin-io/api/reporting/<PREFIX><route>` where `<PREFIX>` is the handler's `PREFIX` class attr. `name` segment is the manifest `name` (`reporting`).
- **Auth:** subclass `StaffSessionAuthMixin, SimpleAPI` — do NOT write `authenticate()`. Logged-in staff id header: `canvas-logged-in-user-id`.
- **Responses:** every route returns `list[Response | Effect]`. `HTMLResponse(str)`, `JSONResponse(dict)`, `Response(bytes, status_code, headers, content_type)` for CSS/JS.
- **Templates/static:** `render_to_string("templates/app.html", context)` and `render_to_string("static/css/app.css")`; paths are relative to the inner package root. Static files are served through routes.
- **SANDBOX IMPORT ALLOWLIST (critical):** from `django.db.models` only `Count, Case, When, Q, F, Value, Model, CharField, IntegerField, BigIntegerField` are importable. **`Sum`, `Avg`, `Max`, `Min`, `ExpressionWrapper`, `Trunc*`, `OuterRef`, `Subquery` are BLOCKED.** Do every sum/ratio in Python; do period bucketing as N separate date-range queries.
- **Appointment model** (`canvas_sdk.v1.data.appointment.Appointment`): fields `provider` (FK Staff, nullable), `location` (FK PracticeLocation, nullable), `start_time` (DateTimeField), `status` (CharField). Status enum `AppointmentProgressStatus`: `unconfirmed, attempted, confirmed, arrived, roomed, exited, noshowed, cancelled`. **No-show is the literal string `"noshowed"`.** Group via `provider__id`; pull display via `provider__first_name`, `provider__last_name`.
- **PK for counting:** `Count("dbid")` (every SDK model has `dbid`).
- **Tests:** SDK + Django are NOT installed; `tests/conftest.py` stubs them in `sys.modules`. Logic lives in pure modules (`query/`, `datasets/`, `services/`) tested as plain functions. Run from the extension dir: `uv run pytest tests/`.
- **No `CLAUDE.md`/`REVIEW.md`** in the repo. Conventions: `from __future__ import annotations` atop modules, type hints, docstrings on classes/routes, Ruff formatting, snake_case package.

---

## File Structure (created this phase)

```
extensions/reporting/
├── pyproject.toml                         # uv project + pytest config
├── README.md
├── LICENSE
├── reporting/                             # inner package (manifest "name")
│   ├── __init__.py
│   ├── CANVAS_MANIFEST.json               # registers Application + SimpleAPI protocol
│   ├── assets/icon.png                    # app drawer icon
│   ├── applications/
│   │   ├── __init__.py
│   │   └── reporting_app.py               # global Application launcher
│   ├── routes/
│   │   ├── __init__.py
│   │   └── reporting_api.py               # SimpleAPI: HTML shell + static + results JSON
│   ├── query/
│   │   ├── __init__.py
│   │   ├── periods.py                     # period window math (pure)
│   │   ├── filters.py                     # FilterClause -> Q (pure)
│   │   ├── measures.py                    # measure defs + count-annotation specs + ratio math (pure)
│   │   └── engine.py                      # orchestration: build qs, run per period, merge (executor-injected)
│   ├── datasets/
│   │   ├── __init__.py                    # dataset registry
│   │   └── appointments.py                # Appointments dataset definition
│   ├── templates/
│   │   └── app.html                       # SPA shell
│   └── static/
│       ├── css/app.css
│       └── js/app.js                      # calls results endpoint, renders a table
└── tests/
    ├── __init__.py
    ├── conftest.py                        # SDK/Django stubs
    ├── applications/{__init__.py,test_reporting_app.py}
    ├── routes/{__init__.py,test_reporting_api.py}
    ├── query/{__init__.py,test_periods.py,test_filters.py,test_measures.py,test_engine.py}
    └── datasets/{__init__.py,test_appointments.py}
```

---

## Task 0: Scaffold the extension project

**Files:**
- Create: `extensions/reporting/pyproject.toml`
- Create: `extensions/reporting/README.md`
- Create: `extensions/reporting/LICENSE`
- Create: `extensions/reporting/reporting/__init__.py` (empty)
- Create: all `__init__.py` files for `applications/`, `routes/`, `query/`, `datasets/`, and every `tests/` subdir (empty)
- Create: `extensions/reporting/reporting/assets/icon.png`

- [ ] **Step 1: Create the directory tree and empty `__init__.py` files**

```bash
cd /Users/amandap-canvas/Code/msf-canvas/extensions
mkdir -p reporting/reporting/{applications,routes,query,datasets,templates,static/css,static/js,assets}
mkdir -p reporting/tests/{applications,routes,query,datasets}
touch reporting/reporting/__init__.py \
      reporting/reporting/applications/__init__.py \
      reporting/reporting/routes/__init__.py \
      reporting/reporting/query/__init__.py \
      reporting/reporting/datasets/__init__.py \
      reporting/tests/__init__.py \
      reporting/tests/applications/__init__.py \
      reporting/tests/routes/__init__.py \
      reporting/tests/query/__init__.py \
      reporting/tests/datasets/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
authors = [
  {email = "amanda.peterson@canvasmedical.com", name = "Amanda Peterson"}
]
description = "In-UI report and dashboard builder for non-technical users, backed by Canvas SDK Data Models."
license = "MIT"
name = "reporting"
readme = "README.md"
requires-python = ">=3.11"
version = "0.1.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v"

[tool.coverage.run]
source = ["reporting"]
omit = ["tests/*", "*/tests/*", "*/__pycache__/*"]
```

- [ ] **Step 3: Write a minimal `README.md` and `LICENSE`**

`README.md`:
```markdown
# Reporting

In-UI report and dashboard builder for Canvas. Launches from the app drawer as a
full-page app. Non-technical users build reports on curated datasets — no SQL.

See the design spec: `docs/superpowers/specs/2026-06-09-canvas-reporting-app-design.md`.
```

`LICENSE`: copy the MIT license text from `extensions/staff_directory/LICENSE`:
```bash
cp /Users/amandap-canvas/Code/msf-canvas/extensions/staff_directory/LICENSE \
   /Users/amandap-canvas/Code/msf-canvas/extensions/reporting/LICENSE
```

- [ ] **Step 4: Provide a placeholder app icon**

```bash
cp /Users/amandap-canvas/Code/msf-canvas/extensions/staff_directory/staff_directory/assets/icon.png \
   /Users/amandap-canvas/Code/msf-canvas/extensions/reporting/reporting/assets/icon.png
```
(Replace with a real Reporting icon later; a 48x48 PNG is required. The `cpa:icon-generation` skill can produce one.)

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting
git commit -m "feat(reporting): scaffold extension project structure"
```

---

## Task 1: Test stubs (conftest)

**Files:**
- Create: `extensions/reporting/tests/conftest.py`

This conftest stubs `canvas_sdk` and `django.db.models` so plugin modules import without the real SDK. It extends the `staff_directory` pattern with the ORM aggregation names and an `Appointment` stub the query/dataset modules need.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
"""Shared test fixtures and Django/Canvas-SDK stubs.

canvas_sdk and Django are not installed in the test env. We stub just enough of
the surface area to let plugin modules import cleanly, then mock behavior per case.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _ensure_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_django_stubs() -> None:
    _ensure_module("django")
    django_db = _ensure_module("django.db")
    m = _ensure_module("django.db.models")

    class Q:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.children = [("AND", list(kwargs.items()))]

        def __or__(self, other):
            combined = Q()
            combined.children = [("OR", [self, other])]
            return combined

        def __and__(self, other):
            combined = Q()
            combined.children = [("AND", [self, other])]
            return combined

    class _Expr:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    m.Q = Q
    for name in ("Count", "Case", "When", "Value", "F"):
        setattr(m, name, type(name, (_Expr,), {}))
    sys.modules["django.db"] = django_db
    sys.modules["django.db.models"] = m


def _install_canvas_sdk_stubs() -> None:
    _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    data = _ensure_module("canvas_sdk.v1.data")
    appt_mod = _ensure_module("canvas_sdk.v1.data.appointment")
    effects_mod = _ensure_module("canvas_sdk.effects")
    launch_modal_mod = _ensure_module("canvas_sdk.effects.launch_modal")
    simple_api_effects = _ensure_module("canvas_sdk.effects.simple_api")
    _ensure_module("canvas_sdk.handlers")
    app_mod = _ensure_module("canvas_sdk.handlers.application")
    simple_api_mod = _ensure_module("canvas_sdk.handlers.simple_api")
    templates_mod = _ensure_module("canvas_sdk.templates")

    class Effect:
        pass

    effects_mod.Effect = Effect

    class _Applied:
        def __init__(self, owner):
            self.owner = owner

    class LaunchModalEffect:
        class TargetType:
            DEFAULT_MODAL = "default_modal"
            NEW_WINDOW = "new_window"
            RIGHT_CHART_PANE = "right_chart_pane"
            RIGHT_CHART_PANE_LARGE = "right_chart_pane_large"
            PAGE = "page"
            NOTE = "note"

        def __init__(self, url=None, content=None, target=None, title="Untitled"):
            self.url = url
            self.content = content
            self.target = target
            self.title = title

        def apply(self):
            return _Applied(self)

    launch_modal_mod.LaunchModalEffect = LaunchModalEffect

    class Response:
        def __init__(self, content=None, status_code=200, headers=None, content_type=None):
            self.content = content
            self.status_code = status_code
            self.headers = headers or {}
            self.content_type = content_type

    class HTMLResponse(Response):
        def __init__(self, content="", status_code=200, headers=None):
            super().__init__(content, status_code, headers, "text/html")

    class JSONResponse(Response):
        def __init__(self, content=None, status_code=200, headers=None):
            super().__init__(content, status_code, headers, "application/json")
            self.data = content  # tests assert on resp.data

    simple_api_effects.Response = Response
    simple_api_effects.HTMLResponse = HTMLResponse
    simple_api_effects.JSONResponse = JSONResponse

    class Application:
        def __init__(self, *args, **kwargs):
            self.context = {}

    app_mod.Application = Application

    class SimpleAPI:
        def __init__(self, *args, **kwargs):
            pass

    class StaffSessionAuthMixin:
        pass

    class _Api:
        def _decorator(self, *a, **k):
            def wrap(fn):
                return fn
            return wrap

        get = post = patch = delete = _decorator

    simple_api_mod.SimpleAPI = SimpleAPI
    simple_api_mod.StaffSessionAuthMixin = StaffSessionAuthMixin
    simple_api_mod.api = _Api()

    templates_mod.render_to_string = lambda name, ctx=None: f"RENDERED:{name}"

    class _Status:
        completed = "completed"
        unconfirmed = "unconfirmed"
        confirmed = "confirmed"
        noshowed = "noshowed"
        cancelled = "cancelled"

    class AppointmentProgressStatus:
        UNCONFIRMED = "unconfirmed"
        ATTEMPTED = "attempted"
        CONFIRMED = "confirmed"
        ARRIVED = "arrived"
        ROOMED = "roomed"
        EXITED = "exited"
        NOSHOWED = "noshowed"
        CANCELLED = "cancelled"

    class Appointment:
        objects = MagicMock()

    appt_mod.Appointment = Appointment
    appt_mod.AppointmentProgressStatus = AppointmentProgressStatus
    data.Appointment = Appointment


_install_django_stubs()
_install_canvas_sdk_stubs()
```

- [ ] **Step 2: Verify pytest collects with the stubs (no tests yet)**

Run: `cd /Users/amandap-canvas/Code/msf-canvas/extensions/reporting && uv run --with pytest pytest tests/ -q`
Expected: `no tests ran` (exit 5) with no import/collection errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/tests/conftest.py
git commit -m "test(reporting): add SDK/Django test stubs"
```

---

## Task 2: Period window math (`query/periods.py`)

The hardest-to-get-right pure logic, and the foundation of comparison. Build it first, fully TDD. Periods are computed in Python (no DB `Trunc`).

**Files:**
- Create: `extensions/reporting/reporting/query/periods.py`
- Test: `extensions/reporting/tests/query/test_periods.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/query/test_periods.py
from __future__ import annotations

from datetime import date, datetime

from reporting.query.periods import PeriodSpec, compute_periods


def test_last_3_months_windows():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=False)
    periods = compute_periods(spec, anchor=date(2026, 6, 15))
    assert [p.label for p in periods] == ["Apr 2026", "May 2026", "Jun 2026"]
    jun = periods[-1]
    assert jun.start == datetime(2026, 6, 1, 0, 0, 0)
    assert jun.end == datetime(2026, 7, 1, 0, 0, 0)  # half-open [start, end)
    apr = periods[0]
    assert apr.start == datetime(2026, 4, 1, 0, 0, 0)
    assert apr.end == datetime(2026, 5, 1, 0, 0, 0)


def test_month_rollover_into_previous_year():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=False)
    periods = compute_periods(spec, anchor=date(2026, 1, 10))
    assert [p.label for p in periods] == ["Nov 2025", "Dec 2025", "Jan 2026"]


def test_rolling_12_months_overrides_count():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=True)
    periods = compute_periods(spec, anchor=date(2026, 6, 15))
    assert len(periods) == 12
    assert periods[0].label == "Jul 2025"
    assert periods[-1].label == "Jun 2026"


def test_quarter_windows():
    spec = PeriodSpec(granularity="quarter", count=2, include_rolling_12=False)
    periods = compute_periods(spec, anchor=date(2026, 5, 1))  # Q2 2026
    assert [p.label for p in periods] == ["Q1 2026", "Q2 2026"]
    assert periods[-1].start == datetime(2026, 4, 1)
    assert periods[-1].end == datetime(2026, 7, 1)


def test_week_windows_start_monday():
    spec = PeriodSpec(granularity="week", count=2, include_rolling_12=False)
    # 2026-06-15 is a Monday
    periods = compute_periods(spec, anchor=date(2026, 6, 17))  # Wed of that week
    assert periods[-1].start == datetime(2026, 6, 15)
    assert periods[-1].end == datetime(2026, 6, 22)
    assert periods[0].start == datetime(2026, 6, 8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_periods.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.query.periods'`.

- [ ] **Step 3: Implement `query/periods.py`**

```python
"""Period window math for time comparison. Pure Python — no DB truncation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GRANULARITIES = ("month", "week", "quarter")


@dataclass(frozen=True)
class PeriodSpec:
    granularity: str           # "month" | "week" | "quarter"
    count: int                 # number of recent periods (e.g. 3)
    include_rolling_12: bool    # if True, return 12 monthly periods regardless of count

    def __post_init__(self) -> None:
        if self.granularity not in GRANULARITIES:
            raise ValueError(f"Unknown granularity: {self.granularity}")
        if self.count < 1:
            raise ValueError("count must be >= 1")


@dataclass(frozen=True)
class Period:
    label: str
    start: datetime    # inclusive
    end: datetime      # exclusive (half-open [start, end))


def _month_start(d: date) -> datetime:
    return datetime(d.year, d.month, 1)


def _add_months(dt: datetime, months: int) -> datetime:
    total = (dt.year * 12 + (dt.month - 1)) + months
    return datetime(total // 12, total % 12 + 1, 1)


def _month_period(anchor_month_start: datetime, offset_from_newest: int) -> Period:
    start = _add_months(anchor_month_start, -offset_from_newest)
    end = _add_months(start, 1)
    return Period(label=f"{_MONTHS[start.month - 1]} {start.year}", start=start, end=end)


def _quarter_period(anchor: date, offset_from_newest: int) -> Period:
    q_index = (anchor.year * 4) + ((anchor.month - 1) // 3) - offset_from_newest
    year, q = divmod(q_index, 4)
    start = datetime(year, q * 3 + 1, 1)
    end = _add_months(start, 3)
    return Period(label=f"Q{q + 1} {year}", start=start, end=end)


def _week_period(anchor: date, offset_from_newest: int) -> Period:
    monday = anchor - timedelta(days=anchor.weekday())
    start_date = monday - timedelta(weeks=offset_from_newest)
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = start + timedelta(weeks=1)
    return Period(label=f"Week of {start.date().isoformat()}", start=start, end=end)


def compute_periods(spec: PeriodSpec, anchor: date) -> list[Period]:
    """Return periods oldest -> newest, newest containing `anchor`."""
    if spec.include_rolling_12:
        base = _month_start(anchor)
        return [_month_period(base, offset) for offset in range(11, -1, -1)]

    n = spec.count
    if spec.granularity == "month":
        base = _month_start(anchor)
        return [_month_period(base, offset) for offset in range(n - 1, -1, -1)]
    if spec.granularity == "quarter":
        return [_quarter_period(anchor, offset) for offset in range(n - 1, -1, -1)]
    return [_week_period(anchor, offset) for offset in range(n - 1, -1, -1)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_periods.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/query/periods.py extensions/reporting/tests/query/test_periods.py
git commit -m "feat(reporting): period window math for time comparison"
```

---

## Task 3: Filter translation (`query/filters.py`)

Translate declarative `FilterClause`s into Django `Q` objects against a field's ORM path. Pure and testable (uses the stubbed `Q`).

**Files:**
- Create: `extensions/reporting/reporting/query/filters.py`
- Test: `extensions/reporting/tests/query/test_filters.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/query/test_filters.py
from __future__ import annotations

import pytest

from reporting.query.filters import FilterClause, OPERATORS, build_lookup


def test_is_operator_single_value():
    clause = FilterClause(orm_path="status", operator="is", values=["noshowed"])
    assert build_lookup(clause) == {"status": "noshowed"}


def test_is_one_of_uses_in_lookup():
    clause = FilterClause(orm_path="status", operator="is_one_of", values=["noshowed", "cancelled"])
    assert build_lookup(clause) == {"status__in": ["noshowed", "cancelled"]}


def test_numeric_operators():
    assert build_lookup(FilterClause("age", "gte", [18])) == {"age__gte": 18}
    assert build_lookup(FilterClause("age", "lt", [65])) == {"age__lt": 65}


def test_unknown_operator_raises():
    with pytest.raises(ValueError):
        build_lookup(FilterClause("status", "matches_regex", ["x"]))


def test_operators_registry_is_closed_set():
    assert set(OPERATORS) == {"is", "is_one_of", "gte", "gt", "lte", "lt"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_filters.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.query.filters'`.

- [ ] **Step 3: Implement `query/filters.py`**

```python
"""Translate declarative filter clauses into Django ORM lookup kwargs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# operator -> Django lookup suffix ("" means exact)
OPERATORS: dict[str, str] = {
    "is": "",
    "is_one_of": "__in",
    "gte": "__gte",
    "gt": "__gt",
    "lte": "__lte",
    "lt": "__lt",
}


@dataclass(frozen=True)
class FilterClause:
    orm_path: str
    operator: str
    values: list[Any]


def build_lookup(clause: FilterClause) -> dict[str, Any]:
    """Return ORM filter kwargs for one clause."""
    if clause.operator not in OPERATORS:
        raise ValueError(f"Unsupported operator: {clause.operator}")
    suffix = OPERATORS[clause.operator]
    key = f"{clause.orm_path}{suffix}"
    if clause.operator == "is_one_of":
        return {key: list(clause.values)}
    return {key: clause.values[0]}


def build_lookups(clauses: list[FilterClause]) -> dict[str, Any]:
    """Combine multiple clauses into a single AND-ed kwargs dict."""
    out: dict[str, Any] = {}
    for clause in clauses:
        out.update(build_lookup(clause))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_filters.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/query/filters.py extensions/reporting/tests/query/test_filters.py
git commit -m "feat(reporting): declarative filter -> ORM lookup translation"
```

---

## Task 4: Measures (`query/measures.py`)

Measures are the pre-built aggregations. Because `Sum`/`Avg` are sandbox-blocked, every measure is built from **named counts** (`Count("dbid", filter=Q(...))`) plus **Python math**. Two measure kinds this phase: `count` (total) and `ratio` (numerator count / denominator count, optionally as a percent).

**Files:**
- Create: `extensions/reporting/reporting/query/measures.py`
- Test: `extensions/reporting/tests/query/test_measures.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/query/test_measures.py
from __future__ import annotations

from reporting.query.measures import (
    CountMeasure,
    RatioMeasure,
    count_specs,
    compute_value,
)


def test_count_measure_declares_one_count_spec():
    m = CountMeasure(key="total", label="Total appointments")
    specs = count_specs(m)
    assert list(specs.keys()) == ["total__all"]
    assert specs["total__all"] is None  # None filter == count everything


def test_count_where_measure_declares_filtered_count():
    m = CountMeasure(key="noshows", label="No-shows", where={"status__in": ["noshowed", "cancelled"]})
    specs = count_specs(m)
    assert specs == {"noshows__all": {"status__in": ["noshowed", "cancelled"]}}


def test_ratio_measure_declares_numerator_and_denominator_specs():
    m = RatioMeasure(
        key="no_show_rate",
        label="No-show rate (%)",
        numerator_where={"status__in": ["noshowed", "cancelled"]},
        as_percent=True,
    )
    specs = count_specs(m)
    assert specs == {
        "no_show_rate__num": {"status__in": ["noshowed", "cancelled"]},
        "no_show_rate__den": None,
    }


def test_compute_count_value_reads_named_count():
    m = CountMeasure(key="total", label="Total")
    assert compute_value(m, {"total__all": 42}) == 42


def test_compute_ratio_as_percent_rounds_to_one_dp():
    m = RatioMeasure(key="r", label="rate", numerator_where={"x": 1}, as_percent=True)
    assert compute_value(m, {"r__num": 3, "r__den": 24}) == 12.5


def test_compute_ratio_zero_denominator_is_zero():
    m = RatioMeasure(key="r", label="rate", numerator_where={"x": 1}, as_percent=True)
    assert compute_value(m, {"r__num": 0, "r__den": 0}) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_measures.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.query.measures'`.

- [ ] **Step 3: Implement `query/measures.py`**

```python
"""Measure definitions. All sums/ratios computed in Python (Sum/Avg are sandbox-blocked).

A measure declares one or more named COUNT specs. The engine turns each spec into a
Count("dbid", filter=Q(**lookup)) annotation (or Count("dbid") when the spec is None),
runs the grouped query, then calls compute_value() per row to derive the final number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# A "count spec" is the ORM lookup kwargs for the Count filter, or None for count-all.
CountSpec = Optional[dict[str, Any]]


@dataclass(frozen=True)
class CountMeasure:
    key: str
    label: str
    where: dict[str, Any] | None = None  # None -> count everything

    kind: str = field(default="count", init=False)


@dataclass(frozen=True)
class RatioMeasure:
    key: str
    label: str
    numerator_where: dict[str, Any]
    denominator_where: dict[str, Any] | None = None  # None -> count-all denominator
    as_percent: bool = True

    kind: str = field(default="ratio", init=False)


Measure = CountMeasure | RatioMeasure


def count_specs(measure: Measure) -> dict[str, CountSpec]:
    """Return {annotation_name: count_spec} the engine must materialize."""
    if isinstance(measure, CountMeasure):
        return {f"{measure.key}__all": measure.where}
    return {
        f"{measure.key}__num": measure.numerator_where,
        f"{measure.key}__den": measure.denominator_where,
    }


def compute_value(measure: Measure, row: dict[str, Any]) -> float | int:
    """Derive the measure's value from a row of materialized named counts."""
    if isinstance(measure, CountMeasure):
        return row[f"{measure.key}__all"]
    num = row[f"{measure.key}__num"]
    den = row[f"{measure.key}__den"]
    if not den:
        return 0.0
    ratio = num / den
    return round(ratio * 100, 1) if measure.as_percent else round(ratio, 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_measures.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/query/measures.py extensions/reporting/tests/query/test_measures.py
git commit -m "feat(reporting): measure defs (count + ratio) with Python-side math"
```

---

## Task 5: Dataset registry + Appointments dataset (`datasets/`)

A dataset declaratively binds friendly fields/measures to a real ORM model. This phase defines the registry and the Appointments dataset.

**Files:**
- Create: `extensions/reporting/reporting/datasets/__init__.py` (overwrite the empty file)
- Create: `extensions/reporting/reporting/datasets/appointments.py`
- Test: `extensions/reporting/tests/datasets/test_appointments.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/datasets/test_appointments.py
from __future__ import annotations

from reporting.datasets import get_dataset, list_datasets
from reporting.query.measures import RatioMeasure


def test_appointments_dataset_registered():
    keys = [d.key for d in list_datasets()]
    assert "appointments" in keys


def test_appointments_has_date_field_and_model():
    ds = get_dataset("appointments")
    assert ds.date_field == "start_time"
    assert ds.model.__name__ == "Appointment"


def test_provider_dimension_resolves_group_paths():
    ds = get_dataset("appointments")
    dim = ds.dimensions["provider"]
    assert dim.group_path == "provider__id"
    assert dim.display_paths == ["provider__first_name", "provider__last_name"]


def test_no_show_rate_measure_present_and_is_ratio():
    ds = get_dataset("appointments")
    m = ds.measures["no_show_rate"]
    assert isinstance(m, RatioMeasure)
    assert m.as_percent is True
    assert m.numerator_where == {"status__in": ["noshowed", "cancelled"]}


def test_status_field_filterable_with_is_one_of():
    ds = get_dataset("appointments")
    f = ds.fields["status"]
    assert "is_one_of" in f.operators
    assert f.orm_path == "status"


def test_get_unknown_dataset_raises():
    import pytest

    with pytest.raises(KeyError):
        get_dataset("nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/datasets/test_appointments.py -q`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` for `reporting.datasets` symbols.

- [ ] **Step 3: Implement the dataset types and registry in `datasets/__init__.py`**

```python
"""Dataset definitions: declarative bindings of friendly fields/measures to ORM models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reporting.query.measures import Measure


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str               # person|place|category|number|date|money|boolean
    orm_path: str
    filterable: bool = False
    operators: tuple[str, ...] = ()
    groupable: bool = False


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    group_path: str             # ORM path used in .values(...)
    display_paths: list[str]    # extra .values(...) paths for human labels


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    model: Any                  # the ORM model class
    date_field: str             # field used for period range filtering
    fields: dict[str, Field]
    dimensions: dict[str, Dimension]
    measures: dict[str, Measure]


_REGISTRY: dict[str, Dataset] = {}


def register(dataset: Dataset) -> None:
    _REGISTRY[dataset.key] = dataset


def get_dataset(key: str) -> Dataset:
    if key not in _REGISTRY:
        raise KeyError(f"Unknown dataset: {key}")
    return _REGISTRY[key]


def list_datasets() -> list[Dataset]:
    return list(_REGISTRY.values())


# Import side-effect: register built-in datasets.
from reporting.datasets import appointments as _appointments  # noqa: E402,F401
```

- [ ] **Step 4: Implement `datasets/appointments.py`**

```python
"""Appointments dataset definition."""

from __future__ import annotations

from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus

from reporting.datasets import Dataset, Dimension, Field, register
from reporting.query.measures import CountMeasure, RatioMeasure

_NO_SHOW_STATUSES = [AppointmentProgressStatus.NOSHOWED, AppointmentProgressStatus.CANCELLED]

DATASET = Dataset(
    key="appointments",
    label="Appointments",
    model=Appointment,
    date_field="start_time",
    fields={
        "status": Field(
            key="status",
            label="Status",
            type="category",
            orm_path="status",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
        ),
        "provider": Field(
            key="provider",
            label="Provider",
            type="person",
            orm_path="provider__id",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
        ),
        "location": Field(
            key="location",
            label="Location",
            type="place",
            orm_path="location__id",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
        ),
    },
    dimensions={
        "provider": Dimension(
            key="provider",
            label="Provider",
            group_path="provider__id",
            display_paths=["provider__first_name", "provider__last_name"],
        ),
        "location": Dimension(
            key="location",
            label="Location",
            group_path="location__id",
            display_paths=["location__full_name"],
        ),
    },
    measures={
        "total": CountMeasure(key="total", label="Total appointments"),
        "no_shows": CountMeasure(
            key="no_shows", label="No-shows", where={"status__in": _NO_SHOW_STATUSES}
        ),
        "no_show_rate": RatioMeasure(
            key="no_show_rate",
            label="No-show rate (%)",
            numerator_where={"status__in": _NO_SHOW_STATUSES},
            as_percent=True,
        ),
    },
)

register(DATASET)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/datasets/test_appointments.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/datasets/ extensions/reporting/tests/datasets/test_appointments.py
git commit -m "feat(reporting): dataset registry + Appointments dataset"
```

---

## Task 6: Query engine (`query/engine.py`)

Orchestrates a report run: resolve the dataset, build period windows, and for each period run ONE grouped `Count` query, then compute measure values in Python. The actual ORM call is isolated behind an injectable `executor` so the merge/period logic is unit-testable without Django.

**Files:**
- Create: `extensions/reporting/reporting/query/engine.py`
- Test: `extensions/reporting/tests/query/test_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/query/test_engine.py
from __future__ import annotations

from datetime import date

from reporting.query.engine import ReportQuery, run_report
from reporting.query.filters import FilterClause
from reporting.query.periods import PeriodSpec


def _fake_executor(calls):
    """Returns an executor that records calls and returns canned grouped rows per period."""
    # canned rows keyed by period label
    canned = {
        "May 2026": [
            {"provider__id": "p1", "provider__first_name": "A", "provider__last_name": "Alvarez",
             "no_show_rate__num": 12, "no_show_rate__den": 100},
        ],
        "Jun 2026": [
            {"provider__id": "p1", "provider__first_name": "A", "provider__last_name": "Alvarez",
             "no_show_rate__num": 11, "no_show_rate__den": 100},
        ],
    }

    def executor(model, lookups, group_paths, count_specs):
        calls.append({"model": model.__name__, "lookups": lookups,
                      "group_paths": group_paths, "count_specs": count_specs})
        # the date range lookups encode the period; map by start_time month
        start = lookups["start_time__gte"]
        label = "Jun 2026" if start.month == 6 else "May 2026"
        return canned[label]

    return executor


def test_run_report_groups_and_computes_ratio_per_period():
    calls = []
    q = ReportQuery(
        dataset_key="appointments",
        filters=[FilterClause(orm_path="status", operator="is_one_of",
                              values=["noshowed", "cancelled"])],
        measure_key="no_show_rate",
        group_by="provider",
        period=PeriodSpec(granularity="month", count=2, include_rolling_12=False),
    )
    result = run_report(q, anchor=date(2026, 6, 15), executor=_fake_executor(calls))

    assert result["measure"] == "No-show rate (%)"
    assert result["periods"] == ["May 2026", "Jun 2026"]
    # one group row, with a value per period
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["group_label"] == "A Alvarez"
    assert row["values"] == {"May 2026": 12.0, "Jun 2026": 11.0}


def test_run_report_runs_one_query_per_period():
    calls = []
    q = ReportQuery(
        dataset_key="appointments", filters=[], measure_key="no_show_rate",
        group_by="provider",
        period=PeriodSpec(granularity="month", count=2, include_rolling_12=False),
    )
    run_report(q, anchor=date(2026, 6, 15), executor=_fake_executor(calls))
    assert len(calls) == 2  # one ORM query per period window


def test_run_report_merges_date_range_into_lookups():
    calls = []
    q = ReportQuery(
        dataset_key="appointments", filters=[], measure_key="total",
        group_by="provider",
        period=PeriodSpec(granularity="month", count=1, include_rolling_12=False),
    )
    # total measure -> executor returns rows with total__all
    def executor(model, lookups, group_paths, count_specs):
        calls.append(lookups)
        return [{"provider__id": "p1", "provider__first_name": "A",
                 "provider__last_name": "B", "total__all": 50}]

    result = run_report(q, anchor=date(2026, 6, 15), executor=executor)
    assert "start_time__gte" in calls[0] and "start_time__lt" in calls[0]
    assert result["rows"][0]["values"]["Jun 2026"] == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.query.engine'`.

- [ ] **Step 3: Implement `query/engine.py`**

```python
"""Report execution: dataset + filters + measure + grouping + period comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from reporting.datasets import get_dataset
from reporting.query.filters import FilterClause, build_lookups
from reporting.query.measures import compute_value, count_specs
from reporting.query.periods import Period, PeriodSpec, compute_periods

# executor(model, lookups, group_paths, count_specs) -> list[row dict]
Executor = Callable[[Any, dict[str, Any], list[str], dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class ReportQuery:
    dataset_key: str
    filters: list[FilterClause]
    measure_key: str
    group_by: str | None
    period: PeriodSpec | None = None


def _orm_executor(model, lookups, group_paths, specs):
    """Default executor: real Django ORM grouped Count query (runs in the sandbox)."""
    from django.db.models import Count, Q

    annotations = {}
    for name, spec in specs.items():
        if spec is None:
            annotations[name] = Count("dbid")
        else:
            annotations[name] = Count("dbid", filter=Q(**spec))
    qs = model.objects.filter(**lookups).values(*group_paths).annotate(**annotations)
    return list(qs)


def _group_label(dataset, dim, row) -> str:
    parts = [str(row.get(p, "")) for p in dim.display_paths]
    label = " ".join(p for p in parts if p).strip()
    return label or str(row.get(dim.group_path, ""))


def run_report(
    query: ReportQuery,
    anchor: date,
    executor: Executor | None = None,
) -> dict[str, Any]:
    executor = executor or _orm_executor
    dataset = get_dataset(query.dataset_key)
    measure = dataset.measures[query.measure_key]
    specs = count_specs(measure)
    base_lookups = build_lookups(query.filters)

    dim = dataset.dimensions[query.group_by] if query.group_by else None
    group_paths: list[str] = []
    if dim:
        group_paths = [dim.group_path, *dim.display_paths]

    spec = query.period or PeriodSpec(granularity="month", count=1, include_rolling_12=False)
    periods: list[Period] = compute_periods(spec, anchor)

    # group_key -> {"group_label": str, "values": {period_label: value}}
    merged: dict[Any, dict[str, Any]] = {}
    for period in periods:
        lookups = dict(base_lookups)
        lookups[f"{dataset.date_field}__gte"] = period.start
        lookups[f"{dataset.date_field}__lt"] = period.end
        rows = executor(dataset.model, lookups, group_paths, specs)
        for row in rows:
            key = row.get(dim.group_path) if dim else "__all__"
            entry = merged.setdefault(
                key,
                {"group_label": _group_label(dataset, dim, row) if dim else "All", "values": {}},
            )
            entry["values"][period.label] = compute_value(measure, row)

    return {
        "dataset": dataset.label,
        "measure": measure.label,
        "group_by": dim.label if dim else None,
        "periods": [p.label for p in periods],
        "rows": list(merged.values()),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query/test_engine.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole query/dataset suite**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/query tests/datasets -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/query/engine.py extensions/reporting/tests/query/test_engine.py
git commit -m "feat(reporting): query engine with per-period grouped counts"
```

---

## Task 7: Application launcher (`applications/reporting_app.py`)

**Files:**
- Create: `extensions/reporting/reporting/applications/reporting_app.py`
- Test: `extensions/reporting/tests/applications/test_reporting_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/applications/test_reporting_app.py
from __future__ import annotations

from reporting.applications.reporting_app import ReportingApp


def test_on_open_launches_full_page_modal():
    app = ReportingApp.__new__(ReportingApp)
    applied = app.on_open()
    effect = applied.owner  # stub .apply() wraps the effect as _Applied(owner)
    assert effect.url == "/plugin-io/api/reporting/app/home"
    assert effect.target == "page"
    assert effect.title == "Reporting"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/applications/test_reporting_app.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.applications.reporting_app'`.

- [ ] **Step 3: Implement `applications/reporting_app.py`**

```python
"""Global Application that launches the Reporting workspace full-page."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ReportingApp(Application):
    """Launches the Reporting SPA as a full-page modal from the app drawer."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/reporting/app/home",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Reporting",
        ).apply()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/applications/test_reporting_app.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/applications/reporting_app.py extensions/reporting/tests/applications/test_reporting_app.py
git commit -m "feat(reporting): global Application full-page launcher"
```

---

## Task 8: SimpleAPI routes — shell HTML, static, results JSON (`routes/reporting_api.py`)

**Files:**
- Create: `extensions/reporting/reporting/routes/reporting_api.py`
- Test: `extensions/reporting/tests/routes/test_reporting_api.py`

The results route accepts a JSON POST body describing the report, builds a `ReportQuery`, and returns `run_report(...)`. Tests patch `run_report` and the date so handler wiring is verified without the ORM.

- [ ] **Step 1: Write the failing tests**

```python
# tests/routes/test_reporting_api.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from reporting.routes.reporting_api import ReportingAPI


def _handler(body=None):
    h = ReportingAPI.__new__(ReportingAPI)
    h.request = MagicMock()
    h.request.headers = {"canvas-logged-in-user-id": "uid"}
    h.request.query_params = {}
    h.request.json = MagicMock(return_value=body or {})
    return h


def test_home_returns_html():
    h = _handler()
    responses = h.home()
    assert responses[0].content_type == "text/html"


def test_app_css_served_as_css():
    h = _handler()
    responses = h.app_css()
    assert responses[0].content_type == "text/css"


def test_datasets_route_lists_datasets_json():
    h = _handler()
    responses = h.datasets()
    data = responses[0].data
    assert any(d["key"] == "appointments" for d in data["datasets"])


def test_run_route_builds_query_and_returns_engine_result():
    body = {
        "dataset_key": "appointments",
        "measure_key": "no_show_rate",
        "group_by": "provider",
        "filters": [{"field": "status", "operator": "is_one_of",
                     "values": ["noshowed", "cancelled"]}],
        "period": {"granularity": "month", "count": 3, "include_rolling_12": False},
    }
    h = _handler(body)
    fake_result = {"rows": [], "periods": ["Apr 2026"]}
    with patch("reporting.routes.reporting_api.run_report", return_value=fake_result) as mock_run:
        responses = h.run()
    assert responses[0].data == fake_result
    # the handler must have resolved the field's orm_path for the filter clause
    called_query = mock_run.call_args.args[0]
    assert called_query.dataset_key == "appointments"
    assert called_query.filters[0].orm_path == "status"
    assert called_query.period.count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/routes/test_reporting_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reporting.routes.reporting_api'`.

- [ ] **Step 3: Implement `routes/reporting_api.py`**

```python
"""SimpleAPI: serves the SPA shell, static assets, dataset metadata, and report runs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from reporting.datasets import get_dataset, list_datasets
from reporting.query.engine import ReportQuery, run_report
from reporting.query.filters import FilterClause
from reporting.query.periods import PeriodSpec

_API_BASE = "/plugin-io/api/reporting/app"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _build_query(dataset_key: str, body: dict) -> ReportQuery:
    dataset = get_dataset(dataset_key)
    clauses: list[FilterClause] = []
    for raw in body.get("filters", []):
        fld = dataset.fields[raw["field"]]
        clauses.append(
            FilterClause(orm_path=fld.orm_path, operator=raw["operator"], values=raw["values"])
        )
    period = None
    if body.get("period"):
        p = body["period"]
        period = PeriodSpec(
            granularity=p.get("granularity", "month"),
            count=int(p.get("count", 3)),
            include_rolling_12=bool(p.get("include_rolling_12", False)),
        )
    return ReportQuery(
        dataset_key=dataset_key,
        filters=clauses,
        measure_key=body["measure_key"],
        group_by=body.get("group_by"),
        period=period,
    )


class ReportingAPI(StaffSessionAuthMixin, SimpleAPI):
    """HTML shell + static assets + JSON endpoints for the Reporting app."""

    PREFIX = "/app"

    @api.get("/home")
    def home(self) -> list[Response | Effect]:
        html = render_to_string("templates/app.html", {"api_base": _API_BASE})
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/app.css")
    def app_css(self) -> list[Response | Effect]:
        css = render_to_string("static/css/app.css")
        return [Response(css.encode(), status_code=HTTPStatus.OK, content_type="text/css")]

    @api.get("/app.js")
    def app_js(self) -> list[Response | Effect]:
        js = render_to_string("static/js/app.js")
        return [
            Response(js.encode(), status_code=HTTPStatus.OK, content_type="application/javascript")
        ]

    @api.get("/datasets")
    def datasets(self) -> list[Response | Effect]:
        payload = [
            {
                "key": d.key,
                "label": d.label,
                "fields": [{"key": f.key, "label": f.label, "type": f.type,
                            "operators": list(f.operators)} for f in d.fields.values()],
                "dimensions": [{"key": dim.key, "label": dim.label} for dim in d.dimensions.values()],
                "measures": [{"key": m.key, "label": m.label} for m in d.measures.values()],
            }
            for d in list_datasets()
        ]
        return [JSONResponse({"datasets": payload})]

    @api.post("/run")
    def run(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        query = _build_query(body["dataset_key"], body)
        result = run_report(query, anchor=_today())
        return [JSONResponse(result)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/routes/test_reporting_api.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/routes/reporting_api.py extensions/reporting/tests/routes/test_reporting_api.py
git commit -m "feat(reporting): SimpleAPI routes for shell, static, datasets, run"
```

---

## Task 9: SPA shell (`templates/app.html`, `static/css/app.css`, `static/js/app.js`)

A minimal SPA that, on load, runs the no-show-rate-by-provider report against the live endpoint and renders a table. This proves the end-to-end path. (The full 4-step builder UI is a later phase.) These are static assets — no unit tests; validated by the smoke test in Task 10.

- [ ] **Step 1: Write `templates/app.html`**

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
    <h1>Reporting</h1>
    <p class="sub">Build dashboards and reports — no SQL required</p>
  </header>
  <main id="app">
    <section class="card">
      <h2 id="report-title">No-show rate by provider</h2>
      <p id="status" class="muted">Loading…</p>
      <table id="results" hidden>
        <thead><tr><th>Provider</th><th id="period-cols-head"></th></tr></thead>
        <tbody id="results-body"></tbody>
      </table>
    </section>
  </main>
  <script>window.API_BASE = "{{ api_base }}";</script>
  <script src="{{ api_base }}/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `static/css/app.css`** (Canvas dark theme)

```css
:root{
  --base01:#030B14;--base02:#051222;--base03:#07182D;
  --primary:#01A4FF;--secondary:#01ECFF;
  --text:#EBF5FC;--head:#FFFFFF;--muted:#8496AA;
  --border:rgba(255,255,255,.06);
}
*{box-sizing:border-box}
body{margin:0;background:var(--base01);color:var(--text);
  font-family:Inter,system-ui,-apple-system,sans-serif;font-size:14px}
.topbar{padding:18px 28px;border-bottom:1px solid var(--border)}
.topbar h1{margin:0;color:var(--head);font-size:20px}
.topbar .sub{margin:2px 0 0;color:var(--muted);font-size:12px}
main{padding:24px 28px}
.card{background:var(--base02);border:1px solid var(--border);border-radius:12px;padding:18px}
.card h2{margin:0 0 12px;color:var(--head);font-size:16px}
.muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
td.num{text-align:right;color:var(--head);font-variant-numeric:tabular-nums}
```

- [ ] **Step 3: Write `static/js/app.js`**

```javascript
(function () {
  const base = window.API_BASE;
  const statusEl = document.getElementById("status");
  const table = document.getElementById("results");
  const head = document.getElementById("period-cols-head");
  const body = document.getElementById("results-body");

  const reportSpec = {
    dataset_key: "appointments",
    measure_key: "no_show_rate",
    group_by: "provider",
    filters: [],
    period: { granularity: "month", count: 3, include_rolling_12: false },
  };

  fetch(base + "/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reportSpec),
  })
    .then((r) => {
      if (!r.ok) throw new Error("Request failed: " + r.status);
      return r.json();
    })
    .then((data) => {
      const periods = data.periods || [];
      head.outerHTML = periods
        .map((p) => `<th class="num">${p}</th>`)
        .join("");
      body.innerHTML = (data.rows || [])
        .map((row) => {
          const cells = periods
            .map((p) => `<td class="num">${row.values[p] ?? "—"}</td>`)
            .join("");
          return `<tr><td>${row.group_label}</td>${cells}</tr>`;
        })
        .join("");
      statusEl.hidden = true;
      table.hidden = false;
    })
    .catch((err) => {
      statusEl.textContent = "Could not load report: " + err.message;
    });
})();
```

- [ ] **Step 4: Run the full test suite (everything should still pass)**

Run: `cd extensions/reporting && uv run --with pytest pytest tests/ -q`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/templates extensions/reporting/reporting/static
git commit -m "feat(reporting): minimal SPA shell rendering one live report"
```

---

## Task 10: Manifest + deploy & sandbox smoke validation

The manifest registers the Application and the SimpleAPI handler. Then validate on a real instance — pytest does NOT exercise the sandbox import allowlist, so the ORM aggregation imports MUST be confirmed live.

**Files:**
- Create: `extensions/reporting/reporting/CANVAS_MANIFEST.json`

- [ ] **Step 1: Write `CANVAS_MANIFEST.json`**

```json
{
    "sdk_version": "0.1.4",
    "plugin_version": "0.1.0",
    "name": "reporting",
    "description": "In-UI report and dashboard builder for non-technical users.",
    "url_permissions": [],
    "components": {
        "protocols": [
            {
                "class": "reporting.routes.reporting_api:ReportingAPI",
                "description": "Serves the Reporting SPA, dataset metadata, and report runs.",
                "data_access": {
                    "event": "",
                    "read": ["Appointment", "Staff", "PracticeLocation"],
                    "write": []
                }
            }
        ],
        "applications": [
            {
                "class": "reporting.applications.reporting_app:ReportingApp",
                "name": "Reporting",
                "description": "Build dashboards and reports — no SQL required.",
                "icon": "assets/icon.png",
                "scope": "global",
                "menu_position": "top"
            }
        ],
        "commands": [],
        "content": [],
        "effects": [],
        "views": []
    },
    "secrets": [],
    "tags": {},
    "references": [],
    "license": "MIT",
    "diagram": false,
    "readme": "../README.md"
}
```

- [ ] **Step 2: Validate the manifest schema**

Run (from repo root): `uv run --project /Users/amandap-canvas/Code/canvas-plugins canvas validate-manifest extensions/reporting/reporting`
Expected: validation passes (no schema errors). If the `canvas` CLI is unavailable, manually confirm every `applications` entry has `class/icon/scope/name/description` and `scope` is `"global"`.

- [ ] **Step 3: Install on a test instance**

Run: `uv run --project /Users/amandap-canvas/Code/canvas-plugins canvas install extensions/reporting/reporting --host <your-test-instance>`
Expected: install succeeds; the plugin appears in the instance's plugin list.

- [ ] **Step 4: Smoke test in the browser**

1. Open the target instance, open the **app drawer**, confirm a **Reporting** tile (with icon) appears.
2. Click it — confirm it launches **full-page** with the "Reporting" title and the SPA shell loads.
3. Confirm the table populates with no-show rate by provider across the last 3 months (or shows an empty-but-not-errored state if the instance has no appointment data).

- [ ] **Step 5: Confirm sandbox import compliance (CRITICAL)**

Inspect the plugin runtime logs during the smoke test for `ImportError` from `reporting.query.engine` (the only module importing `Count`/`Q` from `django.db.models`). Expected: NONE. If an `ImportError` appears, the import is not on the sandbox allowlist — fix `engine.py` to use only `Count, Case, When, Q, F, Value`.

Optional local check against the sandbox allowlist:
Run: `grep -n "from django.db.models import" extensions/reporting/reporting/query/engine.py`
Expected: only `Count` and `Q` imported — both on the allowlist.

- [ ] **Step 6: Commit**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
git add extensions/reporting/reporting/CANVAS_MANIFEST.json
git commit -m "feat(reporting): manifest registering global app + API; deploy validated"
```

---

## Definition of Done (Phase 1)

- [ ] `uv run pytest tests/` is fully green in `extensions/reporting/`.
- [ ] The plugin installs and the **Reporting** tile appears in the app drawer.
- [ ] Clicking it launches a full-page SPA that renders no-show rate by provider for the last 3 months from live data.
- [ ] No sandbox `ImportError` in runtime logs.
- [ ] All work committed on branch `add-reporting-plugin`.

---

## Self-Review (completed by plan author)

**Spec coverage (Phase 1 scope):** scaffold/manifest (Task 0, 10) ✓; global Application + full-page launch (Task 7, 10) ✓; SPA shell (Task 9) ✓; declarative dataset format (Task 5) ✓; Appointments dataset (Task 5) ✓; query engine incl. period comparison (Task 2, 3, 4, 6) ✓. Persistence, builder UI, dashboards, delivery, extra datasets are explicitly deferred to later phases per the scope note. No Phase-1 requirement is unaddressed.

**Placeholder scan:** No "TBD/TODO" in steps. The app icon is an explicit placeholder copied from staff_directory with a noted follow-up — acceptable (a 48x48 PNG is required to validate; real art is non-blocking).

**Type consistency:** `FilterClause(orm_path, operator, values)` is constructed identically in tests, engine, and routes. `count_specs()`/`compute_value()` names match across measures, engine, and tests. `PeriodSpec(granularity, count, include_rolling_12)` and `Period(label, start, end)` are consistent everywhere. `run_report(query, anchor, executor=None)` signature matches its callers in routes and tests. `Dataset`/`Field`/`Dimension`/`Measure` field names match between `datasets/__init__.py`, `appointments.py`, and the engine's use (`dataset.date_field`, `dim.group_path`, `dim.display_paths`, `dataset.measures`).
