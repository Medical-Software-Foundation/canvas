import json
from types import SimpleNamespace

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import FaxFactory, TaskFactory, TeamFactory

from failed_fax_dashboard.api.dashboard_api import CACHE_BUST, PAGE_URL, FailedFaxDashboardAPI
from failed_fax_dashboard.applications.fax_dashboard_app import FailedFaxDashboardApp
from failed_fax_dashboard.models import DashboardPreference, FaxDismissal, FaxResend
from tests.conftest import CallApi
from tests.helpers import make_alert, make_event, make_staff

pytestmark = pytest.mark.django_db

RESTRICTED = {"FAX_DASHBOARD_STAFF_IDS": "staff-1"}

GET_PATHS = ["/index", "/styles.css", "/app.js", "/failures", "/people"]
POST_PATHS = ["/resend", "/dismiss", "/restore", "/preferences", "/tasks/reassign", "/tasks/comment"]


def test_open_by_default_serves_the_page(call_api: CallApi) -> None:
    status, html, _ = call_api("GET", "/index")

    assert status == 200
    assert "Failed faxes" in html
    assert f"/plugin-io/api/failed_fax_dashboard/app/app.js?v={CACHE_BUST}" in html
    assert f"/plugin-io/api/failed_fax_dashboard/app/styles.css?v={CACHE_BUST}" in html
    assert "Mockup" not in html


def test_assets_are_served_with_their_content_types(call_api: CallApi) -> None:
    css_status, css, _ = call_api("GET", "/styles.css")
    js_status, js, _ = call_api("GET", "/app.js")

    assert css_status == 200 and ".contact-card" in css
    assert js_status == 200 and "use strict" in js
    assert "In the live version" not in js


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
    status, _, _ = call_api(
        method, path, body={}, user_type="Patient", event_type=EventType.SIMPLE_API_AUTHENTICATE
    )

    assert status == 401


def test_staff_sessions_pass_authentication(call_api: CallApi) -> None:
    status, _, _ = call_api("GET", "/failures", event_type=EventType.SIMPLE_API_AUTHENTICATE)

    assert status == 200


def test_failures_returns_the_requested_tab_filtered_sorted_and_paged(call_api: CallApi) -> None:
    staff = make_staff("Me", "Myself")
    old = make_event("note", age_days=3)
    make_event("referral", age_days=2)
    new = make_event("note", age_days=1)

    status, body, _ = call_api(
        "GET",
        "/failures",
        query="tab=sent&kinds=note&sort=when&dir=1&page=2&page_size=1",
        staff_id=staff.id,
    )

    assert status == 200
    assert [row["source_id"] for row in body["rows"]] == [str(new.id)]
    assert (body["page"], body["total_pages"], body["shown"]) == (2, 2, 2)
    assert body["totals"] == {"sent": 3, "received": 0}
    assert old.id


def test_failures_defaults_to_the_sent_tab_and_ignores_garbage(call_api: CallApi) -> None:
    make_event("note")

    status, body, _ = call_api("GET", "/failures", query="tab=other&page=abc&page_size=")

    assert status == 200
    assert body["tab"] == "sent"
    assert (body["page"], body["page_size"]) == (1, 25)


def test_failures_received_tab(call_api: CallApi) -> None:
    FaxFactory.create(direction="I", success=False)

    status, body, _ = call_api("GET", "/failures", query="tab=received")

    assert status == 200
    assert [row["direction"] for row in body["rows"]] == ["received"]


def test_people_lists_active_staff_and_teams_as_picker_values(call_api: CallApi) -> None:
    active = make_staff("Dana", "Whitfield")
    make_staff("Gone", "Away", active=False)
    team = TeamFactory.create(name="Front Desk")

    status, body, _ = call_api("GET", "/people")

    assert status == 200
    assert body == {
        "teams": [{"value": f"team:{team.id}", "name": "Front Desk"}],
        "staff": [{"value": f"staff:{active.id}", "name": "Dana Whitfield"}],
    }


def test_preferences_save_load_and_reset(call_api: CallApi) -> None:
    staff = make_staff()
    event = make_event("note", age_days=2)
    make_event("note", age_days=1)
    views = {"sent": {"sort": {"key": "when", "dir": 1}, "q": "note"}}

    save_status, save_body, _ = call_api("POST", "/preferences", body={"views": views}, staff_id=staff.id)
    _, loaded, _ = call_api("GET", "/failures", query="saved=1", staff_id=staff.id)
    reset_status, reset_body, _ = call_api("POST", "/preferences", body={"reset": True}, staff_id=staff.id)
    _, after, _ = call_api("GET", "/failures", query="saved=1", staff_id=staff.id)

    assert (save_status, save_body) == (200, {"ok": True})
    assert loaded["rows"][0]["source_id"] == str(event.id)
    assert loaded["view"]["q"] == "note"
    assert (reset_status, reset_body) == (200, {"ok": True})
    assert DashboardPreference.objects.count() == 0
    assert after["view"]["q"] == ""


def test_preferences_for_a_session_that_is_not_a_staff_record(call_api: CallApi) -> None:
    status, body, _ = call_api("POST", "/preferences", body={"views": {}}, staff_id="nobody")

    assert status == 403
    assert body == {"error": "Staff member not found"}


def test_preferences_rejects_malformed_json(call_api: CallApi) -> None:
    status, body, _ = call_api("POST", "/preferences", raw_body=b"{nope")

    assert status == 400
    assert body == {"error": "Request body must be valid JSON"}


