"""Tests for the chart-view, profile-view, and chart-review-sign handlers.

The plugin records *which patient* a staff member touched, classified
only as chart or profile (no view vs action distinction). The
chart-review-sign handler is a safety net for the inbox/schedule
result-review path, which doesn't fire PATIENT_CHART_SUMMARY__...
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from recent_patients.protocols.track_interactions import (
    CHART_VIEW,
    PROFILE_VIEW,
    TrackChartReviewSign,
    TrackChartView,
    TrackProfileView,
    _record,
    _staff_uuid_from_canvas_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Dynamically created stand-ins whose `__class__.__name__` is exactly
# 'Staff' or 'Patient' — what the production code checks. Using type()
# avoids importing the real SDK models just for a name match.
_StandIn = {
    "Staff": type("Staff", (), {"__init__": lambda self, uuid: setattr(self, "id", uuid)}),
    "Patient": type("Patient", (), {"__init__": lambda self, uuid: setattr(self, "id", uuid)}),
}


def _canvas_user_for(kind: str, uuid: str) -> SimpleNamespace:
    """A CanvasUser-like object whose `person_subclass` is a Staff/Patient stand-in."""
    return SimpleNamespace(person_subclass=_StandIn[kind](uuid))


def _patient_load_event(
    *,
    patient_id: str,
    actor_kind: str | None,
    actor_uuid: str = "staff-1",
) -> SimpleNamespace:
    if actor_kind is None:
        actor = None
    else:
        actor = SimpleNamespace(instance=_canvas_user_for(actor_kind, actor_uuid))
    return SimpleNamespace(
        target=SimpleNamespace(id=patient_id),
        context={},
        actor=actor,
    )


# ---------------------------------------------------------------------------
# TrackChartView
# ---------------------------------------------------------------------------


class TestTrackChartView:
    def test_staff_chart_view_records(self, patch_record: list) -> None:
        event = _patient_load_event(
            patient_id="pt-50", actor_kind="Staff", actor_uuid="staff-50"
        )
        TrackChartView(event=event).compute()
        assert patch_record == [("staff-50", "pt-50", CHART_VIEW)]

    def test_missing_actor_skips(self, patch_record: list) -> None:
        event = _patient_load_event(patient_id="pt-50", actor_kind=None)
        TrackChartView(event=event).compute()
        assert patch_record == []

    def test_patient_actor_does_not_record_staff(
        self, patch_record: list
    ) -> None:
        # A patient session viewing their own chart should not populate
        # any staff member's recent list (no Staff resolves on the actor).
        event = _patient_load_event(
            patient_id="pt-50", actor_kind="Patient", actor_uuid="pt-50"
        )
        TrackChartView(event=event).compute()
        assert patch_record == [(None, "pt-50", CHART_VIEW)]

    def test_actor_without_instance_skips(self, patch_record: list) -> None:
        event = SimpleNamespace(
            target=SimpleNamespace(id="pt-77"),
            context={},
            actor=SimpleNamespace(),  # actor present but missing .instance
        )
        TrackChartView(event=event).compute()
        assert patch_record == [(None, "pt-77", CHART_VIEW)]


# ---------------------------------------------------------------------------
# TrackProfileView
# ---------------------------------------------------------------------------


class TestTrackProfileView:
    def test_staff_profile_view_records(self, patch_record: list) -> None:
        event = _patient_load_event(
            patient_id="pt-60", actor_kind="Staff", actor_uuid="staff-60"
        )
        TrackProfileView(event=event).compute()
        assert patch_record == [("staff-60", "pt-60", PROFILE_VIEW)]

    def test_missing_actor_skips(self, patch_record: list) -> None:
        event = _patient_load_event(patient_id="pt-60", actor_kind=None)
        TrackProfileView(event=event).compute()
        assert patch_record == []


# ---------------------------------------------------------------------------
# TrackChartReviewSign (the inbox / schedule result-review safety net)
# ---------------------------------------------------------------------------


def _nsce_with_category(category: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="nsce-99",
        originator=_canvas_user_for("Staff", "staff-99"),
        note=SimpleNamespace(
            patient=SimpleNamespace(id="pt-99"),
            note_type_version=(
                SimpleNamespace(category=category) if category else None
            ),
        ),
    )


class TestTrackChartReviewSign:
    def _event(self, state: str, patient_id: str = "pt-99") -> SimpleNamespace:
        return SimpleNamespace(
            target=SimpleNamespace(id="nsce-99"),
            context={"state": state, "patient_id": patient_id},
            actor=None,
        )

    def test_ignores_non_locked_states(self, patch_record: list) -> None:
        result = TrackChartReviewSign(event=self._event("NEW")).compute()
        assert result == []
        assert patch_record == []

    def test_chart_review_lock_records_chart_view(
        self, patch_record: list
    ) -> None:
        # Labs / imaging / consults / uncategorized-doc reviews from the
        # schedule view all land as 'review' category notes that get
        # locked. We treat them as a chart touch.
        with patch(
            "recent_patients.protocols.track_interactions"
            ".NoteStateChangeEvent.objects"
        ) as mgr:
            mgr.select_related.return_value.get.return_value = (
                _nsce_with_category("review")
            )
            TrackChartReviewSign(event=self._event("LKD", "pt-99")).compute()

        assert patch_record == [("staff-99", "pt-99", CHART_VIEW)]

    def test_non_review_note_lock_does_not_record(
        self, patch_record: list
    ) -> None:
        # Encounter / message / appointment notes signed elsewhere
        # already get captured via chart_view from when the user opened
        # the chart, so this handler bails out for non-review categories.
        with patch(
            "recent_patients.protocols.track_interactions"
            ".NoteStateChangeEvent.objects"
        ) as mgr:
            mgr.select_related.return_value.get.return_value = (
                _nsce_with_category("encounter")
            )
            result = TrackChartReviewSign(event=self._event("LKD")).compute()
        assert result == []
        assert patch_record == []

    def test_missing_note_type_version_does_not_record(
        self, patch_record: list
    ) -> None:
        with patch(
            "recent_patients.protocols.track_interactions"
            ".NoteStateChangeEvent.objects"
        ) as mgr:
            mgr.select_related.return_value.get.return_value = (
                _nsce_with_category(None)
            )
            TrackChartReviewSign(event=self._event("LKD")).compute()
        assert patch_record == []

    def test_db_miss_is_skipped(self, patch_record: list) -> None:
        from canvas_sdk.v1.data.note import NoteStateChangeEvent

        with patch(
            "recent_patients.protocols.track_interactions"
            ".NoteStateChangeEvent.objects"
        ) as mgr:
            mgr.select_related.return_value.get.side_effect = (
                NoteStateChangeEvent.DoesNotExist
            )
            result = TrackChartReviewSign(event=self._event("LKD")).compute()
        assert result == []
        assert patch_record == []


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestStaffUuidFromCanvasUser:
    def test_none_user_returns_none(self) -> None:
        assert _staff_uuid_from_canvas_user(None) is None

    def test_staff_subclass_returns_uuid(self) -> None:
        user = _canvas_user_for("Staff", "staff-1")
        assert _staff_uuid_from_canvas_user(user) == "staff-1"

    def test_patient_subclass_returns_none(self) -> None:
        user = _canvas_user_for("Patient", "pt-1")
        assert _staff_uuid_from_canvas_user(user) is None

    def test_user_without_subclass_returns_none(self) -> None:
        assert _staff_uuid_from_canvas_user(SimpleNamespace()) is None


# ---------------------------------------------------------------------------
# _record gating
# ---------------------------------------------------------------------------


class TestRecord:
    def test_missing_staff_id_short_circuits(self) -> None:
        with patch(
            "recent_patients.protocols.track_interactions"
            ".RecentPatientInteraction.objects"
        ) as mgr:
            _record(None, "pt-1", CHART_VIEW)
            assert not mgr.update_or_create.called

    def test_missing_patient_id_short_circuits(self) -> None:
        with patch(
            "recent_patients.protocols.track_interactions"
            ".RecentPatientInteraction.objects"
        ) as mgr:
            _record("staff-1", "", CHART_VIEW)
            assert not mgr.update_or_create.called

    def test_valid_pair_writes(self) -> None:
        with patch(
            "recent_patients.protocols.track_interactions"
            ".RecentPatientInteraction.objects"
        ) as mgr:
            _record("staff-1", "pt-1", CHART_VIEW)
            assert mgr.update_or_create.called
            kwargs = mgr.update_or_create.call_args.kwargs
            assert kwargs["staff_id"] == "staff-1"
            assert kwargs["patient_id"] == "pt-1"
            assert kwargs["defaults"]["interaction_type"] == CHART_VIEW
            assert "occurred_at" in kwargs["defaults"]
