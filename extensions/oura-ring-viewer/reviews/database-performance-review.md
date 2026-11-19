# Database Performance Review: oura_ring_viewer

**Generated:** 2026-11-02
**Reviewer:** Claude Code, following the Canvas Plugin Assistant
`/cpa:database-performance-review` checklist (canvas-medical/coding-agents, commit 4e90e08)

## Summary

| Check | Status | Notes |
|---|---|---|
| N+1 query patterns | ✅ Pass | No queries inside loops |
| select_related / prefetch_related | ✅ Pass | No related-object traversal; all reads are keyed `exists()` or `.first()` |
| Unbounded queries | ✅ Pass | Every query is filtered to one patient or one staff member |
| Large queryset materialization | ✅ Pass | No `list()` over querysets; at most one row per model per patient |
| Over-hydration / blob columns | ✅ Pass | No Canvas blob columns are read. Plugin rows are a few short fields |
| Custom-data PK (`dbid`) | ✅ Pass | No `order_by("id")` or `Count("id")` on custom models |
| Write amplification | ✅ Pass | One small status write per successful fetch (see note) |
| Effect-batch ceiling | ✅ Pass | At most one `Message` effect per request |

## Data model

Two custom tables, each with a unique constraint on `patient_id`, so every
plugin read is an indexed point lookup and each patient has at most one row in
each:

- `OuraOAuthToken`: the connection (tokens, expiry, scopes, timestamps).
- `OuraSyncState`: connection status (last read time, last error code, pending link nonce).

**No Oura data is stored.** Summaries are fetched live from Oura for each chart
view and held only in memory for that request, so there is no growing table, no
retention job and no backfill.

## Hot paths

| Path | How often | Queries (approx.) | Writes |
|---|---|---|---|
| `GET /data` (chart open, range change, Refresh) | Per chart view | Gate: `Staff` exists, `CareTeamMembership` exists. Status: 2 keyed reads. Fetch: 1 keyed read. Status again: 2 keyed reads | 1 status upsert. A token refresh adds 1 token upsert |
| `GET /status` (open chart, every 60 s while data is shown) | Per open panel | Gate 2, status 2 | None |
| `GET /data` while not connected (every 10 to 30 s, stops after 30 min) | Per open panel | Gate 2, status 2 | None, and no call to Oura |
| Portal `GET /status` (every 3 s, only after the patient taps Connect, for at most 10 min) | Per waiting patient | 2 keyed reads | None |

Row width is a handful of short columns, so memory per request is negligible.
The Oura response for the largest window (90 days, five endpoints) is a few
hundred small JSON objects held for the length of one request.

## Notes

- **Status write per fetch.** A successful fetch records `last_synced_at` and
  clears any error: one single-row upsert keyed on the unique `patient_id`. It
  triggers no handlers or effects. Accepted: it is what lets the chart show when
  data was last read and clear a stale error.
- **Polling is bounded.** Every client-side poll stops after a fixed time, pauses
  while the browser tab is hidden, and reads only the plugin's own status tables.

## Verdict

**✅ PASS.** No performance issues found.
