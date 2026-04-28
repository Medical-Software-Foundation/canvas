# Database Performance Review: note-production-dashboard

**Generated:** 2026-04-28 15:33:26
**Reviewer:** Claude Code (CPA)
**Plugin version:** 0.1.7

## Summary

| Category | Status | Issues |
|----------|--------|--------|
| N+1 Query Patterns | PASS | 0 |
| `select_related` Usage | PASS | 0 |
| `prefetch_related` Usage | 1 issue (over-fetch) | 1 MEDIUM |
| Query Bounds | PASS | 0 |
| Large Queryset Materialization | PASS | 0 |
| Missing `.iterator()` | PASS | 0 |
| Missing `.only()` | 1 opportunity | 1 LOW |

## Detailed Findings

The plugin has a single ORM call site: `_fetch_locked_state_events` at `note_production_dashboard/handlers/dashboard_api.py:156–187`. It is consumed by two endpoints (`providers_list` and `provider_notes`), each of which iterates the queryset once.

### N+1 Query Patterns

None. Both iteration sites only access related objects that are pre-loaded by the shared helper:

- `providers_list` (`dashboard_api.py:225–241`): reads `event.note.provider` and the provider's `first_name`/`last_name`/`credentialed_name` only. All covered by `select_related("note__provider")`.
- `provider_notes` (`dashboard_api.py:262–301`): reads `note.patient.{first_name, last_name}`, `note.note_type_version.name`, `note.datetime_of_service`, `note.active_billing_items[].cpt`, and `note.rfv_commands_prefetched[0].data`. All covered by the existing `select_related` / `prefetch_related` chain.

### `select_related` Usage

Correctly applied for the three FK paths actually traversed: `note__provider`, `note__patient`, `note__note_type_version`. No FK access elsewhere in plugin code.

### `prefetch_related` Usage

The helper attaches two `Prefetch` blocks unconditionally:

- `note__billing_line_items` filtered to `ACTIVE` (`to_attr=active_billing_items`)
- `note__commands` filtered to `schema_key="reasonForVisit"` ordered by `dbid` (`to_attr=rfv_commands_prefetched`)

`provider_notes` consumes both prefetches. **`providers_list` consumes neither** — it only counts events per provider — yet the two prefetch SELECT queries still fire on every providers_list call. For a Monthly view that touches a few thousand notes, that is two side queries returning data that is immediately discarded.

### Query Bounds

All queries are bounded by `note__datetime_of_service__gte=start` AND `note__datetime_of_service__lt=end`. The window is at most one calendar month. No unbounded `.all()` queries against the canonical Canvas tables (Note, Patient, Staff, Command).

### Large Queryset Materialization

No `list(...)` wrapping anywhere in plugin code.

### Missing `.iterator()`

The result set is bounded by the time window (≤1 month) and by the practice's note volume — typically hundreds-to-low-thousands of rows even for Monthly. `.iterator()` would offer no meaningful memory benefit at this scale and would disable Django's queryset cache (which the second prefetch consumes anyway). Not applicable.

### Missing `.only()`

`Note` is a moderately wide model — it has `body` and `related_data` (both JSONField) plus `billing_note` (TextField). The endpoints read only `id`, `datetime_of_service`, plus the FKs already covered by `select_related`. A `.only(...)` clause could reduce per-row payload from the DB, especially for Monthly windows. Modest gain (LOW priority) and would need to be combined with explicit `select_related` field listing to keep the JOINs.

## Recommendations

| Priority | Issue | Location | Recommendation |
|---|---|---|---|
| MEDIUM | `providers_list` triggers two prefetch SELECTs whose results are never read | `dashboard_api.py:171–182` (helper) consumed at `:225–241` | Make the prefetches optional. Either: (a) add a `with_note_details: bool` param to `_fetch_locked_state_events` (default True; pass False from `providers_list`), or (b) replace `providers_list`'s Python aggregation with a single SQL GROUP BY using `.values("note__provider__id", ...).annotate(count=Count("id"))`. (b) is more scalable; (a) is the smaller diff. |
| LOW | Notes are fetched with all columns including JSON `body`/`related_data` | `dashboard_api.py:163–172` | Add `.only("state", "note__id", "note__datetime_of_service", "note__provider_id", "note__patient_id", "note__note_type_version_id")` (or equivalent) and rely on `select_related` for the joined columns actually rendered. Modest payload reduction; verify nothing else reads the wide fields. |

## Verdict

**1 MEDIUM, 1 LOW** — The plugin has no N+1, no unbounded queries, and no memory hazards. The single notable issue is that the providers_list endpoint shares an over-fetching helper with provider_notes; for typical clinical volumes this is acceptable, but it does cost two unused side queries per refresh and would scale poorly under heavy Monthly usage. The LOW `.only()` finding is a micro-optimization.
