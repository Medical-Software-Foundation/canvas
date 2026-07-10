"""Tests for the readiness board builder.

Pure helpers are tested directly; board assembly + filtering is tested against
real appointment records created in the test DB.
"""

import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from canvas_sdk.effects import EffectType
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.message import Message
from canvas_sdk.v1.data.patient import PatientMetadata
from canvas_sdk.v1.data.task import TaskStatus
from canvas_sdk.v1.data.user import CanvasUser
from canvas_sdk.test_utils.factories import (
    ImagingOrderFactory,
    ImagingReportFactory,
    LabOrderFactory,
    LabReportFactory,
    PatientFactory,
    PracticeLocationFactory,
    PrescriptionFactory,
    StaffFactory,
    TaskFactory,
)

from daily_dashboard.services import readiness


# ── pure helpers ─────────────────────────────────────────────────────────

def test_resolve_tz_defaults_to_utc() -> None:
    assert readiness.resolve_tz(None) is dt_timezone.utc
    assert readiness.resolve_tz("") is dt_timezone.utc
    assert readiness.resolve_tz("  utc ") is dt_timezone.utc


def test_resolve_tz_named_zone() -> None:
    assert readiness.resolve_tz("America/New_York") == ZoneInfo("America/New_York")


def test_resolve_tz_invalid_falls_back_to_utc() -> None:
    assert readiness.resolve_tz("Not/AZone") is dt_timezone.utc


def test_patient_name_last_first() -> None:
    p = SimpleNamespace(first_name="Jane", last_name="Smith")
    assert readiness._patient_name(p) == "Smith, Jane"


def test_patient_name_fallbacks() -> None:
    assert readiness._patient_name(None) == "Unknown patient"
    assert readiness._patient_name(SimpleNamespace(first_name="", last_name="Doe")) == "Doe"


def test_format_time_boundaries() -> None:
    def at(hour: int, minute: int) -> str:
        return readiness._format_time(datetime(2026, 6, 25, hour, minute, tzinfo=dt_timezone.utc))

    assert at(9, 0) == "9:00 AM"
    assert at(0, 5) == "12:05 AM"
    assert at(12, 0) == "12:00 PM"
    assert at(13, 30) == "1:30 PM"
    assert at(23, 45) == "11:45 PM"


def test_date_label_format() -> None:
    from datetime import date

    assert readiness._date_label(date(2026, 6, 25)) == "Thursday, June 25"


# ── board assembly ───────────────────────────────────────────────────────

def _make_appt(
    patient: Any,
    provider: Any,
    location: Any,
    start_time: Any,
    status: Any = AppointmentProgressStatus.CONFIRMED,
) -> Appointment:
    return Appointment.objects.create(
        patient=patient,
        provider=provider,
        location=location,
        start_time=start_time,
        duration_minutes=30,
        status=status,
        telehealth_instructions_sent=False,
    )


@pytest.mark.django_db
def test_board_empty_when_no_appointments() -> None:
    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )
    assert board["rows"] == []
    assert board["providers"] == []
    assert board["locations"] == []
    assert board["scope"] == "all"
    assert board["date_iso"]
    # Panels present and empty.
    for key in ("tasks", "refills", "messages"):
        assert board["panels"][key] == {"count": 0, "items": []}


@pytest.mark.django_db
def test_board_includes_only_todays_live_appointments() -> None:
    patient = PatientFactory(first_name="Jane", last_name="Smith")
    provider = StaffFactory(first_name="Amanda", last_name="Miller")
    location = PracticeLocationFactory()
    now = datetime.now(dt_timezone.utc)

    today = _make_appt(patient, provider, location, now)
    _make_appt(patient, provider, location, now, status=AppointmentProgressStatus.CANCELLED)
    _make_appt(patient, provider, location, now - timedelta(days=1))

    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )

    assert len(board["rows"]) == 1
    row = board["rows"][0]
    assert row["appointment_id"] == str(today.id)
    assert row["patient_name"] == "Smith, Jane"
    assert "Amanda" in row["provider"]

    # The scheduled provider and location are offered as filter options.
    assert str(provider.id) in [p["id"] for p in board["providers"]]
    assert str(location.id) in [loc["id"] for loc in board["locations"]]


