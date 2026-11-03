import datetime
import json
from datetime import UTC
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
from canvas_sdk.effects import EffectType

from public_appointment_booking import booking
from public_appointment_booking.handlers import public_api
from public_appointment_booking.handlers.public_api import PublicBookingAPI

START = datetime.datetime.now(UTC).replace(microsecond=0) + datetime.timedelta(days=2)
SLOT = {
    "provider_id": "prov1",
    "provider_name": "Dr Test Provider",
    "start_iso": START.isoformat(),
    "end_iso": (START + datetime.timedelta(minutes=30)).isoformat(),
    "location_id": "loc-internal",
    "location_name": "Main",
    "location_unresolved": False,
}
ENABLED = {
    "PUBLIC_BOOKING_ENABLED": "true",
    "PUBLIC_BOOKING_NOTE_TYPE_NAME": "New visit",
}
SAME_ORIGIN = {
    "Content-Type": "application/json",
    "Origin": "https://demo.canvasmedical.com",
    "X-Forwarded-For": "203.0.113.9",
}


PROVIDER: dict[str, str] = {"id": "unset"}


def _body(**overrides: Any) -> bytes:
    base = {
        "first_name": "Ana",
        "last_name": "Test",
        "birth_date": "1990-04-01",
        "email": "ana@example.org",
        "phone": "555-123-4567",
        "provider_id": PROVIDER["id"],
        "start_iso": START.isoformat(),
        "reason": "Check-up",
    }
    base.update(overrides)
    return json.dumps(base).encode()


def _api(
    secrets: dict | None = None, headers: dict | None = None, body: bytes = b""
) -> Any:
    api = PublicBookingAPI.__new__(PublicBookingAPI)
    api.secrets = ENABLED if secrets is None else secrets
    api.environment = {"CUSTOMER_IDENTIFIER": "demo"}
    api.request = SimpleNamespace(headers=headers or {}, body=body)
    return api


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, cache: Any) -> dict:
    """Wires the handler to a fake cache, test-utils factories and a stubbed slot search."""
    from canvas_sdk.test_utils.factories import (
        NoteTypeFactory,
        PatientFactory,
        PracticeLocationFactory,
        StaffFactory,
    )

    provider = StaffFactory.create()
    location = PracticeLocationFactory.create()
    note_type = NoteTypeFactory.create(
        name="New visit", is_active=True, is_scheduleable=True, category="encounter"
    )
    note_type.online_duration = 30
    note_type.save()
    slot = {**SLOT, "provider_id": str(provider.id), "location_id": str(location.id)}
    calls: dict[str, Any] = {
        "search": 0,
        "patient": None,
        "real_patient": PatientFactory.create(),
        "slot": slot,
        "location_id": str(location.id),
    }

    def fake_search(**_: Any) -> list[dict]:
        calls["search"] += 1
        return [dict(slot)]

    monkeypatch.setattr(public_api, "get_cache", lambda: cache)
    monkeypatch.setattr(booking, "resolve_note_type", lambda name: note_type)
    monkeypatch.setattr(booking, "search_slots", fake_search)
    monkeypatch.setattr(booking, "active_location", lambda: (str(location.id), None))
    monkeypatch.setattr(
        booking,
        "find_matching_patient",
        lambda **_: (
            calls["real_patient"] if calls["patient"] == "REAL" else calls["patient"]
        ),
    )
    monkeypatch.setattr(
        public_api, "render_to_string", lambda path: "<html>book</html>"
    )
    PROVIDER["id"] = str(provider.id)
    calls["cache"] = cache
    return calls


def _response(result: list) -> Any:
    responses = [
        r for r in result if hasattr(r, "content") and hasattr(r, "status_code")
    ]
    assert len(responses) == 1
    return responses[0]


def _json_of(result: list) -> dict:
    return json.loads(_response(result).content)


def _effect_types(result: list) -> list[int]:
    return [r.type for r in result if not hasattr(r, "status_code")]


# ---- auth + off by default ---------------------------------------------------------


def test_authenticate_is_public() -> None:
    assert _api().authenticate(SimpleNamespace()) is True


@pytest.mark.parametrize("route", ["page", "slots", "book"])
def test_every_route_404s_when_not_enabled(wired: dict, route: str) -> None:
    api = _api(secrets={}, headers=SAME_ORIGIN, body=_body())
    result = getattr(api, route)()
    assert _response(result).status_code == HTTPStatus.NOT_FOUND
    assert _effect_types(result) == []
    assert wired["search"] == 0


