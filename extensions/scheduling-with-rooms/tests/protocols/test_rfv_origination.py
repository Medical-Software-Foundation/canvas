"""Tests for rfv_origination.py."""

import datetime
from unittest.mock import MagicMock, patch

from scheduling_with_rooms.protocols.rfv_origination import ReasonForVisitOrigination


def _handler():
    h = ReasonForVisitOrigination.__new__(ReasonForVisitOrigination)
    event = MagicMock()
    event.target.id = "appt-id-1"
    h.event = event
    h.secrets = {}
    return h


def test_compute_appointment_not_found():
    h = _handler()
    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt:
        from canvas_sdk.v1.data.appointment import Appointment as Appt

        mock_appt.objects.select_related.return_value.get.side_effect = Appt.DoesNotExist
        mock_appt.DoesNotExist = Appt.DoesNotExist
        assert h.compute() == []


def test_compute_missing_patient():
    h = _handler()
    appt = MagicMock()
    appt.patient = None
    appt.provider = MagicMock(id="prov-1")
    appt.start_time = datetime.datetime(2026, 5, 7, 10, 0)
    appt.note = MagicMock(id="note-1")

    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt:
        mock_appt.objects.select_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_missing_provider():
    h = _handler()
    appt = MagicMock()
    appt.patient = MagicMock(id="pt-1")
    appt.provider = None
    appt.start_time = datetime.datetime(2026, 5, 7, 10, 0)

    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt:
        mock_appt.objects.select_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_missing_start_time():
    h = _handler()
    appt = MagicMock()
    appt.patient = MagicMock(id="pt-1")
    appt.provider = MagicMock(id="prov-1")
    appt.start_time = None

    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt:
        mock_appt.objects.select_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_no_cached_text():
    h = _handler()
    appt = MagicMock()
    appt.patient = MagicMock(id="pt-1")
    appt.provider = MagicMock(id="prov-1")
    appt.start_time = datetime.datetime(2026, 5, 7, 10, 0)
    appt.note = MagicMock(id="note-1")

    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.rfv_origination.pop_rfv", return_value=""
    ):
        mock_appt.objects.select_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_no_note():
    h = _handler()
    appt = MagicMock()
    appt.patient = MagicMock(id="pt-1")
    appt.provider = MagicMock(id="prov-1")
    appt.start_time = datetime.datetime(2026, 5, 7, 10, 0)
    appt.note = None

    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.rfv_origination.pop_rfv", return_value="fever"
    ):
        mock_appt.objects.select_related.return_value.get.return_value = appt
        assert h.compute() == []


def test_compute_originates_rfv_command():
    h = _handler()
    appt = MagicMock()
    appt.patient = MagicMock(id="pt-1")
    appt.provider = MagicMock(id="prov-1")
    appt.start_time = datetime.datetime(2026, 5, 7, 10, 0)
    appt.note = MagicMock(id="note-1")

    fake_effect = MagicMock(name="effect")

    with patch(
        "scheduling_with_rooms.protocols.rfv_origination.Appointment"
    ) as mock_appt, patch(
        "scheduling_with_rooms.protocols.rfv_origination.pop_rfv", return_value="fever"
    ), patch(
        "scheduling_with_rooms.protocols.rfv_origination.ReasonForVisitCommand"
    ) as mock_cmd:
        mock_appt.objects.select_related.return_value.get.return_value = appt
        mock_cmd.return_value.originate.return_value = fake_effect

        result = h.compute()
        assert result == [fake_effect]
        # Verify cmd was created with note_uuid and comment
        assert mock_cmd.call_args.kwargs["comment"] == "fever"
