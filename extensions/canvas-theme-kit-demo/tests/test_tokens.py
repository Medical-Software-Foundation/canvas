"""Tests for reading published tokens out of the shared namespace."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from canvas_theme_kit_demo import tokens as tokens_module
from canvas_theme_kit_demo.tokens import (
    EMPTY_BLOCK,
    TOKEN_PREFIX,
    active_tokens,
    cached_tokens,
    inline_tokens_css,
    render_tokens_css,
)

TOKENS = "canvas_theme_kit_demo.tokens"


@pytest.fixture
def cache() -> Iterator[MagicMock]:
    with patch(f"{TOKENS}.get_cache") as get_cache:
        client = MagicMock()
        client.get.return_value = None
        get_cache.return_value = client
        yield client


class TestRenderTokensCss:
    def test_renders_prefixed_root_block(self) -> None:
        assert render_tokens_css({"color-accent": "#ff0000"}) == (
            ":root{--ctk-color-accent:#ff0000;}"
        )

    def test_sorts_by_name(self) -> None:
        assert render_tokens_css({"b": "2", "a": "1"}) == ":root{--ctk-a:1;--ctk-b:2;}"

    def test_empty_tokens_still_render_a_valid_block(self) -> None:
        # An empty string here would produce an empty <style> element; a valid
        # empty rule keeps the page's own fallbacks working.
        assert render_tokens_css({}) == EMPTY_BLOCK

    def test_matches_the_publishers_renderer(self) -> None:
        """Byte-identical to canvas_theme_kit's renderer, or the inline block and
        the linked stylesheet would declare different values for one token."""
        source = (
            Path(__file__).resolve().parent.parent.parent
            / "canvas-theme-kit"
            / "canvas_theme_kit"
            / "theming.py"
        )
        if not source.exists():
            pytest.skip("canvas-theme-kit is not checked out alongside this plugin")

        # Load the publisher's module directly. It depends only on the standard
        # library, so it imports cleanly outside its own plugin.
        spec = importlib.util.spec_from_file_location("_ctk_theming", source)
        assert spec and spec.loader
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)

        assert publisher.TOKEN_PREFIX == TOKEN_PREFIX

        for sample in (
            {},
            {"color-accent": "#ff0000"},
            {"color-accent": "#ff0000", "space-4": "1rem", "a-token": "1"},
            {"font-family": "system-ui, 'Segoe UI', sans-serif"},
        ):
            assert publisher.render_tokens_css(sample) == render_tokens_css(sample)


class TestActiveTokens:
    def test_returns_tokens_of_the_active_revision(self) -> None:
        theme = MagicMock()

        with patch(f"{TOKENS}.Theme") as mock_theme, \
             patch(f"{TOKENS}.ThemeRevision") as mock_rev:
            mock_theme.objects.get.return_value = theme
            # Projected with values_list: this is the page-render hot path, and a
            # hydrated row carries a css blob nothing here reads.
            chain = (
                mock_rev.objects.filter.return_value.order_by.return_value
                .values_list.return_value
            )
            chain.first.return_value = {"color-accent": "#ff0000"}

            assert active_tokens("default") == {"color-accent": "#ff0000"}
            assert mock_theme.objects.get.call_args == call(slug="default")
            # Queried through the manager: a reverse accessor on a CustomModel
            # returns None inside Canvas's sandbox.
            assert mock_rev.objects.filter.call_args == call(
                theme=theme, is_active=True
            )
            values_list = (
                mock_rev.objects.filter.return_value.order_by.return_value.values_list
            )
            assert values_list.call_args == call("tokens", flat=True)

    def test_empty_when_theme_does_not_exist(self) -> None:
        class DoesNotExist(Exception):
            pass

        with patch(f"{TOKENS}.Theme") as mock_theme:
            mock_theme.DoesNotExist = DoesNotExist
            mock_theme.objects.get.side_effect = DoesNotExist()

            assert active_tokens("ghost") == {}

    def test_empty_when_nothing_is_published(self) -> None:
        with patch(f"{TOKENS}.Theme"), patch(f"{TOKENS}.ThemeRevision") as mock_rev:
            mock_rev.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None

            assert active_tokens("default") == {}

    def test_tolerates_a_revision_with_null_tokens(self) -> None:
        with patch(f"{TOKENS}.Theme"), patch(f"{TOKENS}.ThemeRevision") as mock_rev:
            chain = (
                mock_rev.objects.filter.return_value.order_by.return_value
                .values_list.return_value
            )
            chain.first.return_value = None

            assert active_tokens("default") == {}


class TestCachedTokens:
    """The token map is what gets cached, not the rendered block.

    The page needs the map itself (it shows a token count) as well as the block.
    When only the block was cached, the page read the map straight from the
    database on every render, so the cache saved a string join and none of the
    queries.
    """

    def test_reads_through_on_a_miss(self, cache: MagicMock) -> None:
        with patch(f"{TOKENS}.active_tokens", return_value={"color-accent": "#f00"}) as reader:
            assert cached_tokens("default") == {"color-accent": "#f00"}

        assert reader.mock_calls == [call("default")]

    def test_serves_from_cache_without_querying(self, cache: MagicMock) -> None:
        cache.get.return_value = '{"cached": "1"}'

        with patch(f"{TOKENS}.active_tokens") as reader:
            assert cached_tokens("default") == {"cached": "1"}
            assert reader.mock_calls == []

    def test_caches_with_a_short_ttl(self, cache: MagicMock) -> None:
        with patch(f"{TOKENS}.active_tokens", return_value={"a": "1"}):
            cached_tokens("default")

        assert cache.set.call_args == call(
            f"{tokens_module._CACHE_KEY}:default",
            '{"a": "1"}',
            timeout_seconds=tokens_module.CACHE_TTL_SECONDS,
        )

    def test_cache_failure_falls_through_to_a_live_read(self, cache: MagicMock) -> None:
        # A page render must not fail because the cache is unavailable — an
        # unstyled page is exactly what this code exists to prevent.
        cache.get.side_effect = RuntimeError("cache down")
        cache.set.side_effect = RuntimeError("cache down")

        with patch(f"{TOKENS}.active_tokens", return_value={"color-accent": "#f00"}):
            assert cached_tokens("default") == {"color-accent": "#f00"}

    def test_keys_the_cache_per_theme(self, cache: MagicMock) -> None:
        with patch(f"{TOKENS}.active_tokens", return_value={}):
            cached_tokens("clinic-b")

        assert cache.set.call_args.args[0].endswith(":clinic-b")


class TestInlineTokensCss:
    def test_renders_the_cached_tokens(self) -> None:
        with patch(f"{TOKENS}.cached_tokens", return_value={"color-accent": "#f00"}) as tokens:
            assert inline_tokens_css("default") == ":root{--ctk-color-accent:#f00;}"

        assert tokens.mock_calls == [call("default")]
