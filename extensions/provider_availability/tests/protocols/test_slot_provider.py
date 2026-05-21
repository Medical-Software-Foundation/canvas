"""Tests for provider_availability.protocols.slot_provider."""

from unittest.mock import MagicMock

from provider_availability.protocols.slot_provider import SlotAvailabilityProvider


class TestSlotAvailabilityProvider:
    def test_compute_returns_empty(self):
        """SlotAvailabilityProvider is disabled and always returns []."""
        mock_event = MagicMock()
        handler = SlotAvailabilityProvider(mock_event)

        result = handler.compute()

        assert result == []
