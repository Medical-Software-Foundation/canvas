"""Tests for the remaining admin API routes/helpers: bulk-import, reconcile-all, channel-open,
schedulable providers, upsert, page context, and the admin index render path."""

from http import HTTPStatus
from types import SimpleNamespace

from gcal_sync.channels import ChannelConfigError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.routes.google_admin import GoogleCalendarAdminAPI


def _api(secrets=None, staff_id="", body=None):
    api = GoogleCalendarAdminAPI.__new__(GoogleCalendarAdminAPI)
    api.secrets = secrets or {}
    api.request = SimpleNamespace(
        headers={"canvas-logged-in-user-id": staff_id}, json=lambda: (body or {})
    )
    return api


# --- bulk import --------------------------------------------------------------------------------

def test_bulk_import_forbidden():
    assert _api({"ADMIN_STAFF_IDS": ""}, body={"csv": "x"}).bulk_import()[0].status_code == HTTPStatus.FORBIDDEN


def test_bulk_import_no_emails_is_bad_request():
    api = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"csv": ""})
    assert api.bulk_import()[0].status_code == HTTPStatus.BAD_REQUEST


def test_bulk_import_matches_known_and_reports_unmatched(mocker):
    staff = mocker.patch("gcal_sync.routes.google_admin.Staff")
    staff.objects.filter.return_value.values.return_value = [{"id": 14, "user__email": "j@r.com"}]
    upsert = mocker.patch.object(GoogleCalendarAdminAPI, "_upsert_mapping")
    api = _api(
        {"ADMIN_STAFF_IDS": "id1"},
        staff_id="id1",
        body={"csv": "Email\nj@r.com,Joe,Ryan\nx@y.com,X,Y"},
    )
    resp = api.bulk_import()
    assert resp[0].status_code == HTTPStatus.OK
    upsert.assert_called_once_with("14", "j@r.com")


# --- reconcile (all) ----------------------------------------------------------------------------

def test_purge_forbidden_for_non_admin():
    assert _api({"ADMIN_STAFF_IDS": ""}, body={"staff_id": "14"}).purge_one()[0].status_code == HTTPStatus.FORBIDDEN


def test_purge_rejects_provider_without_mapping(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = None
    api = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "99"})
    assert api.purge_one()[0].status_code == HTTPStatus.BAD_REQUEST


def test_purge_cancels_and_reports_count(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com"
    )
    mocker.patch(
        "gcal_sync.routes.google_admin.reset_inbound_for_provider", return_value=["C1", "C2"]
    )
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"}).purge_one()
    # cancel effects applied, plus a JSON summary with the purged count
    assert "C1" in resp and "C2" in resp
    assert resp[-1].status_code == HTTPStatus.OK


def test_reconcile_all_route_forbidden():
    assert _api({"ADMIN_STAFF_IDS": ""}).reconcile()[0].status_code == HTTPStatus.FORBIDDEN


def test_reconcile_all_route_applies_effects(mocker):
    mocker.patch(
        "gcal_sync.routes.google_admin.reconcile_all",
        return_value=({"pushed": 3, "mappings": 1}, ["E"]),
    )
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").reconcile()
    assert "E" in resp
    assert resp[-1].status_code == HTTPStatus.OK


def test_reconcile_all_route_handles_failure(mocker):
    mocker.patch(
        "gcal_sync.routes.google_admin.reconcile_all", side_effect=GoogleApiError(500, "x")
    )
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").reconcile()
    assert resp[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE


# --- channel open helper ------------------------------------------------------------------------

def test_open_channel_best_effort_success(mocker):
    cm = mocker.patch("gcal_sync.routes.google_admin.ChannelManager")
    assert _api({})._open_channel_best_effort("j@r.com") is None
    cm.return_value.open_channel.assert_called_once_with("j@r.com")


def test_open_channel_best_effort_returns_warning_on_failure(mocker):
    cm = mocker.patch("gcal_sync.routes.google_admin.ChannelManager")
    cm.return_value.open_channel.side_effect = ChannelConfigError("no token")
    warning = _api({})._open_channel_best_effort("j@r.com")
    assert warning and "could not be opened" in warning


# --- static helpers -----------------------------------------------------------------------------

def test_schedulable_providers(mocker):
    staff = mocker.patch("gcal_sync.routes.google_admin.Staff")
    staff.objects.filter.return_value.values.return_value.distinct.return_value.order_by.return_value = [
        {"id": 1}
    ]
    assert GoogleCalendarAdminAPI._schedulable_providers() == [{"id": 1}]


def test_upsert_mapping_sets_active(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    m = SimpleNamespace(google_calendar_id="", active=False, save=mocker.Mock())
    scm.objects.get_or_create.return_value = (m, True)
    GoogleCalendarAdminAPI._upsert_mapping("14", "j@r.com")
    assert m.google_calendar_id == "j@r.com"
    assert m.active is True
    m.save.assert_called_once()


def test_latest_channel_by_calendar_keeps_newest(mocker):
    wc = mocker.patch("gcal_sync.routes.google_admin.WatchChannel")
    ch = SimpleNamespace(google_calendar_id="c1", expiration="x")
    wc.objects.all.return_value.order_by.return_value = [ch]
    assert GoogleCalendarAdminAPI._latest_channel_by_calendar()["c1"] is ch


def test_page_context_builds_rows(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.all.return_value = [
        SimpleNamespace(canvas_staff_id="14", google_calendar_id="j@r.com", active=True)
    ]
    css = mocker.patch("gcal_sync.routes.google_admin.CalendarSyncState")
    css.objects.all.return_value = []
    staff = mocker.patch("gcal_sync.routes.google_admin.Staff")
    staff.objects.filter.return_value.values.return_value.order_by.return_value = [
        {"id": 14, "first_name": "Joe", "last_name": "Ryan", "user__email": "j@r.com"}
    ]
    mocker.patch.object(GoogleCalendarAdminAPI, "_latest_channel_by_calendar", return_value={})
    ctx = _api(staff_id="id1")._page_context()
    row = ctx["providers"][0]
    assert row["name"] == "Joe Ryan"
    assert row["active"] is True


# --- index render -------------------------------------------------------------------------------

def test_index_renders_for_admin(mocker):
    mocker.patch("gcal_sync.routes.google_admin.render_to_string", return_value="<html>ok</html>")
    mocker.patch.object(GoogleCalendarAdminAPI, "_page_context", return_value={"providers": []})
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").index()
    assert resp[0].status_code == HTTPStatus.OK


def test_index_render_failure_shows_notice_not_500(mocker):
    mocker.patch(
        "gcal_sync.routes.google_admin.render_to_string", side_effect=Exception("template boom")
    )
    mocker.patch.object(GoogleCalendarAdminAPI, "_page_context", return_value={})
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").index()
    assert resp[0].status_code == HTTPStatus.OK  # readable notice, never blank/500
