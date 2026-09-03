"""Tests for chart_closure_queue.handlers.closure_api."""

from __future__ import annotations

import datetime
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.test_utils.factories import (
    NoteFactory,
    NoteTypeFactory,
    PatientFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

from chart_closure_queue.handlers.closure_api import (
    ClosureAPI,
    _aging_level,
    _build_row,
    _parse_threshold,
)

MODULE = "chart_closure_queue.handlers.closure_api"

UTC = datetime.timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_handler(
    staff_uuid: str = "staff-uuid-001",
    end: str | None = "2026-06-18T23:59:59+00:00",
    secrets: dict[str, str] | None = None,
) -> ClosureAPI:
    """Build a ClosureAPI handler with fully mocked request internals."""
    handler = ClosureAPI(MagicMock())

    handler.request = MagicMock()
    handler.request.headers = (
        {"canvas-logged-in-user-id": staff_uuid} if staff_uuid else {}
    )
    handler.request.query_params = {"end": end} if end is not None else {}
    handler.secrets = secrets or {}
    return handler


def _end_of_today_utc() -> datetime.datetime:
    """End-of-today as a UTC-aware datetime (matches what the browser sends)."""
    today = datetime.date.today()
    return datetime.datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=UTC)


def _dos_days_ago(days: int) -> datetime.datetime:
    """A date of service ``days`` calendar days before today, at 09:00 UTC."""
    day = datetime.date.today() - datetime.timedelta(days=days)
    return datetime.datetime(day.year, day.month, day.day, 9, 0, tzinfo=UTC)


def _make_note_with_state(
    staff: Any,
    state: str,
    dos: datetime.datetime,
    *,
    patient: Any = None,
    note_type: Any = None,
    title: str = "",
) -> Any:
    """Create a Note and an attached CurrentNoteStateEvent in the test DB."""
    kwargs: dict[str, Any] = {
        "provider": staff,
        "datetime_of_service": dos,
        "title": title,
    }
    if patient is not None:
        kwargs["patient"] = patient
    if note_type is not None:
        kwargs["note_type_version"] = note_type
    note = NoteFactory.create(**kwargs)
    CurrentNoteStateEvent.objects.create(note=note, state=state)
    return note


def _call_data(
    staff_uuid: str, secrets: dict[str, str] | None = None
) -> dict[str, Any]:
    """Invoke GET /data for the given provider and return the parsed JSON body."""
    handler = _make_handler(
        staff_uuid=staff_uuid,
        end=_end_of_today_utc().isoformat(),
        secrets=secrets,
    )
    result = handler.get_data()
    assert len(result) == 1
    body: dict[str, Any] = json.loads(result[0].content)
    return body


# ── Static asset routes ───────────────────────────────────────────────────


def test_get_index_returns_html() -> None:
    """GET / must return 200 with HTML content."""
    handler = _make_handler()
    with patch(f"{MODULE}.render_to_string", return_value="<html>Queue</html>"):
        result = handler.get_index()

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    body = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
    assert "Queue" in body


def test_get_index_passes_cache_bust_context() -> None:
    """GET / must pass a digit cache_bust into the template context."""
    handler = _make_handler()
    captured: dict[str, Any] = {}

    def capture_render(
        template: str, context: dict | None = None, **kwargs: Any
    ) -> str:
        captured.update(context or {})
        return "<html></html>"

    with patch(f"{MODULE}.render_to_string", side_effect=capture_render):
        handler.get_index()

    assert captured.get("cache_bust", "").isdigit()


def test_get_js_returns_javascript() -> None:
    """GET /main.js must return 200 with a javascript content type."""
    handler = _make_handler()
    with patch(f"{MODULE}.render_to_string", return_value="console.log('ok');"):
        result = handler.get_js()

    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers.get("Content-Type") == "application/javascript"


def test_get_css_returns_css() -> None:
    """GET /styles.css must return 200 with a css content type."""
    handler = _make_handler()
    with patch(f"{MODULE}.render_to_string", return_value="body{}"):
        result = handler.get_css()

    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers.get("Content-Type") == "text/css"


# ── /data – auth and param validation (fail closed) ──────────────────────


def test_get_data_missing_staff_uuid_returns_400() -> None:
    """Without the staff header the endpoint must fail closed with 400 and no data."""
    handler = _make_handler(staff_uuid="")
    result = handler.get_data()

    resp = result[0]
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(resp.content)
    assert "error" in body
    assert "notes" not in body


