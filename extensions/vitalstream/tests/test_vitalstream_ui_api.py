from __future__ import annotations

import datetime
import json
import sys
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vitalstream.constants import TREATMENT_INTERVALS
from vitalstream.routes import vitalstream_ui_api as api_mod
from vitalstream.routes.vitalstream_ui_api import (
    VitalstreamUIAPI,
    _build_interval_html_table,
    _build_summary_html_table,
    _classify_phase,
    _compute_buckets,
    _create_interval_observations,
    _create_summary_observations,
    _parse_bool_secret,
    _parse_vitals_datetime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(
    *,
    session: object | None,
    path_params: dict | None = None,
    body: dict | None = None,
    secrets: dict | None = None,
    environment: dict | None = None,
    headers: dict | None = None,
) -> VitalstreamUIAPI:
    handler = VitalstreamUIAPI.__new__(VitalstreamUIAPI)
    handler.request = MagicMock()
    handler.request.path_params = path_params or {}
    handler.request.json = MagicMock(return_value=body or {})
    handler.request.headers = headers or {"canvas-logged-in-user-id": "staff-1"}
    handler.secrets = secrets or {}
    handler.environment = environment or {"CUSTOMER_IDENTIFIER": "testsub"}

    _set_session_lookup(session)
    return handler


def _set_session_lookup(session: object | None) -> None:
    """Wire VitalstreamSession.objects.filter().first() → session."""
    chain = MagicMock()
    chain.first.return_value = session
    sys.modules["vitalstream.models"].VitalstreamSession.objects.filter.return_value = chain


def _set_reading_lookup(readings: list) -> None:
    """Wire VitalstreamReading.objects.filter().order_by() → readings."""
    chain = MagicMock()
    chain.order_by.return_value = readings
    sys.modules["vitalstream.models"].VitalstreamReading.objects.filter.return_value = chain


def _make_reading(
    *,
    reading_time: datetime.datetime,
    hr: int | None = None,
    sys: int | None = None,
    dia: int | None = None,
    resp: int | None = None,
    spo2: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        reading_time=reading_time, hr=hr, sys=sys, dia=dia, resp=resp, spo2=spo2
    )


def _make_session(
    *,
    session_id: str = "abc",
    staff_id: str = "staff-1",
    note_id: int = 42,
    status: str = "open",
) -> MagicMock:
    """A session mock whose .save() captures status/ended_at updates."""
    s = MagicMock(spec=["session_id", "staff_id", "note_id", "status", "ended_at",
                        "summary_increment_minutes", "save"])
    s.session_id = session_id
    s.staff_id = staff_id
    s.note_id = note_id
    s.status = status
    s.ended_at = None
    s.summary_increment_minutes = None
    return s


# ---------------------------------------------------------------------------
# _parse_bool_secret
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "on", " enabled "])
def test_parse_bool_secret_truthy(value: str) -> None:
    assert _parse_bool_secret(value) is True


@pytest.mark.parametrize("value", ["", None, "0", "false", "False", "no", "off", "disabled", "anything-else"])
def test_parse_bool_secret_falsy(value: str | None) -> None:
    assert _parse_bool_secret(value) is False


# ---------------------------------------------------------------------------
# _parse_vitals_datetime
# ---------------------------------------------------------------------------


def test_parse_vitals_datetime_iso_with_z_suffix() -> None:
    dt = _parse_vitals_datetime("2026-05-17T14:30:45Z")
    assert dt.year == 2026 and dt.month == 5 and dt.day == 17
    assert dt.hour == 14 and dt.minute == 30 and dt.second == 45
    assert dt.utcoffset() == datetime.timedelta(0)


def test_parse_vitals_datetime_invalid_falls_back_to_now_utc() -> None:
    dt = _parse_vitals_datetime("not-a-time")
    assert dt.utcoffset() == datetime.timedelta(0)


# ---------------------------------------------------------------------------
# _classify_phase
# ---------------------------------------------------------------------------


def test_classify_phase_with_only_start() -> None:
    assert _classify_phase(5, 10, None) == "pre"
    assert _classify_phase(15, 10, None) == "during"


