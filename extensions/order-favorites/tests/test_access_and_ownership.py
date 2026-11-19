"""Who is an admin, what non-admins can't do, and who can change which favorites."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from order_favorites.handlers.admin_app import OrderFavoritesApp
from order_favorites.models import Favorite, FavoritesAdmin, HiddenFavorite
from order_favorites.services.access import is_admin
from tests.conftest import make_api, reply
from tests.helpers import favorite, rx_body

ADMIN_ROUTES = [
    ("admin_data", {}),
    ("admin_create", {}),
    ("admin_update", {"favorite_id": "1"}),
    ("admin_delete", {"favorite_id": "1"}),
    ("admin_settings", {}),
    ("admin_staff", {}),
    ("admin_add", {}),
    ("admin_remove", {"staff_id": "x"}),
    ("admin_import_check", {}),
    ("admin_import", {}),
]


def drawer(staff: Any, secrets: dict[str, str]) -> OrderFavoritesApp:
    app = OrderFavoritesApp.__new__(OrderFavoritesApp)
    app.event = SimpleNamespace(context={"user": {"type": "Staff", "id": str(staff.id)}})
    app.secrets = secrets
    return app


@pytest.mark.parametrize(("route", "path"), ADMIN_ROUTES)
def test_non_admin_gets_403_on_every_admin_route(make_staff: Any, route: str, path: dict[str, str]) -> None:
    admin, me = make_staff(), make_staff()
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    status, _body = reply(getattr(make_api(me, path=path, body={"csv": "x"}), route)())
    assert status == 403


def test_drawer_app_is_for_every_active_staff_member(make_staff: Any) -> None:
    me, gone = make_staff(), make_staff(active=False)
    assert drawer(me, {}).visible() is True
    assert drawer(gone, {}).visible() is False
    with patch("order_favorites.handlers.api.render_to_string", side_effect=lambda path, *a: path) as render:
        [page] = make_api(me).admin_page()
    assert (page.status_code, render.call_args.args[0]) == (200, "static/admin/index.html")
    with patch("order_favorites.handlers.api.render_to_string", side_effect=lambda path, *a: path) as render:
        [page] = make_api(gone).admin_page()
    assert (page.status_code, render.call_args.args[0]) == (403, "static/admin/not_admin.html")


def test_my_favorites_tab_loads_without_a_note(make_staff: Any) -> None:
    me, other = make_staff(), make_staff()
    favorite(me, name="Mine")
    favorite(other, shared=True, name="Practice")
    status, body = reply(make_api(me).panel_data())
    assert status == 200
    assert body["note"] is None
    assert body["is_admin"] is False
    assert sorted(f["name"] for f in body["favorites"]) == ["Mine", "Practice"]


def test_nobody_is_admin_when_first_admin_is_empty(make_staff: Any) -> None:
    me = make_staff(email="pat@example.org")
    assert is_admin(str(me.id), {}) is False


def test_first_admin_is_admin_and_gets_written_to_the_list_once(make_staff: Any) -> None:
    me = make_staff(email="Pat@Example.org")
    other = make_staff(email="other@example.org")
    secrets = {"FIRST_ADMIN": "pat@example.org"}
    assert is_admin(str(me.id), secrets) is True
    assert is_admin(str(other.id), secrets) is False
    assert FavoritesAdmin.objects.count() == 0  # checking only reads

    status, _body = reply(make_api(me, secrets=secrets).admin_data())
    assert status == 200
    assert list(FavoritesAdmin.objects.values_list("staff_id", flat=True)) == [me.dbid]

    # Once the list has someone on it, FIRST_ADMIN isn't read again.
    assert is_admin(str(other.id), {"FIRST_ADMIN": "other@example.org"}) is False


def test_first_admin_email_shared_by_two_staff_matches_nobody(make_staff: Any) -> None:
    a = make_staff(email="shared@example.org")
    make_staff(email="shared@example.org")
    assert is_admin(str(a.id), {"FIRST_ADMIN": "shared@example.org"}) is False


def test_inactive_admin_is_not_an_admin(make_staff: Any) -> None:
    me = make_staff(active=False)
    FavoritesAdmin.objects.create(staff_id=me.dbid)
    assert is_admin(str(me.id), {}) is False


def test_last_admin_cant_be_removed(make_staff: Any) -> None:
    me = make_staff()
    FavoritesAdmin.objects.create(staff_id=me.dbid)
    status, body = reply(make_api(me, path={"staff_id": str(me.id)}).admin_remove())
    assert status == 409
    assert body["error"] == "There must always be at least one admin."
    assert FavoritesAdmin.objects.count() == 1


def test_an_admin_can_remove_another_and_themselves_while_one_remains(make_staff: Any) -> None:
    me, other = make_staff(), make_staff()
    FavoritesAdmin.objects.create(staff_id=me.dbid)
    FavoritesAdmin.objects.create(staff_id=other.dbid)
    status, body = reply(make_api(me, path={"staff_id": str(me.id)}).admin_remove())
    assert status == 200
    assert body["removed_self"] is True
    assert list(FavoritesAdmin.objects.values_list("staff_id", flat=True)) == [other.dbid]


def test_personal_favorite_can_only_be_changed_by_its_owner(make_staff: Any) -> None:
    owner, me = make_staff(), make_staff()
    fav = favorite(owner, name="Mine")
    status, _ = reply(make_api(me, path={"favorite_id": str(fav.dbid)}, body=rx_body(name="Taken")).update_favorite())
    assert status == 404
    status, _ = reply(make_api(me, path={"favorite_id": str(fav.dbid)}).delete_favorite())
    assert status == 404
    fav.refresh_from_db()
    assert fav.name == "Mine"

    status, body = reply(make_api(owner, path={"favorite_id": str(fav.dbid)}, body=rx_body(name="Renamed")).update_favorite())
    assert status == 200
    assert body["favorite"]["name"] == "Renamed"


def test_practice_favorite_cant_be_changed_from_the_panel_even_by_an_admin(make_staff: Any) -> None:
    admin = make_staff()
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    fav = favorite(admin, shared=True, name="Practice")
    status, _ = reply(make_api(admin, path={"favorite_id": str(fav.dbid)}, body=rx_body(name="X")).update_favorite())
    assert status == 404
    status, _ = reply(make_api(admin, path={"favorite_id": str(fav.dbid)}).delete_favorite())
    assert status == 404
    assert Favorite.objects.filter(dbid=fav.dbid).exists()


def test_panel_saves_are_always_personal(make_staff: Any) -> None:
    me = make_staff()
    status, body = reply(make_api(me, body=rx_body(shared=True)).create_favorite())
    assert status == 201
    assert body["favorite"]["shared"] is False
    assert Favorite.objects.get().owner_id == me.dbid


def test_hiding_a_practice_favorite_affects_only_that_person(make_staff: Any, make_note: Any) -> None:
    admin, me, other = make_staff(), make_staff(), make_staff()
    fav = favorite(admin, shared=True)
    reply(make_api(me, path={"favorite_id": str(fav.dbid)}, body={"hidden": True}).hide_favorite())
    note = make_note()
    _s, mine = reply(make_api(me, query={"note_id": str(note.id)}).panel_data())
    _s, theirs = reply(make_api(other, query={"note_id": str(note.id)}).panel_data())
    assert mine["favorites"][0]["hidden"] is True
    assert theirs["favorites"][0]["hidden"] is False

    reply(make_api(me, path={"favorite_id": str(fav.dbid)}, body={"hidden": False}).hide_favorite())
    assert HiddenFavorite.objects.count() == 0


def test_personal_favorites_cant_be_hidden(make_staff: Any) -> None:
    me = make_staff()
    status, _ = reply(make_api(me, path={"favorite_id": str(favorite(me).dbid)}).hide_favorite())
    assert status == 404


def test_panel_lists_practice_and_own_favorites_only(make_staff: Any, make_note: Any) -> None:
    me, other = make_staff(), make_staff()
    favorite(other, shared=True, name="Practice")
    favorite(me, name="Mine")
    favorite(other, name="Theirs")
    _s, body = reply(make_api(me, query={"note_id": str(make_note().id)}).panel_data())
    assert sorted(f["name"] for f in body["favorites"]) == ["Mine", "Practice"]


def test_panel_data_reports_no_note_for_a_letter(make_staff: Any, make_note: Any) -> None:
    _s, body = reply(make_api(make_staff(), query={"note_id": str(make_note(category="letter").id)}).panel_data())
    assert body["note"] is None


# ---------- Canvas support (root) ----------

from order_favorites.services.access import ROOT_STAFF_KEY  # noqa: E402


@pytest.fixture
def root(make_staff: Any) -> Any:
    return make_staff(first="Canvas", last="Support", email="support@canvasmedical.com", key=ROOT_STAFF_KEY)


def test_root_is_admin_with_no_admins_and_no_first_admin(root: Any) -> None:
    assert is_admin(str(root.id), {}) is True
    assert drawer(root, {}).visible() is True


def test_root_is_admin_alongside_the_practice_list_and_never_joins_it(root: Any, make_staff: Any) -> None:
    other = make_staff()
    FavoritesAdmin.objects.create(staff_id=other.dbid)
    status, body = reply(make_api(root).admin_data())
    assert status == 200
    assert [a["name"] for a in body["admins"]] == [f"{other.first_name} {other.last_name}"]
    assert not FavoritesAdmin.objects.filter(staff_id=root.dbid).exists()


def test_inactive_root_is_not_an_admin(make_staff: Any) -> None:
    root = make_staff(key=ROOT_STAFF_KEY, active=False)
    assert is_admin(str(root.id), {}) is False


def test_root_can_add_the_first_real_admin(root: Any, make_staff: Any) -> None:
    new = make_staff(first="New", email="new@example.org")
    status, body = reply(make_api(root, body={"staff_id": str(new.id)}).admin_add())
    assert status == 200
    assert [a["name"] for a in body["admins"]] == ["New Provider"]


def test_root_cant_be_added_or_found_in_staff_search(root: Any, make_staff: Any) -> None:
    admin = make_staff(first="Pat", last="Admin")
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    status, body = reply(make_api(admin, body={"staff_id": ROOT_STAFF_KEY}).admin_add())
    assert (status, body["error"]) == (400, "Canvas support is always an admin.")
    _s, found = reply(make_api(admin, query={"q": "canvas"}).admin_staff())
    assert found["results"] == []


def test_first_admin_set_to_the_root_email_doesnt_write_root_to_the_list(root: Any) -> None:
    reply(make_api(root, secrets={"FIRST_ADMIN": "support@canvasmedical.com"}).admin_data())
    assert FavoritesAdmin.objects.count() == 0


def test_root_row_from_an_older_version_doesnt_count_as_an_admin(root: Any, make_staff: Any) -> None:
    only = make_staff()
    FavoritesAdmin.objects.create(staff_id=root.dbid)
    FavoritesAdmin.objects.create(staff_id=only.dbid)
    status, _ = reply(make_api(only, path={"staff_id": str(only.id)}).admin_remove())
    assert status == 409
