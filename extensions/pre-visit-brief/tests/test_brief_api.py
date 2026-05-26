"""Tests for pre_visit_brief.handlers.brief_api."""

from __future__ import annotations

import datetime
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.test_utils.factories import (
    NoteFactory,
    NoteTypeFactory,
    PatientFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteTypeCategories

from pre_visit_brief.handlers.brief_api import (
    BriefAPI,
    _build_card,
    _format_conditions,
    _format_last_visit,
    _format_medications,
    _format_vitals,
)

MODULE = "pre_visit_brief.handlers.brief_api"

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_handler(
    path: str = "/pre_visit_brief/data",
    staff_uuid: str = "staff-uuid-001",
    extra_headers: dict[str, str] | None = None,
    query_string: str = "",
) -> BriefAPI:
    """Build a BriefAPI handler with fully mocked request internals."""
    mock_event = MagicMock()
    handler = BriefAPI(mock_event)

    handler.request = MagicMock()
    handler.request.path = path
    handler.request.query_string = query_string

    headers: dict[str, str] = {"canvas-logged-in-user-id": staff_uuid}
    if extra_headers:
        headers.update(extra_headers)
    handler.request.headers = headers

    return handler


def _make_appointment(
    *,
    patient: Any = None,
    staff: Any = None,
    start_time: datetime.datetime | None = None,
    status: str = AppointmentProgressStatus.CONFIRMED,
    note_type: Any = None,
) -> MagicMock:
    """Return a mock Appointment with common attributes."""
    appt = MagicMock(spec=Appointment)
    appt.patient = patient or MagicMock(id="pat-1", first_name="Alice", last_name="Doe")
    appt.patient_id = str(appt.patient.id)
    appt.start_time = start_time or datetime.datetime(
        2026, 5, 26, 10, 30, tzinfo=datetime.timezone.utc
    )
    appt.status = status
    appt.note_type = note_type
    return appt


# ── Static asset routes ───────────────────────────────────────────────────


def test_get_index_returns_html() -> None:
    """GET / must return 200 with HTML content."""
    handler = _make_handler(path="/pre_visit_brief/")
    with patch(f"{MODULE}.render_to_string", return_value="<html>Brief</html>"):
        result = handler.get_index()

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    body = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
    assert "Brief" in body


def test_get_index_passes_cache_bust_context() -> None:
    """GET / must pass cache_bust in the template context."""
    handler = _make_handler(path="/pre_visit_brief/")
    captured: dict[str, Any] = {}

    def capture_render(
        template: str, context: dict | None = None, **kwargs: Any
    ) -> str:
        captured.update(context or {})
        return "<html></html>"

    with patch(f"{MODULE}.render_to_string", side_effect=capture_render):
        handler.get_index()

    assert "cache_bust" in captured
    assert isinstance(captured["cache_bust"], str)
    assert captured["cache_bust"].isdigit()


def test_get_js_returns_javascript() -> None:
    """GET /main.js must return 200 with application/javascript content type."""
    handler = _make_handler(path="/pre_visit_brief/main.js")
    with patch(f"{MODULE}.render_to_string", return_value="console.log('ok');"):
        result = handler.get_js()

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers.get("Content-Type") == "application/javascript"


def test_get_css_returns_css() -> None:
    """GET /styles.css must return 200 with text/css content type."""
    handler = _make_handler(path="/pre_visit_brief/styles.css")
    with patch(f"{MODULE}.render_to_string", return_value="body{}"):
        result = handler.get_css()

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers.get("Content-Type") == "text/css"


# ── /data – auth and param validation ────────────────────────────────────


def test_get_data_missing_staff_uuid_returns_400() -> None:
    """GET /data without canvas-logged-in-user-id header must return 400."""
    handler = _make_handler(staff_uuid="")
    handler.request.headers = {}  # No header at all
    result = handler.get_data()

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    import json

    body = json.loads(resp.content)
    assert "error" in body


def test_get_data_missing_start_returns_400() -> None:
    """GET /data without ?start param must return 400."""
    handler = _make_handler(query_string="end=2026-05-26T23:59:59")
    handler.request.query_params = {"end": "2026-05-26T23:59:59"}
    result = handler.get_data()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_data_missing_end_returns_400() -> None:
    """GET /data without ?end param must return 400."""
    handler = _make_handler(query_string="start=2026-05-26T00:00:00")
    handler.request.query_params = {"start": "2026-05-26T00:00:00"}
    result = handler.get_data()

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


# ── /data – no appointments path ─────────────────────────────────────────


@patch(f"{MODULE}.Appointment")
def test_get_data_no_appointments_returns_empty_list(mock_appt_cls: MagicMock) -> None:
    """When no appointments match, response must contain an empty appointments list."""
    mock_qs = MagicMock()
    mock_qs.exclude.return_value = mock_qs
    mock_qs.select_related.return_value = mock_qs
    mock_qs.order_by.return_value = mock_qs
    mock_qs.__getitem__ = lambda self, key: []
    mock_appt_cls.objects.filter.return_value = mock_qs

    # Make __iter__ return empty list for list() conversion
    mock_qs.__iter__ = lambda self: iter([])

    handler = _make_handler()
    handler.request.query_params = {
        "start": "2026-05-26T00:00:00+00:00",
        "end": "2026-05-26T23:59:59+00:00",
    }
    result = handler.get_data()

    import json

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    body = json.loads(resp.content)
    assert body["appointments"] == []


# ── /data – with appointments (integration-style, uses real DB) ──────────


@pytest.mark.django_db
def test_get_data_single_appointment_returns_one_card() -> None:
    """With one qualifying appointment, response must contain exactly one card."""
    staff = StaffFactory.create()
    patient = PatientFactory.create(first_name="Jane", last_name="Smith")
    note_type = NoteTypeFactory.create(name="Office Visit")

    today = datetime.date.today()
    start_time = datetime.datetime(
        today.year, today.month, today.day, 10, 30, tzinfo=datetime.timezone.utc
    )

    Appointment.objects.create(
        patient=patient,
        provider=staff,
        start_time=start_time,
        duration_minutes=30,
        status=AppointmentProgressStatus.CONFIRMED,
        note_type=note_type,
        telehealth_instructions_sent=False,
    )

    day_start = datetime.datetime(
        today.year, today.month, today.day, 0, 0, tzinfo=datetime.timezone.utc
    )
    day_end = datetime.datetime(
        today.year, today.month, today.day, 23, 59, tzinfo=datetime.timezone.utc
    )

    handler = _make_handler(staff_uuid=str(staff.id))
    handler.request.query_params = {
        "start": day_start.isoformat(),
        "end": day_end.isoformat(),
    }
    result = handler.get_data()

    import json

    assert len(result) == 1
    body = json.loads(result[0].content)
    assert len(body["appointments"]) == 1
    card = body["appointments"][0]
    assert card["patient_name"] == "Jane Smith"
    assert card["note_type"] == "Office Visit"


@pytest.mark.django_db
def test_get_data_three_appointments_returns_three_cards() -> None:
    """With three qualifying appointments, response must contain exactly three cards."""
    staff = StaffFactory.create()
    note_type = NoteTypeFactory.create(name="Office Visit")
    today = datetime.date.today()

    for hour in [9, 10, 11]:
        patient = PatientFactory.create()
        start_time = datetime.datetime(
            today.year, today.month, today.day, hour, 0, tzinfo=datetime.timezone.utc
        )
        Appointment.objects.create(
            patient=patient,
            provider=staff,
            start_time=start_time,
            duration_minutes=30,
            status=AppointmentProgressStatus.CONFIRMED,
            note_type=note_type,
            telehealth_instructions_sent=False,
        )

    day_start = datetime.datetime(
        today.year, today.month, today.day, 0, 0, tzinfo=datetime.timezone.utc
    )
    day_end = datetime.datetime(
        today.year, today.month, today.day, 23, 59, tzinfo=datetime.timezone.utc
    )

    handler = _make_handler(staff_uuid=str(staff.id))
    handler.request.query_params = {
        "start": day_start.isoformat(),
        "end": day_end.isoformat(),
    }
    result = handler.get_data()

    import json

    body = json.loads(result[0].content)
    assert len(body["appointments"]) == 3


@pytest.mark.django_db
def test_get_data_cancelled_appointments_excluded() -> None:
    """Cancelled appointments must not appear in the response."""
    staff = StaffFactory.create()
    patient = PatientFactory.create()
    note_type = NoteTypeFactory.create(name="Office Visit")
    today = datetime.date.today()
    start_time = datetime.datetime(
        today.year, today.month, today.day, 9, 0, tzinfo=datetime.timezone.utc
    )

    Appointment.objects.create(
        patient=patient,
        provider=staff,
        start_time=start_time,
        duration_minutes=30,
        status=AppointmentProgressStatus.CANCELLED,
        note_type=note_type,
        telehealth_instructions_sent=False,
    )

    day_start = datetime.datetime(
        today.year, today.month, today.day, 0, 0, tzinfo=datetime.timezone.utc
    )
    day_end = datetime.datetime(
        today.year, today.month, today.day, 23, 59, tzinfo=datetime.timezone.utc
    )

    handler = _make_handler(staff_uuid=str(staff.id))
    handler.request.query_params = {
        "start": day_start.isoformat(),
        "end": day_end.isoformat(),
    }
    result = handler.get_data()

    import json

    body = json.loads(result[0].content)
    assert len(body["appointments"]) == 0


@pytest.mark.django_db
def test_get_data_noshowed_appointments_excluded() -> None:
    """No-showed appointments must not appear in the response."""
    staff = StaffFactory.create()
    patient = PatientFactory.create()
    note_type = NoteTypeFactory.create(name="Office Visit")
    today = datetime.date.today()
    start_time = datetime.datetime(
        today.year, today.month, today.day, 9, 0, tzinfo=datetime.timezone.utc
    )

    Appointment.objects.create(
        patient=patient,
        provider=staff,
        start_time=start_time,
        duration_minutes=30,
        status=AppointmentProgressStatus.NOSHOWED,
        note_type=note_type,
        telehealth_instructions_sent=False,
    )

    day_start = datetime.datetime(
        today.year, today.month, today.day, 0, 0, tzinfo=datetime.timezone.utc
    )
    day_end = datetime.datetime(
        today.year, today.month, today.day, 23, 59, tzinfo=datetime.timezone.utc
    )

    handler = _make_handler(staff_uuid=str(staff.id))
    handler.request.query_params = {
        "start": day_start.isoformat(),
        "end": day_end.isoformat(),
    }
    result = handler.get_data()

    import json

    body = json.loads(result[0].content)
    assert len(body["appointments"]) == 0


@pytest.mark.django_db
def test_get_data_card_contains_expected_keys() -> None:
    """Each card in the response must contain the required top-level keys."""
    staff = StaffFactory.create()
    patient = PatientFactory.create()
    note_type = NoteTypeFactory.create(name="Office Visit")
    today = datetime.date.today()
    start_time = datetime.datetime(
        today.year, today.month, today.day, 9, 0, tzinfo=datetime.timezone.utc
    )

    Appointment.objects.create(
        patient=patient,
        provider=staff,
        start_time=start_time,
        duration_minutes=30,
        status=AppointmentProgressStatus.CONFIRMED,
        note_type=note_type,
        telehealth_instructions_sent=False,
    )

    day_start = datetime.datetime(
        today.year, today.month, today.day, 0, 0, tzinfo=datetime.timezone.utc
    )
    day_end = datetime.datetime(
        today.year, today.month, today.day, 23, 59, tzinfo=datetime.timezone.utc
    )

    handler = _make_handler(staff_uuid=str(staff.id))
    handler.request.query_params = {
        "start": day_start.isoformat(),
        "end": day_end.isoformat(),
    }
    result = handler.get_data()

    import json

    body = json.loads(result[0].content)
    card = body["appointments"][0]

    required_keys = {
        "patient_id",
        "patient_name",
        "start_time",
        "note_type",
        "last_visit",
        "conditions",
        "allergies",
        "medications",
        "vitals",
    }
    assert required_keys.issubset(card.keys())


@pytest.mark.django_db
def test_get_data_with_prior_note_shows_last_visit() -> None:
    """When a prior encounter note exists, last_visit must have a date and snippet."""
    staff = StaffFactory.create()
    patient = PatientFactory.create()
    note_type = NoteTypeFactory.create(name="Office Visit")
    encounter_type = NoteTypeFactory.create(
        name="Encounter",
        category=NoteTypeCategories.ENCOUNTER,
    )
    today = datetime.date.today()
    appt_start = datetime.datetime(
        today.year, today.month, today.day, 9, 0, tzinfo=datetime.timezone.utc
    )

    Appointment.objects.create(
        patient=patient,
        provider=staff,
        start_time=appt_start,
        duration_minutes=30,
        status=AppointmentProgressStatus.CONFIRMED,
        note_type=note_type,
        telehealth_instructions_sent=False,
    )

    # Create a prior encounter note with an HPI command
    from canvas_sdk.v1.data.command import Command

    note = NoteFactory.create(
        patient=patient,
        provider=staff,
        note_type_version=encounter_type,
        datetime_of_service=datetime.datetime(
            2026, 4, 1, 9, 0, tzinfo=datetime.timezone.utc
        ),
    )
    Command.objects.create(
        note=note,
        patient=patient,
        schema_key="hpi",
        data={"narrative": "Cough and fever for 3 days."},
        state="committed",
        origination_source="provider",
        anchor_object_type="",
        anchor_object_dbid=0,
    )

    day_start = datetime.datetime(
        today.year, today.month, today.day, 0, 0, tzinfo=datetime.timezone.utc
    )
    day_end = datetime.datetime(
        today.year, today.month, today.day, 23, 59, tzinfo=datetime.timezone.utc
    )

    handler = _make_handler(staff_uuid=str(staff.id))
    handler.request.query_params = {
        "start": day_start.isoformat(),
        "end": day_end.isoformat(),
    }
    result = handler.get_data()

    import json

    body = json.loads(result[0].content)
    last_visit = body["appointments"][0]["last_visit"]
    assert last_visit["date"] is not None
    assert "Cough" in last_visit["snippet"]


# ── Unit tests for helper functions ──────────────────────────────────────


def test_format_conditions_empty_returns_none_on_record() -> None:
    """No conditions must yield ['None on record']."""
    assert _format_conditions([]) == ["None on record"]


def test_format_conditions_with_coding() -> None:
    """Each condition with a coding must render 'display (code)'."""
    cond = MagicMock()
    coding = MagicMock()
    coding.display = "Hypertension"
    coding.code = "I10"
    cond.codings.all.return_value = [coding]

    result = _format_conditions([cond])
    assert result == ["Hypertension (I10)"]


def test_format_conditions_no_coding_returns_unknown() -> None:
    """Conditions with no codings must render 'Unknown condition'."""
    cond = MagicMock()
    cond.codings.all.return_value = []

    result = _format_conditions([cond])
    assert result == ["Unknown condition"]


def test_format_medications_empty_returns_none_on_record() -> None:
    """No medications must yield ['None on record']."""
    assert _format_medications([]) == ["None on record"]


def test_format_medications_with_coding_and_quantity() -> None:
    """Medication display must combine drug name and clinical quantity."""
    med = MagicMock()
    coding = MagicMock()
    coding.display = "Metformin"
    coding.code = "12345"
    med.codings.all.return_value = [coding]
    med.clinical_quantity_description = "500mg"

    result = _format_medications([med])
    assert result == ["Metformin 500mg"]


def test_format_vitals_empty_returns_none_on_record() -> None:
    """No observations must yield ['None on record']."""
    assert _format_vitals([]) == ["None on record"]


def test_format_vitals_renders_name_value_units() -> None:
    """Each observation must render as 'name: value units'."""
    obs = MagicMock()
    obs.name = "Blood Pressure"
    obs.value = "120/80"
    obs.units = "mmHg"

    result = _format_vitals([obs])
    assert result == ["Blood Pressure: 120/80 mmHg"]


def test_format_last_visit_none_note() -> None:
    """When no prior note exists, snippet must be 'No prior visit on record'."""
    result = _format_last_visit(None)
    assert result["date"] is None
    assert result["snippet"] == "No prior visit on record"


def test_format_last_visit_with_hpi() -> None:
    """When an HPI command exists, the snippet must be taken from it."""
    note = MagicMock()
    note.datetime_of_service = datetime.datetime(2026, 4, 1, 9, 0)
    hpi_cmd = MagicMock()
    hpi_cmd.schema_key = "hpi"
    hpi_cmd.data = {"narrative": "Patient presents with headache."}
    note.commands.all.return_value = [hpi_cmd]

    result = _format_last_visit(note)
    assert result["date"] is not None
    snippet = result["snippet"]
    assert isinstance(snippet, str)
    assert "headache" in snippet


def test_format_last_visit_hpi_truncated_at_120() -> None:
    """HPI narrative longer than 120 chars must be truncated with '...'."""
    note = MagicMock()
    note.datetime_of_service = datetime.datetime(2026, 4, 1, 9, 0)
    long_narrative = "A" * 150
    cmd = MagicMock()
    cmd.schema_key = "hpi"
    cmd.data = {"narrative": long_narrative}
    note.commands.all.return_value = [cmd]

    result = _format_last_visit(note)
    snippet = result["snippet"]
    assert isinstance(snippet, str)
    assert snippet.endswith("...")
    assert len(snippet) == 123  # 120 chars + "..."


def test_format_last_visit_falls_back_to_rfv_when_no_hpi() -> None:
    """When no HPI command, the snippet must fall back to reasonForVisit."""
    note = MagicMock()
    note.datetime_of_service = datetime.datetime(2026, 4, 1, 9, 0)
    rfv_cmd = MagicMock()
    rfv_cmd.schema_key = "reasonForVisit"
    rfv_cmd.data = {"comment": "Annual physical"}
    note.commands.all.return_value = [rfv_cmd]

    result = _format_last_visit(note)
    snippet = result["snippet"]
    assert isinstance(snippet, str)
    assert "Annual physical" in snippet


def test_format_last_visit_no_commands_shows_no_summary() -> None:
    """When no HPI or RFV command exists, snippet must be 'No summary available'."""
    note = MagicMock()
    note.datetime_of_service = datetime.datetime(2026, 4, 1, 9, 0)
    note.commands.all.return_value = []

    result = _format_last_visit(note)
    assert result["snippet"] == "No summary available"


def test_build_card_structure() -> None:
    """_build_card must produce a dict with all required keys."""
    patient = MagicMock()
    patient.id = "pat-1"
    patient.first_name = "Bob"
    patient.last_name = "Jones"

    appt = MagicMock(spec=Appointment)
    appt.patient = patient
    appt.patient_id = "pat-1"
    appt.start_time = datetime.datetime(
        2026, 5, 26, 10, 0, tzinfo=datetime.timezone.utc
    )
    appt.note_type = MagicMock(name="Office Visit")
    appt.note_type.name = "Office Visit"

    card = _build_card(appt, {}, {}, {}, {}, {})

    required_keys = {
        "patient_id",
        "patient_name",
        "start_time",
        "note_type",
        "last_visit",
        "conditions",
        "allergies",
        "medications",
        "vitals",
    }
    assert required_keys.issubset(card.keys())
    assert card["patient_name"] == "Bob Jones"
    assert card["patient_id"] == "pat-1"


def test_build_card_no_data_shows_none_on_record() -> None:
    """_build_card with no clinical data must render 'None on record' for each section."""
    patient = MagicMock()
    patient.id = "pat-empty"
    patient.first_name = "Empty"
    patient.last_name = "Patient"

    appt = MagicMock(spec=Appointment)
    appt.patient = patient
    appt.patient_id = "pat-empty"
    appt.start_time = datetime.datetime(
        2026, 5, 26, 14, 0, tzinfo=datetime.timezone.utc
    )
    appt.note_type = None

    card = _build_card(appt, {}, {}, {}, {}, {})

    assert card["conditions"] == ["None on record"]
    assert card["allergies"] == ["None on record"]
    assert card["medications"] == ["None on record"]
    assert card["vitals"] == ["None on record"]
    assert card["last_visit"]["snippet"] == "No prior visit on record"


# ── Fallback / edge-case helpers ──────────────────────────────────────────


def test_format_medications_no_coding_uses_quantity_only() -> None:
    """A medication with no codings falls back to the clinical quantity description."""
    med = MagicMock()
    med.codings.all.return_value = []
    med.clinical_quantity_description = "500 mg twice daily"

    result = _format_medications([med])
    assert result == ["500 mg twice daily"]


def test_format_medications_no_coding_no_quantity_falls_back_to_unknown() -> None:
    """A medication with no codings and no quantity renders 'Unknown medication'."""
    med = MagicMock()
    med.codings.all.return_value = []
    med.clinical_quantity_description = ""

    result = _format_medications([med])
    assert result == ["Unknown medication"]


def test_format_vitals_skips_skip_list_entries() -> None:
    """Observations whose name is in _SKIP_VITAL_NAMES must not appear in output."""
    panel = MagicMock(name="Vital Signs Panel")
    panel.name = "Vital Signs Panel"
    panel.value = "anything"
    panel.units = ""
    note = MagicMock()
    note.name = "note"
    note.value = "some free text"
    note.units = ""
    pulse = MagicMock()
    pulse.name = "pulse"
    pulse.value = "72"
    pulse.units = "bpm"

    result = _format_vitals([panel, note, pulse])
    assert result == ["Pulse: 72 bpm"]


def test_format_vitals_keeps_only_first_occurrence_per_name() -> None:
    """When the same vital name appears twice, the first (most recent) wins."""
    newer = MagicMock()
    newer.name = "pulse"
    newer.value = "72"
    newer.units = "bpm"
    older = MagicMock()
    older.name = "pulse"
    older.value = "80"
    older.units = "bpm"

    result = _format_vitals([newer, older])
    assert result == ["Pulse: 72 bpm"]


def test_format_vitals_skips_empty_value() -> None:
    """Observations with an empty value string must be filtered out."""
    obs = MagicMock()
    obs.name = "pulse"
    obs.value = ""
    obs.units = "bpm"

    assert _format_vitals([obs]) == ["None on record"]


def test_format_vitals_skips_zero_value() -> None:
    """Observations with value '0' (typical for unrecorded percentiles) are filtered."""
    obs = MagicMock()
    obs.name = "bmi_percentile"
    obs.value = "0"
    obs.units = "%"

    assert _format_vitals([obs]) == ["None on record"]


def test_format_vitals_converts_weight_oz_to_lbs() -> None:
    """Weight stored in ounces must be converted to pounds in the display."""
    weight = MagicMock()
    weight.name = "weight"
    weight.value = "800"
    weight.units = "oz"

    result = _format_vitals([weight])
    assert result == ["Weight: 50 lbs"]


def test_format_vitals_weight_non_numeric_falls_back_to_oz() -> None:
    """A non-numeric weight value falls back to the original oz value, not an error."""
    weight = MagicMock()
    weight.name = "weight"
    weight.value = "not-a-number"
    weight.units = "oz"

    result = _format_vitals([weight])
    assert result == ["Weight: not-a-number oz"]


def test_format_vitals_unknown_name_is_humanized() -> None:
    """A vital name not in _VITAL_LABELS must be Title-Cased from snake_case."""
    obs = MagicMock()
    obs.name = "some_new_vital"
    obs.value = "42"
    obs.units = "u"

    result = _format_vitals([obs])
    assert result == ["Some New Vital: 42 u"]


def test_format_last_visit_hpi_empty_narrative_falls_back_to_rfv() -> None:
    """If the HPI command has an empty narrative, fall through to RFV."""
    note = MagicMock()
    note.datetime_of_service = datetime.datetime(2026, 4, 1, 9, 0)
    hpi_cmd = MagicMock()
    hpi_cmd.schema_key = "hpi"
    hpi_cmd.data = {"narrative": ""}
    rfv_cmd = MagicMock()
    rfv_cmd.schema_key = "reasonForVisit"
    rfv_cmd.data = {"comment": "Follow-up"}
    note.commands.all.return_value = [hpi_cmd, rfv_cmd]

    result = _format_last_visit(note)
    snippet = result["snippet"]
    assert isinstance(snippet, str)
    assert "Follow-up" in snippet


def test_format_last_visit_rfv_empty_comment_shows_no_summary() -> None:
    """If the only RFV command has an empty comment, snippet is 'No summary available'."""
    note = MagicMock()
    note.datetime_of_service = datetime.datetime(2026, 4, 1, 9, 0)
    rfv_cmd = MagicMock()
    rfv_cmd.schema_key = "reasonForVisit"
    rfv_cmd.data = {"comment": ""}
    note.commands.all.return_value = [rfv_cmd]

    result = _format_last_visit(note)
    assert result["snippet"] == "No summary available"