def test_classify_phase_with_only_end() -> None:
    assert _classify_phase(5, None, 10) == "during"
    assert _classify_phase(15, None, 10) == "post"


def test_classify_phase_blank_when_no_window() -> None:
    assert _classify_phase(5, None, None) == ""


# ---------------------------------------------------------------------------
# _compute_buckets — moved server-side from the JS, must match the algorithm.
# ---------------------------------------------------------------------------


def test_compute_buckets_picks_readings_in_1min_window_around_each_mark() -> None:
    start = datetime.datetime(2026, 5, 17, 9, 0, tzinfo=datetime.timezone.utc)
    # Readings at 0min, 0.5min, 5min — only the first two fall inside the 0min
    # window (±0.5), the third falls inside the 5min window.
    readings = [
        _make_reading(reading_time=start, hr=70),
        _make_reading(reading_time=start + datetime.timedelta(seconds=30), hr=80),
        _make_reading(reading_time=start + datetime.timedelta(minutes=5), hr=90),
    ]
    buckets = _compute_buckets(readings, start, increment_minutes=5)

    assert len(buckets) == 2
    assert buckets[0]["label"] == "0 min"
    assert buckets[0]["count"] == "2"
    assert buckets[0]["hr"] == "75"  # mean(70, 80)

    assert buckets[1]["label"] == "5 min"
    assert buckets[1]["count"] == "1"
    assert buckets[1]["hr"] == "90"


def test_compute_buckets_skips_marks_with_no_readings_in_window() -> None:
    """A 25-minute increment with readings only at 0 and 26 minutes should
    produce a bucket at 0 (with the 0min reading) and one at 25 (with the
    26min reading falling inside 25±0.5? — no, it doesn't), so only one
    bucket. This guards against pathological dense bucketing."""
    start = datetime.datetime(2026, 5, 17, 9, 0, tzinfo=datetime.timezone.utc)
    readings = [
        _make_reading(reading_time=start, hr=70),
        _make_reading(reading_time=start + datetime.timedelta(minutes=26), hr=80),
    ]
    buckets = _compute_buckets(readings, start, increment_minutes=10)
    labels = [b["label"] for b in buckets]
    assert "0 min" in labels
    # No bucket at the 10-, 20- min marks because no readings within ±0.5min.
    assert "10 min" not in labels
    assert "20 min" not in labels


def test_compute_buckets_averages_each_field_independently() -> None:
    start = datetime.datetime(2026, 5, 17, 9, 0, tzinfo=datetime.timezone.utc)
    readings = [
        _make_reading(reading_time=start, hr=70, sys=120, dia=80, resp=14, spo2=99),
        _make_reading(reading_time=start, hr=80, sys=130, dia=90, resp=16, spo2=97),
    ]
    bucket = _compute_buckets(readings, start, increment_minutes=5)[0]
    assert bucket["hr"] == "75"
    assert bucket["bp_sys"] == "125"
    assert bucket["bp_dia"] == "85"
    assert bucket["rr"] == "15"
    assert bucket["spo2"] == "98"


def test_compute_buckets_handles_empty() -> None:
    start = datetime.datetime(2026, 5, 17, 9, 0, tzinfo=datetime.timezone.utc)
    assert _compute_buckets([], start, increment_minutes=10) == []


def test_compute_buckets_renders_time_in_local_zone_when_tz_offset_set() -> None:
    """Regression: a UTC reading at 05:30 was displaying as '05:30' in the
    saved command even though the user (EDT) saw it as '01:30'. Bucket time
    must be the user's wall-clock — JS sends getTimezoneOffset() (+240 in EDT)
    and the server subtracts it from the UTC anchor."""
    start = datetime.datetime(2026, 5, 17, 5, 30, tzinfo=datetime.timezone.utc)
    readings = [_make_reading(reading_time=start, hr=70)]
    bucket = _compute_buckets(readings, start, increment_minutes=5,
                              tz_offset_minutes=240)[0]
    assert bucket["time"] == "01:30"  # 05:30 UTC - 4h = 01:30 EDT


