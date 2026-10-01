"""Tests for the collections report API handler."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from collections_report.handlers.api import (
    _compute_summary,
    _serialize_collection,
)


class TestSerializeCollection:
    """Tests for _serialize_collection."""

    def test_serializes_payment_with_patient(self):
        """A payment linked to a patient includes the patient name."""
        payer = MagicMock()
        payer.first_name = "Jane"
        payer.last_name = "Doe"

        bulk = MagicMock()
        bulk.payer = payer

        pc = MagicMock()
        pc.id = 1
        pc.created = datetime(2026, 7, 26, 14, 30, 0, tzinfo=timezone.utc)
        pc.total_collected = Decimal("150.00")
        pc.method = "card"
        pc.description = "Copay"
        pc.check_number = ""
        pc.deposit_date = None
        pc.bulkpatientposting = bulk

        result = _serialize_collection(pc)

        assert result["patient_name"] == "Jane Doe"
        assert result["amount"] == "150.00"
        assert result["amount_display"] == "$150.00"
        assert result["method"] == "card"
        assert result["method_display"] == "Card"
        assert result["date_display"] == "07/26/2026 02:30 PM"

    def test_serializes_payment_without_patient(self):
        """A payment with no linked patient shows a dash."""
        pc = MagicMock()
        pc.id = 2
        pc.created = datetime(2026, 7, 26, 10, 0, 0, tzinfo=timezone.utc)
        pc.total_collected = Decimal("50.00")
        pc.method = "cash"
        pc.description = ""
        pc.check_number = ""
        pc.deposit_date = None

        # Simulate no BulkPatientPosting linked
        type(pc).bulkpatientposting = property(
            lambda self: (_ for _ in ()).throw(
                type("RelatedObjectDoesNotExist", (Exception,), {})()
            )
        )

        result = _serialize_collection(pc)
        assert result["patient_name"] == "—"
        assert result["amount"] == "50.00"

    def test_serializes_zero_amount(self):
        """A payment with zero amount displays $0.00."""
        bulk = MagicMock()
        bulk.payer = None

        pc = MagicMock()
        pc.id = 3
        pc.created = None
        pc.total_collected = None
        pc.method = None
        pc.description = None
        pc.check_number = None
        pc.deposit_date = None
        pc.bulkpatientposting = bulk

        result = _serialize_collection(pc)
        assert result["amount_display"] == "$0.00"
        assert result["date"] is None
        assert result["date_display"] == ""


class TestComputeSummary:
    """Tests for _compute_summary."""

    def test_computes_totals_by_method(self):
        """Summary correctly sums amounts by payment method."""
        collections = [
            {"amount": "100.00", "method": "card"},
            {"amount": "50.00", "method": "card"},
            {"amount": "75.00", "method": "cash"},
            {"amount": "200.00", "method": "check"},
        ]

        summary = _compute_summary(collections)

        assert summary["total"] == "425.00"
        assert summary["total_display"] == "$425.00"
        assert summary["card"] == "150.00"
        assert summary["cash"] == "75.00"
        assert summary["check"] == "200.00"
        assert summary["other"] == "0.00"

    def test_unknown_method_goes_to_other(self):
        """Unrecognized payment methods are bucketed as 'other'."""
        collections = [
            {"amount": "30.00", "method": "wire"},
        ]

        summary = _compute_summary(collections)
        assert summary["other"] == "30.00"
        assert summary["total"] == "30.00"

    def test_empty_collections(self):
        """Empty input returns all zeros."""
        summary = _compute_summary([])

        assert summary["total"] == "0.00"
        assert summary["card"] == "0.00"
        assert summary["cash"] == "0.00"
        assert summary["check"] == "0.00"
        assert summary["other"] == "0.00"
