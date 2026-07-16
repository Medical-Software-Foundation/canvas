"""Periodic (every 15 min) reconciliation + backfill for PatientPanelStats.

The cron is the SOURCE OF TRUTH: it recomputes every patient's row, repairing
drift from missed/failed events and creating rows for patients that never fired
one. reconcile_all_stats() is also the backfill routine (idempotent).

Set-based implementation: ~5 aggregate GROUP BY queries to collect all stats,
then a chunked bulk-upsert over every patient — ~40 DB ops for 35k patients
instead of ~175k. Each bulk_create call is capped at _CHUNK (1,000) records,
well inside the Canvas 10,000-record bulk-operation limit.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from patient_panel.services.stats_recompute import reconcile_all_stats

__all__ = ["PanelStatsReconcile", "reconcile_all_stats"]


class PanelStatsReconcile(CronTask):
    """Full reconciliation of the stats table, every 15 minutes.

    Set-based (~5 aggregates + chunked upsert; seconds even at 35k patients), so
    a 15-min cadence is cheap (<~1% duty cycle). NOTE: this cron is NOT the
    freshness source for last_visit/next_visit/room/tasks — those are updated in
    real time by the panel_stats_sync event handlers (NOTE_*, TASK_*,
    PATIENT_ADDRESS_*). The cadence only governs:
      (1) gaps_due_count — derived from ProtocolCurrent, which has NO event-sync
          handler, so the cron is its ONLY refresh source;
      (2) cold-start — an empty/incomplete table self-heals within <=15 min
          (paired with the LEFT-JOIN-equivalent sort, the panel stays correct
          and fast even before the table is populated);
      (3) drift repair for missed/failed sync events."""

    SCHEDULE = "*/15 * * * *"  # every 15 minutes

    def execute(self) -> list[Effect]:
        reconcile_all_stats()
        return []
