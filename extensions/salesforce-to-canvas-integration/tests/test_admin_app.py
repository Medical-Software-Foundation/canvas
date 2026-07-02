"""Tests for the Salesforce admin application launcher.

The console is a wide multi table dashboard, so it opens as a full page from the
left sidebar nav rather than as a modal. This pins that the launch effect targets
the page surface.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from salesforce_to_canvas_integration.handlers.admin_app import SalesforceAdminApp


def test_on_open_launches_the_page_target() -> None:
    """on_open returns a launch effect aimed at the full page surface."""
    handler = SalesforceAdminApp.__new__(SalesforceAdminApp)
    handler.event = MagicMock()

    effect = handler.on_open()
    payload = json.loads(effect.payload)

    assert payload["data"]["target"] == "page"
