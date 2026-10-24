"""Serves the demo page that proves the inline critical-CSS path works.

The page is rendered server-side with the published token block already in its
`<head>`, which is the whole point: by the time the browser has the first bytes,
it knows what the colors and spacing are. Nothing about the first paint depends
on a stylesheet arriving.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    api,
)
from canvas_sdk.templates import render_to_string

from canvas_theme_kit_demo.tokens import (
    DEFAULT_SLUG,
    cached_tokens,
    render_tokens_css,
)


class DemoPage(SimpleAPI):
    """A styled page and a diagnostic view of what it read."""

    PREFIX = "/demo"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Any logged-in session.

        Matches the asset routes it links against, which serve staff and patient
        sessions alike. `SimpleAPIBase.authenticate` returns False by default, so
        this override is mandatory.
        """
        return credentials.logged_in_user is not None

    @api.get("/page")
    def page(self) -> list[Response | Effect]:
        """Render the page with tokens already inlined."""
        slug = self.request.query_params.get("theme", DEFAULT_SLUG)
        # One cached read serves both the block and the count. Reading the map
        # uncached here would put two queries back on every render.
        tokens = cached_tokens(slug)

        return [
            HTMLResponse(
                render_to_string(
                    "templates/page.html",
                    {
                        "ctk_tokens_css": render_tokens_css(tokens),
                        "ctk_token_count": len(tokens),
                        "ctk_slug": slug,
                        "ctk_has_theme": bool(tokens),
                    },
                )
            )
        ]

    @api.get("/tokens")
    def tokens(self) -> list[Response | Effect]:
        """What this plugin can see through the shared namespace.

        Exists to make a failure legible. If the page renders with fallback
        colors, this says whether the cause is a missing namespace key, an
        unpublished theme, or tokens that genuinely read as empty — three very
        different problems that look identical on a rendered page.
        """
        slug = self.request.query_params.get("theme", DEFAULT_SLUG)
        tokens = cached_tokens(slug)

        return [
            JSONResponse(
                {
                    "theme": slug,
                    "token_count": len(tokens),
                    "tokens": tokens,
                    "inline_css": render_tokens_css(tokens),
                    "reading_shared_namespace": bool(tokens),
                },
                status_code=HTTPStatus.OK,
            )
        ]
