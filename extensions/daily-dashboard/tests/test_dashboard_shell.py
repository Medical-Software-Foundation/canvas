"""Shell tests: the provider-menu app launches the page, the asset routes are
staff-authenticated at the expected paths, and the template shell carries the
structural hooks the client script depends on.
"""

from pathlib import Path
from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

from daily_dashboard.applications.dashboard_app import DASHBOARD_URL, DashboardApp
from daily_dashboard.routes.dashboard_api import (
    ASSET_BASE,
    DashboardIndexRoute,
    DashboardScriptRoute,
    DashboardStylesRoute,
)

TEMPLATES = Path(__file__).resolve().parent.parent / "daily_dashboard" / "templates"


def test_app_opens_dashboard_as_full_page() -> None:
    """on_open returns a LAUNCH_MODAL effect targeting the dashboard URL as a page."""
    effect = DashboardApp(event=Mock()).on_open()
    assert not isinstance(effect, list)

    assert effect.type == EffectType.LAUNCH_MODAL
    assert DASHBOARD_URL in effect.payload
    assert "page" in effect.payload  # TargetType.PAGE


def test_routes_are_staff_authenticated_at_expected_paths() -> None:
    """Each asset route is session-authenticated (fail-closed) at its own path."""
    assert DashboardIndexRoute.PATH == "/app"
    assert DashboardStylesRoute.PATH == "/app/styles.css"
    assert DashboardScriptRoute.PATH == "/app/app.js"

    for route in (DashboardIndexRoute, DashboardStylesRoute, DashboardScriptRoute):
        assert issubclass(route, StaffSessionAuthMixin)


def test_index_template_has_structural_hooks() -> None:
    """The shell references its assets and carries the DOM ids the client targets."""
    html = (TEMPLATES / "index.html").read_text()

    # Assets are referenced via the plugin-io base so relative resolution is correct.
    assert "{{ asset_base }}/styles.css" in html
    assert "{{ asset_base }}/app.js" in html

    # "My day" is the default active view (not "All").
    assert 'class="ui button active" data-scope="mine" data-day="today"' in html
    assert 'class="ui button" data-scope="all" data-day="today"' in html
    # "Tomorrow" is also a "mine" view, so it defaults to the signed-in provider.
    assert 'data-scope="mine" data-day="tomorrow"' in html

    # Panels, table body, and filter controls that the client script populates.
    for hook in (
        "drb-date",
        "drb-tasks-count",
        "drb-refills-count",
        "drb-messages-count",
        "drb-rows",
        "drb-provider",
        "drb-location",
    ):
        assert f'id="{hook}"' in html, f"missing #{hook}"


def test_asset_base_points_at_plugin_io_route() -> None:
    """The HTML asset base matches the index route's served path."""
    assert ASSET_BASE == "/plugin-io/api/daily_dashboard/app"
    assert DASHBOARD_URL == ASSET_BASE


def test_static_assets_are_non_empty_and_safe_for_templating() -> None:
    """CSS/JS exist and avoid Django template tokens that render_to_string would eat."""
    for name in ("styles.css", "app.js"):
        text = (TEMPLATES / name).read_text()
        assert text.strip(), f"{name} is empty"
        assert "{{" not in text, f"{name} contains a Django variable token"
        assert "{%" not in text, f"{name} contains a Django tag token"
