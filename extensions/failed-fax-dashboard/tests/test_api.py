import json
from types import SimpleNamespace

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import FaxFactory, StaffFactory, TeamFactory

from failed_fax_dashboard.api.dashboard_api import CACHE_BUST, PAGE_URL, FailedFaxDashboardAPI
from failed_fax_dashboard.applications.fax_dashboard_app import FailedFaxDashboardApp
from failed_fax_dashboard.models import FaxDismissal
from tests.conftest import CallApi
from tests.helpers import make_event

pytestmark = pytest.mark.django_db

RESTRICTED = {"FAX_DASHBOARD_STAFF_IDS": "staff-1"}

GET_PATHS = [
    "/index",
    "/styles.css",
    "/app.js",
    "/failures",
    "/resend-prefill",
    "/task-options",
]
POST_PATHS = ["/resend", "/task", "/dismiss"]


def test_open_by_default_serves_the_page(call_api: CallApi) -> None:
    status, html, _ = call_api("GET", "/index")

    assert status == 200
    assert "Failed faxes" in html
    assert f"/plugin-io/api/failed_fax_dashboard/app/app.js?v={CACHE_BUST}" in html
    assert f"/plugin-io/api/failed_fax_dashboard/app/styles.css?v={CACHE_BUST}" in html


def test_assets_are_served_with_their_content_types(call_api: CallApi) -> None:
    css_status, css, _ = call_api("GET", "/styles.css")
    js_status, js, _ = call_api("GET", "/app.js")

    assert css_status == 200 and ".overlay" in css
    assert js_status == 200 and "use strict" in js


def test_listed_staff_can_open_the_page(call_api: CallApi) -> None:
    status, html, _ = call_api("GET", "/index", secrets=RESTRICTED, staff_id="staff-1")

    assert status == 200
    assert "Failed faxes" in html


def test_unlisted_staff_gets_a_not_authorized_page(call_api: CallApi) -> None:
    status, html, _ = call_api("GET", "/index", secrets=RESTRICTED, staff_id="staff-2")

    assert status == 403
    assert "Not authorized" in html


@pytest.mark.parametrize("path", GET_PATHS[1:])
def test_unlisted_staff_gets_403_on_every_get_route(call_api: CallApi, path: str) -> None:
    status, body, effects = call_api("GET", path, secrets=RESTRICTED, staff_id="staff-2")

    assert status == 403
    assert effects == []
    if path not in ("/styles.css", "/app.js"):
        assert body == {"error": "Not authorized"}


@pytest.mark.parametrize("path", POST_PATHS)
def test_unlisted_staff_gets_403_on_every_post_route(call_api: CallApi, path: str) -> None:
    status, body, effects = call_api("POST", path, body={}, secrets=RESTRICTED, staff_id="staff-2")

    assert status == 403
    assert body == {"error": "Not authorized"}
    assert effects == []


@pytest.mark.parametrize(("method", "path"), [("GET", p) for p in GET_PATHS] + [("POST", p) for p in POST_PATHS])
def test_patient_sessions_are_rejected_before_any_route_runs(call_api: CallApi, method: str, path: str) -> None:
    status, body, _ = call_api(
        method, path, body={}, user_type="Patient", event_type=EventType.SIMPLE_API_AUTHENTICATE
    )

    assert status == 401


def test_staff_sessions_pass_authentication(call_api: CallApi) -> None:
    status, _, _ = call_api("GET", "/failures", event_type=EventType.SIMPLE_API_AUTHENTICATE)

    assert status == 200


def test_failures_endpoint_returns_rows_and_honors_paging(call_api: CallApi) -> None:
    make_event("note", age_days=2)
    make_event("referral", age_days=1)

    status, body, _ = call_api("GET", "/failures", query="page=2&page_size=1")

    assert status == 200
    assert body["total"] == 2
    assert body["page"] == 2
    assert [row["type"] for row in body["rows"]] == ["note"]


def test_failures_endpoint_ignores_garbage_paging(call_api: CallApi) -> None:
    make_event("note")

    status, body, _ = call_api("GET", "/failures", query="page=abc&page_size=")

    assert status == 200
    assert body["page"] == 1
    assert body["page_size"] == 25


def test_resend_prefill_endpoint(call_api: CallApi) -> None:
    event = make_event("note", number="+15555550100")

    status, body, _ = call_api("GET", "/resend-prefill", query=f"event_id={event.id}")

    assert status == 200
    assert body == {"fax_number": "+15555550100", "recipient_name": ""}


