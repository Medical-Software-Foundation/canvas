"""Tests for PrescribeValidation state check methods."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch


def _make_event(command_id: str = "cmd-1") -> SimpleNamespace:
    """Build a minimal event stand-in with a target id and empty context."""
    return SimpleNamespace(target=SimpleNamespace(id=command_id), context={})


def _make_command(data: dict | None) -> SimpleNamespace:
    """Build a minimal Command stand-in carrying a ``data`` payload."""
    return SimpleNamespace(data=data)


# ─────────────────────────────────────────────────────────────
# _get_all_uuids_for_npi
# ─────────────────────────────────────────────────────────────

def test_get_all_uuids_for_npi() -> None:
    """Returns the stringified id for every Staff sharing the given NPI."""
    s1 = SimpleNamespace(id="uuid-a")
    s2 = SimpleNamespace(id="uuid-b")

    mock_staff = MagicMock()
    mock_staff.objects.filter.return_value = [s1, s2]

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_all_uuids_for_npi

        result = _get_all_uuids_for_npi("1234567890")

    exp_staff_calls = [call.objects.filter(npi_number="1234567890", active=True)]
    assert mock_staff.mock_calls == exp_staff_calls
    assert result == ["uuid-a", "uuid-b"]


# ─────────────────────────────────────────────────────────────
# _get_staff_license_state (module-level helper)
# ─────────────────────────────────────────────────────────────

class _StaffDoesNotExist(Exception):
    pass


def test_get_staff_license_state_prefers_dea() -> None:
    """Returns the DEA license state when a DEA license is present."""
    dea_lic = SimpleNamespace(state="CA")
    staff_obj = MagicMock()
    staff_obj.licenses.filter.return_value.first.return_value = dea_lic

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("uuid-a")

    exp_staff_calls = [
        call.objects.get(id="uuid-a"),
        call.objects.get().licenses.filter(license_type="DEA"),
        call.objects.get().licenses.filter().first(),
    ]
    assert mock_staff.mock_calls == exp_staff_calls
    assert result == "CA"


def test_get_staff_license_state_falls_back_to_any_license() -> None:
    """Falls back to any non-empty state license when no DEA license exists."""
    staff_obj = MagicMock()
    staff_obj.licenses.filter.return_value.first.return_value = None  # no DEA
    other_lic = SimpleNamespace(state="NY")
    staff_obj.licenses.exclude.return_value.exclude.return_value.first.return_value = other_lic

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("uuid-a")

    exp_get_calls = [
        call(id="uuid-a"),
        call().licenses.filter(license_type="DEA"),
        call().licenses.filter().first(),
        call().licenses.exclude(state__isnull=True),
        call().licenses.exclude().exclude(state=""),
        call().licenses.exclude().exclude().first(),
    ]
    assert mock_staff.objects.get.mock_calls == exp_get_calls
    assert result == "NY"


def test_get_staff_license_state_returns_none_when_no_licenses() -> None:
    """Returns None when neither a DEA nor any other state-bearing license exists."""
    staff_obj = MagicMock()
    staff_obj.licenses.filter.return_value.first.return_value = None
    staff_obj.licenses.exclude.return_value.exclude.return_value.first.return_value = None

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("uuid-a")

    exp_get_calls = [
        call(id="uuid-a"),
        call().licenses.filter(license_type="DEA"),
        call().licenses.filter().first(),
        call().licenses.exclude(state__isnull=True),
        call().licenses.exclude().exclude(state=""),
        call().licenses.exclude().exclude().first(),
    ]
    assert mock_staff.objects.get.mock_calls == exp_get_calls
    assert result is None


def test_get_staff_license_state_returns_none_when_staff_not_found() -> None:
    """Returns None when the Staff lookup raises DoesNotExist."""
    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        result = _get_staff_license_state("missing")

    assert mock_staff.objects.get.mock_calls == [call(id="missing")]
    assert result is None


# ─────────────────────────────────────────────────────────────
# PrescribeValidation._check_pharmacy_state
# ─────────────────────────────────────────────────────────────

def test_check_pharmacy_state_returns_none_when_no_pharmacy() -> None:
    """Returns None and skips the license lookup when no pharmacy is selected."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    tested = PrescribeValidation.__new__(PrescribeValidation)
    tested.event = _make_event()
    tested._get_pharmacy_state = MagicMock(return_value=None)
    tested._get_prescriber_license_states = MagicMock()

    result = tested._check_pharmacy_state("prescriber")

    assert tested._get_pharmacy_state.mock_calls == [call()]
    assert tested._get_prescriber_license_states.mock_calls == []
    assert result is None


def test_check_pharmacy_state_returns_no_license_error() -> None:
    """Returns a 'no licenses' error message naming the pharmacy state."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    tested = PrescribeValidation.__new__(PrescribeValidation)
    tested.event = _make_event()
    tested._get_pharmacy_state = MagicMock(return_value="NY")
    tested._get_prescriber_license_states = MagicMock(return_value=[])

    result = tested._check_pharmacy_state("prescriber")

    assert tested._get_pharmacy_state.mock_calls == [call()]
    assert tested._get_prescriber_license_states.mock_calls == [call("prescriber")]
    assert "no licenses" in result.lower()
    assert "NY" in result


def test_check_pharmacy_state_returns_mismatch_error() -> None:
    """Returns a mismatch error listing the prescriber and pharmacy states."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    tested = PrescribeValidation.__new__(PrescribeValidation)
    tested.event = _make_event()
    tested._get_pharmacy_state = MagicMock(return_value="NY")
    tested._get_prescriber_license_states = MagicMock(return_value=["AK", "CA"])

    result = tested._check_pharmacy_state("prescriber")

    assert tested._get_pharmacy_state.mock_calls == [call()]
    assert tested._get_prescriber_license_states.mock_calls == [call("prescriber")]
    assert "AK" in result and "CA" in result
    assert "NY" in result


