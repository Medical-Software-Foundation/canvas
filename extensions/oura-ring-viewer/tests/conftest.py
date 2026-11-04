"""Shared test fixtures.

The Canvas SDK's own pytest plugin already creates the plugin's tables, so no
schema setup is needed here.

``render_to_string`` locates the plugin's templates by inspecting the calling
plugin's runtime frame, which does not exist under pytest. Rather than stub it
out with an echo, this fixture renders the real template files through the same
Django engine the SDK builds, so handler tests exercise the actual templates.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.templates.utils import _engine_for_plugin

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "oura_ring_viewer"


def render_template(template_name: str, context: dict[str, Any] | None = None) -> str:
    """Render a plugin template exactly as the SDK would at runtime."""
    engine = _engine_for_plugin(PLUGIN_DIR)
    return str(engine.render_to_string(str(PLUGIN_DIR / template_name.lstrip("/")), context=context))


@pytest.fixture(autouse=True)
def _real_templates() -> Iterator[None]:
    with (
        patch("oura_ring_viewer.protocols.chart_api.render_to_string", side_effect=render_template),
        patch("oura_ring_viewer.protocols.oauth_api.render_to_string", side_effect=render_template),
        patch("oura_ring_viewer.protocols.portal_api.render_to_string", side_effect=render_template),
    ):
        yield
