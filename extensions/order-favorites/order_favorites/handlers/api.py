"""The favorites panel, the drawer app, and the JSON API behind them.

Every request runs as the signed-in staff member (StaffSessionAuthMixin). Personal favorites can only
be seen and changed by their owner. Practice favorites, settings, the admin list, and import need a
favorites admin (services.access.is_admin); everyone else gets 403.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Staff
from django.db.models import Q

from order_favorites.models import Favorite, FavoritesAdmin, HiddenFavorite
from order_favorites.services import access, catalog, lookups
from order_favorites.services.favorites import (
    Invalid,
    clean_favorite,
    expand_sets,
    favorite_json,
    hidden_ids,
    stale_map,
    visible_to,
)
from order_favorites.services.importer import TEMPLATE, check_csv
from order_favorites.services.notes import eligible_note, note_label, patient_open_notes, reason_for_visit_titles
from order_favorites.services.staging import stage

API_BASE = "/plugin-io/api/order_favorites"
# Changes on every plugin load, so browsers fetch fresh scripts and styles after an update.
CACHE_BUST = str(int(datetime.now(UTC).timestamp()))
TITLES = {
    ("rx", "lab"): "Prescription and Lab Order Favorites",
    ("rx",): "Prescription Favorites",
    ("lab",): "Lab Order Favorites",
}
MIN_QUERY = 2


def _error(message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> list[Response | Effect]:
    return [JSONResponse({"error": message}, status_code=status)]


def _ok(data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> list[Response | Effect]:
    return [JSONResponse(data, status_code=status)]


def _title(kinds: list[str]) -> str:
    return TITLES[tuple(kinds)]


def _list_kinds() -> list[str]:
    """What shows in lists: the enabled order types, plus order sets when they're on."""
    return access.enabled_kinds() + (["set"] if access.sets_enabled() else [])


def _kind_enabled(kind: str) -> bool:
    return kind in _list_kinds()


class OrderFavoritesAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the panel and admin pages and the JSON API they use."""

    # ---------- who is asking ----------

    def _staff_id(self) -> str | None:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        return str(staff_id) if staff_id else None

    def _me(self) -> int | None:
        return access.staff_dbid(self._staff_id())

    def _admin(self) -> bool:
        if not access.is_admin(self._staff_id(), self.secrets):
            return False
        access.seed_first_admin(self.secrets)
        return True

    def _body(self) -> dict[str, Any]:
        try:
            body = self.request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _favorite(self) -> Favorite | None:
        try:
            dbid = int(str(self.request.path_params.get("favorite_id")))
        except (TypeError, ValueError):
            return None
        favorite: Favorite | None = Favorite.objects.select_related("owner").filter(dbid=dbid).first()
        return favorite

    def _query(self) -> str:
        return (self.request.query_params.get("q") or "").strip()

    # ---------- pages and assets ----------

    def _asset(self, path: str, content_type: str) -> list[Response | Effect]:
        body = render_to_string(path) or ""
        return [Response(body.encode(), status_code=HTTPStatus.OK, content_type=content_type, headers={"Cache-Control": "no-cache"})]

    @api.get("/panel/")
    def panel_page(self) -> list[Response | Effect]:
        note_id = self.request.query_params.get("note_id") or ""
        html = render_to_string("static/panel/index.html", {"api_base": API_BASE, "note_id": note_id, "cache_bust": CACHE_BUST}) or ""
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/panel/app.js")
    def panel_js(self) -> list[Response | Effect]:
        return self._asset("static/panel/app.js", "application/javascript")

    @api.get("/panel/app.css")
    def panel_css(self) -> list[Response | Effect]:
        return self._asset("static/panel/app.css", "text/css")

    @api.get("/shared/editor.js")
    def editor_js(self) -> list[Response | Effect]:
        return self._asset("static/shared/editor.js", "application/javascript")

    @api.get("/icon.svg")
    def icon(self) -> list[Response | Effect]:
        return self._asset("assets/icon.svg", "image/svg+xml")

    @api.get("/admin/")
    def admin_page(self) -> list[Response | Effect]:
        """The drawer app. Everyone gets My favorites; the page asks for admin data only if the person is an admin."""
        if self._me() is None:
            html = render_to_string("static/admin/not_admin.html") or ""
            return [HTMLResponse(html, status_code=HTTPStatus.FORBIDDEN)]
        fav = self.request.query_params.get("favorite") or ""
        html = render_to_string("static/admin/index.html", {"api_base": API_BASE, "cache_bust": CACHE_BUST, "favorite": fav}) or ""
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/admin/app.js")
    def admin_js(self) -> list[Response | Effect]:
        return self._asset("static/admin/app.js", "application/javascript")

    @api.get("/admin/app.css")
    def admin_css(self) -> list[Response | Effect]:
        return self._asset("static/admin/app.css", "text/css")

    # ---------- chart panel ----------

    @api.get("/panel/data")
    def panel_data(self) -> list[Response | Effect]:
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        note = eligible_note(self.request.query_params.get("note_id"))
        kinds = access.enabled_kinds()
        hidden = hidden_ids(me)
        favorites = list(visible_to(me, _list_kinds()))
        stale = stale_map(favorites)
        return _ok(
            {
                "note": note_label(note) if note else None,
                "kinds": kinds,
                "sets_enabled": access.sets_enabled(),
                "title": _title(kinds),
                "is_admin": access.is_admin(self._staff_id(), self.secrets),
                "favorites": [favorite_json(f, me, hidden, stale.get(f.dbid)) for f in favorites],
            }
        )

    @api.post("/notes/<note_id>/add")
    def add_to_note(self) -> list[Response | Effect]:
        staff_id, me = self._staff_id(), self._me()
        if staff_id is None or me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        note = eligible_note(self.request.path_params.get("note_id"))
        if note is None:
            return _error("This note is no longer open, so nothing was added. Open a visit or chart review note and try again.", HTTPStatus.CONFLICT)
        ids: list[int] = []
        for value in self._body().get("favorite_ids") or []:
            try:
                ids.append(int(str(value)))
            except (TypeError, ValueError):
                continue
        if not ids:
            return _error("Select favorites to add.")
        by_id = {f.dbid: f for f in visible_to(me, _list_kinds()).filter(dbid__in=ids)}
        chosen = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
        # Order sets become their favorites; anything picked twice (alone and in a set) is added once.
        usable = {f.dbid: f for f in visible_to(me, access.enabled_kinds())}
        orders = expand_sets(chosen, usable)
        if not orders:
            return _error("Those favorites aren't available any more.", HTTPStatus.NOT_FOUND)
        added, skipped, effects = stage(orders, note, staff_id)
        return [*effects, JSONResponse({"note": note_label(note), "added": added, "skipped": skipped})]

    @api.get("/notes/<note_id>/others")
    def other_notes(self) -> list[Response | Effect]:
        """The patient's open visit and chart review notes, for Change in the panel footer."""
        if self._me() is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        clicked = str(self.request.path_params.get("note_id") or "")
        notes, total = patient_open_notes(clicked)
        reasons = reason_for_visit_titles(notes)
        return _ok({"notes": [{**note_label(n, reasons.get(n.dbid, "")), "clicked": str(n.id) == clicked} for n in notes], "total": total})

    # ---------- personal favorites ----------

    @api.post("/favorites")
    def create_favorite(self) -> list[Response | Effect]:
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        try:
            kind, name, details = clean_favorite(self._body(), owner=me, shared=False)
        except Invalid as exc:
            return _error(str(exc))
        if not _kind_enabled(kind):
            return _error("Your practice doesn't use this order type.")
        favorite = Favorite.objects.create(kind=kind, name=name, details=details, shared=False, owner_id=me)
        return _ok({"favorite": favorite_json(favorite, me)}, HTTPStatus.CREATED)

    def _own(self, me: int | None) -> Favorite | None:
        favorite = self._favorite()
        if me is None or favorite is None or favorite.shared or favorite.owner_id != me:
            return None
        return favorite

    @api.patch("/favorites/<favorite_id>")
    def update_favorite(self) -> list[Response | Effect]:
        me = self._me()
        favorite = self._own(me)
        if favorite is None:
            return _error("You can only change your own favorites.", HTTPStatus.NOT_FOUND)
        try:
            _kind, favorite.name, favorite.details = clean_favorite(self._body(), favorite.kind, owner=me, shared=False)
        except Invalid as exc:
            return _error(str(exc))
        favorite.save()
        return _ok({"favorite": favorite_json(favorite, me)})

    @api.delete("/favorites/<favorite_id>")
    def delete_favorite(self) -> list[Response | Effect]:
        favorite = self._own(self._me())
        if favorite is None:
            return _error("You can only delete your own favorites.", HTTPStatus.NOT_FOUND)
        name = favorite.name
        favorite.delete()
        return _ok({"deleted": name})

    @api.post("/favorites/<favorite_id>/hide")
    def hide_favorite(self) -> list[Response | Effect]:
        me, favorite = self._me(), self._favorite()
        if me is None or favorite is None or not favorite.shared:
            return _error("Only practice favorites can be hidden.", HTTPStatus.NOT_FOUND)
        hide = bool(self._body().get("hidden", True))
        if hide:
            HiddenFavorite.objects.get_or_create(favorite_id=favorite.dbid, staff_id=me)
        else:
            HiddenFavorite.objects.filter(favorite_id=favorite.dbid, staff_id=me).delete()
        return _ok({"hidden": hide})

    # ---------- lookups (any staff member) ----------

    def _search(self, finder: Any) -> list[Response | Effect]:
        q = self._query()
        if len(q) < MIN_QUERY:
            return _ok({"results": []})
        try:
            return _ok({"results": finder(q)})
        except lookups.LookupFailed:
            return _error("Canvas's search didn't answer. Try again.", HTTPStatus.SERVICE_UNAVAILABLE)

    @api.get("/lookup/medications")
    def medications(self) -> list[Response | Effect]:
        return self._search(lookups.search_medications)

    @api.get("/lookup/pharmacies")
    def pharmacies(self) -> list[Response | Effect]:
        return self._search(lookups.search_pharmacies)

    @api.get("/lookup/diagnoses")
    def diagnoses(self) -> list[Response | Effect]:
        return self._search(lookups.search_diagnoses)

    @api.get("/lookup/lab-partners")
    def lab_partners(self) -> list[Response | Effect]:
        return _ok({"results": catalog.active_partners()})

    @api.get("/lookup/lab-tests")
    def lab_tests(self) -> list[Response | Effect]:
        partner = self.request.query_params.get("partner_id") or ""
        return _ok({"results": catalog.partner_tests(partner, self._query())})

    @api.get("/lookup/providers")
    def providers(self) -> list[Response | Effect]:
        # The editor shows every provider in one dropdown, so this isn't cut to a search page.
        return _ok({"results": catalog.ordering_providers(self._query(), limit=2000)})

    # ---------- admin: practice favorites, settings, admins, import ----------

    def _admins_json(self, me: int | None) -> list[dict[str, Any]]:
        rows = access.listed_admins().select_related("staff", "staff__user").order_by("staff__last_name", "staff__first_name")
        return [
            {
                "id": str(row.staff.id),
                "name": access.staff_name(row.staff),
                "email": (row.staff.user.email if row.staff.user else "") or "",
                "me": row.staff_id == me,
            }
            for row in rows
        ]

    @api.get("/admin/data")
    def admin_data(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        me = self._me()
        kinds = access.enabled_kinds()
        practice = list(Favorite.objects.select_related("owner").filter(shared=True).order_by("name", "dbid"))
        stale = stale_map(practice)
        return _ok(
            {
                "title": _title(kinds),
                "settings": {"rx_enabled": "rx" in kinds, "lab_enabled": "lab" in kinds, "set_enabled": access.sets_enabled()},
                "admins": self._admins_json(me),
                "favorites": [favorite_json(f, me, None, stale.get(f.dbid)) for f in practice],
                "template": TEMPLATE,
            }
        )

    @api.post("/admin/favorites")
    def admin_create(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        me = self._me()
        try:
            kind, name, details = clean_favorite(self._body(), owner=me, shared=True)
        except Invalid as exc:
            return _error(str(exc))
        favorite = Favorite.objects.create(kind=kind, name=name, details=details, shared=True, owner_id=me)
        return _ok({"favorite": favorite_json(favorite, me)}, HTTPStatus.CREATED)

    def _practice(self) -> Favorite | None:
        favorite = self._favorite()
        return favorite if favorite is not None and favorite.shared else None

    @api.patch("/admin/favorites/<favorite_id>")
    def admin_update(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        favorite = self._practice()
        if favorite is None:
            return _error("Practice favorite not found.", HTTPStatus.NOT_FOUND)
        try:
            _kind, favorite.name, favorite.details = clean_favorite(self._body(), favorite.kind, owner=favorite.owner_id, shared=True)
        except Invalid as exc:
            return _error(str(exc))
        favorite.save()
        return _ok({"favorite": favorite_json(favorite, self._me())})

    @api.delete("/admin/favorites/<favorite_id>")
    def admin_delete(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        favorite = self._practice()
        if favorite is None:
            return _error("Practice favorite not found.", HTTPStatus.NOT_FOUND)
        name = favorite.name
        favorite.delete()
        return _ok({"deleted": name})

    @api.post("/admin/settings")
    def admin_settings(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        body = self._body()
        current = access.enabled_kinds()
        rx = bool(body["rx_enabled"]) if "rx_enabled" in body else "rx" in current
        lab = bool(body["lab_enabled"]) if "lab_enabled" in body else "lab" in current
        sets = bool(body["set_enabled"]) if "set_enabled" in body else access.sets_enabled()
        if not rx and not lab:
            return _error("At least one of prescriptions or labs must stay on.")
        access.set_setting("rx_enabled", rx)
        access.set_setting("lab_enabled", lab)
        access.set_setting("set_enabled", sets)
        return _ok({"settings": {"rx_enabled": rx, "lab_enabled": lab, "set_enabled": sets}, "title": _title(access.enabled_kinds())})

    @api.get("/admin/staff")
    def admin_staff(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        q = self._query()
        if len(q) < MIN_QUERY:
            return _ok({"results": []})
        admin_ids = set(access.listed_admins().values_list("staff_id", flat=True))
        words = q.split()
        # Canvas support is always an admin, so it isn't offered here.
        query = Q(active=True) & ~Q(id=access.ROOT_STAFF_KEY)
        for word in words:
            query &= Q(first_name__icontains=word) | Q(last_name__icontains=word) | Q(user__email__icontains=word)
        staff = Staff.objects.select_related("user").filter(query).order_by("last_name", "first_name")[:20]
        return _ok(
            {
                "results": [
                    {"id": str(s.id), "name": access.staff_name(s), "email": (s.user.email if s.user else "") or ""}
                    for s in staff
                    if s.dbid not in admin_ids
                ]
            }
        )

    @api.post("/admin/admins")
    def admin_add(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        staff_id = str(self._body().get("staff_id") or "")
        if staff_id == access.ROOT_STAFF_KEY:
            return _error("Canvas support is always an admin.")
        dbid = access.staff_dbid(staff_id)
        if dbid is None:
            return _error("Select an active staff member.")
        FavoritesAdmin.objects.get_or_create(staff_id=dbid)
        return _ok({"admins": self._admins_json(self._me())})

    @api.delete("/admin/admins/<staff_id>")
    def admin_remove(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        dbid = Staff.objects.filter(id=self.request.path_params.get("staff_id")).values_list("dbid", flat=True).first()
        row = access.listed_admins().filter(staff_id=dbid).first() if dbid is not None else None
        if row is None:
            return _error("That person isn't an admin.", HTTPStatus.NOT_FOUND)
        if access.listed_admins().filter(staff__active=True).exclude(pk=row.pk).count() == 0:
            return _error("There must always be at least one admin.", HTTPStatus.CONFLICT)
        row.delete()
        return _ok({"admins": self._admins_json(self._me()), "removed_self": dbid == self._me()})

    @api.post("/admin/import/check")
    def admin_import_check(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        result = check_csv(str(self._body().get("csv") or ""))
        for row in result["rows"]:
            row.pop("favorite", None)
        return _ok(result)

    @api.post("/admin/import")
    def admin_import(self) -> list[Response | Effect]:
        """Check the file again and save its good rows as practice favorites."""
        if not self._admin():
            return _error("Only favorites admins can do this.", HTTPStatus.FORBIDDEN)
        me = self._me()
        result = check_csv(str(self._body().get("csv") or ""))
        if result["error"]:
            return _error(result["error"])
        good = [row["favorite"] for row in result["rows"] if row["ok"]]
        Favorite.objects.bulk_create(
            [Favorite(kind=f["kind"], name=f["name"], details=f["details"], shared=True, owner_id=me) for f in good]
        )
        return _ok({"imported": len(good), "skipped": len(result["rows"]) - len(good)})
