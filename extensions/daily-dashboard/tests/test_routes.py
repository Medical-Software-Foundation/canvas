"""Tests for the dashboard SimpleAPI routes.

Routes are exercised by constructing the handler with a mock event and
injecting a fake request (``request`` is a cached_property, so assigning to the
instance __dict__ shadows it). Behaviour asserted: the data route returns the
board JSON, and the write routes validate input and emit the right effects.
"""

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import (
    PatientFactory,
    PracticeLocationFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.appointment import Appointment

from daily_dashboard.routes import dashboard_api as api


def _make_appt(patient: Any, provider: Any, location: Any, start_time: Any) -> Appointment:
    return Appointment.objects.create(
        patient=patient,
        provider=provider,
        location=location,
        start_time=start_time,
        duration_minutes=30,
        status=AppointmentProgressStatus.CONFIRMED,
        telehealth_instructions_sent=False,
    )


def _route(
    route_cls: Any,
    *,
    method: str = "GET",
    body: Any = None,
    query: Any = None,
    headers: Any = None,
    secrets: Any = None,
) -> Any:
    event = Mock()
    event.context = {"method": method, "path": route_cls.PATH}
    handler = route_cls(event=event, secrets=secrets or {})
    handler.__dict__["request"] = SimpleNamespace(
        json=lambda: (body or {}),
        query_params=query or {},
        headers=headers or {},
        path=route_cls.PATH,
        method=method,
    )
    return handler


def _status(resp: Any) -> Any:
    return getattr(resp, "status_code", None)


@pytest.mark.django_db
def test_data_route_returns_board_json() -> None:
    patient = PatientFactory()
    _make_appt(patient, StaffFactory(), PracticeLocationFactory(), datetime.now(dt_timezone.utc))

    route = _route(
        api.DashboardDataRoute,
        query={"scope": "all"},
        headers={"canvas-logged-in-user-id": "staff-1"},
        secrets={"CLINIC_TIMEZONE": "UTC", "CUSTOMER_IDENTIFIER": "example"},
    )
    result = route.get()
    assert len(result) == 1
    assert int(_status(result[0])) == 200


@pytest.mark.django_db
def test_outreach_route_validates_and_emits_effect() -> None:
    patient = PatientFactory()

    # Missing patient_id -> 400.
    bad = _route(api.OutreachRoute, method="POST", body={"channel": "Fax", "recipient_type": "PCP"})
    assert int(_status(bad.post()[0])) == 400

    # Invalid channel -> 400.
    bad_channel = _route(
        api.OutreachRoute, method="POST",
        body={"patient_id": str(patient.id), "channel": "Smoke", "recipient_type": "PCP"},
    )
    assert int(_status(bad_channel.post()[0])) == 400

    # Valid -> [effect, 200].
    ok = _route(
        api.OutreachRoute, method="POST",
        body={"patient_id": str(patient.id), "channel": "Fax", "recipient_type": "PCP",
              "recipient": "Dr. Smith", "outcome": "Sent", "note": "x"},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    result = ok.post()
    assert len(result) == 2
    assert EffectType.Name(result[0].type) == "UPSERT_PATIENT_METADATA"
    assert int(_status(result[1])) == 200


@pytest.mark.django_db
def test_readiness_override_route() -> None:
    patient = PatientFactory()

    bad = _route(api.ReadinessOverrideRoute, method="POST",
                 body={"patient_id": str(patient.id), "category": "nope"})
    assert int(_status(bad.post()[0])) == 400

    ok = _route(api.ReadinessOverrideRoute, method="POST",
                body={"patient_id": str(patient.id), "category": "auth", "complete": True})
    result = ok.post()
    assert EffectType.Name(result[0].type) == "UPSERT_PATIENT_METADATA"
    assert int(_status(result[1])) == 200


@pytest.mark.django_db
def test_create_task_route() -> None:
    patient = PatientFactory()

    # Missing title -> 400.
    bad = _route(api.CreateTaskRoute, method="POST", body={"patient_id": str(patient.id)})
    assert int(_status(bad.post()[0])) == 400

    # Invalid due date -> 400.
    bad_due = _route(api.CreateTaskRoute, method="POST",
                     body={"patient_id": str(patient.id), "title": "X", "due": "not-a-date"})
    assert int(_status(bad_due.post()[0])) == 400

    # Valid with due date -> [effect, 200].
    ok = _route(api.CreateTaskRoute, method="POST",
                body={"patient_id": str(patient.id), "title": "Chase referral", "due": "2026-06-30"})
    result = ok.post()
    assert "TASK" in EffectType.Name(result[0].type)
    assert int(_status(result[1])) == 200


@pytest.mark.django_db
def test_staff_display_name_helper() -> None:
    assert api._staff_display_name(None) == "Unknown user"
    assert api._staff_display_name("does-not-exist") == "Unknown user"
    staff = StaffFactory(first_name="Maria", last_name="Torres")
    assert "Maria" in api._staff_display_name(str(staff.id))


def test_asset_and_chart_route_paths() -> None:
    assert api.DashboardIndexRoute.PATH == "/app"
    assert api.DashboardDataRoute.PATH == "/app/data"
    assert api.OutreachRoute.PATH == "/app/outreach"
    assert api.ReadinessOverrideRoute.PATH == "/app/readiness"
    assert api.CreateTaskRoute.PATH == "/app/task"


def test_asset_routes_render(monkeypatch: pytest.MonkeyPatch) -> None:
    # render_to_string needs the live plugin context; stub it so the routes'
    # Response-wrapping (status + content_type) is what gets exercised.
    monkeypatch.setattr(api, "render_to_string", lambda *a, **k: "stub")

    index = _route(api.DashboardIndexRoute).get()
    assert int(_status(index[0])) == 200

    css = _route(api.DashboardStylesRoute).get()
    assert int(_status(css[0])) == 200
    assert css[0].headers.get("Content-Type") == "text/css"

    js = _route(api.DashboardScriptRoute).get()
    assert int(_status(js[0])) == 200
    assert js[0].headers.get("Content-Type") == "application/javascript"


@pytest.mark.django_db
def test_outreach_route_invalid_recipient_type() -> None:
    patient = PatientFactory()
    bad = _route(
        api.OutreachRoute, method="POST",
        body={"patient_id": str(patient.id), "channel": "Fax", "recipient_type": "Nope"},
    )
    assert int(_status(bad.post()[0])) == 400


def test_readiness_override_route_missing_patient() -> None:
    bad = _route(api.ReadinessOverrideRoute, method="POST", body={"category": "auth"})
    assert int(_status(bad.post()[0])) == 400


def test_create_task_route_missing_patient() -> None:
    bad = _route(api.CreateTaskRoute, method="POST", body={"title": "X"})
    assert int(_status(bad.post()[0])) == 400


def test_task_action_route_invalid_due() -> None:
    bad = _route(api.TaskActionRoute, method="POST",
                 body={"task_id": "t1", "due": "not-a-date"})
    assert int(_status(bad.post()[0])) == 400


@pytest.mark.django_db
def test_prep_route_stages_prompt() -> None:
    patient = PatientFactory()

    # Missing patient_id -> 400.
    bad = _route(api.PrepRoute, method="POST", body={})
    assert int(_status(bad.post()[0])) == 400

    # Valid -> [UPSERT_PATIENT_METADATA, 200]; a configured prompt is honored.
    ok = _route(
        api.PrepRoute, method="POST",
        body={"patient_id": str(patient.id)},
        secrets={"ASSISTANT_PREP_PROMPT": "Custom prep prompt"},
    )
    result = ok.post()
    assert EffectType.Name(result[0].type) == "UPSERT_PATIENT_METADATA"
    assert int(_status(result[1])) == 200


@pytest.mark.django_db
def test_task_action_route() -> None:
    # Missing task_id -> 400.
    assert int(_status(_route(api.TaskActionRoute, method="POST", body={}).post()[0])) == 400
    # Only task_id, nothing to change -> 400.
    nothing = _route(api.TaskActionRoute, method="POST", body={"task_id": "t1"})
    assert int(_status(nothing.post()[0])) == 400
    # Status update -> [UPDATE_TASK, 200].
    upd = _route(api.TaskActionRoute, method="POST", body={"task_id": "t1", "status": "COMPLETED"})
    r = upd.post()
    assert EffectType.Name(r[0].type) == "UPDATE_TASK"
    assert int(_status(r[1])) == 200
    # Comment only -> [CREATE_TASK_COMMENT, 200].
    cmt = _route(api.TaskActionRoute, method="POST", body={"task_id": "t1", "comment": "hi"})
    r2 = cmt.post()
    assert EffectType.Name(r2[0].type) == "CREATE_TASK_COMMENT"
    assert int(_status(r2[1])) == 200
