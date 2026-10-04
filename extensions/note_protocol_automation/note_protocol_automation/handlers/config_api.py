"""SimpleAPI: serves the rule-config UI and CRUD over the Rule custom_data table.
Staff-session authenticated AND admin-gated: every data endpoint (rules CRUD plus
note-types) is restricted, fail-closed, to the staff ids in the ADMIN_STAFF_IDS
secret. A logged-in non-admin staff gets 403 on all of them. The static-serving
routes resolve the Application's
/plugin-io/api/note_protocol_automation/static/index.html URL in the EHR.

Sandbox constraints honored: NO @dataclass, NO pathlib (read static via the
allowlisted canvas_sdk.templates.render_to_string), NO lazy/local imports,
single-segment `<name>` routes only.
"""

import uuid
from http import HTTPStatus
from typing import Any, Final

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import NoteType
from logger import log

from note_protocol_automation.models.rule import Rule


def _canonical_id(value: str) -> str:
    """Return ``value`` as a 32-char hex UUID when possible, else verbatim.

    ``Staff.id`` is stored as ``uuid.uuid4().hex`` (undashed). Operators often
    paste dashed UUIDs into ``ADMIN_STAFF_IDS``; canonicalizing both sides
    through ``uuid.UUID(...)`` makes the dashed and undashed forms compare equal.
    Non-UUID strings are returned unchanged.
    """
    if not value:
        return value
    try:
        return uuid.UUID(value).hex
    except ValueError:
        return value

# ---------------------------------------------------------------------------
# Static-serving config (copied verbatim from the sibling reference handler).
# ---------------------------------------------------------------------------
_CONTENT_TYPES: Final[dict[str, str]] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}

# Clickjacking defense: the chart embeds this app same-origin in an iframe.
_FRAME_ANCESTORS: Final[str] = "frame-ancestors 'self'"

# Read-once cache of rendered static bytes; static assets are immutable for the
# life of the worker process (they change only on redeploy, which restarts it).
_STATIC_CACHE: dict[str, str] = {}

# Let the browser cache served assets (1h). Modules are version-pinned by name.
_CACHE_CONTROL: Final[str] = "public, max-age=3600"


