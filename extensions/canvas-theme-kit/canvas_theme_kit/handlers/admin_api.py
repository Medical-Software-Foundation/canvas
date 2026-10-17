"""Staff-gated admin API behind the theme editor.

Every route here is gated twice: `StaffSessionAuthMixin` rejects patient-portal
sessions up front, and a `StaffRole` allowlist check then rejects staff who are
not authorized. The mixin alone is not enough — it would let any staff member in
the organization restyle every patient-facing page.

Editing and publishing are separate permissions. Saving a draft affects nobody;
publishing changes every consuming page at once.
"""

import re
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff

from canvas_theme_kit.authorization import can_edit, can_publish, current_staff
from canvas_theme_kit.store import default_tokens as store_default_tokens
from canvas_theme_kit.store import get_theme as store_get_theme
from canvas_theme_kit.store import load_revision_into_draft as store_load_into_draft
from canvas_theme_kit.store import reset_draft as store_reset_draft
from canvas_theme_kit.store import publish as store_publish
from canvas_theme_kit.store import rollback as store_rollback
from canvas_theme_kit.store import save_draft as store_save_draft
from canvas_theme_kit.models import Theme, ThemeRevision
from canvas_theme_kit.theming import ValidationError, validate_css, validate_tokens

# Caps the work /admin/roles can be made to do. It is readable by any staff
# session by design — an install with no roles configured must still be
# configurable — so the scan it triggers has to be bounded.
MAX_STAFF_SCANNED = 500

# A slug lands in asset URLs and cache keys. ASCII on purpose: str.isalnum() is
# Unicode-aware and would accept "café" or full-width digits.
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_SLUG = 64
MAX_TITLE = 200

# Distinguishes "the caller already looked this up and found nothing" from "the
# caller did not look". Passing None for both would silently reintroduce an N+1
# for precisely the themes that have no published revision.
#
# Ellipsis rather than object(): Canvas's RestrictedPython sandbox does not
# expose the `object` builtin, so `object()` raises NameError at import time.
# `...` is a literal and needs no builtin lookup.
_NOT_SUPPLIED = ...


class ThemeAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Read and mutate themes. Staff session plus role allowlist required."""

    PREFIX = "/admin"

    # ---- helpers -------------------------------------------------------

    def _staff(self) -> Staff | None:
        return current_staff(self.request.headers)

    def _cross_origin(self) -> bool:
        """Whether this request carries an Origin from somewhere else.

        Mutating routes authenticate on the Canvas session cookie alone. Whether
        that is enough against CSRF depends on the instance's cookie policy,
        which a plugin cannot see — Django defaults to SameSite=Lax, which would
        block it, but the plugin should not rely on an assumption it never
        checks.

        Browsers attach Origin to cross-origin requests and to every POST. Same-
        origin callers (the editor, and the console fetches used to drive it)
        send the instance's own origin, so this rejects nothing legitimate.
        A request with no Origin at all is left alone: server-to-server callers
        omit it, and they are not the CSRF threat.
        """
        origin = self.request.headers.get("origin")
        if not origin:
            return False

        host = self.request.headers.get("host") or ""
        if not host:
            return False
        # Exact match on the origin's authority. A suffix match accepted any
        # host that merely ended with the instance's name, and such a sibling
        # is same-site, so SameSite=Lax would not have stopped it either.
        _, sep, authority = origin.rstrip("/").partition("://")
        return not sep or authority.lower() != host.lower()

    def _body(self) -> dict[str, Any] | None:
        """The request body as a JSON object, or None when it is anything else.

        Every route reads named fields from it, so an array, a string or
        unparseable bytes would otherwise raise on the first `.get` and reach
        the caller as a 500 with no reason attached.
        """
        try:
            body = self.request.json() or {}
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _bad_body(self) -> list[Response | Effect]:
        return self._invalid("Request body must be a JSON object.")

    def _bad_origin(self) -> list[Response | Effect]:
        return [
            JSONResponse(
                {
                    "error": "Cross-origin request rejected.",
                    "hint": (
                        "Mutating routes are same-origin only. Call them from "
                        "the Canvas instance, not from another site."
                    ),
                },
                status_code=HTTPStatus.FORBIDDEN,
            )
        ]

    def _denied(self, action: str) -> list[Response | Effect]:
        """403 with a reason an admin can act on.

        Names the config key rather than saying "forbidden", because the most
        likely cause is an install where the allowlists were never set — and
        deny-by-default means that install authorizes nobody.
        """
        return [
            JSONResponse(
                {
                    "error": f"Not authorized to {action}.",
                    "hint": (
                        "Access is granted by StaffRole internal_code via the "
                        "DS_EDITOR_ROLES and DS_PUBLISHER_ROLES plugin config "
                        "variables. Both are empty by default, which authorizes "
                        "nobody. GET /admin/roles lists the codes available on "
                        "this instance."
                    ),
                },
                status_code=HTTPStatus.FORBIDDEN,
            )
        ]

    def _invalid(self, message: str) -> list[Response | Effect]:
        return [JSONResponse({"error": message}, status_code=HTTPStatus.BAD_REQUEST)]

    def _missing(self, slug: str) -> list[Response | Effect]:
        return [
            JSONResponse(
                {"error": f"No theme with slug {slug!r}."},
                status_code=HTTPStatus.NOT_FOUND,
            )
        ]

    # Pinned by a test. Without it the payload can silently regrow — someone
    # adds draft_css to the default shape and every list response starts
    # carrying full stylesheets.
    THEME_FIELDS = frozenset(
        {
            "slug",
            "title",
            "is_default",
            "updated_at",
            "updated_by",
            "active_revision",
            "content_hash",
        }
    )
    DRAFT_FIELDS = frozenset({"draft_css", "draft_tokens"})

    @staticmethod
    def _active_revisions_by_theme(theme_ids: list[Any]) -> dict[Any, dict[str, Any]]:
        """Active revision summary for many themes, in one query.

        Projected with `.values()` rather than hydrated: a revision row carries
        `css` (up to 256 KB) and `tokens`, and neither is read here. Keyed by
        `theme_id` so the caller can serialize N themes without running N
        queries.
        """
        rows = ThemeRevision.objects.filter(
            theme_id__in=theme_ids, is_active=True
        ).values("theme_id", "revision", "content_hash")
        return {row["theme_id"]: row for row in rows}

    @classmethod
    def _theme_json(
        cls,
        theme: Theme,
        include_draft: bool = False,
        active: Any = _NOT_SUPPLIED,
    ) -> dict[str, Any]:
        if active is _NOT_SUPPLIED:
            active = (
                ThemeRevision.objects.filter(theme=theme, is_active=True)
                .order_by("-revision")
                .values("revision", "content_hash")
                .first()
            )
        payload: dict[str, Any] = {
            "slug": theme.slug,
            "title": theme.title,
            "is_default": theme.is_default,
            "updated_at": theme.updated_at.isoformat() if theme.updated_at else None,
            "updated_by": theme.updated_by,
            "active_revision": active["revision"] if active else None,
            "content_hash": active["content_hash"] if active else None,
        }
        if include_draft:
            payload["draft_css"] = theme.draft_css
            payload["draft_tokens"] = theme.draft_tokens or {}
        return payload

    # ---- ui --------------------------------------------------------------

    @api.get("/ui")
    def editor_ui(self) -> list[Response | Effect]:
        """Serve the editor as a plain page.

        The same editor is reachable from the app drawer, but a `global` scope
        application is only visible outside a patient chart, and an admin who
        cannot find it has no way in. This URL always works for a logged-in
        staff member and is the reliable entry point for setup and debugging.

        Rendering the shell grants nothing: every read and write the page makes
        goes back through the routes below, each of which re-checks the session
        and the role allowlist.

        Served `no-cache` so a redeploy is picked up on the next load. Without it
        the browser reuses the previous editor and a fix looks like it did not
        ship — the reason this needed hard reloads during development. The page
        is small and staff-only, so revalidating it costs nothing worth saving,
        and unlike `core.css` it is not on any patient-facing render path.
        """
        return [
            HTMLResponse(
                render_to_string("templates/admin.html"),
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "private, no-cache"},
            )
        ]

    # ---- discovery -----------------------------------------------------

    @api.get("/roles")
    def list_roles(self) -> list[Response | Effect]:
        """List the StaffRoles on this instance so an admin can configure access.

        This exists because no instance-configuration export reliably captures
        StaffRoles — reports tend to list CareTeamRoles, which are per-patient
        care-team assignments and the wrong thing to authorize against. Without
        this an admin has no way to discover the `internal_code` values the
        config variables expect.

        Readable by any staff member: it exposes role names and codes, which are
        organizational configuration rather than patient data, and requiring the
        editor role to read it would make an unconfigured install impossible to
        configure.
        """
        staff = self._staff()
        if staff is None:
            return self._denied("read roles")

        seen: dict[str, dict[str, Any]] = {}
        # Bounded: this walks staff records to collect the distinct set of
        # roles, and the SDK exposes no direct StaffRole manager. Any
        # organization's full role set appears far inside this many records.
        for role in Staff.objects.all().prefetch_related("roles")[:MAX_STAFF_SCANNED]:
            for entry in role.roles.all():
                code = getattr(entry, "internal_code", None)
                if not code or code in seen:
                    continue
                seen[code] = {
                    "internal_code": code,
                    "name": getattr(entry, "name", ""),
                    "domain": str(getattr(entry, "domain", "") or ""),
                    "role_type": str(getattr(entry, "role_type", "") or ""),
                }

        return [
            JSONResponse(
                {
                    "roles": sorted(seen.values(), key=lambda r: r["internal_code"]),
                    "your_roles": sorted(
                        c for c in (
                            getattr(r, "internal_code", None) for r in staff.roles.all()
                        ) if c
                    ),
                    "you_can_edit": can_edit(staff, self.secrets),
                    "you_can_publish": can_publish(staff, self.secrets),
                }
            )
        ]

    # ---- read ----------------------------------------------------------

    @api.get("/themes")
    def list_themes(self) -> list[Response | Effect]:
        """List every theme with its active revision."""
        staff = self._staff()
        if not can_edit(staff, self.secrets):
            return self._denied("list themes")

        rows = list(Theme.objects.all().order_by("slug"))
        # One query for every theme's active revision, rather than one per theme.
        active = self._active_revisions_by_theme([t.dbid for t in rows])
        themes = [self._theme_json(t, active=active.get(t.dbid)) for t in rows]
        return [JSONResponse({"themes": themes})]

    @api.get("/themes/<slug>")
    def get_theme(self) -> list[Response | Effect]:
        """A theme with its draft and full revision history."""
        staff = self._staff()
        if not can_edit(staff, self.secrets):
            return self._denied("read this theme")

        slug = self.request.path_params["slug"]
        theme = store_get_theme(slug)
        if theme is None:
            return self._missing(slug)

        # Projected, not hydrated: this loads every revision of the theme, and
        # each row can carry 256 KB of CSS that nothing below reads.
        history = [
            {
                "revision": r["revision"],
                "content_hash": r["content_hash"],
                "is_active": r["is_active"],
                "published_at": (
                    r["published_at"].isoformat() if r["published_at"] else None
                ),
                "published_by": r["published_by"],
                "note": r["note"],
            }
            for r in ThemeRevision.objects.filter(theme=theme)
            .order_by("-revision")
            .values(
                "revision",
                "content_hash",
                "is_active",
                "published_at",
                "published_by",
                "note",
            )
        ]
        payload = self._theme_json(theme, include_draft=True)
        payload["revisions"] = history
        return [JSONResponse(payload)]

    # ---- write ---------------------------------------------------------

    @api.post("/themes")
    def create_theme(self) -> list[Response | Effect]:
        """Create a theme. Publishing it is a separate, separately gated step."""
        if self._cross_origin():
            return self._bad_origin()

        staff = self._staff()
        if not can_edit(staff, self.secrets):
            return self._denied("create a theme")

        body = self._body()
        if body is None:
            return self._bad_body()
        slug = str(body.get("slug", "")).strip()
        if len(slug) > MAX_SLUG or not SLUG_RE.fullmatch(slug):
            return self._invalid(
                "Slug must be lowercase alphanumeric with hyphens, e.g. 'clinic-b'."
            )
        title = str(body.get("title", slug))
        if len(title) > MAX_TITLE:
            return self._invalid(f"Title is limited to {MAX_TITLE} characters.")
        if store_get_theme(slug) is not None:
            return self._invalid(f"A theme with slug {slug!r} already exists.")

        # Seed the draft with the neutral starter tokens so a new theme opens as
        # something an admin can edit rather than a blank page. Nothing is
        # published until they explicitly publish.
        theme = Theme.objects.create(
            slug=slug,
            title=title,
            is_default=not Theme.objects.filter(is_default=True).exists(),
            draft_tokens=store_default_tokens(),
            updated_by=staff.id if staff else "",
        )
        return [JSONResponse(self._theme_json(theme), status_code=HTTPStatus.CREATED)]

    @api.post("/themes/<slug>/draft")
    def save_draft(self) -> list[Response | Effect]:
        """Validate and store a draft without changing what anyone is served."""
        if self._cross_origin():
            return self._bad_origin()

        staff = self._staff()
        if not can_edit(staff, self.secrets):
            return self._denied("edit this theme")

        slug = self.request.path_params["slug"]
        theme = store_get_theme(slug)
        if theme is None:
            return self._missing(slug)

        body = self._body()
        if body is None:
            return self._bad_body()
        css = str(body.get("css", ""))
        tokens = body.get("tokens", {})

        try:
            validate_css(css)
            validate_tokens(tokens)
            store_save_draft(theme, css, tokens, staff.id if staff else "")
        except ValidationError as exc:
            return self._invalid(str(exc))

        return [JSONResponse(self._theme_json(theme, include_draft=True))]

    @api.post("/themes/<slug>/reset-draft")
    def reset_draft(self) -> list[Response | Effect]:
        """Restore the shipped starter tokens into the draft.

        Editor permission, not publisher: nothing published changes.
        """
        if self._cross_origin():
            return self._bad_origin()

        staff = self._staff()
        if not can_edit(staff, self.secrets):
            return self._denied("reset this draft")

        slug = self.request.path_params["slug"]
        theme = store_get_theme(slug)
        if theme is None:
            return self._missing(slug)

        store_reset_draft(theme, staff.id if staff else "")
        return [JSONResponse(self._theme_json(theme, include_draft=True))]

    @api.post("/themes/<slug>/load-draft")
    def load_draft(self) -> list[Response | Effect]:
        """Copy a published revision's content into the draft for editing.

        Distinct from rollback, which republishes. This is what someone means by
        "show me the old version again" and needs only edit rights.
        """
        if self._cross_origin():
            return self._bad_origin()

        staff = self._staff()
        if not can_edit(staff, self.secrets):
            return self._denied("edit this draft")

        slug = self.request.path_params["slug"]
        theme = store_get_theme(slug)
        if theme is None:
            return self._missing(slug)

        body = self._body()
        if body is None:
            return self._bad_body()
        raw_revision = body.get("revision")
        if raw_revision is None:
            return self._invalid("Provide the integer 'revision' to load.")
        try:
            target = int(raw_revision)
        except (TypeError, ValueError):
            return self._invalid("Provide the integer 'revision' to load.")

        try:
            store_load_into_draft(theme, target, staff.id if staff else "")
        except ValidationError as exc:
            return self._invalid(str(exc))

        return [JSONResponse(self._theme_json(theme, include_draft=True))]

    @api.post("/themes/<slug>/publish")
    def publish(self) -> list[Response | Effect]:
        """Snapshot the draft as a new active revision."""
        if self._cross_origin():
            return self._bad_origin()

        staff = self._staff()
        if not can_publish(staff, self.secrets):
            return self._denied("publish this theme")

        slug = self.request.path_params["slug"]
        theme = store_get_theme(slug)
        if theme is None:
            return self._missing(slug)

        body = self._body()
        if body is None:
            return self._bad_body()
        try:
            revision = store_publish(
                theme, staff.id if staff else "", str(body.get("note", ""))
            )
        except ValidationError as exc:
            return self._invalid(str(exc))

        return [
            JSONResponse(
                {
                    "slug": theme.slug,
                    "revision": revision.revision,
                    "content_hash": revision.content_hash,
                    "published_by": revision.published_by,
                    "note": revision.note,
                }
            )
        ]

    @api.post("/themes/<slug>/rollback")
    def rollback(self) -> list[Response | Effect]:
        """Republish an earlier revision as a new one. History is never rewritten."""
        if self._cross_origin():
            return self._bad_origin()

        staff = self._staff()
        if not can_publish(staff, self.secrets):
            return self._denied("roll back this theme")

        slug = self.request.path_params["slug"]
        theme = store_get_theme(slug)
        if theme is None:
            return self._missing(slug)

        body = self._body()
        if body is None:
            return self._bad_body()
        raw_revision = body.get("revision")
        if raw_revision is None:
            return self._invalid("Provide the integer 'revision' to roll back to.")
        try:
            target = int(raw_revision)
        except (TypeError, ValueError):
            return self._invalid("Provide the integer 'revision' to roll back to.")

        try:
            revision = store_rollback(theme, target, staff.id if staff else "")
        except ValidationError as exc:
            return self._invalid(str(exc))

        return [
            JSONResponse(
                {
                    "slug": theme.slug,
                    "revision": revision.revision,
                    "restored_from": target,
                    "content_hash": revision.content_hash,
                }
            )
        ]