@pytest.mark.django_db
def test_my_day_scopes_to_logged_in_provider() -> None:
    patient = PatientFactory()
    mine = StaffFactory()
    other = StaffFactory()
    location = PracticeLocationFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, mine, location, now)
    _make_appt(patient, other, location, now)

    mine_board = readiness.build_board(
        tz_name="UTC", staff_id=str(mine.id), scope="mine", provider_id=None, location_id=None
    )
    assert len(mine_board["rows"]) == 1

    # "All" ignores the logged-in provider.
    all_board = readiness.build_board(
        tz_name="UTC", staff_id=str(mine.id), scope="all", provider_id=None, location_id=None
    )
    assert len(all_board["rows"]) == 2


@pytest.mark.django_db
def test_provider_filter_narrows_rows() -> None:
    patient = PatientFactory()
    a = StaffFactory()
    b = StaffFactory()
    location = PracticeLocationFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, a, location, now)
    _make_appt(patient, b, location, now)

    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=str(a.id), location_id=None
    )
    assert len(board["rows"]) == 1
    # Both providers still offered as options regardless of the active filter.
    provider_ids = {p["id"] for p in board["providers"]}
    assert {str(a.id), str(b.id)} <= provider_ids


# ── readiness cells ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_readiness_three_states_render_on_row() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    LabOrderFactory(patient=patient)  # labs: order, no report -> incomplete
    imaging_order = ImagingOrderFactory(patient=patient)
    ImagingReportFactory(patient=patient, order=imaging_order)  # imaging: complete
    # referral: nothing on file -> not-needed

    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )
    cells = board["rows"][0]["readiness"]
    assert cells["labs"] == readiness.INCOMPLETE
    assert cells["imaging"] == readiness.COMPLETE
    assert cells["referral"] == readiness.NOT_NEEDED
    assert cells["auth"] == readiness.NOT_NEEDED  # auth is a manual flag, unset here


@pytest.mark.django_db
def test_report_present_is_complete_and_junked_reports_ignored() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    LabReportFactory(patient=patient)  # report present, no order -> complete
    imaging_order = ImagingOrderFactory(patient=patient)
    ImagingReportFactory(patient=patient, order=imaging_order, junked=True)  # ignored

    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )
    cells = board["rows"][0]["readiness"]
    assert cells["labs"] == readiness.COMPLETE
    assert cells["imaging"] == readiness.INCOMPLETE  # only a junked report exists


@pytest.mark.django_db
def test_pending_order_stays_amber_despite_old_result() -> None:
    """Per-order: a fresh pending order keeps the cell amber even when an older
    order on the same patient already resulted (patient-level would say green)."""
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    resulted_order = ImagingOrderFactory(patient=patient)
    ImagingReportFactory(patient=patient, order=resulted_order)  # old order, resulted
    ImagingOrderFactory(patient=patient)  # new order, still pending

    cells = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]["readiness"]
    assert cells["imaging"] == readiness.INCOMPLETE


@pytest.mark.django_db
def test_every_order_resulted_is_complete() -> None:
    """Per-order: a cell is green only when all of its orders have resulted."""
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    for _ in range(2):
        order = ImagingOrderFactory(patient=patient)
        ImagingReportFactory(patient=patient, order=order)

    cells = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]["readiness"]
    assert cells["imaging"] == readiness.COMPLETE


# ── action panels ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_board_echoes_signed_in_staff_id() -> None:
    """The board returns the signed-in staff id so the UI can default the
    provider filter to them."""
    board = readiness.build_board(
        tz_name="UTC", staff_id="staff-123", scope="mine",
        provider_id=None, location_id=None,
    )
    assert board["current_staff_id"] == "staff-123"
    # Missing staff id degrades to an empty string, not None.
    anon = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )
    assert anon["current_staff_id"] == ""


