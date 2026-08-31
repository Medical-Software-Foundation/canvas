"""The Fax Queue Inboxes application, reachable from the app drawer with no patient in context."""

from __future__ import annotations

from datetime import UTC, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# The deploy time cache bust CPA's own deploy-lite step requires, computed
# once at import rather than per request, so the launch url stays in step
# with the page and the assets it loads for the life of one deploy.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))


class FaxQueueDashboard(Application):
    """Opens the team organised fax dashboard as a full page rather than a modal."""

    def on_open(self) -> Effect:
        """Return the page launch effect for the dashboard route.

        The target is the page target rather than the default modal, and
        content is left unset while url is set. An inline content modal
        loads with an opaque origin and the browser will not attach the
        session cookie to a fetch made from it. The path itself stays
        exactly what 02-spec/SPEC.md Behaviour step 2 names, the cache
        bust rides along as a query string appended to that fixed path
        rather than as a change to it.
        """
        return LaunchModalEffect(
            url=f"/plugin-io/api/fax_queue_inboxes/fax-queue-inboxes/app?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Fax Queue Inboxes",
        ).apply()