def test_get_data_missing_end_returns_400() -> None:
    """Without the ?end param the endpoint must return 400."""
    handler = _make_handler(end=None)
    result = handler.get_data()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_data_invalid_end_returns_400() -> None:
    """An unparseable ?end param must return 400, not raise."""
    handler = _make_handler(end="not-a-date")
    result = handler.get_data()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_data_missing_staff_uuid_never_queries() -> None:
    """The fail-closed path must short-circuit before touching the ORM."""
    handler = _make_handler(staff_uuid="")
    with patch(f"{MODULE}._fetch_open_state_events") as mock_fetch:
        handler.get_data()
    mock_fetch.assert_not_called()


# ── /data – empty path (patched ORM) ─────────────────────────────────────


def test_get_data_no_notes_returns_empty_list() -> None:
    """When no notes match, the response must contain an empty notes list."""
    handler = _make_handler()
    with patch(f"{MODULE}._fetch_open_state_events", return_value=[]):
        result = handler.get_data()

    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    body = json.loads(resp.content)
    assert body["notes"] == []
    assert body["truncated"] is False


def test_get_data_not_truncated_under_limit() -> None:
    """A result at/under the cap must report truncated=False."""
    handler = _make_handler()
    one_row = [SimpleNamespace(note=None)]
    with (
        patch(f"{MODULE}._fetch_open_state_events", return_value=one_row),
        patch(f"{MODULE}._build_row", return_value={"note_id": "n1"}),
    ):
        result = handler.get_data()

    body = json.loads(result[0].content)
    assert body["truncated"] is False
    assert len(body["notes"]) == 1


def test_get_data_truncates_to_limit_and_flags_truncation() -> None:
    """More rows than the cap must be trimmed to the cap with truncated=True.

    The fetch helper returns ``_MAX_NOTES + 1`` rows (its overflow sentinel);
    get_data must drop the extra and set the flag.
    """
    handler = _make_handler()
    rows = [SimpleNamespace(note=None) for _ in range(3)]  # _MAX_NOTES (2) + 1
    with (
        patch(f"{MODULE}._MAX_NOTES", 2),
        patch(f"{MODULE}._fetch_open_state_events", return_value=rows),
        patch(f"{MODULE}._build_row", side_effect=lambda *a, **k: {"x": 1}),
    ):
        result = handler.get_data()

    body = json.loads(result[0].content)
    assert body["truncated"] is True
    assert body["limit"] == 2
    assert len(body["notes"]) == 2


# ── /data – real DB factory tests ────────────────────────────────────────


@pytest.mark.django_db
def test_get_data_returns_only_open_state_note() -> None:
    """A single open note for the provider must produce exactly one row."""
    staff = StaffFactory.create()
    patient = PatientFactory.create(first_name="Jane", last_name="Smith")
    note_type = NoteTypeFactory.create(name="Office Visit")
    _make_note_with_state(
        staff, NoteStates.NEW, _dos_days_ago(1), patient=patient, note_type=note_type
    )

    body = _call_data(str(staff.id))

    assert len(body["notes"]) == 1
    row = body["notes"][0]
    assert row["patient_name"] == "Jane Smith"
    assert row["note_title"] == "Office Visit"
    assert row["state"] == NoteStates.NEW.value
    assert row["state_label"] == "New"


@pytest.mark.django_db
def test_get_data_scopes_to_logged_in_provider() -> None:
    """Notes belonging to a different provider must never appear."""
    me = StaffFactory.create()
    other = StaffFactory.create()
    _make_note_with_state(me, NoteStates.NEW, _dos_days_ago(1))
    _make_note_with_state(other, NoteStates.NEW, _dos_days_ago(1))

    body = _call_data(str(me.id))
    assert len(body["notes"]) == 1


@pytest.mark.django_db
def test_get_data_unknown_provider_id_returns_empty() -> None:
    """A staff id that matches no Staff row resolves to no notes (not all notes)."""
    staff = StaffFactory.create()
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(1))

    body = _call_data("00000000-0000-0000-0000-000000000000")
    assert body["notes"] == []
    assert body["truncated"] is False


