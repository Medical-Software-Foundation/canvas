"""Tests for provider_availability.api.availability_api."""

from __future__ import annotations

import datetime as dt
import json
from datetime import UTC, date, datetime
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.api.availability_api import (
    AvailabilityAPI,
    _check_write_access,
    _enrich_blocks,
    _enrich_recurring_blocks,
    _enrich_rules,
)
from provider_availability.engine.models import (
    AdminBlock,
    AvailableSlot,
    BookingInterval,
    BufferTime,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)


# ── Helpers ──────────────────────────────────────────────────────────────

PROVIDER_ID = "provider-uuid-123"
PROVIDER_ID_2 = "provider-uuid-456"
LOCATION_ID = "location-uuid-456"
VISIT_TYPE_ID = "visit-type-uuid-789"

MODULE = "provider_availability.api.availability_api"


def _parse(response) -> tuple[dict, int]:
    """Extract (body_dict, status_code) from a JSONResponse."""
    body = json.loads(getattr(response, "content"))
    return body, response.status_code


_STAFF_HEX = "5e4fb0011234567890abcdef01234567"  # undashed (Staff.id form)
_STAFF_DASHED = "5e4fb001-1234-5678-90ab-cdef01234567"  # same UUID, dashed
_OTHER_HEX = "aa11bb22cc33dd44ee55ff6677889900"


def _make_handler(
    query_params: dict | None = None,
    path_params: dict | None = None,
    json_body: dict | None = None,
    staff_id: str | None = _STAFF_HEX,
    secrets: dict | None = None,
) -> AvailabilityAPI:
    """Create an AvailabilityAPI handler with a header-based request mock."""
    handler = AvailabilityAPI(MagicMock())
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.request.path_params = path_params or {}
    handler.request.json.return_value = json_body or {}
    handler.request.headers = (
        {"canvas-logged-in-user-id": staff_id} if staff_id is not None else {}
    )
    handler.secrets = secrets or {}
    return handler


def _make_request(staff_id: str | None = _STAFF_HEX) -> MagicMock:
    """Create a request mock with the header-based staff id."""
    request = MagicMock()
    request.headers = (
        {"canvas-logged-in-user-id": staff_id} if staff_id is not None else {}
    )
    return request


# ── _check_write_access ─────────────────────────────────────────────────


class TestCheckWriteAccess:
    def test_empty_secret_allows_any_staff(self):
        """Unset/empty allowed-staff-keys → any logged-in staff is allowed."""
        assert _check_write_access(_make_request(), secrets={}) is None

    def test_listed_staff_undashed_allowed(self):
        assert (
            _check_write_access(
                _make_request(_STAFF_HEX),
                secrets={"allowed-staff-keys": _STAFF_HEX},
            )
            is None
        )

    def test_dashed_secret_matches_undashed_header(self):
        """Regression for PR #339-comment: dashed UUID in secret + undashed header → allowed."""
        assert (
            _check_write_access(
                _make_request(_STAFF_HEX),
                secrets={"allowed-staff-keys": _STAFF_DASHED},
            )
            is None
        )

    def test_unlisted_staff_denied(self):
        result = _check_write_access(
            _make_request(_OTHER_HEX),
            secrets={"allowed-staff-keys": _STAFF_HEX},
        )
        assert result is not None
        body, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert "Access denied" in body["error"]

    def test_missing_header_denied_when_secret_set(self):
        result = _check_write_access(
            _make_request(staff_id=None),
            secrets={"allowed-staff-keys": _STAFF_HEX},
        )
        assert result is not None
        body, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN


# ── Enrichment helpers ───────────────────────────────────────────────────


class TestEnrichRules:
    def test_empty(self):
        assert _enrich_rules([]) == []

    @patch(
        f"{MODULE}.get_scheduleable_visit_types",
        return_value=[{"id": VISIT_TYPE_ID, "name": "Follow-up"}],
    )
    @patch(
        f"{MODULE}.get_active_locations",
        return_value=[{"id": LOCATION_ID, "name": "Main Office"}],
    )
    @patch(
        f"{MODULE}.get_provider_displays",
        return_value={PROVIDER_ID: {"name": "Dr. Smith", "npi_number": "1234567890"}},
    )
    def test_with_data(self, mock_displays, mock_locs, mock_vts):
        rule = ProviderAvailabilityRule(
            id="r1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            visit_types=[VISIT_TYPE_ID],
        )
        result = _enrich_rules([rule])
        assert len(result) == 1
        assert result[0]["provider_name"] == "Dr. Smith"
        assert result[0]["provider_npi"] == "1234567890"
        assert result[0]["location_names"] == ["Main Office"]
        assert result[0]["visit_type_names"] == ["Follow-up"]
        assert mock_displays.mock_calls == [call([PROVIDER_ID])]
        assert mock_locs.mock_calls == [call()]
        assert mock_vts.mock_calls == [call()]

    @patch(
        f"{MODULE}.get_scheduleable_visit_types",
        side_effect=Exception("db error"),
    )
    @patch(
        f"{MODULE}.get_active_locations",
        side_effect=Exception("db error"),
    )
    @patch(
        f"{MODULE}.get_provider_displays",
        return_value={PROVIDER_ID: {"name": "Dr. X"}},
    )
    def test_handles_lookup_errors(self, mock_displays, mock_locs, mock_vts):
        rule = ProviderAvailabilityRule(
            id="r1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            visit_types=[VISIT_TYPE_ID],
        )
        result = _enrich_rules([rule])
        assert len(result) == 1
        # Falls back to raw IDs when lookups fail
        assert result[0]["location_names"] == [LOCATION_ID]
        assert result[0]["visit_type_names"] == [VISIT_TYPE_ID]
        assert mock_displays.mock_calls == [call([PROVIDER_ID])]
        assert mock_locs.mock_calls == [call()]
        assert mock_vts.mock_calls == [call()]

    @patch(
        f"{MODULE}.get_scheduleable_visit_types",
        return_value=[],
    )
    @patch(
        f"{MODULE}.get_active_locations",
        return_value=[],
    )
    @patch(
        f"{MODULE}.get_provider_displays",
        return_value={},
    )
    def test_unknown_provider_gets_empty_name(self, mock_displays, mock_locs, mock_vts):
        """Provider not in displays dict gets empty name/npi."""
        rule = ProviderAvailabilityRule(
            id="r1",
            provider_id="unknown",
            location_ids=[],
            visit_types=[],
        )
        result = _enrich_rules([rule])
        assert result[0]["provider_name"] == ""
        assert result[0]["provider_npi"] == ""
        assert mock_displays.mock_calls == [call(["unknown"])]