def test_resend_returns_the_fax_effect_and_remembers_the_clicker(call_api: CallApi) -> None:
    staff = make_staff()
    event = make_event("note")

    status, body, effects = call_api(
        "POST",
        "/resend",
        staff_id=staff.id,
        body={"event_id": str(event.id), "recipient_name": "Dr. Ada", "recipient_fax_number": "+15555550123"},
    )

    assert status == 200
    assert body == {"ok": True}
    assert [effect.type for effect in effects] == [EffectType.FAX_NOTE]
    assert json.loads(effects[0].payload)["data"]["note_id"] == str(event.note.id)
    assert FaxResend.objects.get().staff_id == staff.dbid


def test_resend_validation_error_returns_400_and_no_effect(call_api: CallApi) -> None:
    staff = make_staff()
    event = make_event("note")

    status, body, effects = call_api(
        "POST", "/resend", staff_id=staff.id,
        body={"event_id": str(event.id), "recipient_name": "", "recipient_fax_number": "1"},
    )

    assert status == 400
    assert body == {"error": "Recipient name is required"}
    assert effects == []


def test_reassign_and_comment_are_authored_by_the_logged_in_staff(call_api: CallApi) -> None:
    clicker = make_staff("Dana", "Whitfield")
    target = make_staff("Cy", "Clark")
    task = TaskFactory.create()
    make_alert(make_event("note"), "note", task)

    status, body, effects = call_api(
        "POST", "/tasks/reassign", staff_id=clicker.id,
        body={"task_id": str(task.id), "assignee": f"staff:{target.id}"},
    )
    comment_status, _, comment_effects = call_api(
        "POST", "/tasks/comment", staff_id=clicker.id, body={"task_id": str(task.id), "body": "Called them"}
    )

    assert (status, body) == (200, {"ok": True})
    assert [effect.type for effect in effects] == [EffectType.UPDATE_TASK, EffectType.CREATE_TASK_COMMENT]
    assert json.loads(effects[1].payload)["data"]["author_id"] == clicker.id
    assert comment_status == 200
    assert json.loads(comment_effects[0].payload)["data"]["author_id"] == clicker.id


def test_reassign_and_comment_errors(call_api: CallApi) -> None:
    clicker = make_staff()
    task = TaskFactory.create()

    reassign = call_api("POST", "/tasks/reassign", staff_id=clicker.id, body={"task_id": str(task.id), "assignee": "staff:x"})
    comment = call_api("POST", "/tasks/comment", staff_id=clicker.id, body={"task_id": str(task.id), "body": "hi"})

    assert (reassign[0], reassign[1], reassign[2]) == (404, {"error": "Task not found"}, [])
    assert (comment[0], comment[1], comment[2]) == (404, {"error": "Task not found"}, [])


def test_dismiss_and_restore_endpoints_record_the_staff_member(call_api: CallApi) -> None:
    staff = make_staff("Dana", "Whitfield")
    failed = FaxFactory.create(direction="I", success=False)
    keys = {"keys": [f"received_fax:{failed.id}"]}

    dismissed = call_api("POST", "/dismiss", staff_id=staff.id, body=keys)
    assert dismissed == (200, {"ok": True}, [])
    assert FaxDismissal.objects.get().dismissed_by == staff.id

    restored = call_api("POST", "/restore", staff_id=staff.id, body=keys)
    assert restored == (200, {"ok": True}, [])
    assert FaxDismissal.objects.count() == 0


def test_dismiss_endpoint_validation_error(call_api: CallApi) -> None:
    staff = make_staff()
    status, body, _ = call_api("POST", "/dismiss", staff_id=staff.id, body={"keys": ["bogus:1"]})

    assert status == 400
    assert body == {"error": "Unknown item type"}


def test_malformed_and_non_object_bodies_are_rejected_cleanly(call_api: CallApi) -> None:
    bad_status, bad_body, _ = call_api("POST", "/dismiss", raw_body=b"{not json")
    list_status, list_body, _ = call_api("POST", "/dismiss", body=[1, 2])

    assert bad_status == 400
    assert bad_body == {"error": "Request body must be valid JSON"}
    assert list_status == 400
    assert list_body == {"error": "Choose at least one row"}


def test_removed_routes_are_gone(call_api: CallApi) -> None:
    for method, path in (("POST", "/task"), ("GET", "/task-options"), ("GET", "/resend-prefill")):
        event = SimpleNamespace(type=EventType.SIMPLE_API_REQUEST, context={"method": method, "path": f"/app{path}"})
        assert FailedFaxDashboardAPI(event).accept_event() is False


def test_unknown_route_is_not_handled() -> None:
    event = SimpleNamespace(type=EventType.SIMPLE_API_REQUEST, context={"method": "GET", "path": "/app/other"})

    assert FailedFaxDashboardAPI(event).accept_event() is False


def test_application_opens_the_dashboard_page() -> None:
    event = SimpleNamespace(type=EventType.APPLICATION__ON_OPEN, target=SimpleNamespace(id="x"))

    effect = FailedFaxDashboardApp(event).on_open()

    assert not isinstance(effect, list)

    data = json.loads(effect.payload)["data"]
    assert data["url"] == f"{PAGE_URL}?v={CACHE_BUST}"
    assert data["target"] == "page"
    assert data["title"] == "Failed faxes"