def test_resend_prefill_endpoint_reports_errors(call_api: CallApi) -> None:
    status, body, _ = call_api("GET", "/resend-prefill", query="event_id=nope")

    assert status == 400
    assert body == {"error": "Invalid id"}


def test_resend_returns_the_fax_effect(call_api: CallApi) -> None:
    event = make_event("note")

    status, body, effects = call_api(
        "POST",
        "/resend",
        body={"event_id": str(event.id), "recipient_name": "Dr. Ada", "recipient_fax_number": "+15555550123"},
    )

    assert status == 200
    assert body == {"ok": True}
    assert [effect.type for effect in effects] == [EffectType.FAX_NOTE]
    assert json.loads(effects[0].payload)["data"]["note_id"] == str(event.note.id)


def test_resend_validation_error_returns_400_and_no_effect(call_api: CallApi) -> None:
    event = make_event("note")

    status, body, effects = call_api(
        "POST", "/resend", body={"event_id": str(event.id), "recipient_name": "", "recipient_fax_number": "1"}
    )

    assert status == 400
    assert body == {"error": "Recipient name is required"}
    assert effects == []


def test_task_options_endpoint(call_api: CallApi) -> None:
    StaffFactory.create()
    TeamFactory.create()

    status, body, _ = call_api("GET", "/task-options")

    assert status == 200
    assert len(body["staff"]) == 1
    assert len(body["teams"]) == 1


def test_create_task_is_authored_by_the_logged_in_staff(call_api: CallApi) -> None:
    event = make_event("referral")
    assignee = StaffFactory.create()

    status, body, effects = call_api(
        "POST",
        "/task",
        staff_id="clicking-staff",
        body={
            "source_type": "referral",
            "source_id": str(event.id),
            "assignee_type": "staff",
            "assignee_id": assignee.id,
            "title": "Follow up",
        },
    )

    assert status == 200
    assert body == {"ok": True}
    assert [effect.type for effect in effects] == [EffectType.CREATE_TASK]
    assert json.loads(effects[0].payload)["data"]["author_id"] == "clicking-staff"


def test_create_task_validation_error(call_api: CallApi) -> None:
    status, body, effects = call_api("POST", "/task", body={"source_type": "note", "title": ""})

    assert status == 400
    assert body == {"error": "Title is required"}
    assert effects == []


def test_dismiss_endpoint_records_the_staff_member(call_api: CallApi) -> None:
    failed = FaxFactory.create(direction="I", success=False)

    status, body, effects = call_api(
        "POST",
        "/dismiss",
        staff_id="dismisser",
        body={"source_type": "received_fax", "source_id": str(failed.id)},
    )

    assert status == 200
    assert body == {"ok": True}
    assert effects == []
    assert FaxDismissal.objects.get().dismissed_by == "dismisser"


def test_dismiss_endpoint_validation_error(call_api: CallApi) -> None:
    status, body, _ = call_api("POST", "/dismiss", body={"source_type": "bogus"})

    assert status == 400
    assert body == {"error": "Unknown item type"}


def test_malformed_and_non_object_bodies_are_rejected_cleanly(call_api: CallApi) -> None:
    bad_status, bad_body, _ = call_api("POST", "/dismiss", raw_body=b"{not json")
    list_status, list_body, _ = call_api("POST", "/dismiss", body=[1, 2])

    assert bad_status == 400
    assert bad_body == {"error": "Request body must be valid JSON"}
    assert list_status == 400
    assert list_body == {"error": "Unknown item type"}


def test_unknown_route_is_not_handled() -> None:
    event = SimpleNamespace(
        type=EventType.SIMPLE_API_REQUEST,
        context={"method": "GET", "path": "/app/other"},
    )

    tested = FailedFaxDashboardAPI(event).accept_event()

    assert tested is False


def test_application_opens_the_dashboard_page() -> None:
    event = SimpleNamespace(type=EventType.APPLICATION__ON_OPEN, target=SimpleNamespace(id="x"))

    effect = FailedFaxDashboardApp(event).on_open()

    assert not isinstance(effect, list)

    data = json.loads(effect.payload)["data"]
    assert data["url"] == f"{PAGE_URL}?v={CACHE_BUST}"
    assert data["target"] == "page"
    assert data["title"] == "Failed faxes"
