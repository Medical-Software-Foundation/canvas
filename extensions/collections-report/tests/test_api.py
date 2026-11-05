"""Tests for the collections report API handler."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.v1.data import PaymentCollection

from collections_report.handlers.api import (
    _balances_summary,
    _compute_summary,
    _csv_cell,
    _query_balances,
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
        missing = PaymentCollection.bulkpatientposting.RelatedObjectDoesNotExist

        class NoPatientPayment:
            """Plain stand-in: Django raises RelatedObjectDoesNotExist (an
            AttributeError) for a missing reverse one-to-one. A MagicMock would
            swallow that AttributeError and hand back a child mock instead."""

            id = 2
            created = datetime(2026, 7, 26, 10, 0, 0, tzinfo=timezone.utc)
            total_collected = Decimal("50.00")
            method = "cash"
            description = ""
            check_number = ""
            deposit_date = None

            @property
            def bulkpatientposting(self):
                raise missing()

        result = _serialize_collection(NoPatientPayment())
        assert result["patient_name"] == "\u2014"
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


def _claim(patient, balance, dos=None):
    """Build a mock claim with a patient balance and a note date of service."""
    claim = MagicMock()
    claim.patient_balance = Decimal(balance)
    claim.note.patient = patient
    claim.note.datetime_of_service = dos
    return claim


def _patient(pid, first, last):
    """Build a mock patient."""
    patient = MagicMock()
    patient.id = pid
    patient.first_name = first
    patient.last_name = last
    return patient


class TestQueryBalances:
    """Tests for _query_balances (one row per patient who owes money)."""

    def test_sums_claims_per_patient_largest_first(self):
        """Claims roll up per patient, sorted by balance, with open claim count and oldest DOS."""
        jane = _patient("p1", "Jane", "Doe")
        john = _patient("p2", "John", "Roe")
        older = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
        claims = [
            _claim(jane, "40.00", newer),
            _claim(jane, "60.00", older),
            _claim(john, "250.00", newer),
        ]
        with patch("collections_report.handlers.api._balance_claims", return_value=claims):
            rows = _query_balances()

        assert [r["patient_name"] for r in rows] == ["John Roe", "Jane Doe"]
        assert rows[0]["balance"] == "250.00"
        assert rows[1]["balance"] == "100.00"
        assert rows[1]["balance_display"] == "$100.00"
        assert rows[1]["open_claims"] == 2
        assert rows[1]["oldest_dos"] == "2026-05-01"
        assert rows[1]["oldest_dos_display"] == "05/01/2026"

    def test_credit_offsets_balance_and_zero_or_negative_totals_are_dropped(self):
        """A negative claim reduces the total; patients who net to zero or a credit are not listed."""
        jane = _patient("p1", "Jane", "Doe")
        john = _patient("p2", "John", "Roe")
        claims = [
            _claim(jane, "100.00"),
            _claim(jane, "-30.00"),
            _claim(john, "20.00"),
            _claim(john, "-20.00"),
        ]
        with patch("collections_report.handlers.api._balance_claims", return_value=claims):
            rows = _query_balances()

        assert len(rows) == 1
        assert rows[0]["patient_name"] == "Jane Doe"
        assert rows[0]["balance"] == "70.00"
        assert rows[0]["open_claims"] == 1

    def test_claims_without_a_patient_are_skipped(self):
        """A claim whose note has no patient contributes nothing."""
        claims = [_claim(None, "50.00")]
        with patch("collections_report.handlers.api._balance_claims", return_value=claims):
            assert _query_balances() == []


class TestBalancesSummary:
    """Tests for _balances_summary."""

    def test_totals_and_patient_count(self):
        """Summary adds up balances and counts patients."""
        summary = _balances_summary([{"balance": "250.00"}, {"balance": "100.50"}])
        assert summary["total"] == "350.50"
        assert summary["total_display"] == "$350.50"
        assert summary["patients"] == 2

    def test_empty(self):
        """No balances means zero owed."""
        summary = _balances_summary([])
        assert summary["total"] == "0.00"
        assert summary["patients"] == 0


class TestCsvCell:
    """Tests for _csv_cell."""

    def test_quotes_and_escapes(self):
        """Values are wrapped in quotes and embedded quotes are doubled."""
        assert _csv_cell('Say "hi"') == '"Say ""hi"""'

    def test_none_becomes_empty(self):
        """None renders as an empty quoted cell."""
        assert _csv_cell(None) == '""'
