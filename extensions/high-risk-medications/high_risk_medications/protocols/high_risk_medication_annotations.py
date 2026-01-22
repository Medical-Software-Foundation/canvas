"""
High Risk Medication Annotations Protocol

This protocol adds "High Risk" annotations to medications in search results
for prescribe, refill, and medication statement commands. The plugin uses
case-insensitive pattern matching to identify medications containing specific
high-risk terms.
"""

import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol

from logger import log

# Default patterns for handlers without access to secrets
HIGH_RISK_PATTERNS = ["warfarin", "insulin", "digoxin", "methotrexate"]


class Protocol(BaseProtocol):
    """
    Annotates medication search results with "High Risk" labels when medication
    names contain specific high-risk patterns.
    """

    # Respond to POST_SEARCH events for prescribe, refill, and med statement commands
    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE__PRESCRIBE__POST_SEARCH),
        EventType.Name(EventType.REFILL__PRESCRIBE__POST_SEARCH),
        EventType.Name(EventType.MEDICATION_STATEMENT__MEDICATION__POST_SEARCH),
        EventType.Name(EventType.ADJUST_PRESCRIPTION__CHANGE_MEDICATION_TO__POST_SEARCH),
        EventType.Name(EventType.ADJUST_PRESCRIPTION__PRESCRIBE__POST_SEARCH),
        EventType.Name(EventType.CHANGE_MEDICATION__MEDICATION__POST_SEARCH),
        EventType.Name(EventType.STOP_MEDICATION__MEDICATION__POST_SEARCH),
    ]

    def compute(self) -> list[Effect]:
        """
        Process medication search results and add "High Risk" annotations
        to medications matching the high-risk patterns.

        Returns:
            List containing a single AUTOCOMPLETE_SEARCH_RESULTS effect with
            the modified search results.
        """
        # Get search results from event context
        results = self.context.get("results")

        # If results is None, return no modifications
        if results is None:
            return [
                Effect(
                    type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS,
                    payload=json.dumps(None)
                )
            ]

        log.info(f"Processing {len(results)} medication search results")

        # Annotate medications matching high-risk patterns
        annotated_count = 0
        for result in results:
            medication_name = result.get("text", "").lower()

            # Check if medication name contains any high-risk pattern
            if any(pattern in medication_name for pattern in HIGH_RISK_PATTERNS):
                if result.get("annotations") is None:
                    result["annotations"] = []
                result["annotations"].append("High Risk")
                annotated_count += 1
                log.info(f"Annotated high-risk medication: {result.get('text')}")

        log.info(f"Annotated {annotated_count} high-risk medications")

        # Return modified search results as JSON
        return [
            Effect(
                type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS,
                payload=json.dumps(results)
            )
        ]
