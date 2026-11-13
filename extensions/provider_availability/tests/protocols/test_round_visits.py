"""Tests for provider_availability.protocols.round_visits."""

from unittest.mock import ANY, MagicMock, call, patch

from provider_availability.protocols.round_visits import (
    OnRoundVisitCanceled,
    OnRoundVisitCreated,
    OnRoundVisitRescheduled,
    OnRoundVisitRestored,
)

MODULE = "provider_availability.protocols.round_visits"


def _event(appointment_id="appt-1"):
    event = MagicMock()
    event.target.id = appointment_id
    return event


def _appt(appointment_id="appt-1", rescheduled_from=None):
    appt = MagicMock()
    appt.id = appointment_id
    appt.appointment_rescheduled_from = rescheduled_from
    return appt


class TestCreated:
    def test_a_new_visit_is_labeled_and_counted(self):
        appt = _appt()
        with patch(f"{MODULE}._load", return_value=appt), \
             patch(f"{MODULE}.visit_effects", return_value=["label", "block"]) as visits:
            assert OnRoundVisitCreated(_event()).compute() == ["label", "block"]
        assert visits.mock_calls == [call(appt)]

    def test_a_replacement_is_left_to_the_reschedule_handler(self):
        with patch(f"{MODULE}._load", return_value=_appt(rescheduled_from=_appt("old"))), \
             patch(f"{MODULE}.visit_effects") as visits:
            assert OnRoundVisitCreated(_event()).compute() == []
        assert visits.mock_calls == []

    def test_a_missing_visit_does_nothing(self):
        with patch(f"{MODULE}._load", return_value=None), patch(f"{MODULE}.visit_effects") as visits:
            assert OnRoundVisitCreated(_event()).compute() == []
        assert visits.mock_calls == []


class TestRescheduled:
    def test_event_on_the_replacement_recounts_both_rounds(self):
        old = _appt("old")
        new = _appt("new", rescheduled_from=old)
        with patch(f"{MODULE}._load", return_value=new), \
             patch(f"{MODULE}.visit_effects", side_effect=[["unblock"], ["label"]]) as visits:
            assert OnRoundVisitRescheduled(_event("new")).compute() == ["unblock", "label"]
        assert visits.mock_calls == [call(old, label=False, counted=ANY), call(new, counted=ANY)]

    def test_event_on_the_original_finds_the_replacement(self):
        old = _appt("old")
        new = _appt("new", rescheduled_from=old)
        with patch(f"{MODULE}._load", return_value=old), \
             patch(f"{MODULE}.Appointment.objects") as objects, \
             patch(f"{MODULE}.visit_effects", side_effect=[["unblock"], ["label"]]) as visits:
            objects.filter.return_value.select_related.return_value.first.return_value = new
            assert OnRoundVisitRescheduled(_event("old")).compute() == ["unblock", "label"]
        assert objects.filter.call_args.kwargs == {"appointment_rescheduled_from__id": "old", "entered_in_error__isnull": True}
        assert visits.mock_calls == [call(old, label=False, counted=ANY), call(new, counted=ANY)]

    def test_original_with_no_replacement_yet_is_only_recounted(self):
        old = _appt("old")
        with patch(f"{MODULE}._load", return_value=old), \
             patch(f"{MODULE}.Appointment.objects") as objects, \
             patch(f"{MODULE}.visit_effects", return_value=["unblock"]) as visits:
            objects.filter.return_value.select_related.return_value.first.return_value = None
            assert OnRoundVisitRescheduled(_event("old")).compute() == ["unblock"]
        assert visits.mock_calls == [call(old, label=False, counted=ANY)]

    def test_a_missing_visit_does_nothing(self):
        with patch(f"{MODULE}._load", return_value=None), patch(f"{MODULE}.visit_effects") as visits:
            assert OnRoundVisitRescheduled(_event()).compute() == []
        assert visits.mock_calls == []


class TestCanceledAndRestored:
    def test_a_cancelled_visit_is_recounted_without_a_label(self):
        appt = _appt()
        with patch(f"{MODULE}._load", return_value=appt), \
             patch(f"{MODULE}.visit_effects", return_value=["unblock"]) as visits:
            assert OnRoundVisitCanceled(_event()).compute() == ["unblock"]
        assert visits.mock_calls == [call(appt, label=False)]

    def test_a_restored_visit_is_labeled_and_recounted(self):
        appt = _appt()
        with patch(f"{MODULE}._load", return_value=appt), \
             patch(f"{MODULE}.visit_effects", return_value=["block"]) as visits:
            assert OnRoundVisitRestored(_event()).compute() == ["block"]
        assert visits.mock_calls == [call(appt)]

    def test_missing_visits_do_nothing(self):
        with patch(f"{MODULE}._load", return_value=None), patch(f"{MODULE}.visit_effects") as visits:
            assert OnRoundVisitCanceled(_event()).compute() == []
            assert OnRoundVisitRestored(_event()).compute() == []
        assert visits.mock_calls == []
