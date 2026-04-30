from __future__ import annotations

import datetime
import json
import sys
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vitalstream.constants import TREATMENT_INTERVALS
from vitalstream.routes import vitalstream_ui_api as api_mod
from vitalstream.routes.vitalstream_ui_api import (
    VitalstreamUIAPI,
    _build_interval_html_table,
    _build_summary_html_table,
    _create_interval_observations,
    _create_summary_observations,
    _parse_vitals_datetime,
)


# ---------------------------------------------------------------------------
# Helpers for constructing a handler without running framework __init__.
# ---------------------------------------------------------------------------


def _make_handler(
    *,
    session: dict | None,
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

    # Pre-wire validate_session via the cache mock unless overridden.
    cache_mod = sys.modules["canvas_sdk.caching.plugins"]
    cache_mock = MagicMock()
    cache_mock.get.return_value = session
    cache_mod.get_cache.return_value = cache_mock
    return handler


# ---------------------------------------------------------------------------
# _parse_vitals_datetime
# ---------------------------------------------------------------------------


def test_parse_vitals_datetime_hhmmss() -> None:
    dt = _parse_vitals_datetime("14:30:45")
    assert dt.hour == 14 and dt.minute == 30 and dt.second == 45
    assert dt.date() == datetime.date.today()


def test_parse_vitals_datetime_hhmm() -> None:
    dt = _parse_vitals_datetime("09:05")
    assert dt.hour == 9 and dt.minute == 5 and dt.second == 0


def test_parse_vitals_datetime_invalid_falls_back_to_midnight() -> None:
    dt = _parse_vitals_datetime("not-a-time")
    assert dt.hour == 0 and dt.minute == 0


def test_parse_vitals_datetime_empty_string_falls_back() -> None:
    dt = _parse_vitals_datetime("")
    assert dt.hour == 0 and dt.minute == 0


# ---------------------------------------------------------------------------
# _build_interval_html_table / _build_summary_html_table
# ---------------------------------------------------------------------------


def _extract_embedded_json(html: str) -> dict:
    # The raw_data div uses HTML-escaped JSON in data-vitals.
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
        {
            "label": "40-min post",
            "time": "09:40",
            "hr": "78",
            "bp_sys": "",
            "bp_dia": "",
            "rr": "",
            "spo2": "97",
        },
    ]
    html = _build_interval_html_table(rows, bp_placement="right_wrist")

    assert "Pre-administration" in html
    assert "40-min post" in html
    assert "120/80" in html
    # BP is blank for the second row since sys/dia are empty — there must
    # only be one "<sys>/<dia>" BP value rendered.
    assert html.count("/80") == 1

    payload = _extract_embedded_json(html)
    assert payload["bp_placement"] == "right_wrist"
    assert payload["rows"] == rows


def test_build_summary_html_table_renders_buckets() -> None:
    buckets = [
        {
            "label": "0 min",
            "count": "5",
            "time": "09:00",
            "hr": "72",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "98",
        }
    ]
    html = _build_summary_html_table(buckets)
    assert "0 min" in html
    assert "120/80" in html
    payload = _extract_embedded_json(html)
    assert payload["buckets"] == buckets
    assert payload["bp_placement"] == "left_wrist"


def test_build_interval_html_table_escapes_html_in_cell_values() -> None:
    # A malicious staff (or compromised client) must not be able to inject
    # script tags via any visible row field.
    rows = [
        {
            "label": "<script>alert(1)</script>",
            "time": "09:00",
            "hr": "72\"><img src=x onerror=alert(1)>",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "98",
        }
    ]
    html = _build_interval_html_table(rows)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # The HR payload must have its quotes and angle brackets escaped too.
    assert "onerror=alert(1)" not in html or "&lt;img" in html
    assert "&quot;" in html


def test_build_summary_html_table_escapes_html_in_cell_values() -> None:
    buckets = [
        {
            "label": "<b>bold</b>",
            "count": "5<script>x</script>",
            "time": "09:00",
            "hr": "72",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "98",
        }
    ]
    html = _build_summary_html_table(buckets)
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "<script>x</script>" not in html


# ---------------------------------------------------------------------------
# _create_interval_observations / _create_summary_observations
# ---------------------------------------------------------------------------


def test_create_interval_observations_skips_rows_missing_time() -> None:
    effects = _create_interval_observations(
        [{"label": "x", "time": "", "hr": "70"}], "p1", 1
    )
    assert effects == []


