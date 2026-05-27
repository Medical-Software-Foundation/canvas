from __future__ import annotations

import sys
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock

from vitalstream.routes.vitalstream_api import CaretakerPortalAPI


OPEN_SESSION = SimpleNamespace(
    dbid=1, session_id="abc-def", staff_id="s1", note_id=42, status="open"
)
CLOSED_SESSION = SimpleNamespace(
    dbid=1, session_id="abc-def", staff_id="s1", note_id=42, status="closed"
)


def _make_portal(
    *,
    body: dict,
    secrets: dict,
    session: object | None = OPEN_SESSION,
) -> CaretakerPortalAPI:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    handler.request = MagicMock()
    handler.request.json = MagicMock(return_value=body)
    handler.secrets = secrets
    _set_session(session)
    return handler


def _set_session(session: object | None) -> None:
    chain = MagicMock()
    chain.first.return_value = session
    sys.modules["vitalstream.models"].VitalstreamSession.objects.filter.return_value = chain


def _reading_objects() -> MagicMock:
    return sys.modules["vitalstream.models"].VitalstreamReading.objects


def test_authenticate_always_true() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    assert handler.authenticate(credentials=object()) is True


def test_convert_timestamp_to_iso8601() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    iso = handler.convert_timestamp_to_iso8601("2026-Jan-07 08:50:14 UTC")
    assert iso.startswith("2026-01-07T08:50:14")
    assert iso.endswith("+00:00")


def test_unauthorized_serial_number_returns_401() -> None:
    handler = _make_portal(
        body={"sn": "UNKNOWN", "patid": "abc"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_authorized_no_session_returns_only_accepted() -> None:
    handler = _make_portal(
        body={"sn": "Known-Serial", "patid": "missing"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        session=None,
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.ACCEPTED
    _reading_objects().bulk_create.assert_not_called()


def test_closed_session_rejects_readings() -> None:
    """Once End Session is clicked the row flips to 'closed' and device posts
    are accepted at the HTTP layer (so the device doesn't retry forever) but
    no readings persist and no broadcast fires."""
    body = {
        "sn": "Known-Serial",
        "patid": "abc-def",
        "v1": {"0": {"ts": "2026-Jan-07 08:50:14 UTC", "hr": 72}},
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
        session=CLOSED_SESSION,
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.ACCEPTED
    _reading_objects().bulk_create.assert_not_called()


def test_open_session_persists_readings_and_broadcasts() -> None:
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
            "0": {"ts": "2026-Jan-07 08:50:14 UTC", "v": 98},
        },
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()

    assert effects[0].status_code == HTTPStatus.ACCEPTED
    # One VitalstreamReading row was bulk-created for the parsed timestamp.
    _reading_objects().bulk_create.assert_called_once()
    rows = _reading_objects().bulk_create.call_args.args[0]
    assert len(rows) == 1
    # Channel name uses underscores in place of hyphens (limitation of the
    # broadcast channel naming).
    broadcast = effects[1]
    assert broadcast.kwargs["channel"] == "abc_def"


def test_missing_sn_returns_401() -> None:
    handler = _make_portal(
        body={"patid": "abc"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_invalid_json_returns_400() -> None:
    handler = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
    handler.request = MagicMock()
    handler.request.json = MagicMock(side_effect=ValueError("bad json"))
    handler.secrets = {"AUTHORIZED_SERIAL_NUMBERS": "known-serial"}
    effects = handler.index()
    assert effects[0].status_code == HTTPStatus.BAD_REQUEST


def test_missing_patid_returns_accepted_only() -> None:
    handler = _make_portal(
        body={"sn": "Known-Serial"},
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    assert len(effects) == 1
    assert effects[0].status_code == HTTPStatus.ACCEPTED


def test_malformed_timestamp_is_skipped_not_fatal() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc-def",
        "v1": {
            "0": {"ts": "totally-not-a-timestamp", "hr": 80},
            "1": {"ts": "2026-Jan-07 08:50:14 UTC", "hr": 72},
        },
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    broadcast = effects[1]
    measurements = broadcast.kwargs["message"]["measurements"]
    # Only the well-formed row made it through.
    assert len(measurements) == 1
    # And only one reading row was persisted.
    _reading_objects().bulk_create.assert_called_once()
    rows = _reading_objects().bulk_create.call_args.args[0]
    assert len(rows) == 1


def test_spo2_without_matching_vitals_timestamp_creates_entry() -> None:
    body = {
        "sn": "Known-Serial",
        "patid": "abc-def",
        "v1": {},
        "spo2": {"0": {"ts": "2026-Jan-07 08:51:00 UTC", "v": 95}},
    }
    handler = _make_portal(
        body=body,
        secrets={"AUTHORIZED_SERIAL_NUMBERS": "known-serial"},
    )
    effects = handler.index()
    broadcast = effects[1]
    measurements = broadcast.kwargs["message"]["measurements"]
    (_, reading), = measurements.items()
    assert reading == {"spo2": 95}
