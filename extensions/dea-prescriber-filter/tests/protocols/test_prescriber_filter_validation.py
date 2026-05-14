"""Tests for PrescribeValidation state check methods."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch


def _make_event(command_id: str = "cmd-1") -> MagicMock:
    event = MagicMock()
    event.target.id = command_id
    event.context = {}
    return event


def _make_command(data: dict | None) -> MagicMock:
    cmd = MagicMock()
    cmd.data = data
    return cmd


# ─────────────────────────────────────────────────────────────
# _check_pharmacy_state
# ─────────────────────────────────────────────────────────────

def test_check_pharmacy_state_returns_none_when_no_pharmacy() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    handler = PrescribeValidation.__new__(PrescribeValidation)
    handler.event = _make_event()
    handler._get_pharmacy_state = MagicMock(return_value=None)
    handler._get_prescriber_license_states = MagicMock()

    assert handler._check_pharmacy_state("prescriber") is None
    assert handler._get_prescriber_license_states.mock_calls == []


def test_check_pharmacy_state_returns_no_license_error() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    handler = PrescribeValidation.__new__(PrescribeValidation)
    handler.event = _make_event()
    handler._get_pharmacy_state = MagicMock(return_value="NY")
    handler._get_prescriber_license_states = MagicMock(return_value=[])

    result = handler._check_pharmacy_state("prescriber")

    assert "no licenses" in result.lower()
    assert "NY" in result


def test_check_pharmacy_state_returns_mismatch_error() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    handler = PrescribeValidation.__new__(PrescribeValidation)
    handler.event = _make_event()
    handler._get_pharmacy_state = MagicMock(return_value="NY")
    handler._get_prescriber_license_states = MagicMock(return_value=["AK", "CA"])

    result = handler._check_pharmacy_state("prescriber")

    assert "AK" in result and "CA" in result
    assert "NY" in result


def test_check_pharmacy_state_returns_none_when_match() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    handler = PrescribeValidation.__new__(PrescribeValidation)
    handler.event = _make_event()
    handler._get_pharmacy_state = MagicMock(return_value="NY")
    handler._get_prescriber_license_states = MagicMock(return_value=["NY"])

    assert handler._check_pharmacy_state("prescriber") is None


def test_check_pharmacy_state_case_insensitive_match() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    handler = PrescribeValidation.__new__(PrescribeValidation)
    handler.event = _make_event()
    handler._get_pharmacy_state = MagicMock(return_value="ny")
    handler._get_prescriber_license_states = MagicMock(return_value=["NY"])

    assert handler._check_pharmacy_state("prescriber") is None


def test_check_pharmacy_state_handles_exception() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    handler = PrescribeValidation.__new__(PrescribeValidation)
    handler.event = _make_event()
    handler._get_pharmacy_state = MagicMock(side_effect=RuntimeError("boom"))

    assert handler._check_pharmacy_state("prescriber") is None


# ─────────────────────────────────────────────────────────────
# _get_pharmacy_state
# ─────────────────────────────────────────────────────────────

def test_get_pharmacy_state_returns_none_when_no_pharmacy() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_event()

        assert handler._get_pharmacy_state() is None


def test_get_pharmacy_state_handles_string_ncpdp() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({"pharmacy": "1234567"})

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("canvas_sdk.utils.http.pharmacy_http") as mock_ph,
    ):
        mock_command.objects = mock_command_qs
        mock_ph.get_pharmacy_by_ncpdp_id.return_value = {"state": "NY"}

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_event()

        result = handler._get_pharmacy_state()

    assert result == "NY"


def test_get_pharmacy_state_handles_dict_ncpdp_id() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({"pharmacy": {"ncpdp_id": "1234567"}})

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("canvas_sdk.utils.http.pharmacy_http") as mock_ph,
    ):
        mock_command.objects = mock_command_qs
        mock_ph.get_pharmacy_by_ncpdp_id.return_value = {"state": "CA"}

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_event()

        assert handler._get_pharmacy_state() == "CA"


def test_get_pharmacy_state_returns_none_when_lookup_fails() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({"pharmacy": "1234567"})

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("canvas_sdk.utils.http.pharmacy_http") as mock_ph,
    ):
        mock_command.objects = mock_command_qs
        mock_ph.get_pharmacy_by_ncpdp_id.return_value = None

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_event()

        assert handler._get_pharmacy_state() is None


def test_get_pharmacy_state_handles_exception() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects.get.side_effect = RuntimeError("db down")

        handler = PrescribeValidation.__new__(PrescribeValidation)
        handler.event = _make_event()

        assert handler._get_pharmacy_state() is None


# ─────────────────────────────────────────────────────────────
# _get_prescriber_license_states
# ─────────────────────────────────────────────────────────────

class _StaffDoesNotExist(Exception):
    pass


def test_get_prescriber_license_states_returns_all_states() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    lic1 = MagicMock(state="NY")
    lic2 = MagicMock(state="CA")
    staff_obj = MagicMock()
    staff_obj.npi_number = ""
    staff_obj.licenses.exclude.return_value.exclude.return_value = [lic1, lic2]

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        handler = PrescribeValidation.__new__(PrescribeValidation)
        result = handler._get_prescriber_license_states("uuid-a")

    assert set(result) == {"NY", "CA"}


def test_get_prescriber_license_states_returns_empty_when_not_found() -> None:
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        handler = PrescribeValidation.__new__(PrescribeValidation)
        assert handler._get_prescriber_license_states("missing") == []


# ─────────────────────────────────────────────────────────────
# _get_staff_license_state (module-level helper)
# ─────────────────────────────────────────────────────────────

def test_get_staff_license_state_prefers_dea() -> None:
    dea_lic = MagicMock(state="CA")
    staff_obj = MagicMock()
    staff_obj.licenses.filter.return_value.first.return_value = dea_lic

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("uuid-a")

    assert result == "CA"


def test_get_staff_license_state_falls_back_to_any_license() -> None:
    staff_obj = MagicMock()
    staff_obj.licenses.filter.return_value.first.return_value = None  # no DEA
    other_lic = MagicMock(state="NY")
    staff_obj.licenses.exclude.return_value.exclude.return_value.first.return_value = other_lic

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("uuid-a")

    assert result == "NY"


def test_get_staff_license_state_returns_none_when_no_licenses() -> None:
    staff_obj = MagicMock()
    staff_obj.licenses.filter.return_value.first.return_value = None
    staff_obj.licenses.exclude.return_value.exclude.return_value.first.return_value = None

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("uuid-a")

    assert result is None


def test_get_staff_license_state_returns_none_when_staff_not_found() -> None:
    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("missing")

    assert result is None


# ─────────────────────────────────────────────────────────────
# _get_all_uuids_for_npi
# ─────────────────────────────────────────────────────────────

def test_get_all_uuids_for_npi() -> None:
    s1 = MagicMock(id="uuid-a")
    s2 = MagicMock(id="uuid-b")

    mock_staff = MagicMock()
    mock_staff.objects.filter.return_value = [s1, s2]

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_all_uuids_for_npi

        result = _get_all_uuids_for_npi("1234567890")

    assert result == ["uuid-a", "uuid-b"]
