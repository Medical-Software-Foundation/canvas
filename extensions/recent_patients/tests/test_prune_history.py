"""Tests for the nightly prune CronTask."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from recent_patients.protocols.prune_history import (
    RETENTION_DAYS,
    PruneOldInteractions,
)


def _cron(target: str = "2026-05-14T03:00:00Z") -> PruneOldInteractions:
    event = SimpleNamespace(target=target, context={})
    return PruneOldInteractions(event=event)


class TestPruneOldInteractions:
    def test_schedule_runs_nightly_at_3am_utc(self) -> None:
        # If someone changes the cron string, this test surfaces it — the
        # spec promises *nightly*, not every-minute or every-day-at-noon.
        assert PruneOldInteractions.SCHEDULE == "0 3 * * *"

    def test_deletes_rows_older_than_retention(self) -> None:
        mock_qs = MagicMock()
        mock_qs.delete.return_value = (3, {"recent_patients.RecentPatientInteraction": 3})

        with patch(
            "recent_patients.protocols.prune_history"
            ".RecentPatientInteraction.objects"
        ) as mgr:
            mgr.filter.return_value = mock_qs
            result = _cron().execute()

        assert result == []
        assert mgr.filter.called
        # The filter must be on occurred_at__lt with a cutoff RETENTION_DAYS in the past.
        kwargs = mgr.filter.call_args.kwargs
        cutoff = kwargs["occurred_at__lt"]
        expected = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        # Allow a small drift since both calls compute datetime.now() separately.
        assert abs((cutoff - expected).total_seconds()) < 5
        assert mock_qs.delete.called

    def test_empty_table_is_handled(self) -> None:
        mock_qs = MagicMock()
        mock_qs.delete.return_value = (0, {})
        with patch(
            "recent_patients.protocols.prune_history"
            ".RecentPatientInteraction.objects"
        ) as mgr:
            mgr.filter.return_value = mock_qs
            result = _cron().execute()
        assert result == []