def test_compute_buckets_zero_tz_offset_preserves_utc_display() -> None:
    start = datetime.datetime(2026, 5, 17, 5, 30, tzinfo=datetime.timezone.utc)
    readings = [_make_reading(reading_time=start, hr=70)]
    bucket = _compute_buckets(readings, start, increment_minutes=5,
                              tz_offset_minutes=0)[0]
    assert bucket["time"] == "05:30"


# ---------------------------------------------------------------------------
# HTML table builders / XSS regression coverage
# ---------------------------------------------------------------------------


def _extract_embedded_json(html: str) -> dict:
    start = html.index('data-vitals="') + len('data-vitals="')
    end = html.index('"', start)
    escaped = html[start:end]
    raw = (
        escaped
        .replace("&#x27;", "'")
        .replace("&quot;", '"')
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
    )
    return json.loads(raw)


def test_build_interval_html_table_renders_each_row_and_embeds_json() -> None:
    rows = [
        {
            "label": "Pre-administration",
            "time": "09:00",
            "hr": "72",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "98",
        },
    ]
    html = _build_interval_html_table(rows, bp_placement="right_wrist")
    assert "Pre-administration" in html
    assert "120/80" in html
    payload = _extract_embedded_json(html)
    assert payload["bp_placement"] == "right_wrist"
    assert payload["rows"] == rows


def test_build_interval_html_table_escapes_cell_html() -> None:
    rows = [{"label": "<script>alert(1)</script>", "time": "09:00", "hr": "72"}]
    html = _build_interval_html_table(rows)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_build_summary_html_table_renders_buckets_and_escapes() -> None:
    buckets = [{"label": "<b>x</b>", "count": "5", "time": "09:00",
                "hr": "72", "bp_sys": "120", "bp_dia": "80", "rr": "16", "spo2": "98"}]
    html = _build_summary_html_table(buckets)
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    payload = _extract_embedded_json(html)
    assert payload["buckets"] == buckets


# ---------------------------------------------------------------------------
# Observation creation
# ---------------------------------------------------------------------------


def test_create_interval_observations_emits_one_per_field(monkeypatch: pytest.MonkeyPatch) -> None:
    obs_ctor = MagicMock()
    monkeypatch.setattr(api_mod, "Observation", obs_ctor)
    rows = [{
        "label": "Pre-administration", "time": "09:00",
        "timestamp": "2026-05-17T09:00:00Z",
        "hr": "70", "bp_sys": "118", "bp_dia": "76", "rr": "14", "spo2": "99",
    }]
    effects = _create_interval_observations(rows, "patient-1", 42)
    assert len(effects) == 4  # HR + BP + SpO2 + RR


def test_create_interval_observations_skips_rows_missing_timestamp() -> None:
    effects = _create_interval_observations(
        [{"label": "x", "time": "09:00", "timestamp": "", "hr": "70"}], "p1", 1
    )
    assert effects == []


def test_create_summary_observations_uses_mean_loinc_names(monkeypatch: pytest.MonkeyPatch) -> None:
    obs_ctor = MagicMock()
    monkeypatch.setattr(api_mod, "Observation", obs_ctor)
    buckets = [{
        "label": "0 min", "time": "09:00", "timestamp": "2026-05-17T09:00:00Z",
        "hr": "72", "bp_sys": "120", "bp_dia": "80", "rr": "16", "spo2": "98",
    }]
    effects = _create_summary_observations(buckets, "patient-1", 42)
    assert len(effects) == 4
    names = [c.kwargs["name"] for c in obs_ctor.call_args_list]
    assert names == [
        "Mean Heart Rate (0 min)",
        "Mean Blood Pressure (0 min)",
        "Mean SpO2 (0 min)",
        "Mean Respiratory Rate (0 min)",
    ]


# ---------------------------------------------------------------------------
# validate_session
# ---------------------------------------------------------------------------


def test_validate_session_returns_none_when_missing() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "abc"})
    assert handler.validate_session("abc") is None


