"""Tests for the RoleBasedHomepage handler.

Run with `uv run pytest`. DB-backed tests (which build Staff/StaffRole/CanvasUser rows with
factories) are marked `integtest`; the rest are pure unit tests over mocked events.
"""

import json
from typing import cast
from unittest.mock import MagicMock, Mock, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.effects.default_homepage import DefaultHomepageEffect
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import StaffFactory, StaffRoleFactory
from canvas_sdk.v1.data.staff import Staff

from role_based_homepage.handlers.event_handlers import RoleBasedHomepage

# A representative config covering pages, an app identifier, and the "*" catch-all.
ROLE_MAP = {
    "MD": "SCHEDULE",
    "RN": "SCHEDULE",
    "CC": "PATIENTS",
    "BL": "REVENUE",
    "CD": "DATA_INTEGRATION",
    "*": "PATIENTS",
}


def make_handler(actor_id: object, role_map: object) -> RoleBasedHomepage:
    """Build a handler with a mocked event actor and a JSON-encoded role map secret.

    ``role_map`` may be a dict (JSON-encoded for the secret), a raw string (used verbatim, to
    exercise invalid-JSON paths), or ``None`` (the secret is absent).
    """
    event = Mock()
    event.actor.id = actor_id

    secrets: dict[str, str] = {}
    if isinstance(role_map, dict):
        secrets["ROLE_HOMEPAGE_MAP"] = json.dumps(role_map)
    elif isinstance(role_map, str):
        secrets["ROLE_HOMEPAGE_MAP"] = role_map

    return RoleBasedHomepage(event=event, secrets=secrets)


def page_value(effect_list: list) -> str | None:
    """Extract the configured page path from a single homepage effect."""
    assert len(effect_list) == 1
    effect = effect_list[0]
    assert effect.type == EffectType.HOMEPAGE_CONFIGURATION
    return cast("str | None", json.loads(effect.payload)["data"]["page"])


# --------------------------------------------------------------------------------------------
# Configuration / event-actor handling (no DB needed)
# --------------------------------------------------------------------------------------------


def test_returns_empty_when_secret_missing() -> None:
    """No ROLE_HOMEPAGE_MAP secret → no override."""
    handler = make_handler(actor_id="123", role_map=None)
    assert handler.compute() == []


def test_returns_empty_when_secret_blank() -> None:
    """Blank secret → no override."""
    handler = make_handler(actor_id="123", role_map="   ")
    assert handler.compute() == []


def test_returns_empty_when_secret_invalid_json() -> None:
    """Non-JSON secret → no override (does not raise)."""
    handler = make_handler(actor_id="123", role_map="not-json{")
    assert handler.compute() == []


def test_returns_empty_when_secret_not_an_object() -> None:
    """JSON that isn't an object (e.g. a list) → no override."""
    handler = make_handler(actor_id="123", role_map="[1, 2, 3]")
    assert handler.compute() == []


def test_returns_empty_when_actor_id_missing() -> None:
    """No actor id on the event → no override."""
    handler = make_handler(actor_id=None, role_map=ROLE_MAP)
    assert handler.compute() == []


def test_responds_to_homepage_configuration_event() -> None:
    """Handler subscribes to the correct event."""
    assert RoleBasedHomepage.RESPONDS_TO == EventType.Name(EventType.GET_HOMEPAGE_CONFIGURATION)


# --------------------------------------------------------------------------------------------
# Destination resolution (_build_effect) — pure, no staff lookup
# --------------------------------------------------------------------------------------------


def test_build_effect_resolves_page_case_insensitively() -> None:
    """A page-name destination (any case) becomes a page effect, never hits the DB."""
    handler = make_handler(actor_id="1", role_map=ROLE_MAP)
    effect = handler._build_effect("schedule")
    assert effect is not None
    payload = json.loads(effect.payload)["data"]
    assert payload["page"] == DefaultHomepageEffect.Pages.SCHEDULE.value
    assert payload["application_identifier"] is None


@patch("canvas_sdk.effects.default_homepage.Application.objects.filter")
def test_build_effect_resolves_existing_application(mock_filter: MagicMock) -> None:
    """A non-page destination is treated as an application identifier."""
    mock_filter.return_value.exists.return_value = True
    handler = make_handler(actor_id="1", role_map=ROLE_MAP)
    effect = handler._build_effect("my_plugin.apps:MyApp")
    assert effect is not None
    payload = json.loads(effect.payload)["data"]
    assert payload["application_identifier"] == "my_plugin.apps:MyApp"
    assert payload["page"] is None


@patch("canvas_sdk.effects.default_homepage.Application.objects.filter")
def test_build_effect_returns_none_for_unresolvable_application(
    mock_filter: MagicMock,
) -> None:
    """An application identifier that doesn't resolve → None (caller returns [])."""
    mock_filter.return_value.exists.return_value = False
    handler = make_handler(actor_id="1", role_map=ROLE_MAP)
    assert handler._build_effect("ghost.apps:Missing") is None


def test_load_role_map_skips_non_string_values() -> None:
    """Config entries with non-string keys/values are dropped, valid ones kept."""
    handler = make_handler(actor_id="1", role_map={"MD": 123, "RN": "SCHEDULE"})
    assert handler._load_role_map() == {"RN": "SCHEDULE"}


def test_load_role_map_skips_blank_keys_and_values() -> None:
    """Entries that normalize to an empty key or value are dropped."""
    handler = make_handler(
        actor_id="1", role_map={"   ": "PATIENTS", "MD": "   ", "RN": "SCHEDULE"}
    )
    assert handler._load_role_map() == {"RN": "SCHEDULE"}


