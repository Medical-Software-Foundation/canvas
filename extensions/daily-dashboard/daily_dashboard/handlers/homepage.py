"""Make the Daily Readiness Dashboard the default homepage on login.

Canvas asks for homepage configuration via GET_HOMEPAGE_CONFIGURATION; returning
a DefaultHomepageEffect pointed at our Application replaces the default schedule
landing view with the dashboard.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.default_homepage import DefaultHomepageEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler

# The dashboard Application's identifier (module:qualname).
DASHBOARD_APP_IDENTIFIER = "daily_dashboard.applications.dashboard_app:DashboardApp"


class HomepageHandler(BaseHandler):
    """Sets the Daily Readiness Dashboard as the default homepage."""

    RESPONDS_TO = EventType.Name(EventType.GET_HOMEPAGE_CONFIGURATION)

    def compute(self) -> list[Effect]:
        """Point the homepage at the dashboard application."""
        return [
            DefaultHomepageEffect(application_identifier=DASHBOARD_APP_IDENTIFIER).apply()
        ]
