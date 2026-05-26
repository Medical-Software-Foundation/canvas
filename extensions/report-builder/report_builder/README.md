# Report Builder

A UI-configurable report engine for Canvas. Build patient worklists, care-gap
lists, and outreach lists across instance-wide data — without writing code or
SQL.

## What it does

- A schema-driven builder UI lets staff filter Patients, Appointments,
  Conditions, Notes, and Lab Orders by field values and one-hop aggregates
  (e.g. "patients with zero completed appointments in the last 90 days").
- Reports are saved per instance and visible to all staff.
- Results render as a paginated table; CSV export is one click.
- An `as_of_date` parameter resolves relative date filters at run time, so the
  same saved report keeps working as a rolling care-gap list.

## Triggers / Surface

- **Application** — launched from the Canvas app drawer. Opens the SPA in a
  full-page modal.

## Installation

```bash
uv run canvas install report_builder --host <your-canvas-host>
```

## Architecture

```
report_builder/
├── handlers/
│   ├── application.py    # ReportBuilderApp — app-drawer entry
│   └── api.py            # ReportBuilderAPI — SPA shell + JSON endpoints
├── schemas/              # Entity Schema Registry — extension point for new entities
│   ├── base.py
│   ├── registry.py
│   ├── patient.py
│   ├── appointment.py
│   ├── condition.py
│   ├── note.py
│   └── lab_order.py
├── reports/              # Domain logic
│   ├── models.py         # Report / *Condition / AggregateColumn dataclasses
│   ├── validate.py       # validate_report
│   ├── query.py          # build_queryset, safe_run, paging
│   ├── storage.py        # CRUD wrapper around the SavedReport CustomModel
│   └── export.py         # streamed CSV
├── models/
│   └── saved_report.py   # SavedReport (Canvas CustomModel)
└── static/               # Preact + HTM SPA, no build step
    ├── index.html
    ├── app.js
    └── …
```

### Adding a new entity

The schema registry is the single extension point. To add an entity:

1. Create `report_builder/schemas/<entity>.py` exposing an `EntitySchema`.
2. Add it to `_ENTITY_LIST` in `report_builder/schemas/registry.py`.

No UI code changes needed.

### Schema deviation: Encounter → Note

The original spec listed an "Encounter" entity, but Canvas's `Encounter` model
has no direct `Patient` FK — it reaches Patient through `Note`. To stay inside
the v1 one-hop-only constraint, the registry exposes `Note` instead. The two
concepts overlap almost completely in Canvas (every encounter has exactly one
note), so this is a no-op for the user-visible reports.

## Safety

- Result sets are capped at 10,000 rows. Past that, the UI refuses to render
  and asks the user to refine.
- All field, relationship, and operator references are whitelisted against the
  schema registry before reaching the ORM — there is no path for user-supplied
  strings to land directly in a `.filter()` call.

## ⚠️ PHI exposure risk

**This plugin gives every authenticated staff member the ability to list
patients by arbitrary clinical criteria.** That is the entire point of a
report builder, but it also means anyone with access can construct a list of
patients with sensitive conditions (HIV, mental health, substance use, etc.)
and export it as a CSV.

**v1 enforces no role-based gating.** A
`pre_run_hook` extension point exists in `reports/query.py` for v2 to wire role
checks without a refactor. Until then, **customers deploying this plugin are
responsible for restricting access at the Canvas role level**, e.g. by only
granting the app-drawer permission to staff who would otherwise be authorized
to run patient reports against this data.

Audit log entries are emitted per create/update/delete/preview/run/export
through the standard Canvas plugin log facility:

```
report-builder audit: {"event": "run", "staff_id": "...", "report_id": "...",
                       "as_of_date": "2026-05-22", "result_count": 42}
```

No patient data is included in the audit log.

## Out of scope (v1)

- Multi-hop relationship traversal.
- OR / nested filter logic. All filters are AND.
- GROUP BY reports / aggregation-only outputs.
- Charts and visualizations.
- Per-user reports, sharing controls, scheduled runs.

## Testing

```bash
uv run pytest                                # run all tests
uv run pytest --cov=report_builder           # with coverage
```

Tests cover the schema registry, validator, query builder, storage layer,
CSV export, Application handler, and every JSON endpoint. UI is not covered
by the Python test suite.
