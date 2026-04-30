from __future__ import annotations

import sys
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest

from vitalstream.routes.vitalstream_api import CaretakerPortalAPI


def _make_portal(
    *,
    body: dict,
    secrets: dict,
    cache_session: dict | None = None,
) -> CaretakerPortalAPI:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    handler.request = MagicMock()
    handler.request.json = MagicMock(return_value=body)
    handler.secrets = secrets
    cache_mock = MagicMock()
    cache_mock.get.return_value = cache_session
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock
    return handler


def test_authenticate_always_true() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    assert handler.authenticate(credentials=object()) is True


def test_convert_timestamp_to_iso8601() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    iso = handler.convert_timestamp_to_iso8601("2026-Jan-07 08:50:14 UTC")
    # Arrow normalizes the offset to +00:00.
    assert iso.startswith("2026-01-07T08:50:14")
    assert iso.endswith("+00:00")


def test_index_unauthorized_serial_number_returns_401() -> None:
    handler = _make_portal(
        body={"sn": "UNKNOWN", "patid": "abc"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial\nanother-serial"},
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_index_empty_serial_number_returns_401() -> None:
    handler = _make_portal(
        body={"sn": "   ", "patid": "abc"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_index_authorized_no_active_session_returns_only_accepted() -> None:
    handler = _make_portal(
        body={"sn": "Known-Serial", "patid": "no-session-id"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session=None,
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.ACCEPTED


def test_index_authorized_with_session_parses_measurements_and_broadcasts() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc-def",
        "v1": {
            "0": {
                "ts": "2026-Jan-07 08:50:14 UTC",
                "hr": 72,
                "sys": 120,
                "dia": 80,
                "resp": 16,
            }
        },
        "spo2": {
            "0": {
                "ts": "2026-Jan-07 08:50:14 UTC",
                "v": 98,
            }
        },
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 42, "staff_id": "s1"},
    )
    effects = handler.index()

    assert effects[0].status_code == HTTPStatus.ACCEPTED
    broadcast = effects[1]
    # "-" in patid gets replaced with "_" for the channel name.
    assert broadcast.kwargs["channel"] == "abc_def"
    (ts_key, reading), = broadcast.kwargs["message"]["measurements"].items()
    assert ts_key.startswith("2026-01-07T08:50:14")
    assert reading == {"hr": 72, "sys": 120, "dia": 80, "resp": 16, "spo2": 98}


def test_index_spo2_without_matching_vitals_timestamp_creates_entry() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc",
        "v1": {},
        "spo2": {
            "0": {"ts": "2026-Jan-07 08:51:00 UTC", "v": 95}
        },
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 1},
    )
    effects = handler.index()
    broadcast = effects[1]
    measurements = broadcast.kwargs["message"]["measurements"]
    (_, reading), = measurements.items()
    assert reading == {"spo2": 95}


def test_index_missing_sn_returns_401() -> None:
    handler = _make_portal(
        body={"patid": "abc"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_index_non_string_sn_returns_401() -> None:
    handler = _make_portal(
        body={"sn": 12345, "patid": "abc"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_index_invalid_json_returns_400() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    handler.request = MagicMock()
    handler.request.json = MagicMock(side_effect=ValueError("bad json"))
    handler.secrets = {"AUTHORIZED_SERIAL_NUMBERS": "known-serial"}
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.BAD_REQUEST


def test_index_non_dict_body_returns_400() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    handler.request = MagicMock()
    handler.request.json = MagicMock(return_value=["not", "a", "dict"])
    handler.secrets = {"AUTHORIZED_SERIAL_NUMBERS": "known-serial"}
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.BAD_REQUEST


def test_index_missing_patid_returns_accepted_only() -> None:
    handler = _make_portal(
        body={"sn": "Known-Serial"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 1},
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.ACCEPTED


def test_index_blank_patid_returns_accepted_only() -> None:
    handler = _make_portal(
        body={"sn": "Known-Serial", "patid": "   "},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 1},
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.ACCEPTED


def test_index_malformed_timestamp_is_skipped_not_fatal() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc",
        "v1": {
            "0": {"ts": "totally-not-a-timestamp", "hr": 80},
            "1": {"ts": "2026-Jan-07 08:50:14 UTC", "hr": 72},
        },
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 1},
    )
    effects = handler.index()
    assert effects[0].status_code == HTTPStatus.ACCEPTED
    broadcast = effects[1]
    measurements = broadcast.kwargs["message"]["measurements"]
    # Only the well-formed row made it through.
    assert len(measurements) == 1
    (ts_key, reading), = measurements.items()
    assert ts_key.startswith("2026-01-07T08:50:14")
    assert reading == {"hr": 72}


def test_index_skips_spo2_rows_with_bad_timestamps() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc",
        "v1": {},
        "spo2": {
            "0": {"ts": "garbage", "v": 90},
            "1": {"ts": 12345, "v": 91},
            "2": {"ts": "2026-Jan-07 08:52:00 UTC", "v": 92},
        },
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 1},
    )
    effects = handler.index()
    broadcast = effects[1]
    measurements = broadcast.kwargs["message"]["measurements"]
    # Only the well-formed spo2 reading is kept.
    assert len(measurements) == 1
    (_, reading), = measurements.items()
    assert reading == {"spo2": 92}


def test_index_skips_non_dict_reading_rows() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc",
        "v1": {"0": "not-a-dict"},
        "spo2": {"0": "not-a-dict-either", "1": {"ts": "2026-Jan-07 08:51:00 UTC", "v": 97}},
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        cache_session={"note_id": 1},
    )
    effects = handler.index()
    broadcast = effects[1]
    measurements = broadcast.kwargs["message"]["measurements"]
    (_, reading), = measurements.items()
    assert reading == {"spo2": 97}