class TestEnrichBlocks:
    def test_with_data(self):
        block = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        displays = {PROVIDER_ID: {"name": "Dr. Smith"}}
        result = _enrich_blocks([block], displays)
        assert len(result) == 1
        assert result[0]["provider_name"] == "Dr. Smith"
        assert result[0]["id"] == "b1"

    def test_empty(self):
        result = _enrich_blocks([], {})
        assert result == []

    def test_unknown_provider(self):
        block = AdminBlock(
            id="b2",
            provider_id="unknown",
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        result = _enrich_blocks([block], {})
        assert result[0]["provider_name"] == ""


class TestEnrichRecurringBlocks:
    def test_with_data(self):
        rb = RecurringBlock(
            id="rb1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"monday": [TimeWindow(dt.time(9, 0), dt.time(12, 0))]},
        )
        displays = {PROVIDER_ID: {"name": "Dr. Smith"}}
        result = _enrich_recurring_blocks([rb], displays)
        assert len(result) == 1
        assert result[0]["provider_name"] == "Dr. Smith"

    def test_empty(self):
        result = _enrich_recurring_blocks([], {})
        assert result == []


# ── Dropdown / list endpoints ────────────────────────────────────────────


class TestListProviders:
    @patch(
        f"{MODULE}.get_active_providers",
        return_value=[
            {"id": "p1", "name": "Dr. A", "npi_number": "111"},
            {"id": "p2", "name": "Dr. B", "npi_number": "222"},
        ],
    )
    def test_success(self, mock_providers):
        handler = _make_handler()
        result = handler.list_providers()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 2
        assert len(body["providers"]) == 2
        assert mock_providers.mock_calls == [call()]

    @patch(f"{MODULE}.get_active_providers", side_effect=Exception("connection error"))
    def test_exception_returns_empty(self, mock_providers):
        handler = _make_handler()
        result = handler.list_providers()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 0
        assert body["providers"] == []
        assert mock_providers.mock_calls == [call()]


class TestListLocations:
    @patch(
        f"{MODULE}.get_active_locations",
        return_value=[{"id": "loc1", "name": "Main"}],
    )
    def test_success(self, mock_locs):
        handler = _make_handler()
        result = handler.list_locations()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert mock_locs.mock_calls == [call()]

    @patch(f"{MODULE}.get_active_locations", side_effect=Exception("fail"))
    def test_exception_returns_empty(self, mock_locs):
        handler = _make_handler()
        result = handler.list_locations()
        body, code = _parse(result[0])
        assert body["count"] == 0
        assert body["locations"] == []
        assert mock_locs.mock_calls == [call()]


class TestListVisitTypes:
    @patch(
        f"{MODULE}.get_scheduleable_visit_types",
        return_value=[{"id": "vt1", "name": "Check-up"}],
    )
    def test_success(self, mock_vts):
        handler = _make_handler()
        result = handler.list_visit_types()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert mock_vts.mock_calls == [call()]

    @patch(f"{MODULE}.get_scheduleable_visit_types", side_effect=Exception("fail"))
    def test_exception_returns_empty(self, mock_vts):
        handler = _make_handler()
        result = handler.list_visit_types()
        body, code = _parse(result[0])
        assert body["count"] == 0
        assert body["visit_types"] == []
        assert mock_vts.mock_calls == [call()]


# ── Provider search ─────────────────────────────────────────────────────


class TestSearchProviders:
    def test_missing_q_returns_error(self):
        handler = _make_handler(query_params={"q": ""})
        result = handler.search_providers_endpoint()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "q query parameter is required" in body["error"]

    def test_missing_q_param_entirely(self):
        handler = _make_handler(query_params={})
        result = handler.search_providers_endpoint()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(
        f"{MODULE}.search_providers",
        return_value=[{"id": "p1", "first_name": "A", "last_name": "B"}],
    )
    def test_success(self, mock_search):
        handler = _make_handler(query_params={"q": "Smith"})
        result = handler.search_providers_endpoint()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert mock_search.mock_calls == [call("Smith", active_only=True)]

    @patch(f"{MODULE}.search_providers", return_value=[])
    def test_active_only_false(self, mock_search):
        handler = _make_handler(query_params={"q": "Smith", "active_only": "false"})
        handler.search_providers_endpoint()
        assert mock_search.mock_calls == [call("Smith", active_only=False)]

    @patch(f"{MODULE}.search_providers", return_value=[])
    def test_whitespace_only_q(self, mock_search):
        handler = _make_handler(query_params={"q": "   "})
        result = handler.search_providers_endpoint()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        # search_providers should not have been called
        assert mock_search.mock_calls == []


# ── Overview endpoint ────────────────────────────────────────────────────


class TestGetOverview:
    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[])
    @patch(f"{MODULE}.get_active_locations", return_value=[])
    @patch(f"{MODULE}.get_provider_displays", return_value={})
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    @patch(f"{MODULE}.get_practice_timezone", return_value="UTC")
    def test_empty(self, mock_ptz, mock_ptzs, mock_rules, mock_blocks, mock_rb, mock_displays, mock_locs, mock_vts):
        handler = _make_handler()
        result = handler.get_overview()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["providers"] == []
        assert mock_rules.mock_calls == [call()]
        assert mock_blocks.mock_calls == [call()]
        assert mock_rb.mock_calls == [call()]
        # get_provider_displays should NOT be called when no providers
        assert mock_displays.mock_calls == []

    @patch(
        f"{MODULE}.get_scheduleable_visit_types",
        return_value=[{"id": VISIT_TYPE_ID, "name": "Follow-up"}],
    )
    @patch(
        f"{MODULE}.get_active_locations",
        return_value=[{"id": LOCATION_ID, "name": "Main Office"}],
    )
    @patch(f"{MODULE}.get_provider_displays")
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    @patch(f"{MODULE}.get_practice_timezone", return_value="UTC")
    def test_with_rules(self, mock_ptz, mock_ptzs, mock_rules, mock_blocks, mock_rb, mock_displays, mock_locs, mock_vts):
        rule = ProviderAvailabilityRule(
            id="r1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            visit_types=[VISIT_TYPE_ID],
        )
        mock_rules.return_value = [rule]
        mock_displays.return_value = {PROVIDER_ID: {"name": "Dr. Smith"}}
        handler = _make_handler()
        result = handler.get_overview()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert len(body["providers"]) == 1
        assert body["providers"][0]["provider_name"] == "Dr. Smith"
        assert len(body["providers"][0]["rules"]) == 1
        assert body["providers"][0]["rules"][0]["location_names"] == ["Main Office"]
        assert body["providers"][0]["rules"][0]["visit_type_names"] == ["Follow-up"]
        assert mock_rules.mock_calls == [call()]
        assert mock_displays.mock_calls == [call([PROVIDER_ID])]

    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[])
    @patch(f"{MODULE}.get_active_locations", return_value=[])
    @patch(f"{MODULE}.get_provider_displays")
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.get_all_blocks")
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    @patch(f"{MODULE}.get_practice_timezone", return_value="UTC")
    def test_with_blocks_and_recurring(self, mock_ptz, mock_ptzs, mock_rules, mock_blocks, mock_rb, mock_displays, mock_locs, mock_vts):
        """Overview includes blocks and recurring blocks grouped by provider."""
        block = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        recurring = RecurringBlock(
            id="rb1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"monday": [TimeWindow(dt.time(9, 0), dt.time(10, 0))]},
        )
        mock_rules.return_value = []
        mock_blocks.return_value = [block]
        mock_rb.return_value = [recurring]
        mock_displays.return_value = {PROVIDER_ID: {"name": "Dr. Smith"}}

        handler = _make_handler()
        result = handler.get_overview()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert len(body["providers"]) == 1
        assert len(body["providers"][0]["blocks"]) == 1
        assert len(body["providers"][0]["recurring_blocks"]) == 1
        assert mock_blocks.mock_calls == [call()]
        assert mock_rb.mock_calls == [call()]

    @patch(f"{MODULE}.get_scheduleable_visit_types", side_effect=Exception("err"))
    @patch(f"{MODULE}.get_active_locations", side_effect=Exception("err"))
    @patch(f"{MODULE}.get_provider_displays", return_value={PROVIDER_ID: {"name": "Dr. Z"}})
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    @patch(f"{MODULE}.get_practice_timezone", return_value="UTC")
    def test_lookup_errors_handled(self, mock_ptz, mock_ptzs, mock_rules, mock_blocks, mock_rb, mock_displays, mock_locs, mock_vts):
        """Location/visit-type lookup failures are caught gracefully."""
        rule = ProviderAvailabilityRule(
            id="r1", provider_id=PROVIDER_ID, location_ids=["loc-x"], visit_types=["vt-x"]
        )
        mock_rules.return_value = [rule]
        handler = _make_handler()
        result = handler.get_overview()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        # Falls back to raw IDs
        assert body["providers"][0]["rules"][0]["location_names"] == ["loc-x"]
        assert body["providers"][0]["rules"][0]["visit_type_names"] == ["vt-x"]