class ConfigAPI(StaffSessionAuthMixin, SimpleAPI):
    """Authoring API for note-protocol rules + static UI serving."""

    PREFIX = ""

    # Test seam: tests set _req; production uses self.request.
    _req = None

    @property
    def req(self) -> Any:
        """The request object — the test seam if set, else the live SimpleAPI request."""
        return self._req or self.request

    # ----------------------------------------------------------------------
    # Admin authorization (fail-closed). StaffSessionAuthMixin only proves the
    # caller is *some* logged-in staff; these rules auto-insert commands into
    # every matching note, so the config surface is gated to an allow-list of
    # admin staff ids declared in the ADMIN_STAFF_IDS secret.
    # ----------------------------------------------------------------------
    def _admin_staff_ids(self) -> set[str]:
        """Return the configured admin staff ids in canonical (.hex) form.

        Fails closed: if ADMIN_STAFF_IDS is unset or empty, the set is empty so
        no caller is ever treated as an admin and the whole config surface is
        denied. A warning is logged so operators can see why access is refused.
        """
        raw = (getattr(self, "secrets", None) or {}).get("ADMIN_STAFF_IDS", "") or ""
        admin_ids = {_canonical_id(sid.strip()) for sid in raw.split(",") if sid.strip()}
        if not admin_ids:
            log.warning(
                "note_protocol_automation: ADMIN_STAFF_IDS is not configured; the "
                "Note Protocols admin surface is denied to all staff. Set this "
                "secret to a comma-separated list of admin staff ids to enable it."
            )
        return admin_ids

    def _is_admin(self) -> bool:
        """True iff the logged-in staff id is in the ADMIN_STAFF_IDS allow-list."""
        staff_id = _canonical_id(
            str(self.req.headers.get("canvas-logged-in-user-id") or "")
        )
        return bool(staff_id) and staff_id in self._admin_staff_ids()

    def _forbidden(self) -> list[Response]:
        """A 403 response for non-admin callers."""
        return [JSONResponse({"error": "Forbidden"}, status_code=HTTPStatus.FORBIDDEN)]

    def _serialize(self, rule: Rule) -> dict:
        """Serialize a Rule row into the JSON shape the UI consumes."""
        return {
            "dbid": rule.dbid,
            "name": rule.name,
            "note_type_id": rule.note_type_id,
            "enabled": rule.enabled,
            "match": rule.match,
            "priority": rule.priority,
            "predicates": rule.predicate_list(),
            "commands": rule.command_list(),
        }

    # ----------------------------------------------------------------------
    # CRUD over the Rule custom_data table.
    # ----------------------------------------------------------------------
    @api.get("/rules")
    def list_rules(self) -> list[Response]:
        """Return all rules ordered by priority."""
        if not self._is_admin():
            return self._forbidden()
        rules = [
            self._serialize(r)
            for r in Rule.objects.all().order_by("priority", "dbid")
        ]
        return [JSONResponse(rules)]

    @api.post("/rules")
    def create_rule(self) -> list[Response]:
        """Create a rule from the JSON body."""
        if not self._is_admin():
            return self._forbidden()
        b = self.req.json()
        rule = Rule(
            name=b.get("name", ""),
            note_type_id=b.get("note_type_id", ""),
            enabled=bool(b.get("enabled", True)),
            match=b.get("match", "all"),
            priority=int(b.get("priority", 0)),
        )
        rule.set_predicates(b.get("predicates", []))
        rule.set_commands(b.get("commands", []))
        rule.save()
        return [JSONResponse({"dbid": rule.dbid}, status_code=HTTPStatus.CREATED)]

    @api.put("/rules/<dbid>")
    def update_rule(self) -> list[Response]:
        """Replace a rule's fields by dbid."""
        if not self._is_admin():
            return self._forbidden()
        b = self.req.json()
        try:
            rule = Rule.objects.get(dbid=self.req.path_params["dbid"])
        except Rule.DoesNotExist:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        rule.name = b.get("name", rule.name)
        rule.note_type_id = b.get("note_type_id", rule.note_type_id)
        rule.enabled = bool(b.get("enabled", rule.enabled))
        rule.priority = int(b.get("priority", rule.priority))
        rule.set_predicates(b.get("predicates", rule.predicate_list()))
        rule.set_commands(b.get("commands", rule.command_list()))
        rule.save()
        return [JSONResponse({"dbid": rule.dbid})]

    @api.delete("/rules/<dbid>")
    def delete_rule(self) -> list[Response]:
        """Delete a rule by dbid."""
        if not self._is_admin():
            return self._forbidden()
        Rule.objects.filter(dbid=self.req.path_params["dbid"]).delete()
        return [JSONResponse({"ok": True})]

    @api.get("/note-types")
    def note_types(self) -> list[Response]:
        """Return the instance's active note types for the config dropdown."""
        if not self._is_admin():
            return self._forbidden()
        rows = list(
            NoteType.objects.filter(is_active=True)
            .values("unique_identifier", "name")
            .order_by("name")
        )
        return [
            JSONResponse(
                [{"id": str(r["unique_identifier"]), "name": r["name"]} for r in rows]
            )
        ]

    # ----------------------------------------------------------------------
    # Static file serving for the config UI (copied verbatim from the sibling).
    # ----------------------------------------------------------------------
    @api.get("/static/index.html")
    def serve_index(self) -> list[Response | Effect]:
        """Serve the iframe entry document."""
        return self._serve_static("index.html")

    @api.get("/static/app.js")
    def serve_app_js(self) -> list[Response | Effect]:
        """Serve the Preact app module."""
        return self._serve_static("app.js")

    @api.get("/static/tokens.css")
    def serve_tokens(self) -> list[Response | Effect]:
        """Serve the synced design tokens stylesheet."""
        return self._serve_static("tokens.css")

    @api.get("/static/ui/<name>")
    def serve_ui(self) -> list[Response | Effect]:
        """Serve a synced UI component module (e.g. ui/Button.js).

        Single-segment `<name>` (regex `(?P<name>[^/]+)`) matches exactly one path
        segment; Flask-style `<path:name>` is NOT supported (colon -> invalid regex
        group -> PluginError at class-definition time). The guard is belt-and-
        suspenders; the route already cannot match a nested path.
        """
        name = self.request.path_params.get("name", "")
        if "/" in name or ".." in name or not name.endswith(".js"):
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return self._serve_static(f"ui/{name}")

    @api.get("/static/vendor/<name>")
    def serve_vendor(self) -> list[Response | Effect]:
        """Serve a locally vendored third-party module (preact/htm).

        Single-segment `<name>` only (same rule as serve_ui). Vendored modules are
        imported same-origin via the index.html import map and SRI-checked.
        """
        name = self.request.path_params.get("name", "")
        if "/" in name or ".." in name or not name.endswith(".js"):
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return self._serve_static(f"vendor/{name}")

    def _read_static(self, relative: str) -> str | None:
        """Read a whitelisted static file via the SDK template helper, cached.

        Uses canvas_sdk.templates.render_to_string (allowlisted) instead of pathlib
        (banned). `relative` resolves against the plugin package root as
        `static/<relative>`. Returns None if the file does not exist.
        """
        if relative in _STATIC_CACHE:
            return _STATIC_CACHE[relative]
        try:
            body: str | None = render_to_string(f"static/{relative}")
        except (FileNotFoundError, PermissionError):
            return None
        if body is None:
            return None
        _STATIC_CACHE[relative] = body
        return body

    def _serve_static(self, relative: str) -> list[Response | Effect]:
        """Read a whitelisted static file and return it typed.

        `relative` is a fixed, route-derived value (never raw client input). The
        per-route guards above ensure ui/ and vendor/ names are single-segment
        filenames before they reach here.
        """
        # Derive the suffix without pathlib: split on the final dot.
        suffix = f".{relative.rsplit('.', 1)[-1]}" if "." in relative else ""
        content_type = _CONTENT_TYPES.get(suffix)
        if content_type is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]

        body = self._read_static(relative)
        if body is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]

        if suffix == ".html":
            return [
                HTMLResponse(
                    body,
                    headers={
                        "Content-Security-Policy": _FRAME_ANCESTORS,
                        "X-Frame-Options": "SAMEORIGIN",
                        "Cache-Control": _CACHE_CONTROL,
                    },
                )
            ]
        return [
            Response(
                body.encode("utf-8"),
                content_type=content_type,
                headers={"Cache-Control": _CACHE_CONTROL},
            )
        ]
