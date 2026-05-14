"""Tests for protocols/prescriber_filter.py — the core auth and validation logic."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest


class _StaffDoesNotExist(Exception):
    pass


def _make_staff_obj(uuid: str = "uuid-1", npi: str = "1234567890") -> MagicMock:
    staff = MagicMock()
    staff.id = uuid
    staff.npi_number = npi
    return staff


# ─────────────────────────────────────────────────────────────
# Helper function tests: _get_staff_uuid
# ─────────────────────────────────────────────────────────────

def test_get_staff_uuid_by_dbid() -> None:
    staff_obj = _make_staff_obj("uuid-1")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_uuid

        result = _get_staff_uuid("123")

    assert result == "uuid-1"
    assert mock_staff.objects.mock_calls == [call.get(pk=123)]


def test_get_staff_uuid_by_uuid_string() -> None:
    staff_obj = _make_staff_obj("uuid-1")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_uuid

        result = _get_staff_uuid("uuid-abc")

    assert result == "uuid-1"
    assert mock_staff.objects.mock_calls == [call.get(id="uuid-abc")]


def test_get_staff_uuid_returns_none_when_not_found() -> None:
    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_uuid

        result = _get_staff_uuid("missing")

    assert result is None


# ─────────────────────────────────────────────────────────────
# Helper function tests: _get_staff_npi
# ─────────────────────────────────────────────────────────────

def test_get_staff_npi_returns_npi_string() -> None:
    staff_obj = _make_staff_obj(npi="1234567890")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        result = _get_staff_npi("uuid-a")

    assert result == "1234567890"


def test_get_staff_npi_returns_none_for_default_npi() -> None:
    staff_obj = _make_staff_obj(npi="1111155556")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        result = _get_staff_npi("uuid-a")

    assert result is None


def test_get_staff_npi_returns_none_when_no_npi() -> None:
    staff_obj = _make_staff_obj(npi="")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        result = _get_staff_npi("uuid-a")

    assert result is None


def test_get_staff_npi_returns_none_when_not_found() -> None:
    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        result = _get_staff_npi("missing")

    assert result is None


# ─────────────────────────────────────────────────────────────
# Helper function tests: _is_authorized
# ─────────────────────────────────────────────────────────────

def test_is_authorized_returns_false_when_user_uuid_missing() -> None:
    with patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid") as mock_uuid:
        mock_uuid.side_effect = [None, "prescriber-uuid"]
        from dea_prescriber_filter.protocols.prescriber_filter import _is_authorized

        result = _is_authorized("user", "prescriber")

    assert result is False


def test_is_authorized_returns_true_when_delegation_matches() -> None:
    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid") as mock_uuid,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_all_uuids_for_npi") as mock_all_uuids,
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations") as mock_delegations,
    ):
        mock_uuid.side_effect = ["user-uuid", "prescriber-uuid"]
        mock_npi.side_effect = ["prescriber-npi", "user-npi"]
        mock_all_uuids.side_effect = [["prescriber-uuid"], ["user-uuid"]]
        mock_delegations.return_value = {"prescriber-uuid": ["user-uuid"]}

        from dea_prescriber_filter.protocols.prescriber_filter import _is_authorized

        result = _is_authorized("user", "prescriber")

    assert result is True


def test_is_authorized_returns_false_when_no_delegation() -> None:
    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid") as mock_uuid,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_all_uuids_for_npi") as mock_all_uuids,
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations") as mock_delegations,
    ):
        mock_uuid.side_effect = ["user-uuid", "prescriber-uuid"]
        mock_npi.side_effect = [None, None]
        mock_all_uuids.return_value = []
        mock_delegations.return_value = {}

        from dea_prescriber_filter.protocols.prescriber_filter import _is_authorized

        result = _is_authorized("user", "prescriber")

    assert result is False


# ─────────────────────────────────────────────────────────────
# PrescribeActionFilter — the security gate
# ─────────────────────────────────────────────────────────────

def _make_action_filter_event(user_id: str = "user-1", command_id: str = "cmd-1") -> MagicMock:
    event = MagicMock()
    event.context = {
        "actions": [{"name": "sign_action"}, {"name": "delete_action"}],
        "user": {"staff": user_id},
    }
    event.target.id = command_id
    return event


def _make_command_with_prescriber(prescriber: object) -> MagicMock:
    cmd = MagicMock()
    cmd.data = {"prescriber": prescriber}
    return cmd


def test_action_filter_allows_when_user_npi_matches_prescriber() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized") as mock_auth,
    ):
        mock_command.objects = mock_command_qs
        mock_npi.side_effect = ["shared-npi", "shared-npi"]
        mock_auth.return_value = False

        handler = PrescribeActionFilter.__new__(PrescribeActionFilter)
        handler.event = _make_action_filter_event()

        effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    action_names = [a["name"] for a in payload]
    assert "sign_action" in action_names


def test_action_filter_restricts_when_unauthorized_and_different_npi() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized") as mock_auth,
    ):
        mock_command.objects = mock_command_qs
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]
        mock_auth.return_value = False

        handler = PrescribeActionFilter.__new__(PrescribeActionFilter)
        handler.event = _make_action_filter_event()

        effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    action_names = [a["name"] for a in payload]
    assert "sign_action" not in action_names
    assert "delete_action" in action_names


def test_action_filter_allows_when_authorized_via_prescriber_assist() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized") as mock_auth,
    ):
        mock_command.objects = mock_command_qs
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]
        mock_auth.return_value = True

        handler = PrescribeActionFilter.__new__(PrescribeActionFilter)
        handler.event = _make_action_filter_event()

        effects = handler.compute()

    payload = json.loads(effects[0].payload)
    action_names = [a["name"] for a in payload]
    assert "sign_action" in action_names


def test_action_filter_caches_user_staff_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import (
        AUTH_USER_CACHE_PREFIX,
        AUTH_USER_CACHE_TTL,
        PrescribeActionFilter,
    )

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi", return_value=None),
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized", return_value=True),
    ):
        mock_command.objects = mock_command_qs

        handler = PrescribeActionFilter.__new__(PrescribeActionFilter)
        handler.event = _make_action_filter_event(user_id="user-xyz", command_id="cmd-abc")

        handler.compute()

    assert mock_cache.set.mock_calls == [
        call(f"{AUTH_USER_CACHE_PREFIX}cmd-abc", "user-xyz", timeout_seconds=AUTH_USER_CACHE_TTL)
    ]


def test_action_filter_restricts_when_no_user_staff_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    with patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache):
        handler = PrescribeActionFilter.__new__(PrescribeActionFilter)
        event = MagicMock()
        event.context = {"actions": [{"name": "sign_action"}, {"name": "review"}], "user": {}}
        event.target.id = "cmd-1"
        handler.event = event

        effects = handler.compute()

    payload = json.loads(effects[0].payload)
    action_names = [a["name"] for a in payload]
    assert "sign_action" not in action_names
    assert "review" in action_names
    assert mock_cache.delete.mock_calls == [call("dea:user:cmd-1")]


# ─────────────────────────────────────────────────────────────
# PrescribeValidation — error message display
# ─────────────────────────────────────────────────────────────

def _make_validation_event(command_id: str = "cmd-1") -> MagicMock:
    event = MagicMock()
    event.target.id = command_id
    event.context = {"patient": {"id": "pt-1"}}
    return event


def test_validation_passes_silently_when_no_prescriber() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(None)
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "empty-effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        effects = handler.compute()

    assert effects == ["empty-effect"]
    assert mock_effect_inst.add_error.mock_calls == []


def test_validation_adds_auth_error_when_user_cached_and_unauthorized() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-abc"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "error-effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized", return_value=False),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        handler.compute()

    assert mock_effect_inst.add_error.mock_calls == [
        call("Not authorized to prescribe for this provider.")
    ]


def test_validation_skips_auth_error_when_user_is_prescriber_by_same_staff_uuid() -> None:
    """Edge case: user and prescriber have no NPI but resolve to the same Staff record."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-key"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-key")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid",
            return_value="same-staff-uuid",
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi", return_value=None),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        handler.compute()

    assert mock_effect_inst.add_error.mock_calls == []