def test_check_pharmacy_state_returns_none_when_match() -> None:
    """Returns None when the pharmacy state is in the prescriber's license list."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    tested = PrescribeValidation.__new__(PrescribeValidation)
    tested.event = _make_event()
    tested._get_pharmacy_state = MagicMock(return_value="NY")
    tested._get_prescriber_license_states = MagicMock(return_value=["NY"])

    result = tested._check_pharmacy_state("prescriber")

    assert tested._get_pharmacy_state.mock_calls == [call()]
    assert tested._get_prescriber_license_states.mock_calls == [call("prescriber")]
    assert result is None


def test_check_pharmacy_state_case_insensitive_match() -> None:
    """Matches the pharmacy state to the license states case-insensitively."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    tested = PrescribeValidation.__new__(PrescribeValidation)
    tested.event = _make_event()
    tested._get_pharmacy_state = MagicMock(return_value="ny")
    tested._get_prescriber_license_states = MagicMock(return_value=["NY"])

    result = tested._check_pharmacy_state("prescriber")

    assert tested._get_pharmacy_state.mock_calls == [call()]
    assert tested._get_prescriber_license_states.mock_calls == [call("prescriber")]
    assert result is None


# ─────────────────────────────────────────────────────────────
# PrescribeValidation._get_pharmacy_state
# ─────────────────────────────────────────────────────────────

def test_get_pharmacy_state_returns_none_when_no_pharmacy() -> None:
    """Returns None when the command has no pharmacy field at all."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_event()

        result = tested._get_pharmacy_state()

    assert mock_command_qs.mock_calls == [call.get(id="cmd-1")]
    assert result is None


def test_get_pharmacy_state_handles_string_ncpdp() -> None:
    """Looks up the pharmacy state when the pharmacy field is a bare NCPDP string."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({"pharmacy": "1234567"})

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("canvas_sdk.utils.http.pharmacy_http") as mock_ph,
    ):
        mock_command.objects = mock_command_qs
        mock_ph.get_pharmacy_by_ncpdp_id.return_value = {"state": "NY"}

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_event()

        result = tested._get_pharmacy_state()

    assert mock_command_qs.mock_calls == [call.get(id="cmd-1")]
    assert mock_ph.mock_calls == [call.get_pharmacy_by_ncpdp_id("1234567")]
    assert result == "NY"


def test_get_pharmacy_state_handles_dict_ncpdp_id() -> None:
    """Reads the NCPDP id from a dict-shaped pharmacy field."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({"pharmacy": {"ncpdp_id": "1234567"}})

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("canvas_sdk.utils.http.pharmacy_http") as mock_ph,
    ):
        mock_command.objects = mock_command_qs
        mock_ph.get_pharmacy_by_ncpdp_id.return_value = {"state": "CA"}

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_event()

        result = tested._get_pharmacy_state()

    assert mock_command_qs.mock_calls == [call.get(id="cmd-1")]
    assert mock_ph.mock_calls == [call.get_pharmacy_by_ncpdp_id("1234567")]
    assert result == "CA"


def test_get_pharmacy_state_returns_none_when_lookup_fails() -> None:
    """Returns None when the pharmacy HTTP lookup yields no record."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command({"pharmacy": "1234567"})

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("canvas_sdk.utils.http.pharmacy_http") as mock_ph,
    ):
        mock_command.objects = mock_command_qs
        mock_ph.get_pharmacy_by_ncpdp_id.return_value = None

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_event()

        result = tested._get_pharmacy_state()

    assert mock_command_qs.mock_calls == [call.get(id="cmd-1")]
    assert mock_ph.mock_calls == [call.get_pharmacy_by_ncpdp_id("1234567")]
    assert result is None


class _CommandDoesNotExist(Exception):
    pass


def test_get_pharmacy_state_returns_none_when_command_missing() -> None:
    """Returns None when the Command row cannot be found."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.DoesNotExist = _CommandDoesNotExist
        mock_command.objects.get.side_effect = _CommandDoesNotExist()

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_event()

        result = tested._get_pharmacy_state()

    assert mock_command.objects.get.mock_calls == [call(id="cmd-1")]
    assert result is None


# ─────────────────────────────────────────────────────────────
# PrescribeValidation._get_prescriber_license_states
# ─────────────────────────────────────────────────────────────

def test_get_prescriber_license_states_returns_all_states() -> None:
    """Returns the deduplicated set of license states for the staff member."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    lic1 = SimpleNamespace(state="NY")
    lic2 = SimpleNamespace(state="CA")
    staff_obj = MagicMock()
    staff_obj.npi_number = ""
    staff_obj.licenses.exclude.return_value.exclude.return_value = [lic1, lic2]

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        tested = PrescribeValidation.__new__(PrescribeValidation)
        result = tested._get_prescriber_license_states("uuid-a")

    exp_get_calls = [
        call(id="uuid-a"),
        call().licenses.exclude(state__isnull=True),
        call().licenses.exclude().exclude(state=""),
    ]
    assert mock_staff.objects.get.mock_calls == exp_get_calls
    assert set(result) == {"NY", "CA"}


def test_get_prescriber_license_states_returns_empty_when_not_found() -> None:
    """Returns an empty list when the staff member does not exist."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        tested = PrescribeValidation.__new__(PrescribeValidation)
        result = tested._get_prescriber_license_states("missing")

    assert mock_staff.objects.get.mock_calls == [call(id="missing")]
    assert result == []
