"""Put the practice's preferred providers at the top of the Refer command's search."""

import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler

from preferred_referrals.directory import matching_preferred, merge_results


class PreferredFirstReferSearch(BaseHandler):
    """Offer matching preferred providers above the shared directory's results.

    POST_SEARCH, not PRE_SEARCH: only the post-search context carries what the
    directory found, and a command pre-search reply replaces the results outright.
    """

    RESPONDS_TO = EventType.Name(EventType.REFER__REFER_TO__POST_SEARCH)

    def compute(self) -> list[Effect]:
        """Return the merged list, or a null payload when there is nothing to add."""
        search_term = str(self.event.context.get("search_term") or "").strip()
        matches = matching_preferred(search_term)
        if not matches:
            return [self._no_opinion()]
        merged = merge_results(matches, self.event.context.get("results") or [])
        return [
            Effect(
                type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(merged)
            )
        ]

    @staticmethod
    def _no_opinion() -> Effect:
        # A null payload keeps the directory's results; an empty list would clear them.
        return Effect(
            type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(None)
        )
