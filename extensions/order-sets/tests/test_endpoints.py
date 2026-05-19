"""Tests for OrderSetsAPI handler methods.

Focus areas (highest security/correctness risk first):
- update_set / delete_set: ownership and admin authorization rules
- execute_set / execute_custom: provider impersonation guard
- Error responses: generic message, no exception leakage
- CRUD happy paths
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest  # noqa: F401  (used by monkeypatch fixture)

from order_sets.api import endpoints
from order_sets.api.endpoints import OrderSetsAPI


# ── Test fixtures ────────────────────────────────────────────────────────────

def make_handler(
    body=None,
    path_params=None,
    query_params=None,
    headers=None,
    request_body=b"",
):
    """Build an OrderSetsAPI instance with a mocked request, without running __init__."""
    handler = OrderSetsAPI.__new__(OrderSetsAPI)
    handler.request = MagicMock()
    handler.request.json.return_value = body if body is not None else {}
    handler.request.path_params = path_params or {}
    handler.request.query_params = query_params or {}
    handler.request.headers = headers or {}
    handler.request.body = request_body
    return handler


def staff(id_="staff-1", first="Ada", last="Lovelace", active=True):
    s = MagicMock()
    s.id = id_
    s.first_name = first
    s.last_name = last
    s.active = active
    return s


def order_set_row(
    set_id="set-1",
    is_shared=False,
    created_by="staff-1",
    order_type="lab",
    items=None,
    lab_partner="partner-1",
    diagnosis_codes=None,
    fasting_required=False,
    comment="",
    name="My Set",
):
    row = MagicMock()
    row.set_id = set_id
    row.name = name
    row.description = ""
    row.is_shared = is_shared
    row.created_by = created_by
    row.created_by_name = "Creator"
    row.order_type = order_type
    row.items = items if items is not None else [{"code": "CBC", "name": "CBC"}]
    row.lab_partner = lab_partner
    row.lab_partner_name = "LabCorp"
    row.diagnosis_codes = diagnosis_codes or []
    row.fasting_required = fasting_required
    row.comment = comment
    row.created_at = None
    row.updated_at = None
    return row


def assert_response(resp, status):
    """Resp is the JSONResponse stand-in built in conftest._fake_response."""
    assert resp.status_code == status


# ── update_set authorization ─────────────────────────────────────────────────

class TestUpdateSetAuthorization:
    def test_404_when_set_missing(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        # Staff must resolve for the handler to reach the set-lookup branch
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"name": "new name"},
            path_params={"set_id": "missing"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.NOT_FOUND)

    def test_401_when_no_staff(self, monkeypatch):
        """Defense-in-depth: handler fails closed when _current_staff returns None."""
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"name": "x"},
            path_params={"set_id": "any"},
            # No canvas-logged-in-user-id header
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.UNAUTHORIZED)

    def test_personal_set_creator_can_update(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        # _current_staff resolves staff-1
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"name": "renamed"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.OK)
        row.save.assert_called_once()
        assert row.name == "renamed"

    def test_personal_set_non_creator_returns_404(self, monkeypatch):
        """Non-creator hitting another user's personal set gets 404 (not 403),
        so existence isn't confirmed. Mirrors execute_set / execute_custom."""
        row = order_set_row(is_shared=False, created_by="creator-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("intruder-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"name": "hacked"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "intruder-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.NOT_FOUND)
        row.save.assert_not_called()

    def test_shared_set_admin_can_update(self, monkeypatch):
        row = order_set_row(is_shared=True, created_by="creator-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("admin-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # Admin lookup says yes
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"name": "admin update"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "admin-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.OK)
        row.save.assert_called_once()

    def test_shared_set_non_admin_denied_with_403(self, monkeypatch):
        row = order_set_row(is_shared=True, created_by="creator-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # Not an admin
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"name": "should be blocked"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.FORBIDDEN)
        row.save.assert_not_called()


# ── delete_set authorization ─────────────────────────────────────────────────

class TestDeleteSetAuthorization:
    def test_404_when_set_missing(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            path_params={"set_id": "missing"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.delete_set()

        assert_response(resp, HTTPStatus.NOT_FOUND)

    def test_401_when_no_staff(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(path_params={"set_id": "any"})
        [resp] = handler.delete_set()
        assert_response(resp, HTTPStatus.UNAUTHORIZED)

    def test_personal_set_non_creator_returns_404(self, monkeypatch):
        """Same 404-for-unauthorized pattern as update_set / execute_*."""
        row = order_set_row(is_shared=False, created_by="creator-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("intruder-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "intruder-1"},
        )
        [resp] = handler.delete_set()

        assert_response(resp, HTTPStatus.NOT_FOUND)
        row.delete.assert_not_called()

    def test_shared_set_non_admin_denied(self, monkeypatch):
        row = order_set_row(is_shared=True, created_by="creator-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.delete_set()

        assert_response(resp, HTTPStatus.FORBIDDEN)
        row.delete.assert_not_called()

    def test_shared_set_admin_can_delete(self, monkeypatch):
        row = order_set_row(is_shared=True, created_by="creator-1")
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("admin-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "admin-1"},
        )
        [resp] = handler.delete_set()

        assert_response(resp, HTTPStatus.OK)
        row.delete.assert_called_once()


# ── execute_set / provider impersonation guard ───────────────────────────────

class TestExecuteProviderGuard:
    def _patch_find_open_note(self, handler, note_uuid="note-1", provider_key=""):
        handler._find_open_note = lambda patient_id: (note_uuid, provider_key)

    def test_logged_in_provider_uses_own_id_ignoring_body(self, monkeypatch):
        row = order_set_row(
            order_type="lab",
            items=[{"code": "CBC", "name": "CBC"}],
            is_shared=True,  # so _can_view passes for the test's logged-in staff
        )
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # provider-1 IS a provider; impersonation-target IS also a provider
        # but should NOT be used.
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1", "provider_id": "different-provider"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "provider-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        self._patch_find_open_note(handler)

        effects = handler.execute_set()

        # The last effect is the JSONResponse summary
        resp = effects[-1]
        assert_response(resp, HTTPStatus.OK)

        # Find the LabOrderCommand among effects and verify it used provider-1
        lab_effects = [e for e in effects if getattr(e, "_kind", None) == "lab"]
        assert len(lab_effects) == 1
        assert lab_effects[0]._kwargs["ordering_provider_key"] == "provider-1"

    def test_non_provider_must_supply_provider_id(self, monkeypatch):
        row = order_set_row(order_type="lab", is_shared=True)
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("ma-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # ma-1 is NOT a provider
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},  # NO provider_id
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "ma-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        self._patch_find_open_note(handler)

        [resp] = handler.execute_set()

        assert_response(resp, HTTPStatus.BAD_REQUEST)
        assert resp.body["needs_provider"] is True

    def test_non_provider_supplies_valid_provider_id(self, monkeypatch):
        row = order_set_row(order_type="lab", is_shared=True)
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("ma-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # First call (ma-1 provider check) → False
        # Second call (provider-9 provider check) → True
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.side_effect = [False, True]
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1", "provider_id": "provider-9"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "ma-1"},
            request_body=b'{"patient_id": "p-1", "provider_id": "provider-9"}',
        )
        self._patch_find_open_note(handler)

        effects = handler.execute_set()

        resp = effects[-1]
        assert_response(resp, HTTPStatus.OK)
        lab_effects = [e for e in effects if getattr(e, "_kind", None) == "lab"]
        assert lab_effects[0]._kwargs["ordering_provider_key"] == "provider-9"

    def test_non_provider_supplies_invalid_provider_id_rejected(self, monkeypatch):
        row = order_set_row(order_type="lab", is_shared=True)
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("ma-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # Both provider checks return False
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1", "provider_id": "not-a-provider"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "ma-1"},
            request_body=b'{"patient_id": "p-1", "provider_id": "not-a-provider"}',
        )
        self._patch_find_open_note(handler)

        [resp] = handler.execute_set()

        assert_response(resp, HTTPStatus.BAD_REQUEST)
        assert resp.body["needs_provider"] is True

    def test_no_open_note_rejected(self, monkeypatch):
        row = order_set_row(order_type="lab", is_shared=True)
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda patient_id: (None, "")

        [resp] = handler.execute_set()

        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_no_items_rejected(self, monkeypatch):
        row = order_set_row(items=[], is_shared=True)
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda patient_id: ("note-1", "")

        [resp] = handler.execute_set()

        assert_response(resp, HTTPStatus.BAD_REQUEST)


# ── execute_set order_type branches ──────────────────────────────────────────

class TestExecuteOrderTypes:
    def _run(self, monkeypatch, row, body=None):
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body=body or {"patient_id": "p-1"},
            path_params={"set_id": row.set_id},
            headers={"canvas-logged-in-user-id": "provider-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda patient_id: ("note-1", "")
        return handler.execute_set()

    def test_lab_order_path(self, monkeypatch):
        row = order_set_row(
            order_type="lab",
            items=[{"code": "CBC", "name": "CBC"}, {"code": "CMP", "name": "CMP"}],
            diagnosis_codes=["Z00.00"],
            fasting_required=True,
            comment="fast 8h",
            is_shared=True,
        )
        effects = self._run(monkeypatch, row)
        lab_effects = [e for e in effects if getattr(e, "_kind", None) == "lab"]
        assert len(lab_effects) == 1
        assert lab_effects[0]._kwargs["tests_order_codes"] == ["CBC", "CMP"]
        assert lab_effects[0]._kwargs["fasting_required"] is True
        resp = effects[-1]
        assert resp.body["items_count"] == 2

    def test_imaging_order_path(self, monkeypatch):
        row = order_set_row(
            order_type="imaging",
            items=[{"code": "71045", "name": "CXR 1V"}, {"code": "73610", "name": "Ankle"}],
            is_shared=True,
        )
        effects = self._run(monkeypatch, row)
        imaging_effects = [e for e in effects if getattr(e, "_kind", None) == "imaging"]
        assert len(imaging_effects) == 2  # one command per imaging item
        codes = [e._kwargs["image_code"] for e in imaging_effects]
        assert codes == ["71045", "73610"]

    def test_poc_order_path_skips_provider_gate_for_non_provider(self, monkeypatch):
        """POC orders use PerformCommand which has no ordering_provider_key, so
        a non-provider (e.g., medical assistant) should be able to place POC
        orders without supplying provider_id and without 400 from the gate."""
        row = order_set_row(
            order_type="poc",
            items=[{"code": "87880", "name": "Rapid Strep"}],
            is_shared=True,
        )
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        # Non-provider staff
        s = staff("ma-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # _is_active_provider returns False (MA is not a provider)
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},  # NO provider_id supplied
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "ma-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda _: ("note-1", "")
        effects = handler.execute_set()

        # Must succeed: POC doesn't require provider attribution
        assert effects[-1].status_code == HTTPStatus.OK
        poc_effects = [e for e in effects if getattr(e, "_kind", None) == "perform"]
        assert len(poc_effects) == 1

    def test_poc_order_path(self, monkeypatch):
        row = order_set_row(
            order_type="poc",
            items=[{"code": "87880", "name": "Rapid Strep"}],
            comment="reflex to culture if neg",
            is_shared=True,
        )
        effects = self._run(monkeypatch, row)
        poc_effects = [e for e in effects if getattr(e, "_kind", None) == "perform"]
        assert len(poc_effects) == 1
        assert poc_effects[0]._kwargs["cpt_code"] == "87880"
        # Comment is appended to the notes field
        assert "reflex" in poc_effects[0]._kwargs["notes"]


# ── execute_custom: only selected codes are ordered ──────────────────────────

class TestExecuteCustom:
    def test_only_selected_codes_ordered(self, monkeypatch):
        row = order_set_row(
            order_type="lab",
            items=[
                {"code": "CBC", "name": "CBC"},
                {"code": "CMP", "name": "CMP"},
                {"code": "TSH", "name": "TSH"},
            ],
            is_shared=True,
        )
        objects = MagicMock()
        objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={
                "set_id": "set-1",
                "patient_id": "p-1",
                "selected_codes": ["CBC", "TSH"],
            },
            headers={"canvas-logged-in-user-id": "provider-1"},
        )
        handler._find_open_note = lambda patient_id: ("note-1", "")

        effects = handler.execute_custom()
        lab_effects = [e for e in effects if getattr(e, "_kind", None) == "lab"]
        assert lab_effects[0]._kwargs["tests_order_codes"] == ["CBC", "TSH"]

    def test_missing_order_set_returns_404(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"set_id": "missing"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.execute_custom()

        assert_response(resp, HTTPStatus.NOT_FOUND)


# ── create_set + list_sets happy paths ──────────────────────────────────────

class TestCreate:
    def test_create_persists_with_creator_attribution(self, monkeypatch):
        created_row = order_set_row(set_id="new-id", created_by="staff-1")
        objects = MagicMock()
        objects.create.return_value = created_row
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        s = staff("staff-1", first="Grace", last="Hopper")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={
                "name": "Morning panel",
                "order_type": "lab",
                "lab_partner": "partner-1",
                "items": [{"code": "CBC", "name": "CBC"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )

        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.CREATED)
        kwargs = objects.create.call_args.kwargs
        assert kwargs["created_by"] == "staff-1"
        assert kwargs["created_by_name"] == "Grace Hopper"


# ── is_shared promotion guard (create + update) ──────────────────────────────
#
# Documented authorization model says: only administrators may set or change
# `is_shared`. Without this guard, a non-admin creator could promote their
# personal set to shared, then lose modify rights under the shared-set rule.

class TestSharedFlagGuard:
    def _setup_staff(self, monkeypatch, staff_id="staff-1", is_admin=False):
        s = staff(staff_id)
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = is_admin
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)
        return s

    def _valid_lab_body(self, **overrides):
        body = {
            "name": "Shared panel",
            "order_type": "lab",
            "lab_partner": "partner-1",
            "items": [{"code": "CBC", "name": "CBC"}],
        }
        body.update(overrides)
        return body

    def test_create_with_is_shared_true_requires_admin(self, monkeypatch):
        self._setup_staff(monkeypatch, is_admin=False)
        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body=self._valid_lab_body(is_shared=True),
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()

        assert_response(resp, HTTPStatus.FORBIDDEN)
        os_objects.create.assert_not_called()

    def test_create_with_is_shared_true_allowed_for_admin(self, monkeypatch):
        self._setup_staff(monkeypatch, is_admin=True)
        created_row = order_set_row(is_shared=True)
        os_objects = MagicMock()
        os_objects.create.return_value = created_row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body=self._valid_lab_body(is_shared=True),
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()

        assert_response(resp, HTTPStatus.CREATED)
        os_objects.create.assert_called_once()

    def test_create_personal_set_does_not_require_admin(self, monkeypatch):
        self._setup_staff(monkeypatch, is_admin=False)
        created_row = order_set_row(is_shared=False)
        os_objects = MagicMock()
        os_objects.create.return_value = created_row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body=self._valid_lab_body(name="Personal panel", is_shared=False),
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()

        assert_response(resp, HTTPStatus.CREATED)

    def test_update_cannot_promote_personal_to_shared_without_admin(self, monkeypatch):
        # Row is currently personal, created by staff-1.
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        # staff-1 is the creator but NOT an admin.
        self._setup_staff(monkeypatch, staff_id="staff-1", is_admin=False)

        handler = make_handler(
            body={"is_shared": True},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.FORBIDDEN)
        row.save.assert_not_called()
        assert row.is_shared is False

    def test_update_admin_creator_can_promote(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="admin-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        self._setup_staff(monkeypatch, staff_id="admin-1", is_admin=True)

        handler = make_handler(
            body={"is_shared": True, "name": "Now shared"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "admin-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.OK)
        row.save.assert_called_once()
        assert row.is_shared is True

    def test_update_without_changing_is_shared_works_for_creator(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        self._setup_staff(monkeypatch, staff_id="staff-1", is_admin=False)

        handler = make_handler(
            body={"name": "renamed"},  # no is_shared in body
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.OK)
        row.save.assert_called_once()


# ── Unexpected exceptions propagate ──────────────────────────────────────────
#
# Per REVIEW.md item #3 ("Do not swallow exceptions with blanket try/except"),
# unexpected exceptions are not caught by the handler — they propagate to the
# SDK framework, which logs them to Sentry and returns a true unhandled 500.

# ── execute visibility (mirror _can_modify for execute paths) ────────────────
#
# Closes the gap where a non-creator could execute another user's personal
# set if they knew its UUID — same auth-bypass shape as the original High
# finding, applied to the execute paths.

class TestExecuteVisibility:
    def test_execute_personal_set_by_non_creator_returns_404(self, monkeypatch):
        """Returning 404 (not 403) avoids confirming the set's existence."""
        row = order_set_row(is_shared=False, created_by="creator-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("intruder-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "intruder-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        [resp] = handler.execute_set()

        assert_response(resp, HTTPStatus.NOT_FOUND)

    def test_execute_custom_personal_set_by_non_creator_returns_404(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="creator-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("intruder-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"set_id": "set-1", "patient_id": "p-1", "selected_codes": ["CBC"]},
            headers={"canvas-logged-in-user-id": "intruder-1"},
        )
        [resp] = handler.execute_custom()

        assert_response(resp, HTTPStatus.NOT_FOUND)

    def test_execute_shared_set_by_any_staff_succeeds(self, monkeypatch):
        row = order_set_row(
            is_shared=True, created_by="someone-else", order_type="lab",
            items=[{"code": "CBC", "name": "CBC"}],
        )
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "provider-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda _: ("note-1", "")
        effects = handler.execute_set()

        # Last effect is the OK summary
        assert effects[-1].status_code == HTTPStatus.OK

    def test_execute_personal_set_by_creator_succeeds(self, monkeypatch):
        row = order_set_row(
            is_shared=False, created_by="provider-1", order_type="lab",
            items=[{"code": "CBC", "name": "CBC"}],
        )
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "provider-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda _: ("note-1", "")
        effects = handler.execute_set()

        assert effects[-1].status_code == HTTPStatus.OK


# ── order_type validation at write + execute time ──────────────────────────

class TestOrderTypeValidation:
    def test_create_rejects_missing_name(self, monkeypatch):
        """REVIEW.md #6: fail explicitly, not silently."""
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        # No "name" field
        handler = make_handler(
            body={"order_type": "lab"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

        # Empty/whitespace name
        handler = make_handler(
            body={"name": "   ", "order_type": "lab"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_unknown_order_type(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={"name": "bad", "order_type": "POC"},  # wrong case
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()

        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

    def test_update_rejects_unknown_order_type(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"order_type": "laboratory"},  # typo
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()

        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_create_rejects_invalid_items_shape(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        # items contains an object without code/name
        handler = make_handler(
            body={
                "name": "Bad", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"foo": "bar"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

        # items contains a non-dict
        handler = make_handler(
            body={
                "name": "Bad", "order_type": "lab", "lab_partner": "p-1",
                "items": ["just a string"],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

        # items has empty code
        handler = make_handler(
            body={
                "name": "Bad", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "", "name": "X"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_lab_requires_non_empty_lab_partner(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "",
                "items": [{"code": "CBC", "name": "CBC"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

    def test_create_imaging_does_not_require_lab_partner(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        created_row = order_set_row(order_type="imaging")
        os_objects = MagicMock()
        os_objects.create.return_value = created_row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "imaging", "lab_partner": "",
                "items": [{"code": "71045", "name": "CXR"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.CREATED)

    def test_create_rejects_string_boolean(self, monkeypatch):
        """`{\"is_shared\": \"false\"}` must NOT silently flip to True."""
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "is_shared": "false",  # STRING, not bool
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

    def test_create_rejects_invalid_diagnosis_codes(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "diagnosis_codes": [123, "Z00.00"],  # contains non-string
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_update_rejects_changing_order_type_to_lab_without_partner(self, monkeypatch):
        # Existing row is imaging-typed with empty lab_partner
        row = order_set_row(
            order_type="imaging", lab_partner="", created_by="staff-1", is_shared=False
        )
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # Request flips order_type to "lab" without supplying lab_partner
        handler = make_handler(
            body={"order_type": "lab"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_update_rejects_invalid_items_shape(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"items": [{"foo": "bar"}]},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_update_rejects_empty_name(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"name": "   "},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_update_rejects_string_boolean_for_is_shared(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"is_shared": "false"},  # STRING
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_create_rejects_non_string_description(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "description": {"not": "a string"},
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

    def test_create_rejects_description_over_max_length(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "description": "x" * 5000,  # over _MAX_DESCRIPTION (2000)
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_oversize_name(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "x" * 500,  # over _MAX_NAME (200)
                "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_duplicate_item_codes(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [
                    {"code": "CBC", "name": "first"},
                    {"code": "CBC", "name": "second"},
                ],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        os_objects.create.assert_not_called()

    def test_create_rejects_oversize_item_code(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "C" * 500, "name": "CBC"}],  # over _MAX_ITEM_CODE
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_oversize_diagnosis_code(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        os_objects = MagicMock()
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "diagnosis_codes": ["Z" * 500],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_execute_custom_rejects_non_list_selected_codes(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"set_id": "set-1", "patient_id": "p-1", "selected_codes": "CBC"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.execute_custom()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_execute_custom_rejects_non_string_in_selected_codes(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"set_id": "set-1", "patient_id": "p-1", "selected_codes": ["CBC", 42]},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.execute_custom()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_update_rejects_oversize_comment(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"comment": "x" * 5000},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_create_unauthorized_when_no_staff(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(body={"name": "X", "order_type": "lab"})
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.UNAUTHORIZED)

    def test_create_rejects_oversize_comment(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "comment": "x" * 5000,
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_oversize_lab_partner(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab",
                "lab_partner": "p" * 500,  # over _MAX_LAB_PARTNER (100)
                "items": [{"code": "CBC", "name": "CBC"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_non_string_lab_partner_name(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "lab_partner_name": 42,  # not a string
                "items": [{"code": "CBC", "name": "CBC"}],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_create_rejects_string_fasting_required(self, monkeypatch):
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={
                "name": "X", "order_type": "lab", "lab_partner": "p-1",
                "items": [{"code": "CBC", "name": "CBC"}],
                "fasting_required": "yes",  # string, not bool
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.create_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)

    def test_update_rejects_invalid_diagnosis_codes(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"diagnosis_codes": [123, "Z00.00"]},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_update_successfully_changes_fasting_required(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1", fasting_required=False)
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"fasting_required": True},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.OK)
        assert row.fasting_required is True
        row.save.assert_called_once()

    def test_execute_unauthorized_when_no_staff(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        [resp] = handler.execute_set()
        assert_response(resp, HTTPStatus.UNAUTHORIZED)

    def test_execute_custom_unauthorized_when_no_staff(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(body={"set_id": "set-1", "patient_id": "p-1"})
        [resp] = handler.execute_custom()
        assert_response(resp, HTTPStatus.UNAUTHORIZED)

    def test_update_rejects_string_fasting_required(self, monkeypatch):
        row = order_set_row(is_shared=False, created_by="staff-1")
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            body={"fasting_required": "yes"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        [resp] = handler.update_set()
        assert_response(resp, HTTPStatus.BAD_REQUEST)
        row.save.assert_not_called()

    def test_execute_rejects_set_with_unknown_order_type(self, monkeypatch):
        """Defense in depth: if an OrderSet row somehow has a bad order_type
        (DB migration, direct write, etc.), execute returns 400 instead of
        silently no-op."""
        row = order_set_row(
            is_shared=True,
            order_type="unknown-thing",
            items=[{"code": "X", "name": "X"}],
        )
        os_objects = MagicMock()
        os_objects.filter.return_value.first.return_value = row
        monkeypatch.setattr(endpoints.OrderSet, "objects", os_objects)

        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(
            body={"patient_id": "p-1"},
            path_params={"set_id": "set-1"},
            headers={"canvas-logged-in-user-id": "provider-1"},
            request_body=b'{"patient_id": "p-1"}',
        )
        handler._find_open_note = lambda _: ("note-1", "")
        effects = handler.execute_set()

        # Single 400 response, no order effects emitted
        assert len(effects) == 1
        assert_response(effects[0], HTTPStatus.BAD_REQUEST)


class TestExceptionsPropagate:
    def test_db_error_raises_instead_of_returning_500(self, monkeypatch):
        import pytest

        # Staff resolves so the handler reaches the OrderSet query.
        s = staff("staff-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        objects = MagicMock()
        objects.filter.side_effect = RuntimeError("internal db detail")
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        handler = make_handler(
            path_params={"set_id": "x"},
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
        with pytest.raises(RuntimeError):
            handler.delete_set()
