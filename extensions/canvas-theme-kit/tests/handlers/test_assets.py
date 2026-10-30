"""Tests for the asset routes.

The caching behavior here is the reason this plugin does not flash unstyled
content, and every rule it depends on is easy to break with a plausible-looking
edit. These tests pin the two that actually bit a production plugin:

- the published Cache-Control must permit serving a stale copy
- ETags must be compared weakly, because Canvas's edge gzips CSS and weakens them
"""

from contextlib import contextmanager
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, call, patch

import pytest

from canvas_theme_kit.handlers.assets import (
    CACHE_CONTROL,
    PREVIEW_CACHE_CONTROL,
    ThemeAssets,
    ThemePreview,
    _ServesAssets,
)


class Serving(_ServesAssets):
    """Bare host for the mixin, with a controllable If-None-Match header."""

    def __init__(self, if_none_match: list[str] | None = None) -> None:
        self.request = MagicMock()
        self.request.headers.get_list.return_value = if_none_match or []


ASSETS = "canvas_theme_kit.handlers.assets"


@contextmanager
def patch_store() -> Iterator[SimpleNamespace]:
    """Patch the store functions the handler imported by name.

    The handler imports these as bare names rather than reaching through the
    module, because Canvas's RestrictedPython sandbox forbids attribute
    access on a plugin's own modules. Patching has to follow suit.
    """
    with (
        patch(f"{ASSETS}.published_css") as published_css,
        patch(f"{ASSETS}.published_tokens_css") as published_tokens_css,
        patch(f"{ASSETS}.get_theme") as get_theme,
    ):
        yield SimpleNamespace(
            published_css=published_css,
            published_tokens_css=published_tokens_css,
            get_theme=get_theme,
        )


def only(responses: list) -> Any:
    """Unwrap a single-response handler return.

    Typed Any deliberately: the SDK's Response is constructed by the handler and
    these tests assert on its attributes, not on its type.
    """
    assert len(responses) == 1
    return responses[0]


class TestCachePolicy:
    """These assertions are the point of the module, not incidental detail."""

    @pytest.mark.parametrize("directive", ["no-cache", "no-store", "must-revalidate"])
    def test_published_policy_never_forbids_serving_stale(self, directive: str) -> None:
        # Each of these requires a successful revalidation before reuse, which
        # puts a round trip in front of first paint while the header still looks
        # reasonable. That is exactly the flash this policy exists to remove.
        assert directive not in CACHE_CONTROL

    def test_published_policy_allows_stale_while_revalidate(self) -> None:
        assert "stale-while-revalidate" in CACHE_CONTROL
        assert "max-age=300" in CACHE_CONTROL

    def test_published_policy_is_private(self) -> None:
        # The routes are session-gated, so a shared cache must not store them.
        assert CACHE_CONTROL.startswith("private")

    def test_preview_policy_forbids_reuse(self) -> None:
        # Preview is the deliberate exception: an editor must see their own
        # change, and the route is staff-only and low traffic.
        assert "no-store" in PREVIEW_CACHE_CONTROL
        assert "private" in PREVIEW_CACHE_CONTROL


class TestConditionalGet:
    def test_serves_200_with_etag_and_cache_control(self) -> None:
        response = only(Serving()._serve(b".a{}", "text/css"))

        assert response.status_code == HTTPStatus.OK
        assert response.headers["Cache-Control"] == CACHE_CONTROL
        assert response.headers["ETag"].startswith('"')

    def test_etag_is_derived_from_the_bytes(self) -> None:
        # Derived from content rather than a version number, so it stays correct
        # when someone publishes without bumping anything.
        first = only(Serving()._serve(b".a{}", "text/css")).headers["ETag"]
        same = only(Serving()._serve(b".a{}", "text/css")).headers["ETag"]
        other = only(Serving()._serve(b".b{}", "text/css")).headers["ETag"]

        assert first == same
        assert first != other

    def test_304_on_matching_strong_etag(self) -> None:
        etag = only(Serving()._serve(b".a{}", "text/css")).headers["ETag"]

        response = only(Serving([etag])._serve(b".a{}", "text/css"))

        assert response.status_code == HTTPStatus.NOT_MODIFIED

    def test_304_on_matching_weak_etag(self) -> None:
        # The regression that mattered: Canvas's edge gzips text/css and marks
        # the ETag weak on the way out, so the browser sends back W/"<hash>". A
        # verbatim comparison never matched and every revalidation returned a
        # full body instead of a 304.
        etag = only(Serving()._serve(b".a{}", "text/css")).headers["ETag"]

        response = only(Serving([f"W/{etag}"])._serve(b".a{}", "text/css"))

        assert response.status_code == HTTPStatus.NOT_MODIFIED

    def test_304_on_wildcard(self) -> None:
        response = only(Serving(["*"])._serve(b".a{}", "text/css"))
        assert response.status_code == HTTPStatus.NOT_MODIFIED

    def test_200_when_etag_does_not_match(self) -> None:
        response = only(Serving(['"stale"'])._serve(b".a{}", "text/css"))
        assert response.status_code == HTTPStatus.OK

    def test_reads_every_tag_not_just_the_first(self) -> None:
        # The SDK treats If-None-Match as list-valued, so headers.get() would
        # return only the first tag and miss a match further down the list.
        etag = only(Serving()._serve(b".a{}", "text/css")).headers["ETag"]
        serving = Serving(['"other"', etag])

        response = only(serving._serve(b".a{}", "text/css"))

        assert response.status_code == HTTPStatus.NOT_MODIFIED
        assert serving.request.headers.get_list.mock_calls == [call("If-None-Match")]

    def test_304_carries_cache_headers(self) -> None:
        etag = only(Serving()._serve(b".a{}", "text/css")).headers["ETag"]
        response = only(Serving([etag])._serve(b".a{}", "text/css"))

        assert response.headers["Cache-Control"] == CACHE_CONTROL
        assert response.headers["ETag"] == etag

    def test_custom_cache_control_is_honored(self) -> None:
        response = only(
            Serving()._serve(b".a{}", "text/css", PREVIEW_CACHE_CONTROL)
        )
        assert response.headers["Cache-Control"] == PREVIEW_CACHE_CONTROL


