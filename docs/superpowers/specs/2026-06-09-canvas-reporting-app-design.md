# Canvas Reporting App — Design Spec

**Date:** 2026-06-09
**Status:** Draft for review
**Author:** Amanda Peterson (with Claude)

## Problem

Canvas has limited native reporting. Today, customers who want dashboards and
reports must connect a SQL/BI tool to the read-replica database — a technical,
developer-dependent path that most clinical and operational staff cannot use.

We will build a **Reporting** app inside the Canvas UI that lets a non-technical
person build dashboards and reports with no SQL, no database connection, and no
setup.

## Goals

- A non-technical user can build a useful report (filter, group, summarize,
  visualize) in minutes, with no query language.
- Reports support period-over-period comparison out of the box.
- Users can compose saved reports into dashboards.
- Reports and dashboards can be exported (CSV, PDF), shared within the
  organization, and delivered on a schedule by email.
- Ships as a productized, multi-tenant Canvas plugin installable on any instance.

## Non-Goals (v1)

- Customer-defined datasets (deferred to v2; the architecture must not preclude it).
- Cross-widget cascading global filters ("full dashboard" behavior).
- AI / natural-language report building.
- Fiscal or custom (e.g. 4-week) period cycles.
- End-user cross-dataset joins.

## Users

Operational leads, practice managers, clinical quality staff, billing/RCM staff —
people who today either wait on an analyst or cannot get the report at all. They
think in questions ("which providers have rising no-show rates?"), not in tables
and joins.

---

## Architecture

The app is a Canvas plugin with three runtime pieces:

1. **Launch** — a global-scoped `Application` handler. `on_open()` returns
   `LaunchModalEffect(target=PAGE)` pointing at the plugin's HTML entry route, so
   the app opens as a full-page workspace from the **global app drawer**. Scope is
   global (practice-wide), not patient-specific.

2. **UI (SPA)** — a single-page app (HTML/CSS/JS) served by the plugin through
   `SimpleAPI` HTML routes under `/plugin-io/api/reporting/...`. The app drawer is
   only a launch point; all in-app navigation (Reports / Dashboards / Datasets, the
   builder, the viewer) lives inside this SPA.

3. **Backend** — `SimpleAPI` endpoints guarded by `StaffSessionAuthMixin` that:
   - serve dataset metadata to the builder,
   - execute report queries against **Canvas SDK Data Models** (Django ORM:
     `filter`, `values`, `annotate`, `Count`/`Sum`/`Avg`/`Case`),
   - persist and retrieve report and dashboard definitions,
   - run exports and scheduled deliveries.

### Tenancy & auth

Every query executes inside the customer's own Canvas sandbox under the
logged-in staff session. Data isolation, multi-tenancy, and access permissions are
inherited from Canvas. The plugin manages no database credentials and performs no
cross-tenant access.

### Data source decision

Data comes exclusively from **Canvas SDK Data Models**, not the read-replica.
Rationale: the SDK is uniformly available in every customer sandbox with zero
setup, respects Canvas permissions, and avoids re-introducing the per-customer SQL
connection the app exists to eliminate. The SDK's data model coverage
(`appointment`, `encounter`, `claim`, `billing`, `invoice`, `payment_collection`,
`condition`, `medication`, `observation`, `lab`, `patient`, `coverage`, `task`,
etc.) spans the operational, financial, clinical, and patient-list categories the
app targets.

---

## Core abstraction: the dataset layer

A **dataset** is a **declarative definition** (configuration data, not hardcoded
query logic) that maps friendly, business-readable concepts onto SDK Data Models.
Each dataset definition contains:

- **Fields** — friendly display name, type (person / place / category / number /
  date / money / boolean), the underlying ORM field path, and any joins required to
  reach it. Joins are pre-declared and hidden from the user.
- **Filters** — which fields are filterable and with which operators; rendered as
  plain-language sentences ("Status is No-show or Cancelled").
