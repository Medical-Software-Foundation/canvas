import json
from unittest.mock import MagicMock

from canvas_sdk.effects import EffectType

from patient_state_scheduling.protocols.location_filter import (
    SECRET_KEY,
    LocationFilterHandler,
)

# Sample practice locations as they would appear in the scheduling form.
LOCATIONS = [
    {"text": "North Clinic", "value": "1"},
    {"text": "South Clinic", "value": "2"},
    {"text": "East Clinic", "value": "4"},
    {"text": "West Clinic", "value": "3"},
]

# Sample state -> location mapping.
MAPPING = {
    "default": ["South Clinic"],
    "California": ["North Clinic"],
    "New York": ["West Clinic"],
    "Kansas": ["East Clinic"],
    "New Jersey": ["North Clinic"],
}


def make_handler(state: str | None, secret: str | None) -> LocationFilterHandler:
    """Build a handler with the given selected state and raw secret value."""
    selected_values: dict = {}
    if state is not None:
        selected_values = {"additional_fields": [{"key": "state", "values": state}]}

    event = MagicMock()
    event.context = {"locations": LOCATIONS, "selected_values": selected_values}

    secrets = {SECRET_KEY: secret} if secret is not None else {}
    return LocationFilterHandler(event=event, secrets=secrets)


def filtered_texts(effects: list) -> list[str]:
    """Extract location display texts from a POST_SEARCH_RESULTS effect."""
    assert len(effects) == 1
    assert effects[0].type == EffectType.APPOINTMENT__FORM__LOCATIONS__POST_SEARCH_RESULTS
    payload = json.loads(effects[0].payload)
    return [loc["text"] for loc in payload["locations"]]


def test_no_state_selected_shows_all() -> None:
    """With no state chosen, no effect is emitted so all locations remain."""
    handler = make_handler(state=None, secret=json.dumps(MAPPING))
    assert handler.compute() == []


def test_empty_state_value_shows_all() -> None:
    """An empty state value is treated as no selection."""
    handler = make_handler(state="", secret=json.dumps(MAPPING))
    assert handler.compute() == []


def test_other_additional_fields_ignored_shows_all() -> None:
    """Non-'state' additional fields are skipped; no state means all locations."""
    event = MagicMock()
    event.context = {
        "locations": LOCATIONS,
        "selected_values": {"additional_fields": [{"key": "other", "values": "x"}]},
    }
    handler = LocationFilterHandler(event=event, secrets={SECRET_KEY: json.dumps(MAPPING)})
    assert handler.compute() == []


def test_explicit_state_rule_filters() -> None:
    """California maps to the North Clinic location only."""
    handler = make_handler(state="California", secret=json.dumps(MAPPING))
    assert filtered_texts(handler.compute()) == ["North Clinic"]


def test_other_explicit_rules_filter() -> None:
    """Each explicitly mapped state resolves to its configured location."""
    cases = {
        "New York": ["West Clinic"],
        "Kansas": ["East Clinic"],
        "New Jersey": ["North Clinic"],
    }
    for state, expected in cases.items():
        handler = make_handler(state=state, secret=json.dumps(MAPPING))
        assert filtered_texts(handler.compute()) == expected


def test_unlisted_state_uses_default() -> None:
    """A state without its own rule falls back to the default location."""
    handler = make_handler(state="Texas", secret=json.dumps(MAPPING))
    assert filtered_texts(handler.compute()) == ["South Clinic"]


def test_unlisted_state_no_default_shows_all() -> None:
    """No matching rule and no default -> fail open (all locations)."""
    mapping = {"California": ["North Clinic"]}  # no "default" key
    handler = make_handler(state="Texas", secret=json.dumps(mapping))
    assert handler.compute() == []


def test_missing_secret_shows_all() -> None:
    """A missing LOCATION_MAPPING secret fails open."""
    handler = make_handler(state="California", secret=None)
    assert handler.compute() == []


def test_invalid_json_secret_shows_all() -> None:
    """A secret that is not valid JSON fails open."""
    handler = make_handler(state="California", secret="not json{")
    assert handler.compute() == []


def test_non_object_secret_shows_all() -> None:
    """A secret that is valid JSON but not an object fails open."""
    handler = make_handler(state="California", secret=json.dumps(["North Clinic"]))
    assert handler.compute() == []


def test_rule_with_no_matching_location_returns_empty_list() -> None:
    """A rule whose location is absent filters everything out (empty list)."""
    mapping = {"California": ["Nonexistent Clinic"]}
    handler = make_handler(state="California", secret=json.dumps(mapping))
    assert filtered_texts(handler.compute()) == []