def test_create_interval_observations_creates_expected_number_of_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    obs_ctor = MagicMock()
    monkeypatch.setattr(api_mod, "Observation", obs_ctor)
    rows = [
        {
            "label": "Pre-administration",
            "time": "09:00",
            "hr": "70",
            "bp_sys": "118",
            "bp_dia": "76",
            "rr": "14",
            "spo2": "99",
        }
    ]
    effects = _create_interval_observations(rows, "patient-1", 42)

    # HR + BP + SpO2 + RR = 4 Observation.create() calls
    assert len(effects) == 4

    names = [c.kwargs["name"] for c in obs_ctor.call_args_list]
    assert names == [
        "Heart Rate (Pre-administration)",
        "Blood Pressure (Pre-administration)",
        "SpO2 (Pre-administration)",
        "Respiratory Rate (Pre-administration)",
    ]


def test_create_summary_observations_creates_mean_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    obs_ctor = MagicMock()
    monkeypatch.setattr(api_mod, "Observation", obs_ctor)
    buckets = [
        {
            "label": "0 min",
            "time": "09:00",
            "hr": "72",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "98",
        }
    ]
    effects = _create_summary_observations(buckets, "patient-1", 42)
    assert len(effects) == 4
    names = [c.kwargs["name"] for c in obs_ctor.call_args_list]
    assert names == [
        "Mean Heart Rate (0 min)",
        "Mean Blood Pressure (0 min)",
        "Mean SpO2 (0 min)",
        "Mean Respiratory Rate (0 min)",
    ]


def test_create_summary_observations_skips_bucket_without_time() -> None:
    effects = _create_summary_observations(
        [{"label": "x", "time": "", "hr": "70"}], "p1", 1
    )
    assert effects == []


# ---------------------------------------------------------------------------
# VitalstreamUIAPI.validate_session
# ---------------------------------------------------------------------------


def test_validate_session_returns_none_when_missing() -> None:
    handler = _make_handler(session=None)
    assert handler.validate_session("abc") is None


def test_validate_session_returns_none_when_staff_mismatches() -> None:
    handler = _make_handler(session={"staff_id": "other-staff", "note_id": 1})
    assert handler.validate_session("abc") is None


def test_validate_session_returns_session_on_match() -> None:
    session = {"staff_id": "staff-1", "note_id": 42}
    handler = _make_handler(session=session)
    assert handler.validate_session("abc") is session


# ---------------------------------------------------------------------------
# VitalstreamUIAPI.index
# ---------------------------------------------------------------------------


def test_index_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.index()
    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_index_detects_spravato_from_note_type() -> None:
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
    )
    note = MagicMock()
    note.note_type_version = SimpleNamespace(name="Spravato Treatment")
    note.title = "Visit 3"
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.get.return_value = note
    note_mgr.select_related.return_value.get.return_value = note

    templates_mod = sys.modules["canvas_sdk.templates"]
    templates_mod.render_to_string.reset_mock()
    templates_mod.render_to_string.return_value = "<html/>"

    handler.index()

    # Context passed to render_to_string should mark spravato true.
    _, kwargs = templates_mod.render_to_string.call_args
    # render_to_string(path, context) — context is positional 2nd arg.
    args, _ = templates_mod.render_to_string.call_args
    context = args[1] if len(args) > 1 else kwargs.get("context", {})
    assert context["is_spravato"] is True
    assert context["subdomain"] == "testsub"
    assert context["treatment_intervals"] == TREATMENT_INTERVALS


def test_index_non_spravato_context() -> None:
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
    )
    note = MagicMock()
    note.note_type_version = SimpleNamespace(name="Follow-up")
    note.title = "Checkup"
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.get.return_value = note
    note_mgr.select_related.return_value.get.return_value = note

    templates_mod = sys.modules["canvas_sdk.templates"]
    templates_mod.render_to_string.reset_mock()
    templates_mod.render_to_string.return_value = "<html/>"

    handler.index()

    args, _ = templates_mod.render_to_string.call_args
    context = args[1]
    assert context["is_spravato"] is False


# ---------------------------------------------------------------------------
# VitalstreamUIAPI.mock_vitals
# ---------------------------------------------------------------------------


def test_mock_vitals_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.mock_vitals()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_mock_vitals_disabled_returns_forbidden() -> None:
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
        secrets={},
    )
    responses = handler.mock_vitals()
    assert responses[0].status_code == HTTPStatus.FORBIDDEN


def test_mock_vitals_enabled_broadcasts_and_returns_ok() -> None:
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "a-b-c"},
        secrets={"ENABLE_MOCK_VITALS": "1"},
    )
    effects = handler.mock_vitals()
    # First effect = Broadcast (with "-" → "_" substitution), second = JSON ok.
    broadcast = effects[0]
    assert broadcast.kwargs["channel"] == "a_b_c"
    assert "measurements" in broadcast.kwargs["message"]
    measurements = broadcast.kwargs["message"]["measurements"]
    (_ts, reading), = measurements.items()
    assert set(reading) == {"hr", "sys", "dia", "resp", "spo2"}
    assert effects[1].status_code == 200