@pytest.mark.django_db
def test_get_data_excludes_locked_and_signed_states() -> None:
    """Locked / signed / deleted notes are closed and must be excluded."""
    staff = StaffFactory.create()
    for state in (NoteStates.LOCKED, NoteStates.SIGNED, NoteStates.DELETED):
        _make_note_with_state(staff, state, _dos_days_ago(1))

    body = _call_data(str(staff.id))
    assert body["notes"] == []


@pytest.mark.django_db
def test_get_data_includes_every_open_state() -> None:
    """Each of the six open/lockable states must be surfaced."""
    staff = StaffFactory.create()
    open_states = [
        NoteStates.NEW,
        NoteStates.PUSHED,
        NoteStates.CONVERTED,
        NoteStates.UNLOCKED,
        NoteStates.RESTORED,
        NoteStates.UNDELETED,
    ]
    for state in open_states:
        _make_note_with_state(staff, state, _dos_days_ago(1))

    body = _call_data(str(staff.id))
    assert len(body["notes"]) == len(open_states)
    assert {row["state"] for row in body["notes"]} == {s.value for s in open_states}


@pytest.mark.django_db
def test_get_data_excludes_future_dated_notes() -> None:
    """A note with a date of service after today must be excluded."""
    staff = StaffFactory.create()
    _make_note_with_state(
        staff, NoteStates.NEW, _dos_days_ago(-3)
    )  # 3 days in the future

    body = _call_data(str(staff.id))
    assert body["notes"] == []


@pytest.mark.django_db
def test_get_data_sorted_oldest_first() -> None:
    """Rows must be ordered by date of service ascending (most overdue first)."""
    staff = StaffFactory.create()
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(1), title="Newest")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(5), title="Oldest")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(3), title="Middle")

    body = _call_data(str(staff.id))
    titles = [row["note_title"] for row in body["notes"]]
    assert titles == ["Oldest", "Middle", "Newest"]
    days = [row["days_open"] for row in body["notes"]]
    assert days == [5, 3, 1]


@pytest.mark.django_db
def test_get_data_caps_result_at_limit_against_real_db() -> None:
    """The ORM-level slice must cap rows and keep the oldest, end-to-end.

    Patches _MAX_NOTES low so the real query/slice path is exercised without
    creating dozens of notes.
    """
    staff = StaffFactory.create()
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(1), title="Newest")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(5), title="Oldest")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(3), title="Middle")

    with patch(f"{MODULE}._MAX_NOTES", 2):
        body = _call_data(str(staff.id))

    assert body["truncated"] is True
    assert body["limit"] == 2
    # Oldest-first ordering means the two most overdue are kept.
    assert [row["note_title"] for row in body["notes"]] == ["Oldest", "Middle"]


@pytest.mark.django_db
def test_get_data_aging_buckets_with_defaults() -> None:
    """Default thresholds (amber 2, red 4) must bucket rows correctly."""
    staff = StaffFactory.create()
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(1), title="d1")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(2), title="d2")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(4), title="d4")

    body = _call_data(str(staff.id))
    aging_by_title = {row["note_title"]: row["aging"] for row in body["notes"]}
    assert aging_by_title == {"d1": "normal", "d2": "amber", "d4": "red"}


@pytest.mark.django_db
def test_get_data_aging_thresholds_from_secrets() -> None:
    """Secrets must override the default aging thresholds."""
    staff = StaffFactory.create()
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(1), title="d1")
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(3), title="d3")

    body = _call_data(
        str(staff.id), secrets={"AGING_AMBER_DAYS": "1", "AGING_RED_DAYS": "3"}
    )
    aging_by_title = {row["note_title"]: row["aging"] for row in body["notes"]}
    assert aging_by_title == {"d1": "amber", "d3": "red"}


@pytest.mark.django_db
def test_get_data_row_contains_expected_keys() -> None:
    """Each row must carry the full set of display keys."""
    staff = StaffFactory.create()
    _make_note_with_state(staff, NoteStates.NEW, _dos_days_ago(1))

    body = _call_data(str(staff.id))
    row = body["notes"][0]
    expected = {
        "note_id",
        "patient_id",
        "patient_name",
        "note_title",
        "note_type",
        "date_of_service",
        "days_open",
        "aging",
        "state",
        "state_label",
    }
    assert expected.issubset(row.keys())


# ── Unit tests for helpers ────────────────────────────────────────────────