# --------------------------------------------------------------------------------------------
# Role-based routing against the test database
# --------------------------------------------------------------------------------------------


def _staff_with_roles(roles: list[dict]) -> Staff:
    """Create a Staff whose roles are exactly ``roles`` (clearing the factory default role).

    Each entry is a dict of StaffRole kwargs (e.g. internal_code, domain_privilege_level).
    """
    staff = StaffFactory.create()
    staff.roles.all().delete()
    for role_kwargs in roles:
        StaffRoleFactory.create(staff=staff, **role_kwargs)
    return staff


@pytest.mark.integtest
def test_single_matching_role_routes_to_page() -> None:
    """Biller (BL) → REVENUE page."""
    staff = _staff_with_roles(
        [{"internal_code": "BL", "name": "Biller", "domain_privilege_level": 100}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=ROLE_MAP)
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.REVENUE.value


@pytest.mark.integtest
def test_highest_privilege_role_wins() -> None:
    """A staff member who is both MD (SCHEDULE, priv 100000) and CC (PATIENTS, priv 100)
    routes as the higher-privilege MD → SCHEDULE."""
    staff = _staff_with_roles(
        [
            {"internal_code": "CC", "name": "Care Coordinator", "domain_privilege_level": 100},
            {"internal_code": "MD", "name": "Physician", "domain_privilege_level": 100000},
        ]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=ROLE_MAP)
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.SCHEDULE.value


@pytest.mark.integtest
def test_highest_privilege_wins_regardless_of_role_order() -> None:
    """Tie-break is order-independent: the higher-privilege role wins even when it is
    encountered before the lower-privilege one (MD created first, then CC)."""
    staff = _staff_with_roles(
        [
            {"internal_code": "MD", "name": "Physician", "domain_privilege_level": 100000},
            {"internal_code": "CC", "name": "Care Coordinator", "domain_privilege_level": 100},
        ]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=ROLE_MAP)
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.SCHEDULE.value


@pytest.mark.integtest
def test_unmapped_role_falls_back_to_wildcard() -> None:
    """A role not in the map (EPCS Admin, EP) falls through to the '*' default → PATIENTS."""
    staff = _staff_with_roles(
        [{"internal_code": "EP", "name": "EPCS Administrator", "domain_privilege_level": 10}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=ROLE_MAP)
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.PATIENTS.value


@pytest.mark.integtest
def test_unmapped_role_without_wildcard_returns_empty() -> None:
    """Same unmapped role, but no '*' key → no override."""
    role_map = {k: v for k, v in ROLE_MAP.items() if k != "*"}
    staff = _staff_with_roles(
        [{"internal_code": "EP", "name": "EPCS Administrator", "domain_privilege_level": 10}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=role_map)
    assert handler.compute() == []


@pytest.mark.integtest
def test_explicit_match_beats_wildcard() -> None:
    """An explicitly mapped role is used even when a '*' default exists."""
    staff = _staff_with_roles(
        [{"internal_code": "BL", "name": "Biller", "domain_privilege_level": 100}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=ROLE_MAP)
    # BL → REVENUE, not the "*" → PATIENTS default.
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.REVENUE.value


@pytest.mark.integtest
def test_matching_is_case_and_whitespace_insensitive() -> None:
    """Lower/odd-cased config keys still match the role's internal_code."""
    staff = _staff_with_roles(
        [{"internal_code": "BL", "name": "Biller", "domain_privilege_level": 100}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map={" bl ": "REVENUE"})
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.REVENUE.value


@pytest.mark.integtest
def test_blank_internal_code_is_ignored() -> None:
    """A role with a blank internal_code can't match; with no '*' the result is empty."""
    role_map = {k: v for k, v in ROLE_MAP.items() if k != "*"}
    staff = _staff_with_roles(
        [{"internal_code": "", "name": "Custom", "domain_privilege_level": 5}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=role_map)
    assert handler.compute() == []


@pytest.mark.integtest
def test_staff_with_no_roles_uses_wildcard() -> None:
    """A resolved staff member with no roles falls through to the '*' default."""
    staff = StaffFactory.create()
    staff.roles.all().delete()
    handler = make_handler(actor_id=str(staff.user.dbid), role_map=ROLE_MAP)
    assert page_value(handler.compute()) == DefaultHomepageEffect.Pages.PATIENTS.value


@pytest.mark.integtest
@patch("canvas_sdk.effects.default_homepage.Application.objects.filter")
def test_compute_returns_empty_when_destination_app_missing(
    mock_filter: MagicMock,
) -> None:
    """A role mapped to an app identifier that doesn't resolve → compute returns []."""
    mock_filter.return_value.exists.return_value = False
    staff = _staff_with_roles(
        [{"internal_code": "BL", "name": "Biller", "domain_privilege_level": 100}]
    )
    handler = make_handler(actor_id=str(staff.user.dbid), role_map={"BL": "ghost.apps:Missing"})
    assert handler.compute() == []


@pytest.mark.integtest
def test_unresolvable_actor_returns_empty() -> None:
    """An actor id that maps to no staff → no override, even with a '*' default configured."""
    # Ensure at least one staff exists, then point at an id that can't be it.
    StaffFactory.create()
    missing_id = str(Staff.objects.order_by("-dbid").first().dbid + 9999)
    handler = make_handler(actor_id=missing_id, role_map=ROLE_MAP)
    assert handler.compute() == []