@pytest.mark.django_db
def test_tasks_panel_lists_all_open_tasks_not_scoped_to_board_patients() -> None:
    """Unfiltered, the tasks panel shows every open task — including tasks for
    patients who are not on today's board."""
    on_board = PatientFactory()
    off_board = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(on_board, StaffFactory(), PracticeLocationFactory(), now)

    TaskFactory(patient=on_board, status=TaskStatus.OPEN, title="On-board task", due=now)
    TaskFactory(patient=off_board, status=TaskStatus.OPEN, title="Off-board task", due=now)
    TaskFactory(patient=on_board, status=TaskStatus.COMPLETED, due=now)  # not open -> excluded

    panels = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["panels"]
    # Both open tasks show even though only one patient is scheduled today.
    assert panels["tasks"]["count"] == 2


@pytest.mark.django_db
def test_tasks_panel_scoped_to_provider_when_filtered() -> None:
    """Filtering the board to a provider scopes the tasks panel to that
    provider's assigned tasks."""
    provider = StaffFactory()
    other = StaffFactory()
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, provider, PracticeLocationFactory(), now)

    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Mine", assignee=provider, due=now)
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Theirs", assignee=other, due=now)
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Unassigned", due=now)

    # Dropdown provider filter.
    by_dropdown = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all",
        provider_id=str(provider.id), location_id=None,
    )["panels"]["tasks"]
    assert by_dropdown["count"] == 1
    assert by_dropdown["items"][0]["title"] == "Mine"
    # Prefill ids are the Staff UUID (matching the picker), not the integer dbid.
    assert by_dropdown["items"][0]["assignee_id"] == str(provider.id)

    # "My day" scope uses the logged-in staff id as the assignee.
    by_mine = readiness.build_board(
        tz_name="UTC", staff_id=str(provider.id), scope="mine",
        provider_id=None, location_id=None,
    )["panels"]["tasks"]
    assert by_mine["count"] == 1
    assert by_mine["items"][0]["title"] == "Mine"


@pytest.mark.django_db
def test_chosen_provider_wins_over_mine_scope() -> None:
    """Picking a provider while on 'My day' shows that provider — not an empty
    set from double-filtering (staff_id AND provider_id)."""
    me = StaffFactory()
    other = StaffFactory()
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, other, PracticeLocationFactory(), now)  # other's appointment

    board = readiness.build_board(
        tz_name="UTC", staff_id=str(me.id), scope="mine",
        provider_id=str(other.id), location_id=None,
    )
    # The explicit provider wins: other's appointment shows, not an empty board.
    assert len(board["rows"]) == 1
    assert board["rows"][0]["patient_name"] == readiness._patient_name(patient)


@pytest.mark.django_db
def test_tomorrow_mine_scopes_to_signed_in_provider() -> None:
    """Tomorrow + mine scope shows the signed-in provider's tomorrow only."""
    me = StaffFactory()
    other = StaffFactory()
    loc = PracticeLocationFactory()
    mine_patient = PatientFactory()
    other_patient = PatientFactory()
    tomorrow = datetime.now(dt_timezone.utc) + timedelta(days=1)
    _make_appt(mine_patient, me, loc, tomorrow)
    _make_appt(other_patient, other, loc, tomorrow)

    board = readiness.build_board(
        tz_name="UTC", staff_id=str(me.id), scope="mine",
        provider_id=None, location_id=None, day="tomorrow",
    )
    assert board["day"] == "tomorrow"
    assert len(board["rows"]) == 1
    assert board["rows"][0]["patient_name"] == readiness._patient_name(mine_patient)


