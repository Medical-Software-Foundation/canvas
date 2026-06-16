import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scheduling_app.handlers.scheduling_web_app import (
    SchedulingWebApp,
    _appointment_labels,
    _appointment_rfv,
    _patient_summary,
    _reference_data,
)

from canvas_sdk.v1.data.task import TaskLabelModule

MODULE = "scheduling_app.handlers.scheduling_web_app"


def _model(items: list) -> MagicMock:
    """Mock a data model whose .objects.filter/all(...).order_by(...) yields items."""
    model = MagicMock()
    model.objects.filter.return_value.order_by.return_value = items
    model.objects.all.return_value.order_by.return_value = items
    return model


def test_handler_prefix() -> None:
    """The web app is mounted at /app."""
    assert SchedulingWebApp.PREFIX == "/app"


def test_reference_data_shapes_and_filters() -> None:
    """Reference data converts RFV durations to minutes and filters labels by module."""
    staff = SimpleNamespace(id="staff-key", full_name="Ada Lovelace")
    location = SimpleNamespace(id="loc-uuid", full_name="Main Clinic")
    visit_type = SimpleNamespace(
        id="nt-uuid",
        name="Office Visit",
        is_telehealth=False,
        is_default_appointment_type=True,
        allow_custom_title=False,
        is_patient_required=True,
    )
    rfv = SimpleNamespace(
        id="rfv-ext-id", code="123", display="Cough", duration=[datetime.timedelta(minutes=20)]
    )
    appt_label = SimpleNamespace(
        id="l1", name="Follow up", color="red", modules=[TaskLabelModule.APPOINTMENTS]
    )
    unscoped_label = SimpleNamespace(id="l2", name="VIP", color="blue", modules=[])
    claims_label = SimpleNamespace(id="l3", name="Billing", color="green", modules=["claims"])

    rfv_model = _model([rfv])
    with (
        patch(f"{MODULE}.Staff", _model([staff])),
        patch(f"{MODULE}.PracticeLocation", _model([location])),
        patch(f"{MODULE}.NoteType", _model([visit_type])),
        patch(f"{MODULE}.ReasonForVisitSettingCoding", rfv_model),
        patch(f"{MODULE}.TaskLabel", _model([appt_label, unscoped_label, claims_label])),
    ):
        data = _reference_data("appointment")

    # Only user-selected codings are offered (matches the built-in modal, hiding
    # inactive/unconfigured codes).
    rfv_model.objects.filter.assert_called_once_with(user_selected=True)

    assert data["providers"] == [{"id": "staff-key", "name": "Ada Lovelace"}]
    assert data["locations"] == [{"id": "loc-uuid", "name": "Main Clinic"}]
    assert data["visitTypes"][0]["isDefault"] is True
    assert data["reasonsForVisit"] == [
        {"id": "rfv-ext-id", "code": "123", "display": "Cough", "durations": [20]}
    ]
    assert data["defaultDurations"] == [15, 20, 30, 45, 60]
    # Mirrors the instance's STRUCTURED_REASON_FOR_VISIT_ENABLED flag (default off).
    assert data["structuredReasonForVisit"] is False
    # Labels: appointment-scoped + unscoped included; claims-only excluded.
    assert [label["name"] for label in data["labels"]] == ["Follow up", "VIP"]


def test_patient_summary_includes_demographics() -> None:
    """A patient summary carries name plus the card's demographics (dob/sex/phone)."""
    patient = SimpleNamespace(
        id="pat-key",
        first_name="Seed",
        last_name="Patient",
        birth_date=datetime.date(1971, 5, 18),
        sex_at_birth="F",
        primary_phone_number=SimpleNamespace(value="(784) 555-0199"),
    )
    assert _patient_summary(patient) == {
        "id": "pat-key",
        "name": "Seed Patient",
        "birthDate": "1971-05-18",
        "sex": "F",
        "phone": "(784) 555-0199",
    }


def test_patient_summary_degrades_missing_phone_and_sex_to_none() -> None:
    """Missing phone / blank sex become None rather than raising or emitting ''."""
    patient = SimpleNamespace(
        id="pat-key",
        first_name="No",
        last_name="Contact",
        birth_date=datetime.date(2000, 1, 2),
        sex_at_birth="",
        primary_phone_number=None,
    )
    summary = _patient_summary(patient)
    assert summary["phone"] is None
    assert summary["sex"] is None
    assert summary["birthDate"] == "2000-01-02"


def _command_model(command: object) -> MagicMock:
    """Mock Command whose filter(...).exclude(...).order_by(...).first() yields command."""
    model = MagicMock()
    model.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = (
        command
    )
    return model


def test_appointment_rfv_free_text_round_trips_via_comment() -> None:
    """A free-text reason comes back as rfvText (the command's comment)."""
    appointment = SimpleNamespace(note=SimpleNamespace())
    command = SimpleNamespace(data={"coding": None, "comment": "Persistent cough"})
    with patch(f"{MODULE}.Command", _command_model(command)):
        rfv = _appointment_rfv(appointment)
    assert rfv == {"rfvCode": None, "rfvText": "Persistent cough", "comment": None}


def test_appointment_rfv_coded_reverse_maps_code_to_external_id() -> None:
    """A coded reason (stored as a code) is reverse-mapped to the dropdown's id."""
    appointment = SimpleNamespace(note=SimpleNamespace())
    command = SimpleNamespace(data={"coding": "699134002", "comment": "since Monday"})
    coding_model = MagicMock()
    coding_model.objects.filter.return_value.values_list.return_value.first.return_value = (
        "rfv-ext-id"
    )
    with (
        patch(f"{MODULE}.Command", _command_model(command)),
        patch(f"{MODULE}.ReasonForVisitSettingCoding", coding_model),
    ):
        rfv = _appointment_rfv(appointment)
    coding_model.objects.filter.assert_called_once_with(code="699134002")
    assert rfv == {"rfvCode": "rfv-ext-id", "rfvText": None, "comment": "since Monday"}


def test_appointment_rfv_none_when_no_command() -> None:
    """No reason-for-visit command yields empty prefill values."""
    appointment = SimpleNamespace(note=SimpleNamespace())
    with patch(f"{MODULE}.Command", _command_model(None)):
        rfv = _appointment_rfv(appointment)
    assert rfv == {"rfvCode": None, "rfvText": None, "comment": None}


def test_appointment_labels_returns_names() -> None:
    """Appointment labels come back as their names (missing task_label skipped)."""
    links = [
        SimpleNamespace(task_label=SimpleNamespace(name="Follow up")),
        SimpleNamespace(task_label=SimpleNamespace(name="VIP")),
        SimpleNamespace(task_label=None),
    ]
    label_model = MagicMock()
    label_model.objects.filter.return_value.select_related.return_value = links
    with patch(f"{MODULE}.AppointmentLabel", label_model):
        names = _appointment_labels(SimpleNamespace())
    assert names == ["Follow up", "VIP"]