- **Measures** — pre-built aggregations Canvas ships per dataset (e.g. "No-show
  rate (%)", "Total charges", "Active patient count"). Measures encapsulate ratio
  and conditional-aggregation logic so users never compute them by hand.
- **Dimensions** — the fields that are sensible and safe to group by.

Canvas engineering ships and maintains a **core dataset library** (starting set:
Appointments, Claims, Patients, Encounters; expanding via plugin updates). Because
definitions are declarative, **customer-defined datasets** — covering their custom
extended columns — become a clean v2 capability with no rewrite of the builder or
query engine.

### Query engine

A single component translates a saved report definition
(dataset + filters + measures + dimensions + comparison settings) into an ORM query
and executes it. It is the only place that touches the ORM; the builder and viewer
speak only in dataset/report definitions. This keeps the dangerous surface small,
testable, and independent of the UI.

---

## Report builder

A 4-step, plain-language flow with a live-updating preview:

1. **Data** — choose a curated dataset. Joins are handled for the user.
2. **Filter to** — add filters as plain-language sentences; fields are chosen from
   friendly names with type hints, never raw columns.
3. **Summarize** — choose a **Measure** and **Group by** dimension(s).
   **Compare over time** lives here: period granularity (Month / Week / Quarter),
   a **Last 3 periods** comparison (default when enabled), and an optional
   **rolling 12-month trend**.
4. **Visualize as** — Bar (grouped bars when comparing), Compare table, Trend
   line, KPI, or Table. All visualizations are driven from the same query result;
   switching type does not re-query unless the shape requires it.

Additional builder behavior:

- **Live preview** updates as the definition changes.
- **Drill-down** — clicking a row/bar opens the underlying records for that slice.
- **Save** — name, category (Operations / Financial / Clinical / Patients), and
  visibility.

---

## Dashboards

- A flexible 4-column grid. Unlimited widgets; each tile spans 1–4 columns; the
  grid flows into as many rows as needed and the page scrolls.
- Each widget is a **reference** to a saved report — editing the underlying report
  updates every dashboard it appears on.
- Widgets **lazy-load on scroll** to keep large dashboards responsive.
- A dashboard-level **Period** control sets a default period that widgets inherit.
  (True cross-widget cascading filters are out of scope for v1.)
- **Edit mode** with drag-to-arrange and an "Add report" tile.

---

## Delivery

All four delivery mechanisms are **in v1**:

- **CSV export** — download the underlying rows of a report (especially patient
  lists / worklists).
- **PDF export** — a formatted render of a report or dashboard.
- **Share within the org** — saved reports/dashboards can be private to the owner
  or shared with the organization. Requires a basic ownership + visibility model on
  the saved objects.
- **Scheduled email delivery** — recurring delivery (e.g. Monday-morning ops
  report) via the SDK `cron_task` handler. This is the heaviest single item in v1
  (see Risks) and should be sequenced last in the implementation plan.

---

## Data model (persisted plugin objects)

- **Report** — id, name, category, owner, visibility, dataset key, filters,
  measures, dimensions, comparison settings, visualization type, created/updated.
- **Dashboard** — id, name, owner, visibility, default period, layout (ordered list
  of widget placements with span + position), created/updated.
- **Schedule** — id, target (report or dashboard), cadence, recipients, format
  (CSV/PDF), next-run, owner.

Dataset definitions are shipped with the plugin (code/config), not stored as
user data.

---

## Error handling & guardrails

- **Query limits** — default row caps, result-size limits, and query timeouts so a
  non-technical user cannot build a query that overloads the instance. Surfaced as
  friendly messages ("This report is too large — add a filter or grouping").
- **Empty / partial states** — clear empty-result and loading states in builder and
  dashboard widgets; a failing widget shows an inline error without breaking the
  rest of the dashboard.
- **Permission-aware** — queries run under the staff session; data the user cannot
  see in Canvas does not appear.
- **Schedule failures** — failed scheduled deliveries are logged and retried; the
  schedule owner is notified rather than failing silently.

---

## Risks / open questions (resolve during planning)

1. **SDK measure feasibility** — confirm each pre-built measure (especially rates
   and financial sums) is expressible and efficient via the ORM. Requires a spike
   against a real instance before finalizing the core measure list.
2. **Query performance & safety** — define concrete row/time limits and how
   comparison queries (3 periods + rolling 12-month) are executed efficiently
   (single grouped query vs. per-period queries).
3. **PDF rendering in the sandbox** — the plugin sandbox forbids many imports;
   identify a sanctioned rendering path for PDF export.
4. **Scheduled email send path** — confirm the email-sending mechanism available to
   a plugin and how a report/dashboard is rendered headlessly for attachment.
5. **App drawer / full-page launch** — validate the full-page (`target=PAGE`)
   experience hosts an SPA of this complexity acceptably.

---

## Implementation phases (for the plan)

1. **Foundation** — plugin scaffold, global Application + full-page launch, SPA
   shell, dataset definition format, query engine, one end-to-end dataset
   (Appointments).
2. **Builder** — 4-step builder, filters, measures, dimensions, the 5
   visualizations, live preview, save/library. Period comparison.
3. **Dashboards** — grid, widget references, lazy-load, edit mode, period
   inheritance.
4. **Delivery** — CSV, then PDF, then sharing/visibility, then scheduled email
   (sequenced last as the heaviest item).
5. **Dataset library expansion** — Claims, Patients, Encounters and their measures.

## Success criteria

- A non-technical user builds and saves a working comparison report on the
  Appointments dataset without help.
- A dashboard of several saved reports renders and refreshes within acceptable time.
- CSV, PDF, share, and scheduled email all function on a real instance.
- No query can exceed the configured safety limits.