@pytest.mark.django_db
def test_tomorrow_view_tasks_filtered_to_due_tomorrow() -> None:
    """Tomorrow view: tasks panel shows only tasks due tomorrow; refills and
    messages (no due date) are not date-filtered and still appear."""
    patient = PatientFactory(first_name="Jane", last_name="Smith")
    now = datetime.now(dt_timezone.utc)
    tomorrow = now + timedelta(days=1)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), tomorrow)  # scheduled tomorrow

    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Due tomorrow", due=tomorrow)
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Due today", due=now)
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="No due date", due=None)

    # A refill and an unread message — neither has a due date.
    PrescriptionFactory(patient=patient, is_refill=True)
    user = CanvasUser.objects.create(email="jane@example.com", phone_number="", is_staff=False)
    patient.user = user
    patient.save()
    Message.objects.create(content="Question about meds", sender=user, read=None)

    panels = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None,
        location_id=None, day="tomorrow",
    )["panels"]

    # Only the due-tomorrow task survives the filter.
    assert panels["tasks"]["count"] == 1
    assert panels["tasks"]["items"][0]["title"] == "Due tomorrow"
    # Refills and messages are unaffected by the due-date filter.
    assert panels["refills"]["count"] == 1
    assert panels["messages"]["count"] == 1


@pytest.mark.django_db
def test_today_view_tasks_due_today_or_earlier() -> None:
    """Today view scopes tasks to those due by end of today: overdue and
    due-today tasks appear; future and no-due-date tasks are excluded."""
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Overdue",
                due=now - timedelta(days=3))
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Due today", due=now)
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Due next week",
                due=now + timedelta(days=7))
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="No due date", due=None)

    tasks = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["panels"]["tasks"]
    # Overdue + due-today survive; future and no-due-date are filtered out.
    assert tasks["count"] == 2
    titles = {item["title"] for item in tasks["items"]}
    assert titles == {"Overdue", "Due today"}


@pytest.mark.django_db
def test_refills_panel_lists_only_refill_prescriptions() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    PrescriptionFactory(patient=patient, is_refill=True)
    PrescriptionFactory(patient=patient, is_refill=False)  # not a refill -> excluded

    refills = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["panels"]["refills"]
    assert refills["count"] == 1
    assert refills["items"][0]["patient_name"] == readiness._patient_name(patient)


@pytest.mark.django_db
def test_refills_panel_excludes_entered_in_error_prescriptions() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    retractor = CanvasUser.objects.create(
        email="retractor@example.com", phone_number="", is_staff=True
    )
    PrescriptionFactory(patient=patient, is_refill=True)  # active refill -> included
    PrescriptionFactory(
        patient=patient, is_refill=True, entered_in_error=retractor
    )  # retracted -> excluded

    refills = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["panels"]["refills"]
    assert refills["count"] == 1


@pytest.mark.django_db
def test_messages_panel_counts_unread_from_board_patients() -> None:
    patient = PatientFactory(first_name="Jane", last_name="Smith")
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    user = CanvasUser.objects.create(email="jane@example.com", phone_number="", is_staff=False)
    patient.user = user
    patient.save()

    Message.objects.create(content="Can I move my appointment?", sender=user, read=None)
    Message.objects.create(content="already read", sender=user, read=now)  # read -> excluded

    messages = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["panels"]["messages"]
    assert messages["count"] == 1
    assert messages["items"][0]["patient_name"] == "Smith, Jane"
    assert "move my appointment" in messages["items"][0]["snippet"]


# ── outreach + manual overrides ──────────────────────────────────────────

@pytest.mark.django_db
def test_manual_override_marks_cells_complete() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    # No orders/reports at all -> labs/imaging/referral would be not-needed,
    # auth always starts not-needed. Overrides force complete.
    PatientMetadata.objects.create(patient=patient, key="dd.override.auth", value="true")
    PatientMetadata.objects.create(patient=patient, key="dd.override.labs", value="true")

    cells = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]
    assert cells["readiness"]["auth"] == readiness.COMPLETE
    assert cells["readiness"]["labs"] == readiness.COMPLETE
    assert cells["readiness"]["imaging"] == readiness.NOT_NEEDED
    assert set(cells["overrides"]) == {"auth", "labs"}