def test_validation_skips_auth_error_when_user_is_prescriber_by_npi() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-abc"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi", return_value="shared-npi"),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        handler.compute()

    assert mock_effect_inst.add_error.mock_calls == []


def test_validation_adds_state_error_when_mismatch() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # No user cached
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value="State mismatch error"),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        handler.compute()

    assert mock_effect_inst.add_error.mock_calls == [call("State mismatch error")]


def test_validation_reads_user_from_event_context_when_present() -> None:
    """Primary path: user.staff is in POST_VALIDATION event context — cache is not consulted."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # cache is empty — proves we read from context
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    event = _make_validation_event()
    event.context = {"patient": {"id": "pt-1"}, "user": {"staff": "user-from-context"}}

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized", return_value=False),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = event

        handler.compute()

    assert mock_effect_inst.add_error.mock_calls == [
        call("Not authorized to prescribe for this provider.")
    ]
    assert mock_cache.get.mock_calls == []  # cache was not consulted


def test_validation_adds_both_errors_when_unauthorized_and_state_mismatch() -> None:
    """When BOTH conditions are true, both error messages must appear together."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-from-cache"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.get_cache", return_value=mock_cache),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect") as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized", return_value=False),
        patch.object(
            PrescribeValidation,
            "_check_pharmacy_state",
            return_value="Prescriber state (AR) does not match pharmacy state (NC).",
        ),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        handler.compute()

    assert mock_effect_inst.add_error.mock_calls == [
        call("Not authorized to prescribe for this provider."),
        call("Prescriber state (AR) does not match pharmacy state (NC)."),
    ]


# ─────────────────────────────────────────────────────────────
# _get_prescriber_key — handles various input formats
# ─────────────────────────────────────────────────────────────

def test_get_prescriber_key_handles_string() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-abc")

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        result = handler._get_prescriber_key()

    assert result == "prescriber-abc"


def test_get_prescriber_key_handles_int() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(123)

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        result = handler._get_prescriber_key()

    assert result == "123"


def test_get_prescriber_key_handles_dict_with_key() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber({"key": "prescriber-xyz"})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        result = handler._get_prescriber_key()

    assert result == "prescriber-xyz"


def test_get_prescriber_key_returns_none_when_missing() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(None)

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_validation_event()

        result = handler._get_prescriber_key()

    assert result is None