# ── Available slots ──────────────────────────────────────────────────────


class TestGetAvailableSlots:
    def test_missing_dates_returns_error(self):
        handler = _make_handler(query_params={"provider_id": PROVIDER_ID})
        result = handler.get_available_slots()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "start_date and end_date are required" in body["error"]

    @patch(f"{MODULE}.resolve_provider_id", side_effect=ValueError("no provider"))
    def test_invalid_provider_returns_error(self, mock_resolve):
        handler = _make_handler(
            query_params={
                "provider_id": "",
                "provider_npi": "bad",
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            }
        )
        result = handler.get_available_slots()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "no provider" in body["error"]
        assert mock_resolve.mock_calls == [call("", "bad")]

    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_no_rules_returns_empty(self, mock_resolve, mock_rules):
        handler = _make_handler(
            query_params={
                "provider_id": PROVIDER_ID,
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
            }
        )
        result = handler.get_available_slots()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["slots"] == []
        assert body["count"] == 0
        assert mock_resolve.mock_calls == [call(PROVIDER_ID, "")]
        assert mock_rules.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}.get_available_slots_for_provider")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_success_with_slots(self, mock_resolve, mock_rules, mock_slots):
        rule = ProviderAvailabilityRule(provider_id=PROVIDER_ID)
        mock_rules.return_value = [rule]
        slot = AvailableSlot(
            start=datetime(2026, 3, 3, 9, 0),
            end=datetime(2026, 3, 3, 9, 15),
            provider_id=PROVIDER_ID,
        )
        mock_slots.return_value = [slot]
        handler = _make_handler(
            query_params={
                "provider_id": PROVIDER_ID,
                "start_date": "2026-03-03",
                "end_date": "2026-03-03",
                "location_id": LOCATION_ID,
                "visit_type": VISIT_TYPE_ID,
            }
        )
        result = handler.get_available_slots()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert body["provider_id"] == PROVIDER_ID
        assert mock_slots.mock_calls == [
            call([rule], date(2026, 3, 3), date(2026, 3, 3), LOCATION_ID, VISIT_TYPE_ID)
        ]

    def test_missing_end_date_returns_error(self):
        handler = _make_handler(
            query_params={"provider_id": PROVIDER_ID, "start_date": "2026-03-01"}
        )
        result = handler.get_available_slots()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST


# ── Available providers ──────────────────────────────────────────────────


class TestGetAvailableProviders:
    def test_missing_dates(self):
        handler = _make_handler(query_params={})
        result = handler.get_available_providers()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "start_date and end_date are required" in data["error"]

    @patch(f"{MODULE}.calculate_available_slots", return_value=[])
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    def test_no_rules(self, mock_rules, mock_calc):
        handler = _make_handler(
            query_params={"start_date": "2026-03-01", "end_date": "2026-03-07"}
        )
        result = handler.get_available_providers()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 0
        assert mock_rules.mock_calls == [call()]
        assert mock_calc.mock_calls == []

    @patch(f"{MODULE}.calculate_available_slots")
    @patch(f"{MODULE}.get_all_rules")
    def test_with_providers(self, mock_rules, mock_calc):
        rule = ProviderAvailabilityRule(id="r1", provider_id=PROVIDER_ID)
        mock_rules.return_value = [rule]
        mock_calc.return_value = [MagicMock()]  # 1 slot
        handler = _make_handler(
            query_params={"start_date": "2026-03-01", "end_date": "2026-03-07"}
        )
        result = handler.get_available_providers()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert body["providers"][0]["provider_id"] == PROVIDER_ID
        assert body["providers"][0]["available_slot_count"] == 1
        assert mock_rules.mock_calls == [call()]
        assert mock_calc.mock_calls == [call(rule, date(2026, 3, 1), date(2026, 3, 7))]

    @patch(f"{MODULE}.calculate_available_slots")
    @patch(f"{MODULE}.get_all_rules")
    def test_location_filter_skips_non_matching(self, mock_rules, mock_calc):
        """Rules with non-matching location_ids are skipped."""
        rule = ProviderAvailabilityRule(
            id="r1", provider_id=PROVIDER_ID, location_ids=["other-loc"]
        )
        mock_rules.return_value = [rule]
        handler = _make_handler(
            query_params={
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "location_id": LOCATION_ID,
            }
        )
        result = handler.get_available_providers()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 0
        assert mock_calc.mock_calls == []

    @patch(f"{MODULE}.calculate_available_slots")
    @patch(f"{MODULE}.get_all_rules")
    def test_visit_type_filter_skips_non_matching(self, mock_rules, mock_calc):
        """Rules with non-matching visit_types are skipped."""
        rule = ProviderAvailabilityRule(
            id="r1", provider_id=PROVIDER_ID, visit_types=["other-vt"]
        )
        mock_rules.return_value = [rule]
        handler = _make_handler(
            query_params={
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "visit_type": VISIT_TYPE_ID,
            }
        )
        result = handler.get_available_providers()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 0
        assert mock_calc.mock_calls == []

    @patch(f"{MODULE}.calculate_available_slots")
    @patch(f"{MODULE}.get_all_rules")
    def test_empty_location_ids_passes_filter(self, mock_rules, mock_calc):
        """Rules with empty location_ids pass the location filter."""
        rule = ProviderAvailabilityRule(
            id="r1", provider_id=PROVIDER_ID, location_ids=[]
        )
        mock_rules.return_value = [rule]
        mock_calc.return_value = [MagicMock()]
        handler = _make_handler(
            query_params={
                "start_date": "2026-03-01",
                "end_date": "2026-03-07",
                "location_id": LOCATION_ID,
            }
        )
        result = handler.get_available_providers()
        body, code = _parse(result[0])
        assert body["count"] == 1
        assert mock_calc.mock_calls == [call(rule, date(2026, 3, 1), date(2026, 3, 7))]