@pytest.mark.django_db
def test_override_value_false_is_ignored() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)
    PatientMetadata.objects.create(patient=patient, key="dd.override.auth", value="false")

    cells = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]
    assert cells["readiness"]["auth"] == readiness.NOT_NEEDED
    assert cells["overrides"] == []


@pytest.mark.django_db
def test_outreach_log_surfaces_latest_and_count() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    log = [
        {"date": "2026-06-24T18:00:00+00:00", "channel": "Call", "recipient_type": "Patient",
         "recipient": "", "outcome": "No answer", "note": "", "user": "Maria Torres"},
        {"date": "2026-06-26T17:30:00+00:00", "channel": "Fax", "recipient_type": "PCP",
         "recipient": "Dr. Smith", "outcome": "Sent", "note": "Sent lab order", "user": "Maria Torres"},
    ]
    PatientMetadata.objects.create(patient=patient, key="dd.outreach.log", value=json.dumps(log))

    row = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]
    # Latest attempt summarised (PCP / Fax), and the count reflects the whole log.
    assert "PCP" in row["outreach"]
    assert "Fax" in row["outreach"]
    assert row["outreach_count"] == 2

    # Full detail is available for the cell popover, newest first, with the note.
    detail = row["outreach_detail"]
    assert len(detail) == 2
    assert detail[0]["channel"] == "Fax"
    assert detail[0]["note"] == "Sent lab order"
    assert detail[0]["recipient"] == "Dr. Smith"
    assert detail[1]["channel"] == "Call"  # older attempt second


@pytest.mark.django_db
def test_record_outreach_returns_patient_metadata_upsert() -> None:
    patient = PatientFactory()
    effect = readiness.record_outreach(
        str(patient.id),
        channel="Fax",
        recipient_type="PCP",
        recipient="Dr. Smith",
        outcome="Sent",
        note="Awaiting result",
        user="Maria Torres",
    )
    assert EffectType.Name(effect.type) == "UPSERT_PATIENT_METADATA"
    payload = json.loads(effect.payload)["data"]
    assert payload["key"] == readiness.OUTREACH_KEY
    logged = json.loads(payload["value"])
    assert logged[-1]["channel"] == "Fax"
    assert logged[-1]["user"] == "Maria Torres"


@pytest.mark.django_db
def test_set_override_returns_expected_upsert() -> None:
    patient = PatientFactory()
    effect = readiness.set_override(str(patient.id), "auth", True)
    payload = json.loads(effect.payload)["data"]
    assert payload["key"] == "dd.override.auth"
    assert payload["value"] == "true"


@pytest.mark.django_db
def test_cell_detail_lists_reports_and_orders() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)

    LabOrderFactory(patient=patient)  # one open lab order
    imaging_order = ImagingOrderFactory(patient=patient)
    ImagingReportFactory(patient=patient, order=imaging_order)  # imaging report received

    row = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]

    # Labs: an order item, no report.
    lab_items = row["details"]["labs"]
    assert any(i["kind"] == "order" for i in lab_items)
    assert all(i["kind"] != "report" for i in lab_items)

    # Imaging: a received report item present.
    assert any(i["kind"] == "report" for i in row["details"]["imaging"])
    # Auth carries no SDK detail.
    assert row["details"]["auth"] == []


@pytest.mark.django_db
def test_cell_detail_caps_at_three_most_recent() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)
    for _ in range(6):
        LabOrderFactory(patient=patient)

    row = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["rows"][0]
    assert len(row["details"]["labs"]) == 3
    # State still reflects that orders exist (derived from the full set).
    assert row["readiness"]["labs"] == readiness.INCOMPLETE


# ── deep-links + create task ─────────────────────────────────────────────