# ---- page ------------------------------------------------------------------------------


def test_page_serves_html_with_csp(wired: dict) -> None:
    resp = _response(_api().page())
    assert resp.status_code == HTTPStatus.OK
    assert "frame-ancestors 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Cache-Control"] == "no-store"


# ---- slots -----------------------------------------------------------------------------


def test_slots_returns_only_public_fields(wired: dict) -> None:
    body = _json_of(_api(headers={"X-Forwarded-For": "1.2.3.4"}).slots())
    assert body == {
        "slots": [
            {
                "provider_id": wired["slot"]["provider_id"],
                "provider_name": "Dr Test Provider",
                "start_iso": SLOT["start_iso"],
                "end_iso": SLOT["end_iso"],
                "location_name": "Main",
                "duration_minutes": 30,
            }
        ]
    }


def test_slots_cached_between_requests(wired: dict) -> None:
    _api().slots()
    _api().slots()
    assert wired["search"] == 1


def test_slots_rate_limited_per_client(wired: dict) -> None:
    headers = {"X-Forwarded-For": "1.2.3.4"}
    for _ in range(60):
        assert _response(_api(headers=headers).slots()).status_code == HTTPStatus.OK
    assert (
        _response(_api(headers=headers).slots()).status_code
        == HTTPStatus.TOO_MANY_REQUESTS
    )
    other = {"X-Forwarded-For": "5.6.7.8"}
    assert _response(_api(headers=other).slots()).status_code == HTTPStatus.OK


def test_slots_503_when_note_type_unset(wired: dict) -> None:
    resp = _response(_api(secrets={"PUBLIC_BOOKING_ENABLED": "true"}).slots())
    assert resp.status_code == HTTPStatus.SERVICE_UNAVAILABLE


# ---- book: request guards -------------------------------------------------------------


def test_book_rejects_non_json_content_type(wired: dict) -> None:
    headers = {**SAME_ORIGIN, "Content-Type": "application/x-www-form-urlencoded"}
    resp = _response(_api(headers=headers, body=_body()).book())
    assert resp.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE


def test_book_rejects_cross_origin(wired: dict) -> None:
    headers = {**SAME_ORIGIN, "Origin": "https://evil.example"}
    result = _api(headers=headers, body=_body()).book()
    assert _response(result).status_code == HTTPStatus.FORBIDDEN
    assert _effect_types(result) == []


def test_book_rejects_oversized_body(wired: dict) -> None:
    big = _body(reason="x" * 9000)
    resp = _response(_api(headers=SAME_ORIGIN, body=big).book())
    assert resp.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


def test_book_rejects_bad_json(wired: dict) -> None:
    resp = _response(_api(headers=SAME_ORIGIN, body=b"{not json").book())
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_book_validation_error_names_field_only(wired: dict) -> None:
    result = _api(headers=SAME_ORIGIN, body=_body(email="nope")).book()
    assert _response(result).status_code == HTTPStatus.BAD_REQUEST
    assert _json_of(result) == {"error": "invalid_field", "field": "email"}


def test_book_rate_limited_per_client(wired: dict) -> None:
    for i in range(5):
        _api(headers=SAME_ORIGIN, body=_body(email=f"a{i}@example.org")).book()
    resp = _response(
        _api(headers=SAME_ORIGIN, body=_body(email="z@example.org")).book()
    )
    assert resp.status_code == HTTPStatus.TOO_MANY_REQUESTS


def test_book_rate_limited_per_email_across_clients(wired: dict) -> None:
    for i in range(3):
        headers = {**SAME_ORIGIN, "X-Forwarded-For": f"10.0.0.{i}"}
        _api(headers=headers, body=_body()).book()
    headers = {**SAME_ORIGIN, "X-Forwarded-For": "10.0.0.99"}
    resp = _response(_api(headers=headers, body=_body()).book())
    assert resp.status_code == HTTPStatus.TOO_MANY_REQUESTS


def test_junk_posts_do_not_use_global_budget(wired: dict, cache: Any) -> None:
    for i in range(10):
        headers = {**SAME_ORIGIN, "X-Forwarded-For": f"10.0.1.{i}"}
        _api(headers=headers, body=b"not json").book()
        _api(headers=headers, body=_body(email="bad")).book()
    assert "rl:book:global" not in cache.data