# ── Rule CRUD ────────────────────────────────────────────────────────────


class TestListRules:
    @patch(f"{MODULE}._enrich_rules", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_by_provider(self, mock_resolve, mock_rules, mock_enrich):
        handler = _make_handler(query_params={"provider_id": PROVIDER_ID})
        result = handler.list_rules()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert mock_resolve.mock_calls == [call(PROVIDER_ID, "")]
        assert mock_rules.mock_calls == [call(PROVIDER_ID)]
        assert mock_enrich.mock_calls == [call([])]

    @patch(f"{MODULE}._enrich_rules", return_value=[])
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    def test_all_rules(self, mock_all_rules, mock_enrich):
        handler = _make_handler(query_params={})
        result = handler.list_rules()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert mock_all_rules.mock_calls == [call()]
        assert mock_enrich.mock_calls == [call([])]

    @patch(f"{MODULE}._enrich_rules")
    @patch(f"{MODULE}.get_all_rules")
    def test_location_filter(self, mock_all_rules, mock_enrich):
        """Rules are filtered by location_id if provided."""
        rule_match = ProviderAvailabilityRule(
            id="r1", provider_id=PROVIDER_ID, location_ids=[LOCATION_ID]
        )
        rule_no_match = ProviderAvailabilityRule(
            id="r2", provider_id=PROVIDER_ID, location_ids=["other-loc"]
        )
        rule_empty = ProviderAvailabilityRule(
            id="r3", provider_id=PROVIDER_ID, location_ids=[]
        )
        mock_all_rules.return_value = [rule_match, rule_no_match, rule_empty]
        mock_enrich.side_effect = lambda rules: [{"id": r.id} for r in rules]

        handler = _make_handler(query_params={"location_id": LOCATION_ID})
        result = handler.list_rules()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        # rule_match matches directly, rule_empty matches because location_ids is empty
        assert body["count"] == 2
        assert mock_all_rules.mock_calls == [call()]

    @patch(f"{MODULE}.resolve_provider_id", side_effect=ValueError("bad npi"))
    def test_resolve_error(self, mock_resolve):
        handler = _make_handler(query_params={"provider_npi": "bad"})
        result = handler.list_rules()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "bad npi" in body["error"]
        assert mock_resolve.mock_calls == [call("", "bad")]


class TestGetProviderRules:
    @patch(f"{MODULE}._enrich_rules", return_value=[{"id": "r1"}])
    @patch(f"{MODULE}.get_rules_for_provider")
    def test_success(self, mock_rules, mock_enrich):
        rule = ProviderAvailabilityRule(id="r1", provider_id=PROVIDER_ID)
        mock_rules.return_value = [rule]
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.get_provider_rules()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert body["provider_id"] == PROVIDER_ID
        assert mock_rules.mock_calls == [call(PROVIDER_ID)]
        assert mock_enrich.mock_calls == [call([rule])]


class TestCreateOrUpdateRule:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_success(self, mock_resolve, mock_overlap, mock_save, mock_sync, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {
                "monday": [{"start": "09:00", "end": "12:00"}],
            },
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Rule saved"
        assert mock_save.mock_calls == [call(mock_save.call_args[0][0])]
        assert mock_sync.mock_calls == [call(PROVIDER_ID)]
        assert mock_resolve.mock_calls == [call(PROVIDER_ID, "")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_returns_error(self, mock_access):
        handler = _make_handler(json_body={})
        result = handler.create_or_update_rule()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id or provider_npi is required" in body["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_invalid_time_window_returns_error(self, mock_resolve, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {
                "monday": [{"start": "12:00", "end": "09:00"}],
            },
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Start time must be before end time" in data["error"]
        assert mock_resolve.mock_calls == [call(PROVIDER_ID, "")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.check_rule_overlap", return_value="Overlapping availability on Monday")
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_overlap_returns_error(self, mock_resolve, mock_overlap, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {
                "monday": [{"start": "09:00", "end": "12:00"}],
            },
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Overlapping" in data["error"]
        assert mock_overlap.mock_calls == [call(mock_overlap.call_args[0][0], exclude_rule_id="")]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(json_body={"provider_id": PROVIDER_ID})
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_backward_compat_single_location(
        self, mock_resolve, mock_overlap, mock_save, mock_sync, mock_access
    ):
        """The endpoint accepts location_id (string) and converts it to location_ids (list)."""
        body = {
            "provider_id": PROVIDER_ID,
            "location_id": LOCATION_ID,
            "visit_type": VISIT_TYPE_ID,
            "weekly_schedule": {},
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.CREATED
        saved_rule = mock_save.call_args[0][0]
        assert saved_rule.location_ids == [LOCATION_ID]
        assert saved_rule.visit_types == [VISIT_TYPE_ID]
        assert mock_save.mock_calls == [call(saved_rule)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", side_effect=ValueError("cannot resolve"))
    def test_resolve_error(self, mock_resolve, mock_access):
        body = {"provider_id": "bad-id"}
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "cannot resolve" in data["error"]
        assert mock_resolve.mock_calls == [call("bad-id", "")]


class TestUpdateRuleGroup:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_success(self, mock_get_rule, mock_overlap, mock_save, mock_get_rules, mock_sync, mock_access):
        body = {
            "id": "r1",
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_rule_group()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 1 rule(s)" in data["message"]
        assert mock_save.mock_calls == [call(mock_save.call_args[0][0])]
        assert mock_sync.mock_calls == [call(PROVIDER_ID)]
        assert mock_overlap.mock_calls == [call(mock_overlap.call_args[0][0], exclude_rule_id="r1")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_id_or_provider(self, mock_access):
        handler = _make_handler(json_body={"id": "", "provider_id": ""})
        result = handler.update_rule_group()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "id and provider_id are required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_id_only(self, mock_access):
        handler = _make_handler(json_body={"provider_id": PROVIDER_ID})
        result = handler.update_rule_group()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.check_rule_overlap", return_value="Overlap found")
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_overlap_error(self, mock_get_rule, mock_overlap, mock_access):
        body = {
            "id": "r1",
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_rule_group()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Overlap" in data["error"]
        assert mock_overlap.mock_calls == [call(mock_overlap.call_args[0][0], exclude_rule_id="r1")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rules_by_group")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_apply_to_group(self, mock_get_rule, mock_overlap, mock_group, mock_save, mock_get_rules, mock_sync, mock_access):
        """When apply_to_group is True, updates all rules in the group."""
        group_rule = ProviderAvailabilityRule(
            id="r2", provider_id=PROVIDER_ID_2, group_id="g1"
        )
        mock_group.return_value = [group_rule]

        body = {
            "id": "r1",
            "provider_id": PROVIDER_ID,
            "group_id": "g1",
            "apply_to_group": True,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_rule_group()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 2 rule(s)" in data["message"]
        # Should save 2 rules (original + group member)
        assert len(mock_save.mock_calls) == 2
        assert mock_group.mock_calls == [call("g1")]
        # Should sync both providers
        assert mock_sync.call_count == 2

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rules_by_group")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_apply_to_group_skips_self(self, mock_get_rule, mock_overlap, mock_group, mock_save, mock_get_rules, mock_sync, mock_access):
        """Group update skips the rule being edited (same ID)."""
        same_rule = ProviderAvailabilityRule(
            id="r1", provider_id=PROVIDER_ID, group_id="g1"
        )
        mock_group.return_value = [same_rule]

        body = {
            "id": "r1",
            "provider_id": PROVIDER_ID,
            "group_id": "g1",
            "apply_to_group": True,
            "weekly_schedule": {},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_rule_group()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 1 rule(s)" in data["message"]
        # Only the main rule save, not the group member since it is the same
        assert len(mock_save.mock_calls) == 1

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(json_body={"id": "r1", "provider_id": PROVIDER_ID})
        result = handler.update_rule_group()
        data, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


class TestDeleteRule:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_success(self, mock_delete, mock_get_rules, mock_sync, mock_access):
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "r1"}
        )
        result = handler.delete_rule()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["message"] == "Rule deleted"
        assert data["rule_id"] == "r1"
        assert mock_delete.mock_calls == [call(PROVIDER_ID, "r1")]
        assert mock_sync.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "r1"}
        )
        result = handler.delete_rule()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


class TestDeleteProviderRules:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_rules_for_provider", return_value=2)
    @patch(f"{MODULE}.build_delete_effects", return_value=[])
    def test_success(self, mock_effects, mock_delete, mock_access):
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.delete_provider_rules()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["deleted_count"] == 2
        assert mock_delete.mock_calls == [call(PROVIDER_ID)]
        assert mock_effects.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.delete_provider_rules()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


# ── Date Override Endpoints ──────────────────────────────────────────────


class TestOverrideEndpoints:
    def _make_rule_with_overrides(self, overrides=None):
        return ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"thursday": [TimeWindow(start=dt.time(9, 0), end=dt.time(15, 0))]},
            date_overrides=overrides or [],
            is_active=True,
        )

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override(self, mock_get, mock_save, mock_get_rb, mock_get_rules, mock_sync, mock_access):
        rule = self._make_rule_with_overrides()
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
            json_body={"date": "2026-04-09", "is_closed": False, "time_windows": [{"start": "12:00", "end": "17:00"}]},
        )
        result = handler.add_override()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "saved" in data["message"].lower()
        assert len(rule.date_overrides) == 1
        assert rule.date_overrides[0].date == date(2026, 4, 9)
        mock_save.assert_called_once_with(rule)

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_replaces_existing(self, mock_get, mock_save, mock_get_rb, mock_get_rules, mock_sync, mock_access):
        existing = DateOverride(
            date=date(2026, 4, 9),
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        )
        rule = self._make_rule_with_overrides([existing])
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
            json_body={"date": "2026-04-09", "time_windows": [{"start": "12:00", "end": "17:00"}]},
        )
        result = handler.add_override()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert len(rule.date_overrides) == 1
        assert rule.date_overrides[0].time_windows[0].start == dt.time(12, 0)

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_remove_override(self, mock_get, mock_save, mock_get_rb, mock_get_rules, mock_sync, mock_access):
        existing = DateOverride(
            date=date(2026, 4, 9),
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        )
        rule = self._make_rule_with_overrides([existing])
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1", "override_date": "2026-04-09"},
        )
        result = handler.remove_override()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert len(rule.date_overrides) == 0
        mock_save.assert_called_once_with(rule)

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_add_override_rule_not_found(self, mock_get, mock_access):
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "nonexistent"},
            json_body={"date": "2026-04-09", "time_windows": [{"start": "12:00", "end": "17:00"}]},
        )
        result = handler.add_override()
        _, code = _parse(result[0])
        assert code == HTTPStatus.NOT_FOUND

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_missing_time_windows(self, mock_get, mock_access):
        rule = self._make_rule_with_overrides()
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
            json_body={"date": "2026-04-09"},
        )
        result = handler.add_override()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "time window" in data["error"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_invalid_time_windows(self, mock_get, mock_access):
        rule = self._make_rule_with_overrides()
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
            json_body={"date": "2026-04-09", "is_closed": False, "time_windows": [{"start": "17:00", "end": "12:00"}]},
        )
        result = handler.add_override()
        _, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_override_wrong_weekday_rejected(self, mock_get, mock_access):
        """Override on a Monday should be rejected when the rule only has Thursday hours."""
        rule = self._make_rule_with_overrides()
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
            # 2026-04-06 is a Monday — rule only has Thursday
            json_body={"date": "2026-04-06", "time_windows": [{"start": "09:00", "end": "12:00"}]},
        )
        result = handler.add_override()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "monday" in data["error"].lower()

    @patch(f"{MODULE}.get_rule_by_id")
    def test_list_overrides(self, mock_get):
        existing = DateOverride(
            date=date(2026, 4, 9),
            time_windows=[TimeWindow(start=dt.time(12, 0), end=dt.time(17, 0))],
        )
        rule = self._make_rule_with_overrides([existing])
        mock_get.return_value = rule
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
        )
        result = handler.list_overrides()
        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["date"] == "2026-04-09"

    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_list_overrides_rule_not_found(self, mock_get):
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "nonexistent"},
        )
        result = handler.list_overrides()
        _, code = _parse(result[0])
        assert code == HTTPStatus.NOT_FOUND


