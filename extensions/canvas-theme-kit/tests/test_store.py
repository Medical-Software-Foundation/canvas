"""Tests for theme persistence, publishing and the cached read path.

The invariants worth protecting here are that publishing is append-only, that
exactly one revision is active at a time, and that a cache failure can never
take down a page render or a publish.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, call, patch

import pytest

from canvas_theme_kit import store
from canvas_theme_kit.theming import ValidationError


@pytest.fixture
def cache() -> Iterator[MagicMock]:
    with patch("canvas_theme_kit.store.get_cache") as get_cache:
        client = MagicMock()
        client.get.return_value = None
        get_cache.return_value = client
        yield client


def make_theme(slug: str = "default", **kwargs: object) -> MagicMock:
    theme = MagicMock(slug=slug, **kwargs)
    return theme


class TestGetTheme:
    def test_returns_theme(self) -> None:
        with patch("canvas_theme_kit.store.Theme") as mock_theme:
            sentinel = MagicMock()
            mock_theme.objects.get.return_value = sentinel

            assert store.get_theme("default") is sentinel
            assert mock_theme.objects.mock_calls == [call.get(slug="default")]

    def test_returns_none_when_missing(self) -> None:
        class DoesNotExist(Exception):
            pass

        with patch("canvas_theme_kit.store.Theme") as mock_theme:
            mock_theme.DoesNotExist = DoesNotExist
            mock_theme.objects.get.side_effect = DoesNotExist()

            assert store.get_theme("ghost") is None


class TestActiveRevision:
    def test_none_when_theme_missing(self) -> None:
        with patch("canvas_theme_kit.store.get_theme", return_value=None):
            assert store.active_revision("ghost") is None

    def test_returns_highest_active_revision(self) -> None:
        revision = MagicMock()
        theme = make_theme()

        with patch("canvas_theme_kit.store.get_theme", return_value=theme),              patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            chain = mock_rev.objects.filter.return_value.order_by.return_value
            chain.first.return_value = revision

            assert store.active_revision("default") is revision
            # Queried through the manager, not `theme.revisions` — the reverse
            # accessor on a CustomModel returns None inside Canvas's sandbox.
            assert mock_rev.objects.filter.call_args == call(
                theme=theme, is_active=True
            )


class TestPublishedCss:
    def test_returns_none_when_never_published(self, cache: MagicMock) -> None:
        # None, not empty string: the route turns this into a 404 so a
        # misconfiguration is visible rather than silent.
        with patch("canvas_theme_kit.store.active_revision", return_value=None):
            assert store.published_css("default") is None

    def test_renders_tokens_then_css(self, cache: MagicMock) -> None:
        revision = MagicMock(css=".a{color:red}", tokens={"color-a": "#fff"})

        with patch("canvas_theme_kit.store.active_revision", return_value=revision):
            rendered = store.published_css("default")

        assert rendered is not None
        assert rendered.index(":root") < rendered.index(".a{color:red}")

    def test_serves_from_cache_without_touching_the_database(
        self, cache: MagicMock
    ) -> None:
        cache.get.return_value = ":root{--ctk-cached:1;}"

        with patch("canvas_theme_kit.store.active_revision") as active:
            assert store.published_css("default") == ":root{--ctk-cached:1;}"
            assert active.mock_calls == []

    def test_caches_with_a_short_ttl(self, cache: MagicMock) -> None:
        revision = MagicMock(css="", tokens={"color-a": "#fff"})

        with patch("canvas_theme_kit.store.active_revision", return_value=revision):
            store.published_css("default")

        set_call = [c for c in cache.mock_calls if c[0] == "set"][0]
        assert set_call.kwargs["timeout_seconds"] == store.CACHE_TTL_SECONDS

    def test_cache_failure_does_not_break_the_render(self, cache: MagicMock) -> None:
        # A page render must not fail because the cache is unavailable.
        cache.get.side_effect = RuntimeError("cache down")
        cache.set.side_effect = RuntimeError("cache down")
        revision = MagicMock(css=".a{}", tokens={})

        with patch("canvas_theme_kit.store.active_revision", return_value=revision):
            assert store.published_css("default") is not None


class TestSaveDraft:
    def test_validates_and_stores(self) -> None:
        theme = make_theme()

        store.save_draft(theme, ".a{color:red}", {"color-a": "#fff"}, "staff-1")

        assert theme.draft_css == ".a{color:red}"
        assert theme.draft_tokens == {"color-a": "#fff"}
        assert theme.updated_by == "staff-1"
        theme.save.assert_called_once_with()

    def test_rejects_unsafe_css_before_storing(self) -> None:
        theme = make_theme()

        with pytest.raises(ValidationError):
            store.save_draft(theme, "@import 'x.css';", {}, "staff-1")

        theme.save.assert_not_called()

    def test_rejects_unsafe_tokens(self) -> None:
        theme = make_theme()

        with pytest.raises(ValidationError):
            store.save_draft(theme, "", {"color-a": "red} body{display:none"}, "s")

        theme.save.assert_not_called()


class TestPublish:
    def _theme(self) -> MagicMock:
        return make_theme(draft_css=".a{color:red}", draft_tokens={"color-a": "#fff"})

    @staticmethod
    def _latest(mock_rev: MagicMock, revision: int | None) -> None:
        """Point the manager chain at an existing latest revision, or none.

        The query projects with `.values_list("revision", flat=True)` so it never
        hydrates the row's css blob — the mock chain mirrors that.
        """
        chain = (
            mock_rev.objects.filter.return_value.order_by.return_value
            .values_list.return_value
        )
        chain.first.return_value = revision

    def test_first_publish_creates_revision_one(self, cache: MagicMock) -> None:
        theme = self._theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            self._latest(mock_rev, None)
            store.publish(theme, "staff-1", "first")

        kwargs = mock_rev.objects.create.call_args.kwargs
        assert kwargs["revision"] == 1
        assert kwargs["is_active"] is True
        assert kwargs["published_by"] == "staff-1"
        assert kwargs["note"] == "first"

    def test_subsequent_publish_increments(self, cache: MagicMock) -> None:
        theme = self._theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            self._latest(mock_rev, 6)
            store.publish(theme, "staff-1")

        assert mock_rev.objects.create.call_args.kwargs["revision"] == 7

    def test_deactivates_the_previous_active_revision(self, cache: MagicMock) -> None:
        theme = self._theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            self._latest(mock_rev, 2)
            store.publish(theme, "staff-1")

        # The previous active revision is deactivated before the new one lands.
        assert call(theme=theme, is_active=True) in mock_rev.objects.filter.call_args_list
        mock_rev.objects.filter.return_value.update.assert_called_once_with(
            is_active=False
        )

    def test_stores_a_content_hash(self, cache: MagicMock) -> None:
        theme = self._theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            self._latest(mock_rev, None)
            store.publish(theme, "staff-1")

        assert len(mock_rev.objects.create.call_args.kwargs["content_hash"]) == 32

    def test_invalidates_the_cache(self, cache: MagicMock) -> None:
        theme = self._theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            self._latest(mock_rev, None)
            store.publish(theme, "staff-1")

        deleted = {c.args[0] for c in cache.delete.call_args_list}
        assert "ctk:v1:css:default" in deleted
        assert "ctk:v1:tokens:default" in deleted

    def test_revalidates_the_draft_before_publishing(self, cache: MagicMock) -> None:
        # The last gate before content reaches a patient-facing page. The
        # validator may have tightened since the draft was saved.
        theme = make_theme(draft_css="@import 'evil.css';", draft_tokens={})

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            with pytest.raises(ValidationError):
                store.publish(theme, "staff-1")

            mock_rev.objects.create.assert_not_called()


class TestRollback:
    def test_republishes_old_content_as_a_new_revision(self, cache: MagicMock) -> None:
        source = MagicMock(css=".old{}", tokens={"color-a": "#000"})
        theme = make_theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.objects.get.return_value = source
            chain = (
                mock_rev.objects.filter.return_value.order_by.return_value
                .values_list.return_value
            )
            chain.first.return_value = 6
            store.rollback(theme, 3, "staff-1")

        kwargs = mock_rev.objects.create.call_args.kwargs
        # History is never rewritten: restoring revision 3 produces revision 7.
        assert kwargs["revision"] == 7
        assert kwargs["css"] == ".old{}"
        assert kwargs["tokens"] == {"color-a": "#000"}
        assert "rollback to revision 3" in kwargs["note"]

    def test_does_not_mutate_the_source_revision(self, cache: MagicMock) -> None:
        source = MagicMock(css=".old{}", tokens={})
        theme = make_theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.objects.get.return_value = source
            chain = (
                mock_rev.objects.filter.return_value.order_by.return_value
                .values_list.return_value
            )
            chain.first.return_value = 1
            store.rollback(theme, 1, "staff-1")

        source.save.assert_not_called()
        source.delete.assert_not_called()

    def test_rejects_unknown_revision(self, cache: MagicMock) -> None:
        class DoesNotExist(Exception):
            pass

        theme = make_theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.DoesNotExist = DoesNotExist
            mock_rev.objects.get.side_effect = DoesNotExist()

            with pytest.raises(ValidationError, match="does not exist"):
                store.rollback(theme, 99, "staff-1")


class TestDefaultTokens:
    def test_loads_and_validates_the_starter_set(self) -> None:
        with patch("canvas_theme_kit.store.render_to_string") as mock_render:
            mock_render.return_value = '{"color-accent": "#0b5fff"}'

            assert store.default_tokens() == {"color-accent": "#0b5fff"}
            assert mock_render.mock_calls == [call("static/default_tokens.json")]

    def test_returns_empty_when_unreadable(self) -> None:
        # A missing starter set should leave an admin with an empty theme to
        # fill in, not a plugin that cannot create themes.
        with patch("canvas_theme_kit.store.render_to_string") as mock_render:
            mock_render.side_effect = RuntimeError("no such template")

            assert store.default_tokens() == {}

    def test_returns_empty_when_invalid(self) -> None:
        with patch("canvas_theme_kit.store.render_to_string") as mock_render:
            mock_render.return_value = '{"Bad Name": "#fff"}'

            assert store.default_tokens() == {}


class TestInvalidate:
    def test_survives_a_cache_failure(self, cache: MagicMock) -> None:
        # A publish must not fail because the cache is unavailable.
        cache.delete.side_effect = RuntimeError("cache down")
        store.invalidate("default")


class TestResetDraft:
    def test_restores_starter_tokens_and_clears_css(self) -> None:
        theme = make_theme(draft_css=".a{color:red}", draft_tokens={"color-a": "#f00"})

        with patch("canvas_theme_kit.store.default_tokens") as defaults:
            defaults.return_value = {"color-accent": "#0b5fff"}
            store.reset_draft(theme, "staff-1")

        assert theme.draft_css == ""
        assert theme.draft_tokens == {"color-accent": "#0b5fff"}
        assert theme.updated_by == "staff-1"
        theme.save.assert_called_once_with()

    def test_publishes_nothing(self, cache: MagicMock) -> None:
        # A draft-only operation: live pages keep serving the published revision
        # until someone with publish rights ships the reset.
        theme = make_theme(draft_css=".a{}", draft_tokens={})

        with patch("canvas_theme_kit.store.default_tokens", return_value={}), \
             patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            store.reset_draft(theme, "staff-1")
            mock_rev.objects.create.assert_not_called()

        cache.delete.assert_not_called()


class TestLoadRevisionIntoDraft:
    def test_copies_revision_content_into_the_draft(self) -> None:
        source = MagicMock(css=".old{}", tokens={"color-a": "#000"})
        theme = make_theme(draft_css=".new{}", draft_tokens={"color-a": "#fff"})

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.objects.get.return_value = source
            store.load_revision_into_draft(theme, 2, "staff-1")

            assert mock_rev.objects.get.call_args == call(theme=theme, revision=2)

        assert theme.draft_css == ".old{}"
        assert theme.draft_tokens == {"color-a": "#000"}
        theme.save.assert_called_once_with()

    def test_does_not_republish(self, cache: MagicMock) -> None:
        source = MagicMock(css="", tokens={})
        theme = make_theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.objects.get.return_value = source
            store.load_revision_into_draft(theme, 1, "staff-1")
            mock_rev.objects.create.assert_not_called()

        cache.delete.assert_not_called()

    def test_rejects_unknown_revision(self) -> None:
        class DoesNotExist(Exception):
            pass

        theme = make_theme()

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.DoesNotExist = DoesNotExist
            mock_rev.objects.get.side_effect = DoesNotExist()

            with pytest.raises(ValidationError, match="does not exist"):
                store.load_revision_into_draft(theme, 99, "staff-1")


class TestQueryShape:
    def test_next_revision_number_does_not_hydrate_the_row(
        self, cache: MagicMock
    ) -> None:
        """Only the integer is needed; a hydrated row drags the css blob along."""
        theme = make_theme(draft_css="", draft_tokens={})

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            chain = (
                mock_rev.objects.filter.return_value.order_by.return_value
                .values_list.return_value
            )
            chain.first.return_value = 4
            store.publish(theme, "staff-1")

            values_list = (
                mock_rev.objects.filter.return_value.order_by.return_value.values_list
            )
            assert values_list.call_args == call("revision", flat=True)

        assert mock_rev.objects.create.call_args.kwargs["revision"] == 5


class TestTokensCssDoesNotHydrateTheRevision:
    def test_projects_to_the_tokens_column(self, cache: MagicMock) -> None:
        """tokens.css reads one column. A hydrated revision row carries up to
        256 KB of css that this route never serves, loaded on every cache miss."""
        with patch("canvas_theme_kit.store.get_theme", return_value=make_theme()), \
             patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            chain = mock_rev.objects.filter.return_value.order_by.return_value
            chain.values.return_value.first.return_value = {"tokens": {"color-a": "#fff"}}

            assert store.published_tokens_css("default") == ":root{--ctk-color-a:#fff;}"

        assert chain.values.call_args == call("tokens")
        assert chain.first.mock_calls == []

    def test_none_when_the_theme_was_never_published(self, cache: MagicMock) -> None:
        with patch("canvas_theme_kit.store.get_theme", return_value=make_theme()), \
             patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            chain = mock_rev.objects.filter.return_value.order_by.return_value
            chain.values.return_value.first.return_value = None

            assert store.published_tokens_css("default") is None

    def test_none_when_the_theme_does_not_exist(self, cache: MagicMock) -> None:
        with patch("canvas_theme_kit.store.get_theme", return_value=None):
            assert store.published_tokens_css("ghost") is None


class TestRollbackRevalidates:
    def test_refuses_content_the_current_validator_rejects(self, cache: MagicMock) -> None:
        """Publish re-validates because the validator may have tightened since
        the content was saved. Rollback replays content that is older still,
        so it needs the same gate, or it becomes the way around it."""
        source = MagicMock(css=".a { background: url(https://evil.example/x); }", tokens={})

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.objects.get.return_value = source
            with pytest.raises(ValidationError, match="Off-origin"):
                store.rollback(make_theme(), 3, "staff-1")

        assert mock_rev.objects.create.mock_calls == []

    def test_refuses_tokens_the_current_validator_rejects(self, cache: MagicMock) -> None:
        source = MagicMock(css="", tokens={"brand": "url(https://evil.example/x)"})

        with patch("canvas_theme_kit.store.ThemeRevision") as mock_rev:
            mock_rev.objects.get.return_value = source
            with pytest.raises(ValidationError):
                store.rollback(make_theme(), 3, "staff-1")

        assert mock_rev.objects.create.mock_calls == []