def test_validate_session_returns_none_when_staff_mismatches() -> None:
    session = _make_session(staff_id="other-staff")
    handler = _make_handler(session=session, path_params={"session_id": "abc"})
    assert handler.validate_session("abc") is None


def test_validate_session_returns_session_on_match() -> None:
    session = _make_session(staff_id="staff-1")
    handler = _make_handler(session=session, path_params={"session_id": "abc"})
    assert handler.validate_session("abc") is session


# ---------------------------------------------------------------------------
# index — receives note_dbid, does get-or-create against the DB
# ---------------------------------------------------------------------------


def _set_session_chain(open_session: object | None, latest_session: object | None) -> None:
    """Configure the get-or-create lookup chain inside the UI handler:
    first the OPEN filter (.filter(...).order_by(...).first()), then the
    fallback that returns the most recent row of any status."""
    open_chain = MagicMock()
    open_chain.order_by.return_value.first.return_value = open_session
    latest_chain = MagicMock()
    latest_chain.order_by.return_value.first.return_value = latest_session
    sys.modules["vitalstream.models"].VitalstreamSession.objects.filter.side_effect = [
        open_chain,
        latest_chain,
    ]


def _render_context(handler: VitalstreamUIAPI) -> dict:
    templates_mod = sys.modules["canvas_sdk.templates"]
    templates_mod.render_to_string.reset_mock()
    templates_mod.render_to_string.return_value = "<html/>"
    handler.index()
    args, _ = templates_mod.render_to_string.call_args
    return args[1]


def _make_index_handler(
    note_type_name: str,
    note_title: str,
    secrets: dict | None = None,
    *,
    open_session: object | None = None,
    latest_session: object | None = None,
    note_exists: bool = True,
) -> VitalstreamUIAPI:
    """Build the handler and wire the Note + VitalstreamSession lookups.

    By default no session pre-exists, so the handler will call save() on a
    fresh VitalstreamSession instance. Pass `open_session=` to test the
    reuse path.
    """
    handler = VitalstreamUIAPI.__new__(VitalstreamUIAPI)
    handler.request = MagicMock()
    handler.request.path_params = {"note_dbid": "42"}
    handler.request.json = MagicMock(return_value={})
    handler.request.headers = {"canvas-logged-in-user-id": "staff-1"}
    handler.secrets = secrets or {}
    handler.environment = {"CUSTOMER_IDENTIFIER": "testsub"}

    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    if note_exists:
        note = MagicMock()
        note.note_type_version = SimpleNamespace(name=note_type_name)
        note.title = note_title
        note_mgr.select_related.return_value.get.return_value = note
    else:
        # The handler catches Note.DoesNotExist; make .get raise that.
        note_mgr.select_related.return_value.get.side_effect = (
            sys.modules["canvas_sdk.v1.data.note"].Note.DoesNotExist
        )

    _set_session_chain(open_session, latest_session)
    return handler


def test_index_returns_404_when_note_does_not_exist() -> None:
    # Wire DoesNotExist on the Note mock — the handler should fail closed.
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})
    handler = _make_index_handler("", "", note_exists=False)
    responses = handler.index()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_index_creates_session_when_none_exists() -> None:
    # Wire a real DoesNotExist class so the handler's try/except works.
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})

    handler = _make_index_handler("Follow-up", "")
    VitalstreamSession = sys.modules["vitalstream.models"].VitalstreamSession
    _render_context(handler)
    VitalstreamSession.assert_called_once()
    kwargs = VitalstreamSession.call_args.kwargs
    assert kwargs["staff_id"] == "staff-1"
    assert kwargs["status"] == "open"
    VitalstreamSession.return_value.save.assert_called_once()


def test_index_reuses_existing_open_session() -> None:
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})

    existing = SimpleNamespace(session_id="existing-uuid", status="open")
    handler = _make_index_handler("Follow-up", "", open_session=existing)
    VitalstreamSession = sys.modules["vitalstream.models"].VitalstreamSession
    context = _render_context(handler)
    assert context["session_id"] == "existing-uuid"
    assert context["session_status"] == "open"
    VitalstreamSession.assert_not_called()