def test_concurrent_claim_of_same_slot_conflicts(wired: dict, cache: Any) -> None:
    """A slot already claimed between the open-slot check and the hold is refused."""
    start = datetime.datetime.fromisoformat(SLOT["start_iso"])
    key = booking.hold_key(wired["slot"]["provider_id"], start)
    real_get_many = cache.get_many
    # The open-slot check sees the slot as free, but another request holds it.
    cache.get_many = lambda keys: {}
    cache.data[key] = "other-request"
    try:
        result = _api(headers=SAME_ORIGIN, body=_body()).book()
    finally:
        cache.get_many = real_get_many
    assert _response(result).status_code == HTTPStatus.CONFLICT
    assert _effect_types(result) == []


def test_book_conflict_when_slot_not_offered(wired: dict) -> None:
    other = (START + datetime.timedelta(hours=1)).isoformat()
    result = _api(headers=SAME_ORIGIN, body=_body(start_iso=other)).book()
    assert _response(result).status_code == HTTPStatus.CONFLICT
    assert _effect_types(result) == []


# ---- book: outcomes -----------------------------------------------------------------------


def test_matched_patient_gets_appointment_and_confirm_task(wired: dict) -> None:
    wired["patient"] = wired["real_patient"]
    result = _api(headers=SAME_ORIGIN, body=_body()).book()
    assert _response(result).status_code == HTTPStatus.ACCEPTED
    assert _effect_types(result) == [
        EffectType.CREATE_APPOINTMENT,
        EffectType.CREATE_TASK,
        EffectType.CREATE_TASK_COMMENT,
    ]
    appt = json.loads(result[0].payload)["data"]
    assert appt["patient_id"] == str(wired["real_patient"].id)
    assert appt["provider_id"] == wired["slot"]["provider_id"]
    assert appt["practice_location_id"] == wired["location_id"]
    assert appt["status"] == "unconfirmed"


def test_unmatched_request_creates_review_task_only(wired: dict) -> None:
    wired["patient"] = None
    result = _api(headers=SAME_ORIGIN, body=_body()).book()
    assert _response(result).status_code == HTTPStatus.ACCEPTED
    assert _effect_types(result) == [
        EffectType.CREATE_TASK,
        EffectType.CREATE_TASK_COMMENT,
    ]
    task = json.loads(result[0].payload)["data"]
    assert task["patient"]["id"] is None
    comment = json.loads(result[1].payload)["data"]
    assert "ana@example.org" in comment["body"]


def test_response_identical_whether_or_not_patient_exists(
    wired: dict, cache: Any
) -> None:
    wired["patient"] = "REAL"
    matched = _response(_api(headers=SAME_ORIGIN, body=_body()).book())
    cache.data.clear()
    wired["patient"] = None
    unmatched = _response(_api(headers=SAME_ORIGIN, body=_body()).book())
    assert matched.status_code == unmatched.status_code == HTTPStatus.ACCEPTED
    assert matched.content == unmatched.content
    assert matched.headers == unmatched.headers
    assert json.loads(matched.content) == public_api.RECEIVED_BODY


@pytest.mark.parametrize("patient", ["REAL", None])
def test_slot_is_held_for_both_outcomes(wired: dict, patient: Any) -> None:
    wired["patient"] = patient
    _api(headers=SAME_ORIGIN, body=_body()).book()
    assert _json_of(_api().slots()) == {"slots": []}
    again = _api(
        headers={**SAME_ORIGIN, "X-Forwarded-For": "9.9.9.9"},
        body=_body(email="b@example.org"),
    )
    assert _response(again.book()).status_code == HTTPStatus.CONFLICT


def test_book_response_contains_no_request_details(wired: dict) -> None:
    wired["patient"] = "REAL"
    content = _response(_api(headers=SAME_ORIGIN, body=_body()).book()).content.decode()
    patient_id = str(wired["real_patient"].id)
    for secret_ish in (
        "Ana",
        "ana@example.org",
        "5551234567",
        "1990-04-01",
        patient_id,
    ):
        assert secret_ish not in content


def test_no_origin_header_still_rate_limited_and_validated(wired: dict) -> None:
    headers = {"Content-Type": "application/json"}
    result = _api(headers=headers, body=_body()).book()
    assert _response(result).status_code == HTTPStatus.ACCEPTED


def test_task_assigned_to_team_when_configured(wired: dict) -> None:
    secrets = {**ENABLED, "PUBLIC_BOOKING_TASK_TEAM_ID": "team-9"}
    result = _api(secrets=secrets, headers=SAME_ORIGIN, body=_body()).book()
    task = json.loads(result[0].payload)["data"]
    assert task["team"]["id"] == "team-9"