@pytest.mark.django_db
def test_chart_base_from_customer_identifier() -> None:
    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None,
        location_id=None, customer_identifier="acme-clinic",
    )
    assert board["chart_base"] == "https://acme-clinic.canvasmedical.com"


@pytest.mark.django_db
def test_chart_base_empty_when_unconfigured() -> None:
    # Without CUSTOMER_IDENTIFIER there is no instance to link to, so chart_base
    # is empty and the UI hides the chart actions.
    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )
    assert board["chart_base"] == ""


@pytest.mark.django_db
def test_panel_items_carry_patient_id_for_deeplinks() -> None:
    patient = PatientFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), now)
    TaskFactory(patient=patient, status=TaskStatus.OPEN, title="Follow up", due=now)

    item = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )["panels"]["tasks"]["items"][0]
    assert item["patient_id"] == str(patient.id)


@pytest.mark.django_db
def test_create_task_returns_add_task_effect() -> None:
    patient = PatientFactory()
    effect = readiness.create_task(str(patient.id), "Chase referral for J. Doe")
    assert "TASK" in EffectType.Name(effect.type)
    data = json.loads(effect.payload)["data"]
    assert data["title"] == "Chase referral for J. Doe"
    assert "daily-dashboard" in data["labels"]
    assert data["patient"]["id"] == str(patient.id)


# ── in-dashboard task edit ───────────────────────────────────────────────

def test_update_task_only_sends_set_fields() -> None:
    eff = readiness.update_task("task-1", status="COMPLETED", assignee_id="staff-9")
    assert EffectType.Name(eff.type) == "UPDATE_TASK"
    data = json.loads(eff.payload)["data"]
    assert data["status"] == "COMPLETED"
    assert data["assignee"] == {"id": "staff-9"}
    # Untouched fields are not sent (so they aren't nulled out).
    assert "title" not in data
    assert "team" not in data
    assert "due" not in data


def test_update_task_maps_priority_and_due() -> None:
    from datetime import datetime as _dt

    eff = readiness.update_task("task-1", priority="urgent", due=_dt(2026, 7, 1))
    data = json.loads(eff.payload)["data"]
    assert data["priority"] == "urgent"
    assert data["due"].startswith("2026-07-01")


def test_comment_task_returns_create_task_comment() -> None:
    eff = readiness.comment_task("task-1", "Called patient, no answer")
    assert EffectType.Name(eff.type) == "CREATE_TASK_COMMENT"
    assert "Called patient, no answer" in eff.payload


# ── tomorrow view ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tomorrow_view_loads_next_day_appointments() -> None:
    patient = PatientFactory()
    provider = StaffFactory()
    location = PracticeLocationFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, provider, location, now)                      # today
    _make_appt(patient, provider, location, now + timedelta(days=1))  # tomorrow

    today_board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None, location_id=None
    )
    assert len(today_board["rows"]) == 1
    assert today_board["day"] == "today"

    tomorrow_board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None,
        location_id=None, day="tomorrow"
    )
    assert len(tomorrow_board["rows"]) == 1
    assert tomorrow_board["day"] == "tomorrow"
    # The two windows surface different appointments.
    assert today_board["rows"][0]["appointment_id"] != tomorrow_board["rows"][0]["appointment_id"]
    assert today_board["date_iso"] != tomorrow_board["date_iso"]


# ── service edge cases (coverage) ─────────────────────────────────────────

def test_med_name_variants() -> None:
    assert readiness._med_name(None) == "Medication"
    # First coding with a display wins.
    coded = SimpleNamespace(
        codings=SimpleNamespace(all=lambda: [
            SimpleNamespace(display=""),
            SimpleNamespace(display="Lisinopril 10mg"),
        ]),
        national_drug_code="x",
    )
    assert readiness._med_name(coded) == "Lisinopril 10mg"
    # No display anywhere -> NDC fallback.
    ndc_only = SimpleNamespace(
        codings=SimpleNamespace(all=lambda: [SimpleNamespace(display=None)]),
        national_drug_code="00071-0155",
    )
    assert readiness._med_name(ndc_only) == "00071-0155"


