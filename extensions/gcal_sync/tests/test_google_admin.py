"""Tests for the admin API: fail-closed authorization and the mapping/auto-map/provider routes.

The handler is instantiated bare (``__new__``) with ``secrets`` and a fake ``request`` set directly,
since the route methods only read those two. Models and channel-opening are mocked.
"""

from http import HTTPStatus
from types import SimpleNamespace

from gcal_sync.routes.google_admin import GoogleCalendarAdminAPI


def _api(secrets=None, staff_id="", body=None):
    api = GoogleCalendarAdminAPI.__new__(GoogleCalendarAdminAPI)
    api.secrets = secrets or {}
    api.request = SimpleNamespace(
        headers={"canvas-logged-in-user-id": staff_id}, json=lambda: (body or {})
    )
    return api


# --- authorization: fails closed ----------------------------------------------------------------

def test_is_admin_denies_when_list_unset():
    # Empty ADMIN_STAFF_IDS must deny everyone, even with a logged-in id present.
    assert _api({"ADMIN_STAFF_IDS": ""}, staff_id="abc")._is_admin() is False


def test_is_admin_denies_unlisted_staff():
    assert _api({"ADMIN_STAFF_IDS": "id1,id2"}, staff_id="other")._is_admin() is False


def test_is_admin_allows_listed_staff():
    assert _api({"ADMIN_STAFF_IDS": "id1, id2"}, staff_id="id2")._is_admin() is True


# --- index renders a readable notice for non-admins (never blank, never 500) --------------------

def test_index_non_admin_returns_html_200():
    resp = _api({"ADMIN_STAFF_IDS": ""}, staff_id="abc").index()
    assert len(resp) == 1
    assert resp[0].status_code == HTTPStatus.OK


# --- save_mapping -------------------------------------------------------------------------------

def test_save_mapping_forbidden_for_non_admin():
    resp = _api({"ADMIN_STAFF_IDS": ""}, body={"staff_id": "14"}).save_mapping()
    assert resp[0].status_code == HTTPStatus.FORBIDDEN


def test_save_mapping_requires_staff_id():
    api = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": ""})
    assert api.save_mapping()[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_mapping_requires_email_when_active():
    api = _api(
        {"ADMIN_STAFF_IDS": "id1"},
        staff_id="id1",
        body={"staff_id": "14", "calendar_email": "", "active": True},
    )
    assert api.save_mapping()[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_mapping_persists_and_opens_channel(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    mapping = SimpleNamespace(google_calendar_id="", active=False, save=mocker.Mock())
    scm.objects.get_or_create.return_value = (mapping, True)
    opened = mocker.patch.object(
        GoogleCalendarAdminAPI, "_open_channel_best_effort", return_value=None
    )
    api = _api(
        {"ADMIN_STAFF_IDS": "id1"},
        staff_id="id1",
        body={"staff_id": "14", "calendar_email": "j@r.com", "active": True},
    )
    resp = api.save_mapping()
    assert resp[0].status_code == HTTPStatus.OK
    assert mapping.google_calendar_id == "j@r.com"
    assert mapping.active is True
    mapping.save.assert_called_once()
    opened.assert_called_once_with("j@r.com")


# --- auto_map -----------------------------------------------------------------------------------

def test_auto_map_maps_with_email_and_reports_skips(mocker):
    mocker.patch.object(
        GoogleCalendarAdminAPI,
        "_schedulable_providers",
        return_value=[
            {"id": 1, "first_name": "A", "last_name": "B", "user__email": "a@x.com"},
            {"id": 2, "first_name": "C", "last_name": "D", "user__email": ""},
        ],
    )
    upsert = mocker.patch.object(GoogleCalendarAdminAPI, "_upsert_mapping")
    resp = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1").auto_map()
    assert resp[0].status_code == HTTPStatus.OK
    # Only the provider with an email is mapped; the other is skipped (reported, not guessed).
    upsert.assert_called_once_with("1", "a@x.com")


# --- per-provider actions (reconcile / re-import) -----------------------------------------------

def test_provider_action_rejects_unenrolled(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = None
    api = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "99"})
    assert api.reimport_one()[0].status_code == HTTPStatus.BAD_REQUEST


def test_reconcile_one_runs_for_enrolled_provider(mocker):
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com"
    )
    mocker.patch("gcal_sync.routes.google_admin.acquire_provider_lock", return_value=True)
    release = mocker.patch("gcal_sync.routes.google_admin.release_provider_lock")
    mocker.patch(
        "gcal_sync.routes.google_admin.reconcile_provider",
        return_value=({"pushed": 1, "blocks_pushed": 0, "blocks_deleted": 0}, ["E"]),
    )
    api = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"})
    resp = api.reconcile_one()
    # effects are applied alongside the JSON summary.
    assert resp[-1].status_code == HTTPStatus.OK
    release.assert_called_once_with("j@r.com")  # lock released after the action


def test_provider_action_conflicts_when_lock_held(mocker):
    # A double-click / second admin: the lock is already held -> 409, and the action never runs.
    scm = mocker.patch("gcal_sync.routes.google_admin.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="j@r.com"
    )
    mocker.patch("gcal_sync.routes.google_admin.acquire_provider_lock", return_value=False)
    action = mocker.patch("gcal_sync.routes.google_admin.reimport_provider")
    api = _api({"ADMIN_STAFF_IDS": "id1"}, staff_id="id1", body={"staff_id": "14"})
    resp = api.reimport_one()
    assert resp[0].status_code == HTTPStatus.CONFLICT
    action.assert_not_called()