def test_index_reuses_most_recent_closed_session_for_read_only_revisit() -> None:
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})

    closed = SimpleNamespace(session_id="closed-uuid", status="closed")
    handler = _make_index_handler("Follow-up", "", latest_session=closed)
    VitalstreamSession = sys.modules["vitalstream.models"].VitalstreamSession
    context = _render_context(handler)
    assert context["session_id"] == "closed-uuid"
    assert context["session_status"] == "closed"
    VitalstreamSession.assert_not_called()


def test_index_detects_spravato_from_note_type_name() -> None:
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})
    existing = SimpleNamespace(session_id="s1", status="open")
    handler = _make_index_handler("Spravato Treatment", "Visit 3", open_session=existing)
    context = _render_context(handler)
    assert context["is_spravato"] is True
    assert context["treatment_intervals"] == TREATMENT_INTERVALS


def test_index_detects_spravato_from_note_title_case_insensitive() -> None:
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})
    existing = SimpleNamespace(session_id="s1", status="open")
    handler = _make_index_handler("Follow-up", "SPRAVATO session", open_session=existing)
    context = _render_context(handler)
    assert context["is_spravato"] is True


def test_index_treatment_plan_does_not_match_as_spravato() -> None:
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.Note.DoesNotExist = type("DoesNotExist", (Exception,), {})
    existing = SimpleNamespace(session_id="s1", status="open")
    handler = _make_index_handler("Treatment Plan", "", open_session=existing)
    context = _render_context(handler)
    assert context["is_spravato"] is False


# ---------------------------------------------------------------------------
# list_readings — used by the UI to backfill on open
# ---------------------------------------------------------------------------


def test_list_readings_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.list_readings()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_list_readings_returns_persisted_readings_with_status_and_prefs() -> None:
    session = _make_session(status="open")
    handler = _make_handler(session=session, path_params={"session_id": "s1"})

    readings = [
        _make_reading(
            reading_time=datetime.datetime(2026, 5, 17, 9, 0, tzinfo=datetime.timezone.utc),
            hr=70, sys=120, dia=80, resp=14, spo2=99,
        ),
        _make_reading(
            reading_time=datetime.datetime(2026, 5, 17, 9, 0, 30, tzinfo=datetime.timezone.utc),
            hr=72, sys=121, dia=81, resp=14, spo2=99,
        ),
    ]
    _set_reading_lookup(readings)

    # Cache returns previously saved preferences.
    cache_mock = MagicMock()
    cache_mock.get.return_value = {"bp_placement": "right_wrist", "increment_minutes": 15}
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    responses = handler.list_readings()
    body = responses[0].data
    assert body["status"] == "open"
    assert len(body["readings"]) == 2
    assert body["readings"][0]["hr"] == 70
    assert body["preferences"] == {"bp_placement": "right_wrist", "increment_minutes": 15}


def test_list_readings_returns_empty_prefs_when_cache_empty() -> None:
    session = _make_session(status="open")
    handler = _make_handler(session=session, path_params={"session_id": "s1"})
    _set_reading_lookup([])

    cache_mock = MagicMock()
    cache_mock.get.return_value = None
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    body = handler.list_readings()[0].data
    assert body["preferences"] == {}


# ---------------------------------------------------------------------------
# save_preferences — persists the form inputs in the cache
# ---------------------------------------------------------------------------


def test_save_preferences_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.save_preferences()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_save_preferences_persists_whitelisted_keys_with_ttl() -> None:
    session = _make_session()
    cache_mock = MagicMock()
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock
    handler = _make_handler(
        session=session,
        path_params={"session_id": "abc"},
        body={
            "treatment_type": "spravato",
            "increment_minutes": 15,
            "bp_placement": "right_wrist",
            "treatment_start": "09:00",
            "treatment_end": "10:30",
            # extra keys must be dropped — the cache isn't a generic dump
            "something_else": "<script>",
        },
    )
    responses = handler.save_preferences()
    assert responses[0].status_code == 200
    set_call = cache_mock.set.call_args
    assert set_call.args[0] == "vs_prefs:abc"
    stored = set_call.args[1]
    assert "something_else" not in stored
    assert stored["treatment_type"] == "spravato"
    assert stored["increment_minutes"] == 15
    assert stored["bp_placement"] == "right_wrist"
    # TTL should be 48 hours.
    assert set_call.kwargs.get("timeout_seconds") == 60 * 60 * 48