# ── Admin Block CRUD ─────────────────────────────────────────────────────


class TestListBlocks:
    @patch(f"{MODULE}.get_blocks_for_provider", return_value=[])
    def test_success_empty(self, mock_blocks):
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.list_blocks()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 0
        assert body["provider_id"] == PROVIDER_ID
        assert mock_blocks.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}.get_blocks_for_provider")
    def test_success_with_blocks(self, mock_blocks):
        block = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        mock_blocks.return_value = [block]
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.list_blocks()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert body["blocks"][0]["id"] == "b1"
        assert mock_blocks.mock_calls == [call(PROVIDER_ID)]


class TestCreateBlock:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    def test_success(self, mock_save, mock_effects, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
            "reason": "PTO",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Block created"
        assert mock_save.mock_calls == [call(mock_save.call_args[0][0])]
        assert mock_effects.mock_calls == [call(mock_effects.call_args[0][0])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_fields_returns_error(self, mock_access):
        handler = _make_handler(json_body={"provider_id": PROVIDER_ID})
        result = handler.create_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "start, and end are required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_id(self, mock_access):
        body = {"start": "2026-03-10T09:00:00", "end": "2026-03-10T12:00:00"}
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_invalid_time_range(self, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T12:00:00",
            "end": "2026-03-10T09:00:00",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Start time must be before end time" in data["error"]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(
            json_body={
                "provider_id": PROVIDER_ID,
                "start": "2026-03-10T09:00:00",
                "end": "2026-03-10T12:00:00",
            }
        )
        result = handler.create_block()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    def test_multi_date_all_day_creates_one_block_per_date(
        self, mock_save, mock_effects, mock_access
    ):
        body = {
            "provider_id": PROVIDER_ID,
            "dates": ["2026-07-04", "2026-12-25", "2026-11-26"],
            "all_day": True,
            "reason": "Holidays",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Created 3 block(s)"
        assert len(data["blocks"]) == 3
        assert data["group_id"] is not None
        # All three blocks share the same group_id and are all_day
        for b in data["blocks"]:
            assert b["all_day"] is True
            assert b["group_id"] == data["group_id"]
        # Dates sorted ascending
        starts = [b["start"][:10] for b in data["blocks"]]
        assert starts == ["2026-07-04", "2026-11-26", "2026-12-25"]
        # All-day end is next-day midnight (the visual rendering is handled
        # in event_sync via naive datetimes, not by truncating the duration).
        assert data["blocks"][0]["end"] == "2026-07-05T00:00:00"
        assert len(mock_save.mock_calls) == 3
        assert len(mock_effects.mock_calls) == 3

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    def test_single_date_all_day_no_group_id(
        self, mock_save, mock_effects, mock_access
    ):
        body = {
            "provider_id": PROVIDER_ID,
            "dates": ["2026-07-04"],
            "all_day": True,
            "reason": "July 4",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, _ = _parse(result[-1])
        assert len(data["blocks"]) == 1
        # Single-date batch shouldn't mint a group_id
        assert data["group_id"] is None
        assert data["blocks"][0]["all_day"] is True

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_multi_date_invalid_format(self, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "dates": ["not-a-date"],
            "all_day": True,
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "YYYY-MM-DD" in data["error"]


class TestUpdateBlock:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_block_by_id", return_value=None)
    def test_success(self, mock_get, mock_del_effects, mock_save, mock_create_effects, mock_access):
        body = {
            "id": "b1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
        }
        handler = _make_handler(json_body=body)
        result = handler.update_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 1 block(s)" in data["message"]
        assert mock_get.mock_calls == [call(PROVIDER_ID, "b1")]
        assert mock_save.mock_calls == [call(mock_save.call_args[0][0])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_fields(self, mock_access):
        body = {"id": "b1"}
        handler = _make_handler(json_body=body)
        result = handler.update_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "id, provider_id, start, and end are required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_invalid_time_range(self, mock_access):
        body = {
            "id": "b1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T14:00:00",
            "end": "2026-03-10T09:00:00",
        }
        handler = _make_handler(json_body=body)
        result = handler.update_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Start time must be before end time" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_block_by_id")
    def test_with_existing_old_block(
        self, mock_get, mock_del_effects, mock_save, mock_create_effects, mock_access
    ):
        """When old block exists, delete effects are generated for it."""
        old_block = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 8, 0),
            end=datetime(2026, 3, 10, 11, 0),
        )
        mock_get.return_value = old_block
        body = {
            "id": "b1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
        }
        handler = _make_handler(json_body=body)
        result = handler.update_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert mock_get.mock_calls == [call(PROVIDER_ID, "b1")]
        assert mock_del_effects.mock_calls == [call(PROVIDER_ID, old_block)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_block_by_id", return_value=None)
    @patch(f"{MODULE}.get_blocks_by_group")
    def test_apply_to_group(
        self, mock_group, mock_get, mock_del_effects, mock_save, mock_create_effects, mock_access
    ):
        """When apply_to_group is True, updates all blocks in the group."""
        group_block = AdminBlock(
            id="b2",
            provider_id=PROVIDER_ID_2,
            start=datetime(2026, 3, 10, 8, 0),
            end=datetime(2026, 3, 10, 11, 0),
            group_id="g1",
        )
        mock_group.return_value = [group_block]
        body = {
            "id": "b1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
            "group_id": "g1",
            "apply_to_group": True,
        }
        handler = _make_handler(json_body=body)
        result = handler.update_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 2 block(s)" in data["message"]
        # Should save both the main block and the group member
        assert len(mock_save.mock_calls) == 2
        assert mock_group.mock_calls == [call("g1")]


class TestDeleteBlockEndpoint:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_blocks_for_provider")
    def test_success(self, mock_get_blocks, mock_effects, mock_delete, mock_access):
        block = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        mock_get_blocks.return_value = [block]
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "block_id": "b1"}
        )
        result = handler.delete_block_endpoint()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["message"] == "Block deleted"
        assert data["block_id"] == "b1"
        assert mock_delete.mock_calls == [call(PROVIDER_ID, "b1")]
        assert mock_get_blocks.mock_calls == [call(PROVIDER_ID)]
        assert mock_effects.mock_calls == [call(PROVIDER_ID, block)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_blocks_for_provider", return_value=[])
    def test_block_not_found(self, mock_get_blocks, mock_effects, mock_delete, mock_access):
        """When block is not found, passes None to build_delete_block_effects."""
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "block_id": "missing"}
        )
        result = handler.delete_block_endpoint()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["message"] == "Block deleted"
        assert mock_effects.mock_calls == [call(PROVIDER_ID, None)]
        assert mock_delete.mock_calls == [call(PROVIDER_ID, "missing")]


# ── Recurring Block CRUD ────────────────────────────────────────────────


class TestListRecurringBlocks:
    @patch(f"{MODULE}.get_recurring_blocks_for_provider", return_value=[])
    def test_success_empty(self, mock_blocks):
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.list_recurring_blocks()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 0
        assert body["provider_id"] == PROVIDER_ID
        assert mock_blocks.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}.get_recurring_blocks_for_provider")
    def test_success_with_blocks(self, mock_blocks):
        rb = RecurringBlock(
            id="rb1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"friday": [TimeWindow(dt.time(12, 0), dt.time(13, 0))]},
        )
        mock_blocks.return_value = [rb]
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.list_recurring_blocks()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["count"] == 1
        assert mock_blocks.mock_calls == [call(PROVIDER_ID)]


