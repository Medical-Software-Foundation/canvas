"""Tests for my_schedule.handlers.schedule_api.

The important ones prove the API only ever answers for the logged-in staff member.
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

from my_schedule.handlers import schedule_api
from my_schedule.handlers.schedule_api import (
    MyScheduleAPI,
    _parse_iso,
    _serialize_appointment,
)

ME = "11111111-1111-1111-1111-111111111111"
APPT_ID = "22222222-2222-2222-2222-222222222222"
ALL_ON = {"ALLOW_STATUS_UPDATES": "yes", "ALLOW_CANCEL": "yes", "ALLOW_NO_SHOW": "yes"}


def _api(query=None, path=None, body=None, secrets=None, headers=None) -> MyScheduleAPI:
    api = MyScheduleAPI.__new__(MyScheduleAPI)
    raw = json.dumps(body).encode() if body is not None else b"not json"

    def _json():
        return json.loads(raw)

    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": ME},
        query_params=query or {},
        path_params=path or {},
        json=_json,
    )
    api.secrets = secrets or {}
    return api


def _body(response):
    return json.loads(response.content)


def _note(state):
    """A note whose current state is `state`, or has no state row when None."""
    note = MagicMock()
    note.id = "note-uuid"
    if state is None:
        type(note).current_state = property(
            lambda self: (_ for _ in ()).throw(CurrentNoteStateEvent.DoesNotExist())
        )
    else:
        note.current_state.state = state
    return note


def _appt(note_state=NoteStates.BOOKED, note_id=5):
    return SimpleNamespace(id=APPT_ID, note_id=note_id, note=_note(note_state))


class TestParseIso:
    def test_accepts_z(self) -> None:
        assert _parse_iso("2026-10-27T00:00:00Z") == datetime(2026, 10, 27, tzinfo=timezone.utc)

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError):
            _parse_iso("2026-10-27T00:00:00")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            _parse_iso("tomorrow")


class TestSerialize:
    def test_full(self) -> None:
        appt = SimpleNamespace(
            id="a1",
            start_time=datetime(2026, 10, 27, 9, tzinfo=timezone.utc),
            duration_minutes=30,
            patient=SimpleNamespace(id="p-key", first_name="Agent", last_name="Alpha"),
            note_type=SimpleNamespace(name="Follow-up"),
            description="Check-in",
            location=SimpleNamespace(full_name="Main Clinic"),
            status="confirmed",
        )
        assert _serialize_appointment(appt) == {
            "id": "a1",
            "start_time": "2026-10-27T09:00:00+00:00",
            "duration_minutes": 30,
            "patient_id": "p-key",
            "patient_name": "Agent Alpha",
            "appointment_type": "Follow-up",
            "reason_for_visit": "Check-in",
            "location": "Main Clinic",
            "status": "confirmed",
        }

    def test_blanks(self) -> None:
        appt = SimpleNamespace(
            id="a2", start_time=None, duration_minutes=None, patient=None,
            note_type=None, description=None, location=None, status=None,
        )
        result = _serialize_appointment(appt)
        assert result["patient_name"] == ""
        assert result["location"] == ""
        assert result["start_time"] is None


class TestIndex:
    def test_flags_off_by_default(self) -> None:
        with patch.object(schedule_api, "render_to_string", return_value="<html>") as render:
            _api().index()
        context = render.call_args.args[1]
        assert context["allow_status"] == "false"
        assert context["allow_cancel"] == "false"
        assert context["allow_noshow"] == "false"

    def test_flags_on(self) -> None:
        with patch.object(schedule_api, "render_to_string", return_value="<html>") as render:
            _api(secrets=ALL_ON).index()
        context = render.call_args.args[1]
        assert context["allow_status"] == context["allow_cancel"] == context["allow_noshow"] == "true"


class TestAppointments:
    QUERY = {"start": "2026-10-27T00:00:00Z", "end": "2026-10-28T00:00:00Z"}

    def test_scoped_to_logged_in_staff(self) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            qs = model.objects.filter.return_value
            qs.exclude.return_value.exclude.return_value.select_related.return_value.order_by.return_value = []
            response = _api(query=self.QUERY).appointments()[0]
        assert response.status_code == HTTPStatus.OK
        kwargs = model.objects.filter.call_args.kwargs
        assert kwargs["provider__id"] == ME
        assert kwargs["entered_in_error__isnull"] is True

    def test_provider_param_is_ignored(self) -> None:
        query = dict(self.QUERY, provider_id="someone-else", provider="someone-else")
        with patch.object(schedule_api, "Appointment") as model:
            qs = model.objects.filter.return_value
            qs.exclude.return_value.exclude.return_value.select_related.return_value.order_by.return_value = []
            _api(query=query).appointments()
        assert model.objects.filter.call_args.kwargs["provider__id"] == ME

    @pytest.mark.parametrize(
        "query",
        [
            {},
            {"start": "2026-10-27T00:00:00Z"},
            {"start": "bad", "end": "2026-10-28T00:00:00Z"},
            {"start": "2026-10-27T00:00:00", "end": "2026-10-28T00:00:00"},
            {"start": "2026-10-28T00:00:00Z", "end": "2026-10-27T00:00:00Z"},
            {"start": "2026-01-01T00:00:00Z", "end": "2026-12-31T00:00:00Z"},
        ],
    )
    def test_bad_ranges_rejected(self, query) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            response = _api(query=query).appointments()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        model.objects.filter.assert_not_called()


class TestActions:
    @pytest.mark.parametrize("action", ["update_status", "cancel", "noshow"])
    def test_off_by_default(self, action) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            response = getattr(_api(path={"appointment_id": APPT_ID}), action)()[0]
        assert response.status_code == HTTPStatus.FORBIDDEN
        model.objects.filter.assert_not_called()

    @pytest.mark.parametrize("action", ["update_status", "cancel", "noshow"])
    def test_someone_elses_appointment_is_not_found(self, action) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            model.objects.filter.return_value.select_related.return_value.first.return_value = None
            api = _api(path={"appointment_id": APPT_ID}, body={"status": "arrived"}, secrets=ALL_ON)
            result = getattr(api, action)()
        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND
        kwargs = model.objects.filter.call_args.kwargs
        assert kwargs == {"id": APPT_ID, "provider__id": ME, "entered_in_error__isnull": True}

    @pytest.mark.parametrize("action", ["update_status", "cancel", "noshow"])
    def test_non_uuid_id_is_not_found_without_query(self, action) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            api = _api(path={"appointment_id": "1 OR 1=1"}, secrets=ALL_ON)
            response = getattr(api, action)()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND
        model.objects.filter.assert_not_called()

    def _own(self, model, appt):
        model.objects.filter.return_value.select_related.return_value.first.return_value = appt

    def test_status_update_on_own(self) -> None:
        with (
            patch.object(schedule_api, "Appointment") as model,
            patch.object(schedule_api, "AppointmentEffect") as effect,
        ):
            self._own(model, _appt())
            result = _api(
                path={"appointment_id": APPT_ID}, body={"status": "arrived"}, secrets=ALL_ON
            ).update_status()
        effect.assert_called_once_with(
            instance_id=APPT_ID, status=AppointmentProgressStatus.ARRIVED
        )
        assert result[0] is effect.return_value.update.return_value
        assert result[1].status_code == HTTPStatus.OK

    @pytest.mark.parametrize(
        "body",
        [{"status": "noshowed"}, {"status": "cancelled"}, {}, ["x"], {"status": []}, {"status": {}}],
    )
    def test_status_rejects_other_values(self, body) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            self._own(model, _appt())
            result = _api(path={"appointment_id": APPT_ID}, body=body, secrets=ALL_ON).update_status()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_status_rejects_bad_json(self) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            self._own(model, _appt())
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).update_status()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize("state", [NoteStates.BOOKED, NoteStates.CONVERTED])
    def test_cancel_own(self, state) -> None:
        with (
            patch.object(schedule_api, "Appointment") as model,
            patch.object(schedule_api, "AppointmentEffect") as effect,
        ):
            self._own(model, _appt(note_state=state))
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).cancel()
        effect.assert_called_once_with(instance_id=APPT_ID)
        assert result[0] is effect.return_value.cancel.return_value
        assert result[1].status_code == HTTPStatus.OK

    @pytest.mark.parametrize("state", [NoteStates.LOCKED, None])
    def test_cancel_refused_for_locked_or_unknown_note(self, state) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            self._own(model, _appt(note_state=state))
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).cancel()
        assert result[0].status_code == HTTPStatus.CONFLICT

    def test_cancel_refused_without_note(self) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            self._own(model, _appt(note_id=None))
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).cancel()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize("state", [NoteStates.BOOKED, NoteStates.REVERTED])
    def test_noshow_own(self, state) -> None:
        with (
            patch.object(schedule_api, "Appointment") as model,
            patch.object(schedule_api, "NoteEffect") as effect,
        ):
            self._own(model, _appt(note_state=state))
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).noshow()
        effect.assert_called_once_with(instance_id="note-uuid")
        assert result[0] is effect.return_value.no_show.return_value
        assert result[1].status_code == HTTPStatus.OK

    @pytest.mark.parametrize("state", [NoteStates.CONVERTED, NoteStates.NOSHOW, None])
    def test_noshow_refused_in_other_states(self, state) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            self._own(model, _appt(note_state=state))
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).noshow()
        assert result[0].status_code == HTTPStatus.CONFLICT

    def test_noshow_refused_without_note(self) -> None:
        with patch.object(schedule_api, "Appointment") as model:
            self._own(model, _appt(note_id=None))
            result = _api(path={"appointment_id": APPT_ID}, secrets=ALL_ON).noshow()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST


class TestStaticAssets:
    @pytest.mark.parametrize(
        ("method", "content_type"),
        [("main_js", "text/javascript"), ("styles_css", "text/css")],
    )
    def test_assets(self, method, content_type) -> None:
        with patch.object(schedule_api, "render_to_string", return_value="x"):
            response = getattr(_api(), method)()[0]
        assert response.status_code == HTTPStatus.OK
        assert response.headers["Content-Type"].startswith(content_type)
