"""Tests for module-level helpers in api/endpoints.py.

These functions encapsulate the authorization rules and are the most
security-relevant pieces of the plugin, so they get dedicated coverage.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from order_sets.api import endpoints
from order_sets.api.endpoints import (
    _can_modify,
    _coerce_bool,
    _is_active_provider,
    _is_admin,
    _serialize_set,
    _validate_diagnosis_codes,
    _validate_items,
    _validate_str,
    _validate_string_list,
)


# ── _is_active_provider ──────────────────────────────────────────────────────

class TestIsActiveProvider:
    def test_empty_staff_id_returns_false(self):
        assert _is_active_provider("") is False

    def test_none_returns_false(self):
        assert _is_active_provider(None) is False  # type: ignore[arg-type]

    def test_active_provider_returns_true(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        assert _is_active_provider("staff-123") is True

        objects.filter.assert_called_once_with(
            role_type="PROVIDER",
            staff__id="staff-123",
            staff__active=True,
        )

    def test_no_matching_provider_returns_false(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        assert _is_active_provider("staff-123") is False


# ── _is_admin ────────────────────────────────────────────────────────────────

class TestIsAdmin:
    def test_none_staff_returns_false(self):
        assert _is_admin(None) is False

    def test_staff_with_admin_role_returns_true(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        staff = MagicMock(id="staff-1")
        assert _is_admin(staff) is True
        # Verify we queried for the administrative domain
        kwargs = objects.filter.call_args.kwargs
        assert kwargs["staff"] is staff
        assert kwargs["domain"] == endpoints.StaffRole.RoleDomain.ADMINISTRATIVE

    def test_staff_without_admin_role_returns_false(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        staff = MagicMock(id="staff-1")
        assert _is_admin(staff) is False


# ── _can_modify (the critical authorization rule) ────────────────────────────

class TestCanModify:
    def _personal_set(self, created_by="creator-1"):
        return MagicMock(is_shared=False, created_by=created_by)

    def _shared_set(self, created_by="creator-1"):
        return MagicMock(is_shared=True, created_by=created_by)

    def test_none_staff_denied(self):
        assert _can_modify(None, self._personal_set()) is False
        assert _can_modify(None, self._shared_set()) is False

    def test_personal_set_creator_allowed(self):
        staff = MagicMock(id="creator-1")
        assert _can_modify(staff, self._personal_set("creator-1")) is True

    def test_personal_set_non_creator_denied(self):
        staff = MagicMock(id="someone-else")
        assert _can_modify(staff, self._personal_set("creator-1")) is False

    def test_personal_set_admin_who_did_not_create_denied(self, monkeypatch):
        """Admin status doesn't grant access to other people's personal sets."""
        # Force _is_admin to return True; should still be denied for personal sets
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        staff = MagicMock(id="admin-99")
        assert _can_modify(staff, self._personal_set("creator-1")) is False

    def test_shared_set_admin_allowed(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        staff = MagicMock(id="admin-1")
        assert _can_modify(staff, self._shared_set("creator-1")) is True

    def test_shared_set_non_admin_creator_denied(self, monkeypatch):
        """Even the creator can't modify a shared set unless they're an admin."""
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        staff = MagicMock(id="creator-1")
        assert _can_modify(staff, self._shared_set("creator-1")) is False

    def test_shared_set_non_admin_other_staff_denied(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", objects)

        staff = MagicMock(id="random-staff")
        assert _can_modify(staff, self._shared_set("creator-1")) is False


# ── _serialize_set ───────────────────────────────────────────────────────────

class TestSerializeSet:
    def _row(self, **overrides):
        defaults = {
            "set_id": "abc-123",
            "name": "Annual labs",
            "description": "Standard annual panel",
            "order_type": "lab",
            "is_shared": True,
            "created_by": "staff-1",
            "created_by_name": "Dr. Smith",
            "diagnosis_codes": ["Z00.00"],
            "lab_partner": "partner-1",
            "lab_partner_name": "LabCorp",
            "items": [{"code": "CBC", "name": "Complete Blood Count"}],
            "fasting_required": True,
            "comment": "fast 8h",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_id_field_renamed_from_set_id(self):
        result = _serialize_set(self._row())
        assert result["id"] == "abc-123"
        assert "set_id" not in result

    def test_timestamps_serialized_as_iso(self):
        result = _serialize_set(self._row())
        assert result["created_at"] == "2026-01-01T00:00:00+00:00"
        assert result["updated_at"] == "2026-02-01T00:00:00+00:00"

    def test_missing_timestamps_default_to_empty_string(self):
        result = _serialize_set(self._row(created_at=None, updated_at=None))
        assert result["created_at"] == ""
        assert result["updated_at"] == ""

    def test_all_fields_present(self):
        result = _serialize_set(self._row())
        for field in [
            "id", "name", "description", "order_type", "is_shared",
            "created_by", "created_by_name", "diagnosis_codes",
            "lab_partner", "lab_partner_name", "items", "fasting_required",
            "comment", "created_at", "updated_at",
        ]:
            assert field in result, f"missing field: {field}"


# ── Validation helpers (direct unit tests) ──────────────────────────────────

class TestValidateItems:
    def test_non_list_rejected(self):
        assert _validate_items("not a list") == "items must be a list"

    def test_non_dict_element_rejected(self):
        assert _validate_items(["string"]) == "items[0] must be an object"

    def test_missing_code_rejected(self):
        err = _validate_items([{"name": "X"}])
        assert err and "code" in err

    def test_empty_name_rejected(self):
        err = _validate_items([{"code": "X", "name": "   "}])
        assert err and "name" in err

    def test_oversize_code_rejected(self):
        err = _validate_items([{"code": "x" * 500, "name": "X"}])
        assert err and "exceeds maximum length" in err

    def test_oversize_name_rejected(self):
        err = _validate_items([{"code": "X", "name": "x" * 500}])
        assert err and "exceeds maximum length" in err

    def test_valid_items_pass(self):
        assert _validate_items([{"code": "CBC", "name": "Complete Blood Count"}]) is None

    def test_empty_list_passes(self):
        assert _validate_items([]) is None

    def test_duplicate_codes_rejected(self):
        err = _validate_items([
            {"code": "CBC", "name": "First"},
            {"code": "CBC", "name": "Second"},
        ])
        assert err and "duplicates" in err


class TestValidateDiagnosisCodes:
    def test_non_list_rejected(self):
        assert _validate_diagnosis_codes("Z00.00") == "diagnosis_codes must be a list"

    def test_non_string_element_rejected(self):
        err = _validate_diagnosis_codes([123])
        assert err and "must be a string" in err

    def test_oversize_code_rejected(self):
        err = _validate_diagnosis_codes(["X" * 100])
        assert err and "exceeds maximum length" in err

    def test_valid_passes(self):
        assert _validate_diagnosis_codes(["Z00.00", "E11.9"]) is None

    def test_empty_list_passes(self):
        assert _validate_diagnosis_codes([]) is None


class TestValidateStringList:
    def test_non_list_rejected(self):
        assert _validate_string_list("CBC", "selected_codes", max_item_length=10) == \
            "selected_codes must be a list"

    def test_non_string_element_rejected(self):
        err = _validate_string_list(["CBC", 42], "selected_codes", max_item_length=10)
        assert err and "[1]" in err

    def test_oversize_element_rejected(self):
        err = _validate_string_list(["x" * 50], "selected_codes", max_item_length=10)
        assert err and "exceeds maximum length" in err

    def test_valid_passes(self):
        assert _validate_string_list(["CBC", "TSH"], "selected_codes", max_item_length=10) is None


class TestValidateStr:
    def test_none_required_rejected(self):
        cleaned, err = _validate_str(None, "name", max_length=200, required=True)
        assert cleaned is None and err == "name is required"

    def test_none_optional_returns_empty(self):
        cleaned, err = _validate_str(None, "description", max_length=2000)
        assert cleaned == "" and err is None

    def test_non_string_rejected(self):
        cleaned, err = _validate_str({"foo": "bar"}, "name", max_length=200)
        assert cleaned is None and err and "must be a string" in err

    def test_oversize_rejected(self):
        cleaned, err = _validate_str("x" * 500, "name", max_length=200)
        assert cleaned is None and err and "exceeds maximum length" in err

    def test_whitespace_only_required_rejected(self):
        cleaned, err = _validate_str("   ", "name", max_length=200, required=True)
        assert cleaned is None and err == "name is required"

    def test_valid_returns_value(self):
        cleaned, err = _validate_str("Hello", "name", max_length=200)
        assert cleaned == "Hello" and err is None


class TestCoerceBool:
    def test_true_accepted(self):
        v, err = _coerce_bool(True, "is_shared")
        assert v is True and err is None

    def test_false_accepted(self):
        v, err = _coerce_bool(False, "is_shared")
        assert v is False and err is None

    def test_string_rejected(self):
        v, err = _coerce_bool("false", "is_shared")
        assert v is False and err and "must be a JSON boolean" in err

    def test_int_rejected(self):
        v, err = _coerce_bool(1, "is_shared")
        assert v is False and err and "must be a JSON boolean" in err

    def test_none_rejected(self):
        v, err = _coerce_bool(None, "is_shared")
        assert v is False and err and "must be a JSON boolean" in err