def test_parse_threshold_valid() -> None:
    assert _parse_threshold("5", 2) == 5


def test_parse_threshold_none_uses_default() -> None:
    assert _parse_threshold(None, 2) == 2


def test_parse_threshold_non_numeric_uses_default() -> None:
    assert _parse_threshold("abc", 4) == 4


def test_parse_threshold_negative_uses_default() -> None:
    assert _parse_threshold("-1", 4) == 4


def test_parse_threshold_whitespace_is_stripped() -> None:
    assert _parse_threshold("  3 ", 2) == 3


def test_aging_level_normal() -> None:
    assert _aging_level(1, 2, 4) == "normal"


def test_aging_level_amber_at_boundary() -> None:
    assert _aging_level(2, 2, 4) == "amber"


def test_aging_level_red_at_boundary() -> None:
    assert _aging_level(4, 2, 4) == "red"


def test_aging_level_red_takes_precedence() -> None:
    """When both thresholds are equal/crossed, red wins."""
    assert _aging_level(10, 2, 4) == "red"


def _fake_event(
    *,
    state: str = NoteStates.UNLOCKED.value,
    first: str = "Bob",
    last: str = "Jones",
    patient_id: str = "pat-uuid",
    note_id: str = "note-uuid",
    note_type_name: str | None = "Office Visit",
    title: str = "",
    dos: datetime.datetime | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace mimicking a CurrentNoteStateEvent + note graph."""
    patient = SimpleNamespace(id=patient_id, first_name=first, last_name=last)
    note_type_version = (
        SimpleNamespace(name=note_type_name) if note_type_name is not None else None
    )
    note = SimpleNamespace(
        id=note_id,
        patient=patient,
        provider=SimpleNamespace(id="prov"),
        note_type_version=note_type_version,
        title=title,
        datetime_of_service=dos,
    )
    return SimpleNamespace(note=note, state=state)


def test_build_row_basic_shape_and_state_label() -> None:
    ref_date = datetime.date(2026, 6, 18)
    dos = datetime.datetime(2026, 6, 14, 9, 0, tzinfo=UTC)
    row = _build_row(_fake_event(dos=dos), ref_date, UTC, 2, 4)

    assert row["patient_name"] == "Bob Jones"
    assert row["patient_id"] == "pat-uuid"
    assert (
        row["note_title"] == "Office Visit"
    )  # falls back to note type when title empty
    assert row["days_open"] == 4
    assert row["aging"] == "red"
    assert row["state_label"] == "Unlocked"


def test_build_row_prefers_title_over_note_type() -> None:
    ref_date = datetime.date(2026, 6, 18)
    dos = datetime.datetime(2026, 6, 18, 9, 0, tzinfo=UTC)
    row = _build_row(
        _fake_event(title="Telehealth follow-up", dos=dos), ref_date, UTC, 2, 4
    )
    assert row["note_title"] == "Telehealth follow-up"


def test_build_row_unknown_state_falls_back_to_raw_value() -> None:
    ref_date = datetime.date(2026, 6, 18)
    dos = datetime.datetime(2026, 6, 18, 9, 0, tzinfo=UTC)
    row = _build_row(_fake_event(state="ZZZ", dos=dos), ref_date, UTC, 2, 4)
    assert row["state_label"] == "ZZZ"


def test_build_row_missing_patient_is_handled() -> None:
    ref_date = datetime.date(2026, 6, 18)
    dos = datetime.datetime(2026, 6, 18, 9, 0, tzinfo=UTC)
    event = _fake_event(dos=dos)
    event.note.patient = None
    row = _build_row(event, ref_date, UTC, 2, 4)
    assert row["patient_name"] == "Unknown Patient"
    assert row["patient_id"] == ""


def test_build_row_clamps_negative_days_open() -> None:
    """A future date of service must never render as negative days open."""
    ref_date = datetime.date(2026, 6, 18)
    dos = datetime.datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
    row = _build_row(_fake_event(dos=dos), ref_date, UTC, 2, 4)
    assert row["days_open"] == 0


def test_build_row_handles_missing_dos() -> None:
    ref_date = datetime.date(2026, 6, 18)
    row = _build_row(_fake_event(dos=None), ref_date, UTC, 2, 4)
    assert row["days_open"] == 0
    assert row["date_of_service"] is None
