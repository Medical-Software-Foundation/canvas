import json
from typing import Any

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log

# Plugin secret holding the state -> allowed practice locations mapping.
#
# The value is a JSON object keyed by full state name (matching the options in
# AdditionalFieldsHandler), plus a "default" entry applied to any state not
# listed explicitly. Each value is a list of practice-location names; a location
# is kept when one of those names appears in its display text. Example:
#
#   {
#     "default":    ["Main Street Clinic"],
#     "California":  ["West Coast Medical Group"],
#     "New York":    ["East Coast Medical Group"],
#     "Kansas":      ["Central Plains Clinic"],
#     "New Jersey":  ["Garden State Health"]
#   }
#
# The secret is set per instance, so the mapping can change without a code change
# or redeploy.
SECRET_KEY = "LOCATION_MAPPING"
DEFAULT_KEY = "default"


def _selected_state(selected_values: dict[str, Any]) -> str:
    """Return the value chosen for the 'state' additional field, or ''."""
    for field in selected_values.get("additional_fields", []):
        if field.get("key") == "state":
            return str(field.get("values") or "")
    return ""


class LocationFilterHandler(BaseHandler):
    """Filter the practice-location dropdown based on the selected patient state.

    Filtering fails open: if no state is selected, the LOCATION_MAPPING secret is
    missing or invalid, or no rule (and no default) matches the state, all
    locations are shown so scheduling is never blocked by configuration.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT__FORM__LOCATIONS__POST_SEARCH)

    def compute(self) -> list[Effect]:
        locations = self.event.context.get("locations", [])
        selected = self.event.context.get("selected_values", {})
        state = _selected_state(selected)

        if not state:
            return []

        mapping = self._load_mapping()
        if mapping is None:
            return []

        allowed = mapping.get(state) or mapping.get(DEFAULT_KEY)
        if not allowed:
            log.info(f"LocationFilter: no rule or default for state='{state}'; showing all locations")
            return []

        filtered = [
            loc
            for loc in locations
            if any(name in loc.get("text", "") for name in allowed)
        ]
        log.info(
            f"LocationFilter: state='{state}', {len(locations)} -> {len(filtered)} locations"
        )

        return [
            Effect(
                type=EffectType.APPOINTMENT__FORM__LOCATIONS__POST_SEARCH_RESULTS,
                payload=json.dumps({"locations": filtered}),
            )
        ]

    def _load_mapping(self) -> dict[str, Any] | None:
        """Parse the LOCATION_MAPPING secret, or return None to fail open."""
        raw = self.secrets.get(SECRET_KEY)
        if not raw:
            log.warning(f"LocationFilter: secret '{SECRET_KEY}' not set; showing all locations")
            return None
        try:
            mapping = json.loads(raw)
        except (TypeError, ValueError):
            log.warning(f"LocationFilter: secret '{SECRET_KEY}' is not valid JSON; showing all locations")
            return None
        if not isinstance(mapping, dict):
            log.warning(f"LocationFilter: secret '{SECRET_KEY}' must be a JSON object; showing all locations")
            return None
        return mapping