class TestNotFound:
    def test_unpublished_theme_404s_rather_than_serving_empty_css(self) -> None:
        # An empty 200 is indistinguishable from a published theme with no
        # rules, which would turn a misconfiguration into a silent one.
        response = only(Serving()._not_found("missing"))

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert b"missing" in response.content
        assert "no-store" in response.headers["Cache-Control"]


class TestThemeAssetsRoutes:
    def _handler(self, slug: str = "default") -> ThemeAssets:
        handler = ThemeAssets.__new__(ThemeAssets)
        handler.request = MagicMock()
        handler.request.headers.get_list.return_value = []
        handler.request.path_params = {"slug": slug}
        return handler

    def test_core_css_serves_published_stylesheet(self) -> None:
        with patch_store() as mock_store:
            mock_store.published_css.return_value = ":root{--ctk-a:1;}"

            response = only(self._handler().core_css())

            assert response.status_code == HTTPStatus.OK
            assert mock_store.published_css.mock_calls == [call("default")]

    def test_core_css_404s_for_unpublished_theme(self) -> None:
        with patch_store() as mock_store:
            mock_store.published_css.return_value = None

            response = only(self._handler("ghost").core_css())

            assert response.status_code == HTTPStatus.NOT_FOUND
            assert mock_store.published_css.mock_calls == [call("ghost")]

    def test_tokens_css_serves_token_block_only(self) -> None:
        with patch_store() as mock_store:
            mock_store.published_tokens_css.return_value = ":root{--ctk-a:1;}"

            response = only(self._handler().tokens_css())

            assert response.content == b":root{--ctk-a:1;}"
            assert mock_store.published_tokens_css.mock_calls == [call("default")]

    def test_core_js_is_served_from_the_package(self) -> None:
        with patch("canvas_theme_kit.handlers.assets.render_to_string") as mock_render:
            mock_render.return_value = "/* js */"

            response = only(self._handler().core_js())

            assert response.status_code == HTTPStatus.OK
            assert mock_render.mock_calls == [call("static/core.js")]

    def test_authenticate_accepts_any_logged_in_session(self) -> None:
        # Patient portal pages are a primary consumer, so this cannot narrow to
        # staff.
        handler = ThemeAssets.__new__(ThemeAssets)
        assert handler.authenticate(MagicMock(logged_in_user={"id": "p1"})) is True

    def test_authenticate_rejects_anonymous(self) -> None:
        handler = ThemeAssets.__new__(ThemeAssets)
        assert handler.authenticate(MagicMock(logged_in_user=None)) is False


class TestThemePreviewRoute:
    def _handler(self, slug: str = "default") -> ThemePreview:
        handler = ThemePreview.__new__(ThemePreview)
        handler.request = MagicMock()
        handler.request.headers.get_list.return_value = []
        handler.request.path_params = {"slug": slug}
        handler.secrets = {"DS_EDITOR_ROLES": "designer"}
        return handler

    def test_forbids_staff_without_the_editor_role(self) -> None:
        with patch("canvas_theme_kit.handlers.assets.can_edit", return_value=False), \
             patch("canvas_theme_kit.handlers.assets.current_staff"):
            response = only(self._handler().preview_css())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "no-store" in response.headers["Cache-Control"]

    def test_renders_draft_for_an_authorized_editor(self) -> None:
        theme = MagicMock(draft_css=".a{color:red}", draft_tokens={"color-a": "#fff"})

        with patch("canvas_theme_kit.handlers.assets.can_edit", return_value=True), \
             patch("canvas_theme_kit.handlers.assets.current_staff"), \
             patch_store() as mock_store:
            mock_store.get_theme.return_value = theme

            response = only(self._handler().preview_css())

        assert response.status_code == HTTPStatus.OK
        assert b".a{color:red}" in response.content
        # Draft preview must never be stored, or the editor sees a stale render.
        assert response.headers["Cache-Control"] == PREVIEW_CACHE_CONTROL

    def test_404s_for_unknown_theme(self) -> None:
        with patch("canvas_theme_kit.handlers.assets.can_edit", return_value=True), \
             patch("canvas_theme_kit.handlers.assets.current_staff"), \
             patch_store() as mock_store:
            mock_store.get_theme.return_value = None

            response = only(self._handler("ghost").preview_css())

        assert response.status_code == HTTPStatus.NOT_FOUND
