"""Tests for provider_availability.protocols.round_visits."""

from unittest.mock import ANY, MagicMock, call, patch

import pytest

from provider_availability.protocols.round_visits import (
    OnRoundVisitCanceled,
    OnRoundVisitCreated,
    OnRoundVisitRescheduled,
    OnRoundVisitRestored,
    OnRoundVisitUpdated,
    _load,
)

MODULE = "provider_availability.protocols.round_visits"


@pytest.fixture(autouse=True)
def remembered():
    """Saving where a visit was counted needs the plugin cache."""
    with patch(f"{MODULE}.remember_visit") as remember:
        yield remember


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


NOTE = {"provider_id": "prov-1", "start": "2026-11-03T17:00:00+00:00", "countable": True}
MOVED = {**NOTE, "provider_id": "prov-2"}


class TestUpdated:
    """An edit: stop when the visit didn't move; otherwise recount its old and new places."""

    def _run(self, appt, current, before, drawn=True):
        with patch(f"{MODULE}.rounds_drawn", return_value=drawn), \
             patch(f"{MODULE}._load", return_value=appt) as load, \
             patch(f"{MODULE}.visit_note", return_value=current), \
             patch(f"{MODULE}.get_round_visit", return_value=before), \
             patch(f"{MODULE}.recount_previous", return_value=["old"]) as previous, \
             patch(f"{MODULE}.visit_effects", return_value=["new"]) as visits, \
             patch(f"{MODULE}.recheck_full_effects", return_value=["stale"]) as recheck:
            effects = OnRoundVisitUpdated(_event()).compute()
        return effects, load, previous, visits, recheck

    def _appt(self):
        appt = _appt()
        appt.status = "confirmed"
        return appt

    def test_an_edit_that_did_not_move_the_visit_stops_early(self, remembered):
        effects, _, previous, visits, recheck = self._run(self._appt(), NOTE, dict(NOTE))
        assert effects == []
        assert previous.mock_calls == visits.mock_calls == recheck.mock_calls == remembered.mock_calls == []

    def test_a_moved_visit_recounts_its_old_and_new_places(self, remembered):
        appt = self._appt()
        effects, _, previous, visits, recheck = self._run(appt, MOVED, NOTE)
        assert effects == ["old", "new"]
        assert previous.mock_calls == [call(NOTE, ANY)]
        counted = previous.mock_calls[0].args[1]
        assert visits.mock_calls == [call(appt, label=False, counted=counted)]
        assert recheck.mock_calls == []
        assert remembered.mock_calls == [call(appt, MOVED)]

    def test_a_visit_without_a_note_rechecks_its_provider(self, remembered):
        appt = self._appt()
        effects, _, previous, visits, recheck = self._run(appt, NOTE, None)
        assert effects == ["new", "stale"]
        assert previous.mock_calls == []
        assert recheck.mock_calls == [call("prov-1", ANY)]
        assert remembered.mock_calls == [call(appt, NOTE)]

    def test_a_visit_moved_off_every_round_provider_recounts_its_old_place(self, remembered):
        with patch(f"{MODULE}.clear_round_visit") as clear:
            effects, _, previous, _, recheck = self._run(self._appt(), None, NOTE)
        assert effects == ["old", "new"]
        assert recheck.mock_calls == []
        assert remembered.mock_calls == []
        assert clear.mock_calls == [call("appt-1")]

    def test_a_visit_that_never_touched_a_round_reads_nothing_more(self):
        effects, _, previous, visits, _ = self._run(self._appt(), None, None)
        assert effects == []
        assert previous.mock_calls == visits.mock_calls == []

    def test_rounds_off_and_removed_reads_nothing(self):
        effects, load, *_ = self._run(self._appt(), NOTE, None, drawn=False)
        assert effects == []
        assert load.mock_calls == []

    def test_canceled_visits_are_left_to_the_cancel_handler(self):
        from canvas_sdk.v1.data.appointment import AppointmentProgressStatus

        appt = _appt()
        appt.status = AppointmentProgressStatus.CANCELLED
        effects, _, previous, visits, _ = self._run(appt, NOTE, None)
        assert effects == []
        assert previous.mock_calls == visits.mock_calls == []

    def test_missing_visit(self):
        assert self._run(None, None, None)[0] == []


def test_every_round_handler_remembers_the_visit(remembered):
    appt = _appt()
    with patch(f"{MODULE}._load", return_value=appt), patch(f"{MODULE}.visit_effects", return_value=[]):
        OnRoundVisitCreated(_event()).compute()
        OnRoundVisitCanceled(_event()).compute()
        OnRoundVisitRestored(_event()).compute()
    assert remembered.mock_calls == [call(appt)] * 3


def test_load_includes_entered_in_error_visits():
    with patch(f"{MODULE}.Appointment") as model:
        _load("appt-1")
    assert model.objects.filter.mock_calls[0] == call(id="appt-1")
