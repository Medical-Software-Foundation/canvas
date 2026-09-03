"""Tests for resolving a command's prescriber identity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from photon_integration import prescriber

MODULE = "photon_integration.prescriber"


def _staff(email="kristen@example.com", first="Kristen", last="ONeill", telecom_email=None):
    staff = MagicMock()
    staff.first_name = first
    staff.last_name = last
    staff.user = SimpleNamespace(email=email) if email else None
    contact = SimpleNamespace(value=telecom_email) if telecom_email else None
    staff.telecom.filter.return_value.first.return_value = contact
    return staff


def _passthrough_select_related(staff_cls):
    """Make Staff.objects.select_related("user") return the same objects mock, so
    the existing `objects.filter(...)` assertions stay valid."""
    staff_cls.objects.select_related.return_value = staff_cls.objects


def test_resolves_email_by_staff_dbid():
    with patch(f"{MODULE}.Staff") as staff_cls:
        _passthrough_select_related(staff_cls)
        staff_cls.objects.filter.return_value.first.return_value = _staff()
        result = prescriber.resolve_prescriber(
            {"prescriber": {"text": "Kristen ONeill", "value": 358}}
        )
    assert result == {"email": "kristen@example.com", "name": "Kristen ONeill"}
    # numeric prescriber value is the Staff integer pk
    staff_cls.objects.filter.assert_called_once_with(dbid=358)
    # the CanvasUser join is folded in to avoid a second query
    staff_cls.objects.select_related.assert_called_once_with("user")


def test_resolves_by_id_for_non_numeric_ref():
    with patch(f"{MODULE}.Staff") as staff_cls:
        _passthrough_select_related(staff_cls)
        staff_cls.objects.filter.return_value.first.return_value = _staff()
        prescriber.resolve_prescriber({"prescriber": {"value": "stf_abc"}})
    staff_cls.objects.filter.assert_called_once_with(id="stf_abc")


def test_falls_back_to_telecom_email():
    with patch(f"{MODULE}.Staff") as staff_cls:
        _passthrough_select_related(staff_cls)
        staff_cls.objects.filter.return_value.first.return_value = _staff(
            email=None, telecom_email="t@example.com"
        )
        assert prescriber.resolve_prescriber(
            {"prescriber": {"value": 358}}
        )["email"] == "t@example.com"


def test_no_prescriber():
    with patch(f"{MODULE}.Staff") as staff_cls:
        result = prescriber.resolve_prescriber({})
    assert result == {"email": None, "name": None}
    staff_cls.objects.filter.assert_not_called()


def test_staff_not_found_keeps_name_no_email():
    with patch(f"{MODULE}.Staff") as staff_cls:
        _passthrough_select_related(staff_cls)
        staff_cls.objects.filter.return_value.first.return_value = None
        result = prescriber.resolve_prescriber({"prescriber": {"text": "Dr X", "value": "u1"}})
    assert result == {"email": None, "name": "Dr X"}


def test_query_error_propagates():
    # No broad except: a real error from the Staff query surfaces (reaches Sentry)
    # rather than being silently swallowed. The "not found" case is None via
    # .first() (test_staff_not_found_keeps_name_no_email), not an exception.
    with patch(f"{MODULE}.Staff") as staff_cls:
        _passthrough_select_related(staff_cls)
        staff_cls.objects.filter.side_effect = RuntimeError("db connection lost")
        with pytest.raises(RuntimeError):
            prescriber.resolve_prescriber({"prescriber": {"text": "Dr X", "value": "u1"}})


class TestStaffIdentity:
    def test_resolves_by_dbid(self):
        with patch(f"{MODULE}.Staff") as staff_cls:
            _passthrough_select_related(staff_cls)
            staff_cls.objects.filter.return_value.first.return_value = _staff()
            result = prescriber.staff_identity(358)
        assert result["email"] == "kristen@example.com"
        staff_cls.objects.filter.assert_called_once_with(dbid=358)

    def test_resolves_by_public_id(self):
        with patch(f"{MODULE}.Staff") as staff_cls:
            _passthrough_select_related(staff_cls)
            staff_cls.objects.filter.return_value.first.return_value = _staff()
            prescriber.staff_identity("stf_abc")
        staff_cls.objects.filter.assert_called_once_with(id="stf_abc")

    def test_none_ref(self):
        with patch(f"{MODULE}.Staff") as staff_cls:
            assert prescriber.staff_identity(None) == {"email": None, "name": None}
        staff_cls.objects.filter.assert_not_called()


def test_email_lowercased():
    with patch(f"{MODULE}.Staff") as staff_cls:
        _passthrough_select_related(staff_cls)
        staff_cls.objects.filter.return_value.first.return_value = _staff(email="Mixed@Example.com")
        assert prescriber.resolve_prescriber(
            {"prescriber": {"value": "stf_1"}}
        )["email"] == "mixed@example.com"
