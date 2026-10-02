"""Tests for the demo page and its diagnostic route."""

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from canvas_theme_kit_demo.handlers.demo_page import DemoPage

PAGE = "canvas_theme_kit_demo.handlers.demo_page"


@pytest.fixture
def handler() -> DemoPage:
    page = DemoPage.__new__(DemoPage)
    page.request = MagicMock()
    page.request.query_params = {}
    return page


def only(responses: list) -> Any:
    assert len(responses) == 1
    return responses[0]


class TestAuthenticate:
    """SimpleAPIBase.authenticate returns False by default, so without this
    override every request is refused."""

    def test_admits_any_logged_in_session(self, handler: DemoPage) -> None:
        credentials = MagicMock(logged_in_user={"id": "u1", "type": "Patient"})
        assert handler.authenticate(credentials) is True

    def test_refuses_a_request_with_no_session(self, handler: DemoPage) -> None:
        assert handler.authenticate(MagicMock(logged_in_user=None)) is False


class TestPage:
    def test_inlines_the_token_block_into_the_template(self, handler: DemoPage) -> None:
        with patch(f"{PAGE}.cached_tokens", return_value={"color-accent": "#f00"}), \
             patch(f"{PAGE}.render_to_string", return_value="<html></html>") as render:
            response = only(handler.page())

        assert response.status_code == HTTPStatus.OK
        assert render.call_args == call(
            "templates/page.html",
            {
                "ctk_tokens_css": ":root{--ctk-color-accent:#f00;}",
                "ctk_token_count": 1,
                "ctk_slug": "default",
                "ctk_has_theme": True,
            },
        )

    def test_reads_the_tokens_once_through_the_cache(self, handler: DemoPage) -> None:
        """The block and the count come from one cached read. Reading the map
        uncached as well put two queries on every render, warm cache or not."""
        with patch(f"{PAGE}.cached_tokens", return_value={}) as tokens, \
             patch(f"{PAGE}.render_to_string", return_value=""):
            handler.page()

        assert tokens.mock_calls == [call("default")]

    def test_honors_the_theme_query_parameter(self, handler: DemoPage) -> None:
        handler.request.query_params = {"theme": "clinic-b"}

        with patch(f"{PAGE}.cached_tokens", return_value={}) as tokens, \
             patch(f"{PAGE}.render_to_string", return_value="") as render:
            handler.page()

        assert tokens.mock_calls == [call("clinic-b")]
        assert render.call_args.args[1]["ctk_slug"] == "clinic-b"
        assert render.call_args.args[1]["ctk_has_theme"] is False


class TestTokens:
    def test_reports_what_the_namespace_returned(self, handler: DemoPage) -> None:
        with patch(f"{PAGE}.cached_tokens", return_value={"space-4": "1rem"}):
            response = only(handler.tokens())

        assert response.status_code == HTTPStatus.OK
        assert json.loads(response.content) == {
            "theme": "default",
            "token_count": 1,
            "tokens": {"space-4": "1rem"},
            "inline_css": ":root{--ctk-space-4:1rem;}",
            "reading_shared_namespace": True,
        }

    def test_distinguishes_an_empty_read(self, handler: DemoPage) -> None:
        # The route exists so "the page has fallback colors" can be traced to a
        # cause. An empty read has to say so plainly.
        with patch(f"{PAGE}.cached_tokens", return_value={}):
            body = json.loads(only(handler.tokens()).content)

        assert body["reading_shared_namespace"] is False
        assert body["inline_css"] == ":root{}"