# ---------------------------------------------------------------------------
# mock_vitals — must persist a reading AND broadcast
# ---------------------------------------------------------------------------


def test_mock_vitals_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.mock_vitals()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_mock_vitals_disabled_returns_forbidden() -> None:
    session = _make_session()
    handler = _make_handler(session=session, path_params={"session_id": "s1"}, secrets={})
    responses = handler.mock_vitals()
    assert responses[0].status_code == HTTPStatus.FORBIDDEN


def test_mock_vitals_rejected_when_session_closed() -> None:
    session = _make_session(status="closed")
    handler = _make_handler(
        session=session,
        path_params={"session_id": "s1"},
        secrets={"ENABLE_MOCK_VITALS": "true"},
    )
    responses = handler.mock_vitals()
    assert responses[0].status_code == HTTPStatus.CONFLICT


def test_mock_vitals_persists_a_reading_and_broadcasts() -> None:
    session = _make_session()
    handler = _make_handler(
        session=session,
        path_params={"session_id": "a-b-c"},
        secrets={"ENABLE_MOCK_VITALS": "1"},
    )

    # Patch the model constructor so we can verify save() was called.
    reading_ctor = MagicMock()
    saved_reading = MagicMock()
    reading_ctor.return_value = saved_reading
    saved_reading.hr = 80
    saved_reading.sys = 120
    saved_reading.dia = 80
    saved_reading.resp = 16
    saved_reading.spo2 = 99
    with patch.object(api_mod, "VitalstreamReading", reading_ctor):
        effects = handler.mock_vitals()

    reading_ctor.assert_called_once()
    saved_reading.save.assert_called_once()
    # First effect = Broadcast, second = JSON ok.
    broadcast = effects[0]
    assert broadcast.kwargs["channel"] == "a_b_c"
    assert "measurements" in broadcast.kwargs["message"]


# ---------------------------------------------------------------------------
# save_intervals — Spravato workflow, must NOT end the session
# ---------------------------------------------------------------------------


def test_save_intervals_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.save_intervals()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_save_intervals_empty_rows_returns_400() -> None:
    session = _make_session()
    handler = _make_handler(
        session=session, path_params={"session_id": "s1"}, body={"rows": []}
    )
    responses = handler.save_intervals()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_intervals_does_not_close_session() -> None:
    """Regression: the new end-session button is separate from save-intervals.
    Spravato users may save intervals mid-session without ending recording."""
    session = _make_session()
    rows = [{
        "label": "Pre-administration", "time": "09:00",
        "timestamp": "2026-05-17T09:00:00Z",
        "hr": "70", "bp_sys": "120", "bp_dia": "80", "rr": "16", "spo2": "99",
    }]
    handler = _make_handler(
        session=session,
        path_params={"session_id": "s1"},
        body={"rows": rows, "bp_placement": "right_wrist"},
    )
    note = MagicMock()
    note.id = "abcd-1234"
    note.dbid = 42
    note.patient.id = "patient-1"
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.get.return_value = note
    note_mgr.select_related.return_value.get.return_value = note

    with patch.object(api_mod, "CustomCommand", MagicMock()), \
         patch.object(api_mod, "Observation", MagicMock()):
        handler.save_intervals()

    # save() must not be called on the session row.
    session.save.assert_not_called()


# ---------------------------------------------------------------------------
# end_session — atomically closes, computes means, writes observations
# ---------------------------------------------------------------------------


