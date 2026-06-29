"""Candid claim timeline application.

Shows on /revenue/claims/<id> pages. Displays a timeline of all Candid
activity (submission, syncs, ERA postings, patient payments) and provides
a button to trigger a manual adjudication sync.

The UI (HTML/CSS/JS) lives in ``static/claim-timeline.*`` and is served by
``candid.api.app.CandidAppAssets``; this handler iframes that page, passing the
claim id as a query param (the page shows a placeholder when none is present).
"""

from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

APP_URL = "/plugin-io/api/candid/app/claim-timeline"


class CandidClaimTimeline(Application):
    """Claim-level Candid activity timeline with manual sync trigger."""

    def on_open(self) -> Effect:
        """Load timeline if already on a claim page, otherwise show placeholder."""
        claim = self.event.context.get("claim")
        return self._render(claim["id"] if claim else None)

    def on_context_change(self) -> Effect | list[Effect] | None:
        """Update the timeline when the user navigates to a claim."""
        claim = self.event.context.get("claim")
        if not claim:
            return None
        return self._render(claim["id"])

    def _render(self, claim_id: str | None) -> Effect:
        url = APP_URL
        if claim_id:
            url = f"{url}?{urlencode({'claim_id': claim_id})}"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Candid Activity",
        ).apply()