class TestCreateRecurringBlock:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.save_recurring_block")
    def test_success(self, mock_save, mock_effects, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {
                "friday": [{"start": "12:00", "end": "13:00"}],
            },
            "reason": "Lunch",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_recurring_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Recurring block created"
        assert mock_save.mock_calls == [call(mock_save.call_args[0][0])]
        assert mock_effects.mock_calls == [call(mock_effects.call_args[0][0])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_id(self, mock_access):
        body = {"weekly_schedule": {"friday": [{"start": "12:00", "end": "13:00"}]}}
        handler = _make_handler(json_body=body)
        result = handler.create_recurring_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id is required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_weekly_schedule(self, mock_access):
        body = {"provider_id": PROVIDER_ID}
        handler = _make_handler(json_body=body)
        result = handler.create_recurring_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "weekly_schedule is required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_invalid_time_window(self, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {
                "friday": [{"start": "14:00", "end": "12:00"}],
            },
        }
        handler = _make_handler(json_body=body)
        result = handler.create_recurring_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Start time must be before end time" in data["error"]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(
            json_body={
                "provider_id": PROVIDER_ID,
                "weekly_schedule": {"friday": [{"start": "12:00", "end": "13:00"}]},
            }
        )
        result = handler.create_recurring_block()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


class TestUpdateRecurringBlock:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.save_recurring_block")
    def test_success(self, mock_save, mock_effects, mock_access):
        body = {
            "id": "rb1",
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_recurring_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 1 recurring block(s)" in data["message"]
        assert mock_save.mock_calls == [call(mock_save.call_args[0][0])]
        assert mock_effects.mock_calls == [call(mock_effects.call_args[0][0])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_id_or_provider(self, mock_access):
        body = {"weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]}}
        handler = _make_handler(json_body=body)
        result = handler.update_recurring_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "id and provider_id are required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_weekly_schedule(self, mock_access):
        body = {"id": "rb1", "provider_id": PROVIDER_ID}
        handler = _make_handler(json_body=body)
        result = handler.update_recurring_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "weekly_schedule is required" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.save_recurring_block")
    @patch(f"{MODULE}.get_recurring_blocks_by_group")
    def test_apply_to_group(self, mock_group, mock_save, mock_effects, mock_access):
        """When apply_to_group is True, updates all recurring blocks in the group."""
        group_block = RecurringBlock(
            id="rb2",
            provider_id=PROVIDER_ID_2,
            group_id="g1",
            weekly_schedule={"tuesday": [TimeWindow(dt.time(8, 0), dt.time(9, 0))]},
        )
        mock_group.return_value = [group_block]
        body = {
            "id": "rb1",
            "provider_id": PROVIDER_ID,
            "group_id": "g1",
            "apply_to_group": True,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_recurring_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 2 recurring block(s)" in data["message"]
        assert len(mock_save.mock_calls) == 2
        assert mock_group.mock_calls == [call("g1")]
        # Effects called for both blocks
        assert len(mock_effects.mock_calls) == 2

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.save_recurring_block")
    @patch(f"{MODULE}.get_recurring_blocks_by_group")
    def test_apply_to_group_skips_self(self, mock_group, mock_save, mock_effects, mock_access):
        """Group update skips the block being edited (same ID)."""
        same_block = RecurringBlock(
            id="rb1",
            provider_id=PROVIDER_ID,
            group_id="g1",
            weekly_schedule={"monday": [TimeWindow(dt.time(9, 0), dt.time(12, 0))]},
        )
        mock_group.return_value = [same_block]
        body = {
            "id": "rb1",
            "provider_id": PROVIDER_ID,
            "group_id": "g1",
            "apply_to_group": True,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_recurring_block()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert "Updated 1 recurring block(s)" in data["message"]
        assert len(mock_save.mock_calls) == 1

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(
            json_body={"id": "rb1", "provider_id": PROVIDER_ID, "weekly_schedule": {"m": []}}
        )
        result = handler.update_recurring_block()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


class TestDeleteRecurringBlockEndpoint:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_recurring_block")
    @patch(f"{MODULE}.build_delete_recurring_block_effects", return_value=[])
    @patch(f"{MODULE}.get_recurring_block_by_id", return_value=None)
    def test_success(self, mock_get, mock_effects, mock_delete, mock_access):
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "block_id": "rb1"}
        )
        result = handler.delete_recurring_block_endpoint()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["message"] == "Recurring block deleted"
        assert data["block_id"] == "rb1"
        assert mock_delete.mock_calls == [call(PROVIDER_ID, "rb1")]
        assert mock_get.mock_calls == [call(PROVIDER_ID, "rb1")]
        assert mock_effects.mock_calls == [call(PROVIDER_ID, None)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_recurring_block")
    @patch(f"{MODULE}.build_delete_recurring_block_effects", return_value=[])
    @patch(f"{MODULE}.get_recurring_block_by_id")
    def test_with_existing_block(self, mock_get, mock_effects, mock_delete, mock_access):
        """When the recurring block exists, it is passed to delete effects."""
        existing = RecurringBlock(id="rb1", provider_id=PROVIDER_ID)
        mock_get.return_value = existing
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "block_id": "rb1"}
        )
        result = handler.delete_recurring_block_endpoint()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert mock_effects.mock_calls == [call(PROVIDER_ID, existing)]
        assert mock_get.mock_calls == [call(PROVIDER_ID, "rb1")]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "block_id": "rb1"}
        )
        result = handler.delete_recurring_block_endpoint()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


