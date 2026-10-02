"""Asset routes: the stylesheets and script consuming plugins link against.

The caching here is load-bearing, not cosmetic, and is carried forward from a
production design-system plugin where getting it wrong produced a visible flash
of unstyled content on every page.

Two rules must not be relaxed:

1. **Nothing in the published policy may forbid serving a stale copy.**
   `no-cache`, `no-store` and `must-revalidate` each require a successful
   revalidation before reuse, which puts a network round trip in front of first
   paint while the header still looks reasonable. That is exactly the flash.
   `stale-while-revalidate` paints from cache and revalidates in the background.

2. **ETags must be compared weakly.** Canvas's edge gzips `text/css` and, as a
   gzipping proxy must, marks the ETag weak on the way out. The browser then
   sends back `W/"<hash>"`. A verbatim comparison never matches, so every
   revalidation returns a full body instead of a 304.

Each request here costs two plugin-runner dispatches (`SIMPLE_API_AUTHENTICATE`
and `SIMPLE_API_REQUEST`) on a runner shared with every other plugin on the
instance, which is why avoiding round trips matters more than it would on an
ordinary static host.
"""

from hashlib import sha256
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string

from canvas_theme_kit.authorization import can_edit, current_staff
from canvas_theme_kit.store import get_theme, published_css, published_tokens_css
from canvas_theme_kit.theming import full_stylesheet

# Published assets: fresh for five minutes, then served stale while a background
# revalidation runs. A consuming page is typically one view behind a publish and
# never more than a day.
CACHE_CONTROL = "private, max-age=300, stale-while-revalidate=86400"

# Preview is the one route that deliberately forbids reuse. It is staff-only and
# low traffic, and an editor seeing their own unsaved-looking change is worth
# more than a cached round trip. `private` keeps shared caches out of it.
PREVIEW_CACHE_CONTROL = "private, no-store"


class _ServesAssets:
    """Shared conditional-GET behavior for the asset routes."""

    def _serve(
        self,
        body: bytes,
        content_type: str,
        cache_control: str = CACHE_CONTROL,
    ) -> list[Response | Effect]:
        """Serve an asset, answering a conditional GET with 304 when unchanged.

        The ETag is derived from the response bytes rather than from a version
        number, so it stays correct when someone publishes without bumping
        anything — which is the mistake this is here to absorb.
        """
        etag = f'"{sha256(body).hexdigest()[:32]}"'
        headers = {"Cache-Control": cache_control, "ETag": etag}

        if self._client_has(etag):
            # A 304 carries no body and needs no Content-Type: the client
            # already has the bytes and only asked whether they are still good.
            return [Response(b"", status_code=HTTPStatus.NOT_MODIFIED, headers=headers)]

        return [
            Response(
                body,
                status_code=HTTPStatus.OK,
                headers=headers,
                content_type=content_type,
            )
        ]

    def _client_has(self, etag: str) -> bool:
        """Whether the request's If-None-Match covers `etag`, compared weakly.

        The SDK treats If-None-Match as list-valued, so `headers.get()` would
        return only the first tag; `get_list()` returns all of them. `W/` is
        stripped per RFC 7232 section 3.2 weak comparison — see the module
        docstring for why that is not pedantry here.
        """
        candidates = {
            value.strip().removeprefix("W/")
            for value in self.request.headers.get_list("If-None-Match")  # type: ignore[attr-defined]
        }
        return "*" in candidates or etag in candidates

    def _not_found(self, slug: str) -> list[Response | Effect]:
        """404 for a theme that exists but has never been published.

        Deliberately not an empty 200: an empty stylesheet is indistinguishable
        from a published theme that happens to have no rules, which turns a
        configuration mistake into a silent one.
        """
        return [
            Response(
                f"/* canvas_theme_kit: no published revision for theme {slug!r} */".encode(),
                status_code=HTTPStatus.NOT_FOUND,
                headers={"Cache-Control": "private, no-store"},
                content_type="text/css",
            )
        ]


class ThemeAssets(_ServesAssets, SimpleAPI):
    """Serves published stylesheets and the shared script to any logged-in session."""

    PREFIX = "/assets"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Serve published assets to any logged-in session, staff or patient.

        Patient-portal pages are a primary consumer, so this cannot be narrowed
        to staff. Note the consequence: pre-login surfaces (portal login,
        registration, password reset) cannot load these. Returning True
        unconditionally would make them public — they carry no patient data —
        but that is a deployment decision, not a default.

        The override is mandatory either way: `SimpleAPIBase.authenticate`
        returns False by default, so without it every route would refuse every
        request.
        """
        return credentials.logged_in_user is not None

    @api.get("/<slug>/core.css")
    def core_css(self) -> list[Response | Effect]:
        """The full published stylesheet for a theme: tokens, then authored CSS."""
        slug = self.request.path_params["slug"]
        rendered = published_css(slug)
        if rendered is None:
            return self._not_found(slug)
        return self._serve(rendered.encode(), "text/css")

    @api.get("/<slug>/tokens.css")
    def tokens_css(self) -> list[Response | Effect]:
        """Just the `:root` token block.

        Served separately so a consumer can inline it into `<head>` without
        carrying the whole stylesheet inline.
        """
        slug = self.request.path_params["slug"]
        rendered = published_tokens_css(slug)
        if rendered is None:
            return self._not_found(slug)
        return self._serve(rendered.encode(), "text/css")

    @api.get("/core.js")
    def core_js(self) -> list[Response | Effect]:
        """The shared behavior bundle.

        Ships with the plugin and is versioned in the repository — it is
        deliberately not admin-editable. Admin-authored JavaScript served into
        patient sessions would be a stored-XSS surface by design.
        """
        return self._serve(
            render_to_string("static/core.js").encode(), "text/javascript"
        )


class ThemePreview(_ServesAssets, StaffSessionAuthMixin, SimpleAPI):
    """Serves the unpublished draft to authorized editors only.

    Split into its own handler because `SimpleAPI` authenticates per class, and
    this needs a strictly narrower gate than the published routes:
    `StaffSessionAuthMixin` rejects patient sessions up front, and the role
    check then rejects staff who are not on the editor allowlist.
    """

    PREFIX = "/preview"

    @api.get("/<slug>/preview.css")
    def preview_css(self) -> list[Response | Effect]:
        """Render the current draft, uncached.

        This is what makes "instant preview, five-minute publish" work: the
        editor sees their own change immediately without anyone touching the
        cache policy that keeps published pages from flashing.
        """
        staff = current_staff(self.request.headers)
        if not can_edit(staff, self.secrets):
            return [
                Response(
                    b"/* canvas_theme_kit: not authorized to preview */",
                    status_code=HTTPStatus.FORBIDDEN,
                    headers={"Cache-Control": PREVIEW_CACHE_CONTROL},
                    content_type="text/css",
                )
            ]

        slug = self.request.path_params["slug"]
        theme = get_theme(slug)
        if theme is None:
            return self._not_found(slug)

        rendered = full_stylesheet(theme.draft_css or "", theme.draft_tokens or {})
        return self._serve(rendered.encode(), "text/css", PREVIEW_CACHE_CONTROL)
