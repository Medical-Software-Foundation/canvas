"""Tests for resolving a command's prescriber identity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from photon_integration import prescriber

MODULE = "photon_integration.prescriber"


def _staff(email="kristen@example.com", first="Kristen", last="ONeill"):
    staff = MagicMock()
    staff.first_name = first
    staff.last_name = last
    contact = SimpleNamespace(value=email) if email else None
    staff.telecom.filter.return_value.first.return_value = contact
    return staff


def test_resolves_email_and_name_from_staff():
    with patch(f"{MODULE}.Staff") as staff_cls:
        staff_cls.objects.filter.return_value.first.side_effect = [_staff(), None]
        result = prescriber.resolve_prescriber(
            {"prescriber": {"text": "Kristen ONeill", "value": "usr_1"}}
        )
    assert result == {"email": "kristen@example.com", "name": "Kristen ONeill"}


def test_no_prescriber():
    with patch(f"{MODULE}.Staff") as staff_cls:
        result = prescriber.resolve_prescriber({})
    assert result == {"email": None, "name": None}
    staff_cls.objects.filter.assert_not_called()


def test_staff_not_found_keeps_name_no_email():
    with patch(f"{MODULE}.Staff") as staff_cls:
        staff_cls.objects.filter.return_value.first.return_value = None
        result = prescriber.resolve_prescriber({"prescriber": {"text": "Dr X", "value": "usr_9"}})
    assert result == {"email": None, "name": "Dr X"}


def test_email_lowercased():
    with patch(f"{MODULE}.Staff") as staff_cls:
        staff_cls.objects.filter.return_value.first.side_effect = [
            _staff(email="MixedCase@Example.com"), None
        ]
        assert prescriber.resolve_prescriber(
            {"prescriber": {"value": "usr_1"}}
        )["email"] == "mixedcase@example.com"