# ── Timezone endpoints ───────────────────────────────────────────────────


class TestGetTimezone:
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    def test_success(self, mock_tz):
        handler = _make_handler()
        result = handler.get_timezone()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["timezone"] == "US/Eastern"
        assert "US/Pacific" in body["available"]
        assert mock_tz.mock_calls == [call()]


class TestSetTimezone:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.set_practice_timezone")
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_success(self, mock_set, mock_access):
        handler = _make_handler(json_body={"timezone": "US/Eastern"})
        result = handler.set_timezone()
        resp = result[-1]
        data, code = _parse(resp)
        assert code == HTTPStatus.OK
        assert data["timezone"] == "US/Eastern"
        assert mock_set.mock_calls == [call("US/Eastern")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone(self, mock_access):
        handler = _make_handler(json_body={"timezone": "Mars/Olympus"})
        result = handler.set_timezone()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_empty_timezone(self, mock_access):
        handler = _make_handler(json_body={"timezone": ""})
        result = handler.set_timezone()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(json_body={"timezone": "US/Eastern"})
        result = handler.set_timezone()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


# ── Provider-timezone endpoints ──────────────────────────────────────────


class TestGetProviderTimezone:
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.get_provider_timezone", return_value=None)
    def test_falls_back_to_practice_when_no_explicit(self, mock_get, mock_practice):
        handler = _make_handler(query_params={"provider_id": PROVIDER_ID})
        result = handler.get_provider_tz()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["timezone"] == "US/Eastern"
        assert body["explicit"] is False
        assert mock_get.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}.get_provider_timezone", return_value="US/Pacific")
    def test_returns_explicit_timezone(self, mock_get):
        handler = _make_handler(query_params={"provider_id": PROVIDER_ID})
        result = handler.get_provider_tz()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["timezone"] == "US/Pacific"
        assert body["explicit"] is True
        assert mock_get.mock_calls == [call(PROVIDER_ID)]

    def test_missing_provider_id_is_bad_request(self):
        handler = _make_handler(query_params={})
        result = handler.get_provider_tz()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id is required" in body["error"]


