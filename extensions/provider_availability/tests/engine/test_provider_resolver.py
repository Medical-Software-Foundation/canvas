"""Tests for provider_availability.engine.provider_resolver."""

from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.engine.provider_resolver import (
    get_provider_display,
    get_provider_displays,
    resolve_provider_id,
    search_providers,
)

STAFF_OBJECTS = "provider_availability.engine.provider_resolver.Staff.objects"


# ── resolve_provider_id ───────────────────────────────────────────────


class TestResolveProviderId:
    def test_returns_provider_id_when_given(self):
        result = resolve_provider_id(provider_id="p1")
        assert result == "p1"

    def test_npi_lookup_success(self):
        mock_staff = MagicMock()
        mock_staff.id = "staff-uuid-123"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.get.return_value = mock_staff

            result = resolve_provider_id(provider_npi="1234567890")

            assert mock_objects.mock_calls == [call.get(npi_number="1234567890")]
            # staff.id is a plain attribute (no mock call); str() on a string is a no-op
            assert mock_staff.mock_calls == []
            assert result == "staff-uuid-123"

    def test_npi_not_found(self):
        from canvas_sdk.v1.data import Staff

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.get.side_effect = Staff.DoesNotExist

            with pytest.raises(ValueError, match="No provider found"):
                resolve_provider_id(provider_npi="9999999999")

            assert mock_objects.mock_calls == [call.get(npi_number="9999999999")]

    def test_npi_multiple_found(self):
        from canvas_sdk.v1.data import Staff

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.get.side_effect = Staff.MultipleObjectsReturned

            with pytest.raises(ValueError, match="Multiple providers found"):
                resolve_provider_id(provider_npi="1234567890")

            assert mock_objects.mock_calls == [call.get(npi_number="1234567890")]

    def test_neither_provided_raises(self):
        with pytest.raises(ValueError, match="Either provider_id or provider_npi"):
            resolve_provider_id()


# ── search_providers ──────────────────────────────────────────────────


class TestSearchProviders:
    def test_empty_query_returns_empty(self):
        assert search_providers("") == []

    def test_whitespace_query_returns_empty(self):
        assert search_providers("   ") == []

    def test_npi_prefix_search(self):
        mock_staff = MagicMock()
        mock_staff.id = "s1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.npi_number = "1234567890"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_qs = MagicMock()
            mock_objects.all.return_value = mock_qs
            mock_qs.filter.return_value = mock_qs
            mock_qs.__getitem__ = MagicMock(return_value=[mock_staff])

            result = search_providers("123")

            assert mock_objects.mock_calls[0] == call.all()
            assert len(result) == 1
            assert result[0]["npi_number"] == "1234567890"

    def test_name_search_single_part(self):
        mock_staff = MagicMock()
        mock_staff.id = "s1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.npi_number = "123"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_qs = MagicMock()
            mock_objects.all.return_value = mock_qs
            mock_qs.filter.return_value = mock_qs
            mock_qs.__or__ = MagicMock(return_value=mock_qs)
            mock_qs.__getitem__ = MagicMock(return_value=[mock_staff])

            result = search_providers("Jane")

            assert len(result) == 1
            assert result[0]["first_name"] == "Jane"

    def test_name_search_two_parts(self):
        mock_staff = MagicMock()
        mock_staff.id = "s1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.npi_number = "123"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_qs = MagicMock()
            mock_objects.all.return_value = mock_qs
            mock_qs.filter.return_value = mock_qs
            mock_qs.__getitem__ = MagicMock(return_value=[mock_staff])

            result = search_providers("Jane Doe")

            assert len(result) == 1

    def test_inactive_filter(self):
        with patch(STAFF_OBJECTS) as mock_objects:
            mock_qs = MagicMock()
            mock_objects.all.return_value = mock_qs
            mock_qs.filter.return_value = mock_qs
            mock_qs.__or__ = MagicMock(return_value=mock_qs)
            mock_qs.__getitem__ = MagicMock(return_value=[])

            search_providers("Jane", active_only=False)

            # Should NOT call filter(active=True) — verify no active filter in the chain
            for c in mock_qs.filter.call_args_list:
                assert "active" not in (c.kwargs or {})


# ── get_provider_display ──────────────────────────────────────────────


class TestGetProviderDisplay:
    def test_found(self):
        mock_staff = MagicMock()
        mock_staff.id = "p1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.npi_number = "1234567890"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.get.return_value = mock_staff

            result = get_provider_display("p1")

            assert mock_objects.mock_calls == [call.get(id="p1")]
            assert result["name"] == "Jane Doe"
            assert result["npi_number"] == "1234567890"

    def test_not_found(self):
        from canvas_sdk.v1.data import Staff

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.get.side_effect = Staff.DoesNotExist

            result = get_provider_display("p1")

            assert mock_objects.mock_calls == [call.get(id="p1")]
            assert result == {"id": "p1", "name": "", "npi_number": ""}


# ── get_provider_displays ─────────────────────────────────────────────


class TestGetProviderDisplays:
    def test_empty_list(self):
        result = get_provider_displays([])
        assert result == {}

    def test_batch_lookup(self):
        mock_staff1 = MagicMock()
        mock_staff1.id = "p1"
        mock_staff1.first_name = "Jane"
        mock_staff1.last_name = "Doe"
        mock_staff1.npi_number = "111"

        mock_staff2 = MagicMock()
        mock_staff2.id = "p2"
        mock_staff2.first_name = "John"
        mock_staff2.last_name = "Smith"
        mock_staff2.npi_number = "222"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.filter.return_value = [mock_staff1, mock_staff2]

            result = get_provider_displays(["p1", "p2"])

            assert "p1" in result
            assert "p2" in result
            assert result["p1"]["name"] == "Jane Doe"
            assert result["p2"]["name"] == "John Smith"

    def test_missing_provider_fallback(self):
        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.filter.return_value = []

            result = get_provider_displays(["p-missing"])

            assert result["p-missing"] == {"id": "p-missing", "name": "", "npi_number": ""}

    def test_deduplicates_ids(self):
        mock_staff = MagicMock()
        mock_staff.id = "p1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.npi_number = "111"

        with patch(STAFF_OBJECTS) as mock_objects:
            mock_objects.filter.return_value = [mock_staff]

            result = get_provider_displays(["p1", "p1"])

            assert len(result) == 1