def test_end_session_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.end_session()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_end_session_with_no_readings_still_closes_and_broadcasts() -> None:
    session = _make_session()
    handler = _make_handler(
        session=session, path_params={"session_id": "a-b-c"}, body={}
    )
    _set_reading_lookup([])

    effects = handler.end_session()
    assert session.status == "closed"
    assert session.ended_at is not None
    session.save.assert_called_once()
    # No buckets, but session_closed broadcast still fires.
    broadcast = next(e for e in effects if hasattr(e, "kwargs") and "channel" in e.kwargs)
    assert broadcast.kwargs["channel"] == "a_b_c"
    assert broadcast.kwargs["message"]["event_type"] == "session_closed"


def test_end_session_writes_summary_observations_for_persisted_readings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full end-session flow: close session, read readings, compute means,
    write a CustomCommand + Observations, then broadcast session_closed."""
    session = _make_session()
    handler = _make_handler(
        session=session,
        path_params={"session_id": "abc-def"},
        body={"summary_increment_minutes": 5},
    )
    start = datetime.datetime(2026, 5, 17, 9, 0, tzinfo=datetime.timezone.utc)
    readings = [
        _make_reading(reading_time=start, hr=70, sys=120, dia=80, resp=14, spo2=99),
        _make_reading(reading_time=start + datetime.timedelta(minutes=5),
                       hr=72, sys=122, dia=82, resp=14, spo2=99),
    ]
    _set_reading_lookup(readings)
    note = MagicMock()
    note.dbid = 42
    note.patient.id = "patient-1"
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.select_related.return_value.get.return_value = note

    custom_cmd_ctor = MagicMock()
    obs_ctor = MagicMock()
    monkeypatch.setattr(api_mod, "CustomCommand", custom_cmd_ctor)
    monkeypatch.setattr(api_mod, "Observation", obs_ctor)

    effects = handler.end_session()

    # 1. Session row was flipped to closed and saved.
    assert session.status == "closed"
    assert session.summary_increment_minutes == 5
    session.save.assert_called_once()
    # 2. CustomCommand was constructed with the mean schema_key.
    assert custom_cmd_ctor.call_args.kwargs["schema_key"] == "vitalstreamSummary"
    # 3. Mean Observations were created.
    names = [c.kwargs["name"] for c in obs_ctor.call_args_list]
    assert any(name.startswith("Mean Heart Rate") for name in names)
    # 4. session_closed broadcast was emitted.
    broadcast = next(
        e for e in effects
        if hasattr(e, "kwargs") and e.kwargs.get("message", {}).get("event_type") == "session_closed"
    )
    assert broadcast.kwargs["channel"] == "abc_def"
    # 5. Final JSON response reports closed status with bucket count.
    final = effects[-1]
    assert final.data["status"] == "closed"
    assert len(final.data["buckets"]) >= 1


def test_end_session_phase_uses_client_supplied_elapsed_mins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: with a UTC session_start and a user typing local HH:MM, the
    server used to do its own HH:MM-to-elapsed math against UTC, classifying
    every bucket as 'post'. Now the client sends elapsed-minute floats and
    the server uses them directly — pre/during/post must classify correctly."""
    session = _make_session()
    handler = _make_handler(
        session=session,
        path_params={"session_id": "abc-def"},
        body={
            "summary_increment_minutes": 5,
            # Session starts at the wall-clock equivalent of "treatment_start - 2 min",
            # so 0 min bucket is "pre", 5 min and 10 min are "during", 15 min is "post".
            "treatment_start_elapsed_min": 2,
            "treatment_end_elapsed_min": 12,
            "tz_offset_minutes": 240,
        },
    )
    start = datetime.datetime(2026, 5, 17, 5, 30, tzinfo=datetime.timezone.utc)
    readings = [
        _make_reading(reading_time=start, hr=70),
        _make_reading(reading_time=start + datetime.timedelta(minutes=5), hr=72),
        _make_reading(reading_time=start + datetime.timedelta(minutes=10), hr=74),
        _make_reading(reading_time=start + datetime.timedelta(minutes=15), hr=76),
    ]
    _set_reading_lookup(readings)
    note = MagicMock()
    note.dbid = 42
    note.patient.id = "patient-1"
    sys.modules["canvas_sdk.v1.data.note"].Note.objects.select_related.return_value.get.return_value = note

    monkeypatch.setattr(api_mod, "CustomCommand", MagicMock())
    monkeypatch.setattr(api_mod, "Observation", MagicMock())

    effects = handler.end_session()
    final = effects[-1]
    buckets = final.data["buckets"]
    phases = {b["label"]: b["phase"] for b in buckets if b.get("label") != "Discharge"}
    assert phases["0 min"] == "pre"      # 0 < start_elapsed=2
    assert phases["5 min"] == "during"   # 2 <= 5 <= 12
    assert phases["10 min"] == "during"
    assert phases["15 min"] == "post"    # 15 > end_elapsed=12


