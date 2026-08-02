"""Tests for remaining uncovered google_admin routes: dryrun-provider, reimport-all,
cancel-reimport-all, purge with chunked mode, provider_action lock conflict, and
provider_action error handling.
"""

from http import HTTPStatus
from types import SimpleNamespace

from gcal_sync.google.auth import GoogleAuthError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.routes.google_admin import GoogleCalendarAdminAPI, parse_provider_emails


def _api(secrets=None, staff_id="", body=None):
    api = GoogleCalendarAdminAPI.__new__(GoogleCalendarAdminAPI)
    api.secrets = secrets or {}
    api.request = SimpleNamespace(
        headers={"canvas-logged-in-user-id": staff_id}, json=lambda: (body or {})
    )
    return api


# --- parse_provider_emails -----------------------------------------------------------------------


def test_parse_provider_emails_basic():
    csv = "Email,First,Last\njoe@x.com,Joe,Ryan\n\nbad-line\njane@x.com,Jane,Smith"
    result = parse_provider_emails(csv)
    assert result == ["joe@x.com", "jane@x.com"]


def test_parse_provider_emails_skips_header_row():
    csv = "email\njo@x.com"
    result = parse_provider_emails(csv)
    assert result == ["jo@x.com"]


# --- dryrun_one -----------------------------------------------------------------------------------


def test_dryrun_forbidden_for_non_admin():
    resp = _api({"ADMIN_STAFF_IDS": ""}, body={"staff_id": "14"}).dryrun_one()
    assert resp[0].status_code == HTTPStatus.FORBIDDEN


def test_dryrun_rejects_unenrolled(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = None
    resp = _api(
        {"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "99"}
    ).dryrun_one()
    assert resp[0].status_code == HTTPStatus.BAD_REQUEST


def test_dryrun_returns_stats_without_effects(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com", active=True
    )
    mocker.patch(
        "gcal_sync.routes.google_admin.reimport_provider",
        return_value=({"holds_created": 3, "holds_updated": 1}, ["WOULD_BE_EFFECT"]),
    )
    resp = _api(
        {"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"}
    ).dryrun_one()
    # Effects are discarded in dry_run; only JSON summary returned
    assert len(resp) == 1
    assert resp[0].status_code == HTTPStatus.OK


def test_dryrun_handles_error(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com", active=True
    )
    mocker.patch(
        "gcal_sync.routes.google_admin.reimport_provider",
        side_effect=GoogleApiError(500, "fail"),
    )
    resp = _api(
        {"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"}
    ).dryrun_one()
    assert resp[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE


# --- reimport_all ----------------------------------------------------------------------------------


def test_reimport_all_forbidden_for_non_admin():
    resp = _api({"ADMIN_STAFF_IDS": ""}).reimport_all()
    assert resp[0].status_code == HTTPStatus.FORBIDDEN


def test_reimport_all_queues_and_returns_stats(mocker):
    mocker.patch("gcal_sync.routes.google_admin.enqueue_fleet_reimport", return_value=5)
    mocker.patch("gcal_sync.routes.google_admin.reimport_queue_depth", return_value=5)
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").reimport_all()
    assert resp[0].status_code == HTTPStatus.OK


# --- cancel_reimport_all --------------------------------------------------------------------------


def test_cancel_reimport_all_forbidden_for_non_admin():
    resp = _api({"ADMIN_STAFF_IDS": ""}).cancel_reimport_all()
    assert resp[0].status_code == HTTPStatus.FORBIDDEN


def test_cancel_reimport_all_clears_queue(mocker):
    mocker.patch("gcal_sync.routes.google_admin.cancel_fleet_reimport", return_value=3)
    mocker.patch("gcal_sync.routes.google_admin.reimport_queue_depth", return_value=0)
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").cancel_reimport_all()
    assert resp[0].status_code == HTTPStatus.OK


# --- purge with chunked mode ----------------------------------------------------------------------


def test_purge_chunked_mode(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com"
    )
    mocker.patch(
        "gcal_sync.routes.google_admin.purge_holds_chunk",
        return_value=(["C1"], "last-id", False),
    )
    resp = _api(
        {"ADMIN_STAFF_IDS": "id1"},
        staff_id="id1",
        body={"staff_id": "14", "limit": 50, "after_id": ""},
    ).purge_one()
    # Effects + JSON
    assert "C1" in resp
    assert resp[-1].status_code == HTTPStatus.OK


# --- provider_action lock conflict ----------------------------------------------------------------


def test_provider_action_lock_conflict_returns_409(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com"
    )
    mocker.patch("gcal_sync.routes.google_admin.acquire_provider_lock", return_value=False)
    resp = _api(
        {"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"}
    ).reconcile_one()
    assert resp[0].status_code == HTTPStatus.CONFLICT


# --- provider_action error handling ---------------------------------------------------------------


def test_provider_action_error_returns_503(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com"
    )
    mocker.patch("gcal_sync.routes.google_admin.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.routes.google_admin.release_provider_lock")
    mocker.patch(
        "gcal_sync.routes.google_admin.reconcile_provider",
        side_effect=GoogleAuthError("auth fail"),
    )
    resp = _api(
        {"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"}
    ).reconcile_one()
    assert resp[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE


# --- auto_map forbidden ---------------------------------------------------------------------------


def test_auto_map_forbidden_for_non_admin():
    resp = _api({"ADMIN_STAFF_IDS": ""}).auto_map()
    assert resp[0].status_code == HTTPStatus.FORBIDDEN
