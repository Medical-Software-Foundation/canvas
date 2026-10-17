"""Tests for the staff-gated admin API.

The authorization assertions carry most of the weight. Every mutating route must
fail closed, and editing must stay separable from publishing — an editor who can
publish by accident defeats the reason the two permissions were split.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, call, patch

import pytest

from canvas_theme_kit.handlers.admin_api import ThemeAdminAPI
from canvas_theme_kit.theming import ValidationError

AUTH = "canvas_theme_kit.handlers.admin_api"


@contextmanager
def patch_store() -> Iterator[SimpleNamespace]:
    """Patch the store functions the handler imported under aliases.

    Canvas's RestrictedPython sandbox forbids attribute access on a plugin's
    own modules, so the handler imports each function by name and the tests
    patch those names.
    """
    with (
        patch(f"{AUTH}.store_get_theme") as get_theme,
        patch(f"{AUTH}.store_publish") as publish,
        patch(f"{AUTH}.store_rollback") as rollback,
        patch(f"{AUTH}.store_save_draft") as save_draft,
        patch(f"{AUTH}.store_default_tokens") as default_tokens,
        patch(f"{AUTH}.store_reset_draft") as reset_draft,
        patch(f"{AUTH}.store_load_into_draft") as load_into_draft,
        patch(f"{AUTH}.ThemeRevision") as revision_model,
    ):
        # Queried through the manager rather than `theme.revisions`: the reverse
        # accessor on a CustomModel returns None inside Canvas's sandbox.
        # Queries project with .values()/.values_list() now, so the mock chain
        # ends in a dict rather than a model instance.
        chain = revision_model.objects.filter.return_value.order_by.return_value.values.return_value
        chain.first.return_value = {"revision": 3, "content_hash": "h" * 32}
        chain.__iter__.return_value = iter([])
        revision_model.objects.filter.return_value.values.return_value = []
        # Serializable defaults: these routes JSON-encode what the store
        # returns, so bare MagicMocks would fail encoding rather than the
        # behavior under test.
        publish.return_value = MagicMock(
            revision=1, content_hash="h" * 32, published_by="staff-1", note=""
        )
        rollback.return_value = MagicMock(revision=2, content_hash="h" * 32)
        yield SimpleNamespace(
            revision_model=revision_model,
            revision_chain=chain,
            get_theme=get_theme,
            publish=publish,
            rollback=rollback,
            save_draft=save_draft,
            default_tokens=default_tokens,
            reset_draft=reset_draft,
            load_into_draft=load_into_draft,
        )


def only(responses: list) -> Any:
    """Unwrap a single-response handler return.

    Typed Any deliberately: the SDK's Response is constructed by the handler and
    these tests assert on its attributes, not on its type.
    """
    assert len(responses) == 1
    return responses[0]


def make_theme(slug: str = "default") -> MagicMock:
    theme = MagicMock(
        slug=slug,
        title="Default",
        is_default=True,
        updated_at=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc),
        updated_by="staff-1",
        draft_css=".a{}",
        draft_tokens={"color-a": "#fff"},
    )
    return theme


@pytest.fixture
def handler() -> ThemeAdminAPI:
    api = ThemeAdminAPI.__new__(ThemeAdminAPI)
    api.request = MagicMock()
    api.request.path_params = {"slug": "default"}
    # Real headers, not a MagicMock: a mock Origin is truthy and only passed the
    # old suffix-match guard by accident. No Origin is what a same-origin
    # server-to-server call sends.
    api.request.headers = {"host": "acme.canvasmedical.com"}
    api.request.json.return_value = {}
    api.secrets = {"DS_EDITOR_ROLES": "designer"}
    return api


def allow(edit: bool = True, publish: bool = True) -> tuple[Any, Any, Any]:
    """Patch the authorization gate and staff resolution together."""
    return (
        patch(f"{AUTH}.can_edit", return_value=edit),
        patch(f"{AUTH}.can_publish", return_value=publish),
        patch(f"{AUTH}.current_staff", return_value=MagicMock(id="staff-1")),
    )


class TestAuthorizationGate:
    """Every mutating route must fail closed, and say why."""

    @pytest.mark.parametrize(
        "method,body",
        [
            ("list_themes", {}),
            ("get_theme", {}),
            ("create_theme", {"slug": "x"}),
            ("save_draft", {"css": ""}),
        ],
    )
    def test_editor_routes_denied_without_edit_permission(
        self, handler: ThemeAdminAPI, method: str, body: dict
    ) -> None:
        handler.request.json.return_value = body
        a, b, c = allow(edit=False, publish=False)
        with a, b, c:
            response = only(getattr(handler, method)())

        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize("method", ["publish", "rollback"])
    def test_publisher_routes_denied_for_editor_only_staff(
        self, handler: ThemeAdminAPI, method: str
    ) -> None:
        # The split in practice: full edit rights, no ability to ship.
        a, b, c = allow(edit=True, publish=False)
        with a, b, c:
            response = only(getattr(handler, method)())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_denial_names_the_config_keys(self, handler: ThemeAdminAPI) -> None:
        # Deny-by-default means the likeliest cause is an install where the
        # allowlists were never set, so the error has to be actionable.
        a, b, c = allow(edit=False, publish=False)
        with a, b, c:
            response = only(handler.list_themes())

        body = response.content.decode()
        assert "DS_EDITOR_ROLES" in body
        assert "DS_PUBLISHER_ROLES" in body
        assert "/admin/roles" in body


class TestListRoles:
    def test_reports_codes_and_the_callers_permissions(
        self, handler: ThemeAdminAPI
    ) -> None:
        role = MagicMock(internal_code="designer")
        # `name` is a reserved MagicMock constructor kwarg, so it has to be set
        # after construction or `role.name` returns a child mock.
        role.name = "Designer"
        role.domain = "ADMINISTRATIVE"
        role.role_type = "NON_LICENSED"
        staff_member = MagicMock()
        staff_member.roles.all.return_value = [role]

        caller = MagicMock(id="staff-1")
        caller.roles.all.return_value = [role]

        with patch(f"{AUTH}.current_staff", return_value=caller), \
             patch(f"{AUTH}.can_edit", return_value=True), \
             patch(f"{AUTH}.can_publish", return_value=False), \
             patch(f"{AUTH}.Staff") as mock_staff:
            mock_staff.objects.all.return_value.prefetch_related.return_value = [
                staff_member
            ]
            response = only(handler.list_roles())

        body = response.content.decode()
        assert "designer" in body
        assert '"you_can_edit": true' in body.lower().replace(" ", " ")
        assert '"you_can_publish": false' in body.lower()

    def test_requires_a_staff_session(self, handler: ThemeAdminAPI) -> None:
        with patch(f"{AUTH}.current_staff", return_value=None):
            response = only(handler.list_roles())

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestReadRoutes:
    def test_list_themes(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store(), patch(f"{AUTH}.Theme") as mock_theme:
            mock_theme.objects.all.return_value.order_by.return_value = [make_theme()]
            response = only(handler.list_themes())

        assert response.status_code == HTTPStatus.OK
        assert "default" in response.content.decode()

    def test_get_theme_includes_draft_and_history(
        self, handler: ThemeAdminAPI
    ) -> None:
        theme = make_theme()

        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = theme
            history = [
                {
                    "revision": 3,
                    "content_hash": "h" * 32,
                    "is_active": True,
                    "published_at": datetime(2026, 9, 16, tzinfo=timezone.utc),
                    "published_by": "staff-1",
                    "note": "",
                }
            ]
            mock_store.revision_chain.__iter__.return_value = iter(history)
            response = only(handler.get_theme())

        body = response.content.decode()
        assert "draft_css" in body
        assert "revisions" in body

    def test_get_theme_404s_when_missing(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = None
            response = only(handler.get_theme())

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestCreateTheme:
    @pytest.mark.parametrize(
        "slug",
        # The last two pass str.isalnum(), which is Unicode-aware. Slugs land
        # in asset URLs and cache keys, so they are held to ASCII.
        ["", "Bad-Slug", "bad slug", "bad_slug", "BAD", "café", "theme１"],
    )
    def test_rejects_malformed_slug(self, handler: ThemeAdminAPI, slug: str) -> None:
        handler.request.json.return_value = {"slug": slug}
        a, b, c = allow()
        with a, b, c:
            response = only(handler.create_theme())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_rejects_an_overlong_title(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"slug": "clinic-b", "title": "x" * 201}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = None
            response = only(handler.create_theme())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Title" in response.content.decode()

    def test_rejects_duplicate_slug(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"slug": "default"}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(handler.create_theme())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "already exists" in response.content.decode()

    def test_creates_and_seeds_starter_tokens(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"slug": "clinic-b", "title": "Clinic B"}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store, \
             patch(f"{AUTH}.Theme") as mock_theme:
            mock_store.get_theme.return_value = None
            mock_store.default_tokens.return_value = {"color-accent": "#0b5fff"}
            mock_theme.objects.filter.return_value.exists.return_value = True
            mock_theme.objects.create.return_value = make_theme("clinic-b")

            response = only(handler.create_theme())

        assert response.status_code == HTTPStatus.CREATED
        kwargs = mock_theme.objects.create.call_args.kwargs
        assert kwargs["slug"] == "clinic-b"
        assert kwargs["draft_tokens"] == {"color-accent": "#0b5fff"}
        # First theme on a fresh install becomes the default; this is not one.
        assert kwargs["is_default"] is False

    def test_first_theme_becomes_default(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"slug": "first"}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store, \
             patch(f"{AUTH}.Theme") as mock_theme:
            mock_store.get_theme.return_value = None
            mock_store.default_tokens.return_value = {}
            mock_theme.objects.filter.return_value.exists.return_value = False
            mock_theme.objects.create.return_value = make_theme("first")

            handler.create_theme()

        assert mock_theme.objects.create.call_args.kwargs["is_default"] is True


class TestSaveDraft:
    def test_saves_valid_draft(self, handler: ThemeAdminAPI) -> None:
        theme = make_theme()
        handler.request.json.return_value = {"css": ".a{}", "tokens": {"color-a": "#fff"}}

        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = theme
            response = only(handler.save_draft())

        assert response.status_code == HTTPStatus.OK
        assert mock_store.save_draft.call_args.args[0] is theme

    def test_rejects_unsafe_css(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"css": "@import 'evil.css';"}

        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(handler.save_draft())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "@import" in response.content.decode()
        mock_store.save_draft.assert_not_called()

    def test_404s_for_unknown_theme(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = None
            response = only(handler.save_draft())

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestPublish:
    def test_publishes_and_reports_the_revision(self, handler: ThemeAdminAPI) -> None:
        theme = make_theme()
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = theme
            mock_store.publish.return_value = MagicMock(
                revision=4, content_hash="h" * 32, published_by="staff-1", note="ship"
            )
            response = only(handler.publish())

        assert response.status_code == HTTPStatus.OK
        assert '"revision": 4' in response.content.decode()

    def test_surfaces_validation_errors(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            mock_store.publish.side_effect = ValidationError("bad css")
            response = only(handler.publish())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "bad css" in response.content.decode()

    def test_404s_for_unknown_theme(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = None
            response = only(handler.publish())

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestRollback:
    def test_rolls_back_to_a_revision(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"revision": 2}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            mock_store.rollback.return_value = MagicMock(
                revision=7, content_hash="h" * 32
            )
            response = only(handler.rollback())

        body = response.content.decode()
        assert '"restored_from": 2' in body
        assert '"revision": 7' in body

    @pytest.mark.parametrize("value", [None, "abc", {}])
    def test_rejects_non_integer_revision(
        self, handler: ThemeAdminAPI, value: object
    ) -> None:
        handler.request.json.return_value = {"revision": value}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(handler.rollback())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_surfaces_unknown_revision(self, handler: ThemeAdminAPI) -> None:
        handler.request.json.return_value = {"revision": 99}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            mock_store.rollback.side_effect = ValidationError("does not exist")
            response = only(handler.rollback())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_404s_for_unknown_theme(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = None
            response = only(handler.rollback())

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestEditorUI:
    """The editor is reachable at a plain URL, not only via the app drawer."""

    def test_serves_the_editor_page(self, handler: ThemeAdminAPI) -> None:
        with patch(f"{AUTH}.render_to_string") as mock_render:
            mock_render.return_value = "<html>editor</html>"
            response = only(handler.editor_ui())

        assert response.status_code == HTTPStatus.OK
        assert mock_render.mock_calls == [call("templates/admin.html")]

    def test_rendering_the_shell_is_not_an_authorization_decision(
        self, handler: ThemeAdminAPI
    ) -> None:
        """No role check here, deliberately.

        An unconfigured install must still be able to open the page in order to
        reach /admin/roles and discover the codes to configure. Every action the
        page can take is gated individually.
        """
        with patch(f"{AUTH}.render_to_string", return_value="<html></html>"), \
             patch(f"{AUTH}.can_edit", return_value=False) as can_edit_mock, \
             patch(f"{AUTH}.can_publish", return_value=False):
            response = only(handler.editor_ui())

        assert response.status_code == HTTPStatus.OK
        assert can_edit_mock.mock_calls == []


class TestOriginGuard:
    """Mutating routes are same-origin only.

    These routes authenticate on the session cookie alone, so whether that is
    enough against CSRF depends on the instance's cookie policy — which a plugin
    cannot inspect. The guard removes the dependency on that assumption.
    """

    MUTATING = [
        "create_theme",
        "save_draft",
        "reset_draft",
        "load_draft",
        "publish",
        "rollback",
    ]

    @pytest.mark.parametrize("method", MUTATING)
    def test_rejects_a_foreign_origin(
        self, handler: ThemeAdminAPI, method: str
    ) -> None:
        handler.request.headers = {
            "origin": "https://evil.example",
            "host": "acme.canvasmedical.com",
        }
        a, b, c = allow()
        with a, b, c:
            response = only(getattr(handler, method)())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Cross-origin" in response.content.decode()

    @pytest.mark.parametrize("method", MUTATING)
    def test_allows_the_instances_own_origin(
        self, handler: ThemeAdminAPI, method: str
    ) -> None:
        handler.request.headers = {
            "origin": "https://acme.canvasmedical.com",
            "host": "acme.canvasmedical.com",
        }
        handler.request.json.return_value = {"slug": "x", "revision": 1, "css": ""}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(getattr(handler, method)())

        # Anything but the origin rejection: the guard let it through.
        assert "Cross-origin" not in response.content.decode()

    def test_allows_a_request_with_no_origin(self, handler: ThemeAdminAPI) -> None:
        # Server-to-server callers omit Origin, and they are not the CSRF threat.
        handler.request.headers = {"host": "acme.canvasmedical.com"}
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(handler.publish())

        assert "Cross-origin" not in response.content.decode()

    def test_read_routes_are_not_gated_on_origin(
        self, handler: ThemeAdminAPI
    ) -> None:
        # Reads are not state-changing, so the guard would add nothing.
        handler.request.headers = {
            "origin": "https://evil.example",
            "host": "acme.canvasmedical.com",
        }
        a, b, c = allow()
        with a, b, c, patch_store(), patch(f"{AUTH}.Theme") as mock_theme:
            mock_theme.objects.all.return_value.order_by.return_value = []
            response = only(handler.list_themes())

        assert response.status_code == HTTPStatus.OK


class TestRoleScanIsBounded:
    def test_staff_scan_is_capped(self, handler: ThemeAdminAPI) -> None:
        """The route is open to any staff session by design, so cap its work."""
        from canvas_theme_kit.handlers.admin_api import MAX_STAFF_SCANNED

        caller = MagicMock(id="staff-1")
        caller.roles.all.return_value = []

        with patch(f"{AUTH}.current_staff", return_value=caller), \
             patch(f"{AUTH}.can_edit", return_value=True), \
             patch(f"{AUTH}.can_publish", return_value=True), \
             patch(f"{AUTH}.Staff") as mock_staff:
            queryset = mock_staff.objects.all.return_value.prefetch_related.return_value
            queryset.__getitem__.return_value = []

            only(handler.list_roles())

            queryset.__getitem__.assert_called_once_with(slice(None, MAX_STAFF_SCANNED))


class TestQueryShape:
    """Locks in the projections and the batched lookup.

    A ThemeRevision row can carry 256 KB of CSS, so hydrating one to read a
    couple of scalars is the difference between a small response and megabytes
    of wasted I/O. These assertions exist because that regression is invisible
    in behavior — the endpoint returns identical JSON either way.
    """

    def test_theme_payload_fields_are_locked(self, handler: ThemeAdminAPI) -> None:
        # Without this, someone adds draft_css to the default shape and every
        # list response silently starts carrying full stylesheets.
        a, b, c = allow()
        with a, b, c, patch_store():
            payload = ThemeAdminAPI._theme_json(make_theme())

        assert set(payload) == set(ThemeAdminAPI.THEME_FIELDS)

    def test_draft_fields_only_appear_when_requested(
        self, handler: ThemeAdminAPI
    ) -> None:
        a, b, c = allow()
        with a, b, c, patch_store():
            payload = ThemeAdminAPI._theme_json(make_theme(), include_draft=True)

        expected = set(ThemeAdminAPI.THEME_FIELDS) | set(ThemeAdminAPI.DRAFT_FIELDS)
        assert set(payload) == expected

    def test_active_revision_lookup_projects_away_the_blob(
        self, handler: ThemeAdminAPI
    ) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            ThemeAdminAPI._theme_json(make_theme())

        values = mock_store.revision_model.objects.filter.return_value.order_by.return_value.values
        assert values.call_args == call("revision", "content_hash")

    def test_history_projects_away_the_blob(self, handler: ThemeAdminAPI) -> None:
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            only(handler.get_theme())

        values = (
            mock_store.revision_model.objects.filter.return_value
            .order_by.return_value.values
        )
        every_projection = {a for c in values.call_args_list for a in c.args}
        history_projection = max(
            (set(c.args) for c in values.call_args_list), key=len
        )

        assert "css" not in every_projection
        assert "tokens" not in every_projection
        assert {"revision", "content_hash", "is_active"} <= history_projection

    def test_list_themes_runs_one_revision_query_for_all_themes(
        self, handler: ThemeAdminAPI
    ) -> None:
        """The N+1 guard: N themes must not mean N revision queries."""
        themes = [make_theme("a"), make_theme("b"), make_theme("c")]
        for i, t in enumerate(themes):
            t.dbid = i + 1

        a, b, c = allow()
        with a, b, c, patch_store() as mock_store, patch(f"{AUTH}.Theme") as mock_theme:
            mock_theme.objects.all.return_value.order_by.return_value = themes
            mock_store.revision_model.objects.filter.return_value.values.return_value = []

            only(handler.list_themes())

            filter_calls = mock_store.revision_model.objects.filter.call_args_list

        assert len(filter_calls) == 1, (
            f"Expected one batched revision query, got {len(filter_calls)} — "
            "the N+1 is back."
        )
        assert filter_calls[0] == call(theme_id__in=[1, 2, 3], is_active=True)


class TestEditorPageCaching:
    def test_editor_page_is_revalidated(self, handler: ThemeAdminAPI) -> None:
        """The editor must not be served from cache after a redeploy.

        Distinct from the asset routes, which deliberately permit stale copies
        to keep a round trip off the first paint. The editor is staff-only, off
        every patient-facing path, and stale means a shipped fix appears not to
        have shipped.
        """
        with patch(f"{AUTH}.render_to_string", return_value="<html></html>"):
            response = only(handler.editor_ui())

        assert "no-cache" in response.headers["Cache-Control"]
        assert "private" in response.headers["Cache-Control"]


class TestOriginIsComparedExactly:
    """The guard once used `origin.endswith(host)`, which a security review
    showed accepts any host that merely ends with the instance's name. That
    sibling is same-site, so SameSite=Lax would not stop it either."""

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evilacme.canvasmedical.com",
            "https://acme.canvasmedical.com.evil.example",
            "https://acme.canvasmedical.com:8443",
            "null",
        ],
    )
    def test_rejects_an_origin_that_is_not_exactly_the_host(
        self, handler: ThemeAdminAPI, origin: str
    ) -> None:
        handler.request.headers = {"origin": origin, "host": "acme.canvasmedical.com"}
        a, b, c = allow()
        with a, b, c:
            response = only(handler.publish())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Cross-origin" in response.content.decode()

    def test_host_comparison_ignores_case(self, handler: ThemeAdminAPI) -> None:
        handler.request.headers = {
            "origin": "https://ACME.canvasmedical.com",
            "host": "acme.canvasmedical.com",
        }
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(handler.publish())

        assert "Cross-origin" not in response.content.decode()


class TestBodyMustBeAnObject:
    """A JSON array or string body reached `body.get` and raised, which the
    caller saw as a 500 rather than a reason."""

    MUTATING_WITH_BODY = ["create_theme", "save_draft", "load_draft", "publish", "rollback"]

    @pytest.mark.parametrize("method", MUTATING_WITH_BODY)
    @pytest.mark.parametrize("body", [["slug", "x"], "x", 3])
    def test_non_object_body_is_a_400(
        self, handler: ThemeAdminAPI, method: str, body: Any
    ) -> None:
        handler.request.json.return_value = body
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(getattr(handler, method)())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "JSON object" in response.content.decode()

    @pytest.mark.parametrize("method", MUTATING_WITH_BODY)
    def test_unparseable_body_is_a_400(self, handler: ThemeAdminAPI, method: str) -> None:
        handler.request.json.side_effect = ValueError("Expecting value")
        a, b, c = allow()
        with a, b, c, patch_store() as mock_store:
            mock_store.get_theme.return_value = make_theme()
            response = only(getattr(handler, method)())

        assert response.status_code == HTTPStatus.BAD_REQUEST


def test_origin_guard_defers_when_the_request_has_no_host(handler: ThemeAdminAPI) -> None:
    # Without a Host there is nothing to compare against. Rejecting here would
    # lock the editor out behind a proxy that strips it; the cookie policy and
    # the role allowlist still apply.
    handler.request.headers = {"origin": "https://acme.canvasmedical.com"}
    a, b, c = allow()
    with a, b, c, patch_store() as mock_store:
        mock_store.get_theme.return_value = make_theme()
        response = only(handler.publish())

    assert "Cross-origin" not in response.content.decode()