# ---------------------------------------------------------------------------
# VitalstreamUIAPI.save_intervals
# ---------------------------------------------------------------------------


def test_save_intervals_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.save_intervals()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_save_intervals_empty_rows_returns_400() -> None:
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
        body={"rows": []},
    )
    responses = handler.save_intervals()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_intervals_happy_path_produces_effects_and_json_ok() -> None:
    rows = [
        {
            "label": "Pre-administration",
            "time": "09:00",
            "hr": "70",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "99",
        },
        {
            "label": "40-min post",
            "time": "09:40",
            "hr": "72",
            "bp_sys": "118",
            "bp_dia": "78",
            "rr": "16",
            "spo2": "99",
        },
        {
            "label": "Pre-discharge",
            "time": "10:00",
            "hr": "70",
            "bp_sys": "116",
            "bp_dia": "76",
            "rr": "16",
            "spo2": "99",
        },
    ]
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
        body={"rows": rows, "bp_placement": "right_wrist"},
    )
    note = MagicMock()
    note.id = "note-uuid"
    note.dbid = 42
    note.patient.id = "patient-1"
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.get.return_value = note
    note_mgr.select_related.return_value.get.return_value = note

    custom_cmd_ctor = MagicMock()
    from unittest.mock import patch
    with patch.object(api_mod, "CustomCommand", custom_cmd_ctor), \
         patch.object(api_mod, "Observation", MagicMock()):
        effects = handler.save_intervals()

    # Must end with a JSONResponse that reports ok.
    assert effects[-1].status_code == 200
    assert effects[-1].data == {"status": "ok"}

    # A broadcast should be queued on the spravato_notify channel.
    broadcast_channels = [
        e.kwargs.get("channel")
        for e in effects
        if hasattr(e, "kwargs") and isinstance(e.kwargs, dict) and "channel" in e.kwargs
    ]
    assert "spravato_notify" in broadcast_channels

    # The CustomCommand was constructed with the spravato vitals schema.
    assert custom_cmd_ctor.call_args.kwargs["schema_key"] == "spravatoVitals"


# ---------------------------------------------------------------------------
# VitalstreamUIAPI.save_summary
# ---------------------------------------------------------------------------


def test_save_summary_missing_session_returns_404() -> None:
    handler = _make_handler(session=None, path_params={"session_id": "s1"})
    responses = handler.save_summary()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_save_summary_empty_buckets_returns_400() -> None:
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
        body={"buckets": []},
    )
    responses = handler.save_summary()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_summary_happy_path() -> None:
    buckets = [
        {
            "label": "0 min",
            "count": "5",
            "time": "09:00",
            "hr": "72",
            "bp_sys": "120",
            "bp_dia": "80",
            "rr": "16",
            "spo2": "98",
        }
    ]
    handler = _make_handler(
        session={"staff_id": "staff-1", "note_id": 42},
        path_params={"session_id": "s1"},
        body={"buckets": buckets},
    )
    note = MagicMock()
    note.id = "note-uuid"
    note.dbid = 42
    note.patient.id = "patient-1"
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.get.return_value = note
    note_mgr.select_related.return_value.get.return_value = note

    custom_cmd_ctor = MagicMock()
    from unittest.mock import patch
    with patch.object(api_mod, "CustomCommand", custom_cmd_ctor), \
         patch.object(api_mod, "Observation", MagicMock()):
        effects = handler.save_summary()

    assert effects[-1].status_code == 200
    assert custom_cmd_ctor.call_args.kwargs["schema_key"] == "vitalstreamSummary"


# ---------------------------------------------------------------------------
# Static asset routes
# ---------------------------------------------------------------------------


def test_get_main_js_returns_javascript_response() -> None:
    templates_mod = sys.modules["canvas_sdk.templates"]
    templates_mod.render_to_string.return_value = "console.log('hi');"
    handler = VitalstreamUIAPI.__new__(VitalstreamUIAPI)

    responses = handler.get_main_js()
    assert responses[0].content_type == "text/javascript"
    assert responses[0].status_code == HTTPStatus.OK


def test_get_css_returns_stylesheet_response() -> None:
    templates_mod = sys.modules["canvas_sdk.templates"]
    templates_mod.render_to_string.return_value = "body {}"
    handler = VitalstreamUIAPI.__new__(VitalstreamUIAPI)

    responses = handler.get_css()
    assert responses[0].content_type == "text/css"
    assert responses[0].status_code == HTTPStatus.OK