def test_outreach_summary_handles_bad_date() -> None:
    # No attempt -> empty.
    assert readiness._outreach_summary(None, dt_timezone.utc) == ""
    # Unparseable date -> label without the date suffix.
    summary = readiness._outreach_summary(
        {"recipient_type": "PCP", "channel": "Fax", "date": "not-a-date"}, dt_timezone.utc
    )
    assert summary == "PCP Fax"


def test_fmt_dateish_and_sortkey() -> None:
    from datetime import date

    assert readiness._fmt_dateish(None, dt_timezone.utc) == ""
    # Plain date.
    assert readiness._fmt_dateish(date(2026, 6, 26), dt_timezone.utc) == "Jun 26"
    # Datetime path.
    dt = datetime(2026, 6, 26, 9, 0, tzinfo=dt_timezone.utc)
    assert readiness._fmt_dateish(dt, dt_timezone.utc) == "Jun 26"

    # _sortkey: None sorts oldest, datetime and date both produce finite keys.
    assert readiness._sortkey(None) == float("-inf")
    assert readiness._sortkey(dt) == dt.timestamp()
    assert readiness._sortkey(date(2026, 6, 26)) > 0


@pytest.mark.django_db
def test_record_outreach_recovers_from_corrupt_log() -> None:
    patient = PatientFactory()
    # Existing value is not valid JSON -> treated as an empty log, not an error.
    PatientMetadata.objects.create(
        patient=patient, key=readiness.OUTREACH_KEY, value="{not json"
    )
    effect = readiness.record_outreach(
        str(patient.id), channel="Call", recipient_type="Patient",
        recipient="", outcome="Reached", note="", user="Nurse",
    )
    assert EffectType.Name(effect.type) == "UPSERT_PATIENT_METADATA"


@pytest.mark.django_db
def test_metadata_by_patient_recovers_from_corrupt_log() -> None:
    patient = PatientFactory()
    PatientMetadata.objects.create(
        patient=patient, key=readiness.OUTREACH_KEY, value="{not json"
    )
    meta = readiness._metadata_by_patient({patient.pk})
    assert meta[patient.pk]["outreach"] is None
    assert meta[patient.pk]["outreach_count"] == 0


@pytest.mark.django_db
def test_stage_prep_prompt_emits_upsert() -> None:
    patient = PatientFactory()
    effect = readiness.stage_prep_prompt(str(patient.id), "Prep this visit")
    assert EffectType.Name(effect.type) == "UPSERT_PATIENT_METADATA"


def test_create_task_with_all_fields() -> None:
    priority = next(iter(readiness._TASK_PRIORITY))
    effect = readiness.create_task(
        "patient-1", "Chase auth", None,
        assignee_id="staff-9", team_id="team-3", priority=priority,
    )
    assert "TASK" in EffectType.Name(effect.type)


def test_update_task_with_all_fields() -> None:
    effect = readiness.update_task(
        "task-1", assignee_id="staff-9", team_id="team-3", title="Renamed",
        due=datetime(2026, 6, 30, tzinfo=dt_timezone.utc),
    )
    assert EffectType.Name(effect.type) == "UPDATE_TASK"


@pytest.mark.django_db
def test_board_filters_by_location() -> None:
    patient = PatientFactory()
    provider = StaffFactory()
    loc_a = PracticeLocationFactory()
    loc_b = PracticeLocationFactory()
    now = datetime.now(dt_timezone.utc)
    _make_appt(patient, provider, loc_a, now)
    _make_appt(patient, provider, loc_b, now)

    board = readiness.build_board(
        tz_name="UTC", staff_id=None, scope="all", provider_id=None,
        location_id=str(loc_a.id),
    )
    assert len(board["rows"]) == 1
    assert board["rows"][0]["location"] == (loc_a.full_name or "—")