def test_end_session_renders_bucket_time_in_user_local_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _make_session()
    handler = _make_handler(
        session=session,
        path_params={"session_id": "abc"},
        body={"summary_increment_minutes": 5, "tz_offset_minutes": 240},
    )
    start = datetime.datetime(2026, 5, 17, 5, 30, tzinfo=datetime.timezone.utc)
    _set_reading_lookup([_make_reading(reading_time=start, hr=70)])
    note = MagicMock()
    note.dbid = 42
    note.patient.id = "patient-1"
    sys.modules["canvas_sdk.v1.data.note"].Note.objects.select_related.return_value.get.return_value = note

    monkeypatch.setattr(api_mod, "CustomCommand", MagicMock())
    monkeypatch.setattr(api_mod, "Observation", MagicMock())

    effects = handler.end_session()
    bucket = effects[-1].data["buckets"][0]
    # 05:30 UTC - 4h (EDT offset) = 01:30 local.
    assert bucket["time"] == "01:30"


def test_end_session_defaults_invalid_increment_to_10() -> None:
    session = _make_session()
    handler = _make_handler(
        session=session,
        path_params={"session_id": "abc"},
        body={"summary_increment_minutes": 7},  # not in {5,10,15,20,30}
    )
    _set_reading_lookup([])
    handler.end_session()
    assert session.summary_increment_minutes == 10


def test_end_session_idempotent_when_already_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-calling end_session on an already-closed session must NOT write
    another CustomCommand + Observation set. Doing so would duplicate chart
    artifacts and pick up any readings that raced in after the original
    close."""
    session = _make_session(status="closed")
    session.ended_at = datetime.datetime(2026, 5, 17, 10, 0, tzinfo=datetime.timezone.utc)
    handler = _make_handler(
        session=session, path_params={"session_id": "abc-def"}, body={}
    )

    custom_cmd_ctor = MagicMock()
    obs_ctor = MagicMock()
    monkeypatch.setattr(api_mod, "CustomCommand", custom_cmd_ctor)
    monkeypatch.setattr(api_mod, "Observation", obs_ctor)

    effects = handler.end_session()

    # No re-save: no new session.save(), no new CustomCommand, no new Observations.
    session.save.assert_not_called()
    custom_cmd_ctor.assert_not_called()
    obs_ctor.assert_not_called()

    # Still broadcasts session_closed so any other open UIs lock down.
    broadcast = next(
        e for e in effects
        if hasattr(e, "kwargs") and e.kwargs.get("message", {}).get("event_type") == "session_closed"
    )
    assert broadcast.kwargs["channel"] == "abc_def"

    # The JSON response flags this as a re-call.
    final = effects[-1]
    assert final.data == {"status": "closed", "already_closed": True}


# ---------------------------------------------------------------------------
# Static asset routes
# ---------------------------------------------------------------------------


def test_get_main_js_returns_javascript_response() -> None:
    sys.modules["canvas_sdk.templates"].render_to_string.return_value = "console.log('hi');"
    handler = VitalstreamUIAPI.__new__(VitalstreamUIAPI)
    responses = handler.get_main_js()
    assert responses[0].content_type == "text/javascript"


def test_get_css_returns_stylesheet_response() -> None:
    sys.modules["canvas_sdk.templates"].render_to_string.return_value = "body {}"
    handler = VitalstreamUIAPI.__new__(VitalstreamUIAPI)
    responses = handler.get_css()
    assert responses[0].content_type == "text/css"