class TestGetAllProviderTimezones:
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={PROVIDER_ID: "US/Pacific"})
    def test_returns_all(self, mock_all):
        handler = _make_handler()
        result = handler.get_all_provider_tzs()
        body, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert body["timezones"] == {PROVIDER_ID: "US/Pacific"}
        assert mock_all.mock_calls == [call()]


class TestSetProviderTimezone:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.set_provider_timezone")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[MagicMock()])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[MagicMock()])
    def test_success_resyncs_provider_and_blocks(
        self, mock_build_rb, mock_get_rbs, mock_sync, mock_set, mock_access
    ):
        rb_match = RecurringBlock(id="rb-1", provider_id=PROVIDER_ID, is_active=True)
        rb_other = RecurringBlock(id="rb-2", provider_id=PROVIDER_ID_2, is_active=True)
        mock_get_rbs.return_value = [rb_match, rb_other]

        handler = _make_handler(json_body={"provider_id": PROVIDER_ID, "timezone": "US/Pacific"})
        result = handler.set_provider_tz()

        body, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert body["timezone"] == "US/Pacific"
        assert mock_set.mock_calls == [call(PROVIDER_ID, "US/Pacific")]
        assert mock_sync.mock_calls == [call(PROVIDER_ID)]
        # Only the matching provider's recurring block is re-synced
        assert mock_build_rb.mock_calls == [call(rb_match)]
        # 1 sync effect + 1 recurring-block effect + final JSONResponse
        assert len(result) == 3

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_id_is_bad_request(self, mock_access):
        handler = _make_handler(json_body={"timezone": "US/Pacific"})
        result = handler.set_provider_tz()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id is required" in body["error"]
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone_is_bad_request(self, mock_access):
        handler = _make_handler(json_body={"provider_id": PROVIDER_ID, "timezone": "Mars/Olympus"})
        result = handler.set_provider_tz()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in body["error"]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(json_body={"provider_id": PROVIDER_ID, "timezone": "US/Pacific"})
        result = handler.set_provider_tz()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_access.mock_calls == [call(handler.request, handler.secrets)]


class TestSetProviderTimezoneBulk:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.set_provider_timezone")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[MagicMock()])
    def test_success_sets_all(
        self, mock_build_rb, mock_get_rbs, mock_sync, mock_set, mock_access
    ):
        rb_match = RecurringBlock(id="rb-1", provider_id=PROVIDER_ID_2, is_active=True)
        mock_get_rbs.return_value = [rb_match]

        handler = _make_handler(json_body={
            "provider_ids": [PROVIDER_ID, PROVIDER_ID_2],
            "timezone": "US/Pacific",
        })
        result = handler.set_provider_tz_bulk()

        body, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert body["count"] == 2
        assert body["timezone"] == "US/Pacific"
        assert mock_set.mock_calls == [
            call(PROVIDER_ID, "US/Pacific"),
            call(PROVIDER_ID_2, "US/Pacific"),
        ]
        assert mock_sync.mock_calls == [call(PROVIDER_ID), call(PROVIDER_ID_2)]
        assert mock_build_rb.mock_calls == [call(rb_match)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_empty_provider_ids_is_bad_request(self, mock_access):
        handler = _make_handler(json_body={"provider_ids": [], "timezone": "US/Pacific"})
        result = handler.set_provider_tz_bulk()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_ids is required" in body["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone_is_bad_request(self, mock_access):
        handler = _make_handler(json_body={"provider_ids": [PROVIDER_ID], "timezone": "Mars/Olympus"})
        result = handler.set_provider_tz_bulk()
        body, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in body["error"]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(json_body={"provider_ids": [PROVIDER_ID], "timezone": "US/Pacific"})
        result = handler.set_provider_tz_bulk()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN


# ── Static asset serving ─────────────────────────────────────────────────


class TestServeStaticAssets:
    @patch(f"{MODULE}.render_to_string", return_value=":root { --x: 1; }")
    def test_tokens_css(self, mock_render):
        handler = _make_handler()
        result = handler.get_tokens_css()
        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        assert resp.headers["Content-Type"] == "text/css"
        assert mock_render.mock_calls == [call("static/tokens.css")]

    @patch(f"{MODULE}.render_to_string", return_value="body { font: x; }")
    def test_typography_css(self, mock_render):
        handler = _make_handler()
        result = handler.get_typography_css()
        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        assert resp.headers["Content-Type"] == "text/css"
        assert mock_render.mock_calls == [call("static/typography.css")]

    @patch(f"{MODULE}.render_to_string", return_value="customElements.define('x', X);")
    def test_canvas_components_js(self, mock_render):
        handler = _make_handler()
        result = handler.get_canvas_components()
        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        assert resp.headers["Content-Type"] == "application/javascript"
        assert mock_render.mock_calls == [call("static/canvas-components.js")]
