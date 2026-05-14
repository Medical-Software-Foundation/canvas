"""Tests for protocols/prescriber_filter.py — the core auth and validation logic."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest


class _StaffDoesNotExist(Exception):
    pass


class _CommandDoesNotExist(Exception):
    pass


def _make_staff_obj(uuid: str = "uuid-1", npi: str = "1234567890") -> SimpleNamespace:
    """Build a Staff-like SimpleNamespace with ``id`` and ``npi_number``."""
    return SimpleNamespace(id=uuid, npi_number=npi)


def _make_license(license_type: str = "DEA", state: str = "NY") -> SimpleNamespace:
    """Build a license-like SimpleNamespace for use with prefetched licenses."""
    return SimpleNamespace(license_type=license_type, state=state)


def _make_staff_with_licenses(
    uuid: str = "uuid-1", npi: str = "1234567890", licenses: list | None = None
) -> SimpleNamespace:
    """Staff-like SimpleNamespace whose ``.licenses.all()`` returns the given list."""
    licenses = licenses or []
    licenses_manager = SimpleNamespace(all=lambda: list(licenses))
    return SimpleNamespace(id=uuid, npi_number=npi, licenses=licenses_manager)


# ─────────────────────────────────────────────────────────────
# Helper function tests: _get_staff_uuid
# ─────────────────────────────────────────────────────────────

def test_get_staff_uuid_by_dbid() -> None:
    """Digit keys hit the ``pk=`` lookup branch and return the resolved UUID."""
    staff_obj = _make_staff_obj("uuid-1")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_uuid

        tested = _get_staff_uuid
        result = tested("123")

    expected = "uuid-1"
    exp_objects_calls = [call.get(pk=123)]
    assert result == expected
    assert mock_staff.objects.mock_calls == exp_objects_calls


def test_get_staff_uuid_by_uuid_string() -> None:
    """Non-digit keys hit the ``id=`` lookup branch."""
    staff_obj = _make_staff_obj("uuid-1")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_uuid

        tested = _get_staff_uuid
        result = tested("uuid-abc")

    expected = "uuid-1"
    exp_objects_calls = [call.get(id="uuid-abc")]
    assert result == expected
    assert mock_staff.objects.mock_calls == exp_objects_calls


def test_get_staff_uuid_returns_none_when_not_found() -> None:
    """Missing staff records resolve to ``None`` via the DoesNotExist branch."""
    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_uuid

        tested = _get_staff_uuid
        result = tested("missing")

    assert result is None
    assert mock_staff.objects.mock_calls == [call.get(id="missing")]


# ─────────────────────────────────────────────────────────────
# Helper function tests: _get_staff_npi
# ─────────────────────────────────────────────────────────────

def test_get_staff_npi_by_dbid() -> None:
    """Digit keys for _get_staff_npi route through the ``pk=`` branch (line 39)."""
    staff_obj = _make_staff_obj(npi="1234567890")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        tested = _get_staff_npi
        result = tested("42")

    expected = "1234567890"
    exp_objects_calls = [call.get(pk=42)]
    assert result == expected
    assert mock_staff.objects.mock_calls == exp_objects_calls


def test_get_staff_npi_returns_npi_string() -> None:
    """Non-digit keys resolve via UUID lookup and return the NPI string."""
    staff_obj = _make_staff_obj(npi="1234567890")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        tested = _get_staff_npi
        result = tested("uuid-a")

    expected = "1234567890"
    assert result == expected
    assert mock_staff.objects.mock_calls == [call.get(id="uuid-a")]


def test_get_staff_npi_returns_none_for_default_npi() -> None:
    """The DEFAULT_NPI placeholder is treated as no NPI."""
    staff_obj = _make_staff_obj(npi="1111155556")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        tested = _get_staff_npi
        result = tested("uuid-a")

    assert result is None
    assert mock_staff.objects.mock_calls == [call.get(id="uuid-a")]


def test_get_staff_npi_returns_none_when_no_npi() -> None:
    """Empty NPI on staff returns ``None``."""
    staff_obj = _make_staff_obj(npi="")
    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff_obj
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        tested = _get_staff_npi
        result = tested("uuid-a")

    assert result is None
    assert mock_staff.objects.mock_calls == [call.get(id="uuid-a")]


def test_get_staff_npi_returns_none_when_not_found() -> None:
    """Missing staff produces ``None`` via the DoesNotExist handler."""
    mock_staff = MagicMock()
    mock_staff.objects.get.side_effect = _StaffDoesNotExist()
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_npi

        tested = _get_staff_npi
        result = tested("missing")

    assert result is None
    assert mock_staff.objects.mock_calls == [call.get(id="missing")]


# ─────────────────────────────────────────────────────────────
# Helper function tests: _is_authorized
# ─────────────────────────────────────────────────────────────

def test_is_authorized_returns_false_when_user_uuid_missing() -> None:
    """Missing user UUID short-circuits to ``False``."""
    with patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid") as mock_uuid:
        mock_uuid.side_effect = [None, "prescriber-uuid"]
        from dea_prescriber_filter.protocols.prescriber_filter import _is_authorized

        tested = _is_authorized
        result = tested("user", "prescriber")

    exp_uuid_calls = [call("user"), call("prescriber")]
    assert result is False
    assert mock_uuid.mock_calls == exp_uuid_calls


def test_is_authorized_returns_true_when_delegation_matches() -> None:
    """A delegation entry mapping prescriber→user authorizes signing."""
    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid") as mock_uuid,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_all_uuids_for_npi"
        ) as mock_all_uuids,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations"
        ) as mock_delegations,
    ):
        mock_uuid.side_effect = ["user-uuid", "prescriber-uuid"]
        mock_npi.side_effect = ["prescriber-npi", "user-npi"]
        mock_all_uuids.side_effect = [["prescriber-uuid"], ["user-uuid"]]
        mock_delegations.return_value = {"prescriber-uuid": ["user-uuid"]}

        from dea_prescriber_filter.protocols.prescriber_filter import _is_authorized

        tested = _is_authorized
        result = tested("user", "prescriber")

    exp_uuid_calls = [call("user"), call("prescriber")]
    exp_npi_calls = [call("prescriber"), call("user")]
    exp_all_uuids_calls = [call("prescriber-npi"), call("user-npi")]
    exp_delegations_calls = [call()]
    assert result is True
    assert mock_uuid.mock_calls == exp_uuid_calls
    assert mock_npi.mock_calls == exp_npi_calls
    assert mock_all_uuids.mock_calls == exp_all_uuids_calls
    assert mock_delegations.mock_calls == exp_delegations_calls


def test_is_authorized_returns_false_when_no_delegation() -> None:
    """Without a delegation entry, even known users are denied."""
    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid") as mock_uuid,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_all_uuids_for_npi"
        ) as mock_all_uuids,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations"
        ) as mock_delegations,
    ):
        mock_uuid.side_effect = ["user-uuid", "prescriber-uuid"]
        mock_npi.side_effect = [None, None]
        mock_all_uuids.return_value = []
        mock_delegations.return_value = {}

        from dea_prescriber_filter.protocols.prescriber_filter import _is_authorized

        tested = _is_authorized
        result = tested("user", "prescriber")

    exp_uuid_calls = [call("user"), call("prescriber")]
    exp_npi_calls = [call("prescriber"), call("user")]
    exp_delegations_calls = [call()]
    assert result is False
    assert mock_uuid.mock_calls == exp_uuid_calls
    assert mock_npi.mock_calls == exp_npi_calls
    assert mock_all_uuids.mock_calls == []
    assert mock_delegations.mock_calls == exp_delegations_calls


# ─────────────────────────────────────────────────────────────
# Helper function tests: _get_staff_license_state
# ─────────────────────────────────────────────────────────────

def test_get_staff_license_state_by_dbid() -> None:
    """Digit keys hit the ``pk=`` branch (covers line 106)."""
    dea_lic = SimpleNamespace(state="NY")
    licenses_manager = MagicMock()
    licenses_manager.filter.return_value.first.return_value = dea_lic
    staff = SimpleNamespace(licenses=licenses_manager)

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _get_staff_license_state

        tested = _get_staff_license_state
        result = tested("42")

    expected = "NY"
    assert result == expected
    assert mock_staff.objects.mock_calls == [call.get(pk=42)]


# ─────────────────────────────────────────────────────────────
# Helper function tests: _bulk_fetch_staff (lines 132-154)
# ─────────────────────────────────────────────────────────────

def test_bulk_fetch_staff_returns_empty_for_empty_input() -> None:
    """Empty list short-circuits without any DB query (line 130-131)."""
    mock_staff = MagicMock()

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _bulk_fetch_staff

        tested = _bulk_fetch_staff
        result = tested([])

    expected: dict = {}
    assert result == expected
    assert mock_staff.objects.mock_calls == []


def test_bulk_fetch_staff_only_pk_keys() -> None:
    """All-digit keys route through a single ``pk__in=`` query."""
    staff1 = SimpleNamespace(pk=1, id="uuid-1")
    staff2 = SimpleNamespace(pk=2, id="uuid-2")

    mock_qs = MagicMock()
    mock_qs.prefetch_related.return_value = [staff1, staff2]
    mock_staff = MagicMock()
    mock_staff.objects.filter.return_value = mock_qs

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _bulk_fetch_staff

        tested = _bulk_fetch_staff
        result = tested(["1", "2"])

    expected = {"1": staff1, "2": staff2}
    exp_filter_calls = [call(pk__in=[1, 2]), call().prefetch_related("licenses")]
    assert result == expected
    assert mock_staff.objects.filter.mock_calls == exp_filter_calls


def test_bulk_fetch_staff_only_uuid_keys() -> None:
    """All non-digit keys route through a single ``id__in=`` query."""
    staff1 = SimpleNamespace(pk=1, id="uuid-a")
    staff2 = SimpleNamespace(pk=2, id="uuid-b")

    mock_qs = MagicMock()
    mock_qs.prefetch_related.return_value = [staff1, staff2]
    mock_staff = MagicMock()
    mock_staff.objects.filter.return_value = mock_qs

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _bulk_fetch_staff

        tested = _bulk_fetch_staff
        result = tested(["uuid-a", "uuid-b"])

    expected = {"uuid-a": staff1, "uuid-b": staff2}
    exp_filter_calls = [call(id__in=["uuid-a", "uuid-b"]), call().prefetch_related("licenses")]
    assert result == expected
    assert mock_staff.objects.filter.mock_calls == exp_filter_calls


def test_bulk_fetch_staff_mixed_keys() -> None:
    """Mixed digit/UUID keys issue two batched queries and merge results."""
    staff1 = SimpleNamespace(pk=1, id="uuid-1")
    staff_b = SimpleNamespace(pk=2, id="uuid-b")

    mock_staff = MagicMock()

    def filter_side_effect(**kwargs):
        qs = MagicMock()
        if "pk__in" in kwargs:
            qs.prefetch_related.return_value = [staff1]
        else:
            qs.prefetch_related.return_value = [staff_b]
        return qs

    mock_staff.objects.filter.side_effect = filter_side_effect

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _bulk_fetch_staff

        tested = _bulk_fetch_staff
        result = tested(["1", "uuid-b"])

    expected = {"1": staff1, "uuid-b": staff_b}
    assert result == expected


def test_bulk_fetch_staff_partial_match_omits_missing_keys() -> None:
    """Keys not present in the DB result are simply omitted from the dict."""
    staff1 = SimpleNamespace(pk=1, id="uuid-1")

    mock_qs = MagicMock()
    mock_qs.prefetch_related.return_value = [staff1]
    mock_staff = MagicMock()
    mock_staff.objects.filter.return_value = mock_qs

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        from dea_prescriber_filter.protocols.prescriber_filter import _bulk_fetch_staff

        tested = _bulk_fetch_staff
        result = tested(["1", "2"])

    expected = {"1": staff1}
    assert result == expected


# ─────────────────────────────────────────────────────────────
# Helper function tests: _npi_of_staff (lines 161-162)
# ─────────────────────────────────────────────────────────────

def test_npi_of_staff_returns_none_when_staff_is_none() -> None:
    """A None staff returns None without any attribute access."""
    from dea_prescriber_filter.protocols.prescriber_filter import _npi_of_staff

    tested = _npi_of_staff
    assert tested(None) is None


def test_npi_of_staff_returns_none_when_no_npi_attr() -> None:
    """Staff without an NPI returns None."""
    from dea_prescriber_filter.protocols.prescriber_filter import _npi_of_staff

    staff = SimpleNamespace(npi_number=None)
    tested = _npi_of_staff
    assert tested(staff) is None


def test_npi_of_staff_returns_npi_string() -> None:
    """Real NPI values are coerced to string."""
    from dea_prescriber_filter.protocols.prescriber_filter import _npi_of_staff

    staff = SimpleNamespace(npi_number="1234567890")
    tested = _npi_of_staff
    result = tested(staff)

    expected = "1234567890"
    assert result == expected


def test_npi_of_staff_returns_none_for_default_npi() -> None:
    """The DEFAULT_NPI placeholder is treated as no NPI."""
    from dea_prescriber_filter.protocols.prescriber_filter import _npi_of_staff

    staff = SimpleNamespace(npi_number="1111155556")
    tested = _npi_of_staff
    assert tested(staff) is None


# ─────────────────────────────────────────────────────────────
# Helper function tests: _license_state_of_staff (lines 167-174)
# ─────────────────────────────────────────────────────────────

def test_license_state_of_staff_returns_none_for_no_staff() -> None:
    """A falsy staff argument returns None."""
    from dea_prescriber_filter.protocols.prescriber_filter import _license_state_of_staff

    tested = _license_state_of_staff
    assert tested(None) is None


def test_license_state_of_staff_prefers_dea_license() -> None:
    """DEA license state wins when one is present."""
    from dea_prescriber_filter.protocols.prescriber_filter import _license_state_of_staff

    licenses = [
        _make_license(license_type="MD", state="CA"),
        _make_license(license_type="DEA", state="NY"),
    ]
    staff = _make_staff_with_licenses(licenses=licenses)

    tested = _license_state_of_staff
    result = tested(staff)

    expected = "NY"
    assert result == expected


def test_license_state_of_staff_falls_back_to_any_license() -> None:
    """Without a DEA license, the first license with a state is used."""
    from dea_prescriber_filter.protocols.prescriber_filter import _license_state_of_staff

    licenses = [
        _make_license(license_type="MD", state=""),
        _make_license(license_type="RN", state="TX"),
    ]
    staff = _make_staff_with_licenses(licenses=licenses)

    tested = _license_state_of_staff
    result = tested(staff)

    expected = "TX"
    assert result == expected


def test_license_state_of_staff_returns_none_when_no_licenses() -> None:
    """Staff with no licenses returns None."""
    from dea_prescriber_filter.protocols.prescriber_filter import _license_state_of_staff

    staff = _make_staff_with_licenses(licenses=[])

    tested = _license_state_of_staff
    result = tested(staff)

    assert result is None


# ─────────────────────────────────────────────────────────────
# PrescriberSearchPrioritization branch coverage (lines 221, 225-229)
# ─────────────────────────────────────────────────────────────

def test_search_prioritization_skips_npi_query_when_no_npis() -> None:
    """When no prescribers have NPIs, the NPI->uuids batch query is skipped."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    user_staff = SimpleNamespace(id="user-uuid", npi_number=None)
    prescriber_staff = _make_staff_with_licenses(
        uuid="prescriber-uuid", npi=None, licenses=[]
    )

    mock_staff = MagicMock()
    mock_delegations = {}

    event = SimpleNamespace(
        context={
            "results": [{"text": "Dr Smith", "value": "prescriber-uuid"}],
            "user": {"staff": "user-key"},
        }
    )

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-key": user_staff, "prescriber-uuid": prescriber_staff},
        ) as mock_bulk,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value=mock_delegations,
        ) as mock_get_dels,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff
        ),
    ):
        tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        tested.event = event

        result = tested.compute()

    # The Staff NPI->uuids query was NOT issued because npis_to_query was empty.
    assert mock_staff.objects.filter.mock_calls == []
    assert len(result) == 1
    assert mock_bulk.mock_calls == [call(["user-key", "prescriber-uuid"])]
    assert mock_get_dels.mock_calls == [call()]


def test_search_prioritization_adds_prescriber_npi_to_query_set() -> None:
    """When a prescriber has an NPI, it's added to ``prescriber_npis`` (line 221)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescriberSearchPrioritization

    user_staff = _make_staff_with_licenses(uuid="user-uuid", npi=None, licenses=[])
    prescriber_staff = _make_staff_with_licenses(
        uuid="prescriber-uuid", npi="9999999999", licenses=[]
    )
    extra_staff = SimpleNamespace(id="other-uuid", npi_number="9999999999")

    mock_staff_qs = MagicMock()
    mock_staff_qs.only.return_value = [extra_staff]
    mock_staff = MagicMock()
    mock_staff.objects.filter.return_value = mock_staff_qs

    event = SimpleNamespace(
        context={
            "results": [{"text": "Dr Smith", "value": "prescriber-uuid"}],
            "user": {"staff": "user-key"},
        }
    )

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._bulk_fetch_staff",
            return_value={"user-key": user_staff, "prescriber-uuid": prescriber_staff},
        ) as mock_bulk,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_all_delegations",
            return_value={},
        ) as mock_get_dels,
        patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff),
    ):
        tested = PrescriberSearchPrioritization.__new__(PrescriberSearchPrioritization)
        tested.event = event

        result = tested.compute()

    # NPI batch query was issued with the prescriber's NPI.
    assert mock_staff.objects.filter.mock_calls == [
        call(npi_number__in={"9999999999"}, active=True),
        call(npi_number__in={"9999999999"}, active=True).only("id", "npi_number"),
    ]
    assert len(result) == 1
    assert mock_bulk.mock_calls == [call(["user-key", "prescriber-uuid"])]
    assert mock_get_dels.mock_calls == [call()]


# ─────────────────────────────────────────────────────────────
# PrescribeActionFilter — the security gate
# ─────────────────────────────────────────────────────────────

def _make_action_filter_event(
    user_id: str | None = "user-1", command_id: str = "cmd-1"
) -> SimpleNamespace:
    """Build an ActionFilter event with user/actions context."""
    return SimpleNamespace(
        context={
            "actions": [{"name": "sign_action"}, {"name": "delete_action"}],
            "user": {"staff": user_id} if user_id is not None else {},
        },
        target=SimpleNamespace(id=command_id),
    )


def _make_command_with_prescriber(prescriber: object) -> SimpleNamespace:
    """Build a Command-like SimpleNamespace whose ``.data`` carries a prescriber field."""
    return SimpleNamespace(data={"prescriber": prescriber})


def test_action_filter_allows_when_user_npi_matches_prescriber() -> None:
    """Shared NPI between user and prescriber lets sign actions through."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized") as mock_auth,
    ):
        mock_command.objects = mock_command_qs
        mock_npi.side_effect = ["shared-npi", "shared-npi"]
        mock_auth.return_value = False

        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested.compute()

    payload = json.loads(result[0].payload)
    action_names = [a["name"] for a in payload]
    assert len(result) == 1
    assert "sign_action" in action_names
    # _is_authorized may or may not be called depending on _is_own_prescriber short-circuit;
    # what we assert is that auth was NOT used to restrict.
    assert mock_auth.mock_calls in ([call("user-1", "prescriber-uuid")], [])


def test_action_filter_restricts_when_unauthorized_and_different_npi() -> None:
    """Different NPIs + unauthorized → sign actions are stripped."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized") as mock_auth,
    ):
        mock_command.objects = mock_command_qs
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]
        mock_auth.return_value = False

        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested.compute()

    payload = json.loads(result[0].payload)
    action_names = [a["name"] for a in payload]
    exp_auth_calls = [call("user-1", "prescriber-uuid")]
    assert len(result) == 1
    assert "sign_action" not in action_names
    assert "delete_action" in action_names
    assert mock_auth.mock_calls == exp_auth_calls


def test_action_filter_allows_when_authorized_via_prescriber_assist() -> None:
    """An authorized user with a non-matching NPI gets the sign actions."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch("dea_prescriber_filter.protocols.prescriber_filter._is_authorized") as mock_auth,
    ):
        mock_command.objects = mock_command_qs
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]
        mock_auth.return_value = True

        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested.compute()

    payload = json.loads(result[0].payload)
    action_names = [a["name"] for a in payload]
    exp_auth_calls = [call("user-1", "prescriber-uuid")]
    assert "sign_action" in action_names
    assert mock_auth.mock_calls == exp_auth_calls


def test_action_filter_caches_user_staff_key() -> None:
    """The current user's staff key is cached for the validation handler to read."""
    from dea_prescriber_filter.protocols.prescriber_filter import (
        AUTH_USER_CACHE_PREFIX,
        AUTH_USER_CACHE_TTL,
        PrescribeActionFilter,
    )

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi",
            return_value=None,
        ),
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._is_authorized",
            return_value=True,
        ),
    ):
        mock_command.objects = mock_command_qs

        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event(user_id="user-xyz", command_id="cmd-abc")

        tested.compute()

    exp_cache_set_calls = [
        call(
            f"{AUTH_USER_CACHE_PREFIX}cmd-abc",
            "user-xyz",
            timeout_seconds=AUTH_USER_CACHE_TTL,
        )
    ]
    assert mock_cache.set.mock_calls == exp_cache_set_calls


def test_action_filter_restricts_when_no_user_staff_key() -> None:
    """Missing user context wipes the cache entry and restricts actions."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    with patch(
        "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
        return_value=mock_cache,
    ):
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = SimpleNamespace(
            context={"actions": [{"name": "sign_action"}, {"name": "review"}], "user": {}},
            target=SimpleNamespace(id="cmd-1"),
        )

        result = tested.compute()

    payload = json.loads(result[0].payload)
    action_names = [a["name"] for a in payload]
    exp_cache_delete_calls = [call("dea:user:cmd-1")]
    assert "sign_action" not in action_names
    assert "review" in action_names
    assert mock_cache.delete.mock_calls == exp_cache_delete_calls


def test_action_filter_passes_actions_when_no_prescriber_key() -> None:
    """If the command has no prescriber yet, all actions pass through (line 358)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_cache = MagicMock()
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(None)

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
    ):
        mock_command.objects = mock_command_qs

        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested.compute()

    payload = json.loads(result[0].payload)
    action_names = [a["name"] for a in payload]
    assert "sign_action" in action_names
    assert "delete_action" in action_names


# ─────────────────────────────────────────────────────────────
# PrescribeActionFilter._get_prescriber_key (lines 377-378, 382, 384, 387-390)
# ─────────────────────────────────────────────────────────────

def test_action_filter_get_prescriber_key_returns_none_when_command_missing() -> None:
    """Missing Command record (DoesNotExist) returns ``None`` (lines 377-378)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command = MagicMock()
    mock_command.objects.get.side_effect = _CommandDoesNotExist()
    mock_command.DoesNotExist = _CommandDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command", mock_command):
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    assert result is None


def test_action_filter_get_prescriber_key_returns_none_when_prescriber_missing() -> None:
    """No prescriber field on the command returns ``None`` (line 382)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(None)

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    assert result is None


def test_action_filter_get_prescriber_key_handles_int() -> None:
    """An int prescriber field is coerced to string (line 384)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(123)

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    expected = "123"
    assert result == expected


def test_action_filter_get_prescriber_key_handles_string() -> None:
    """A string prescriber field is passed through."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-abc")

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    expected = "prescriber-abc"
    assert result == expected


def test_action_filter_get_prescriber_key_handles_dict_with_key() -> None:
    """Dict prescriber uses the ``key`` field first (lines 387-389)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber({"key": "kkk"})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    expected = "kkk"
    assert result == expected


def test_action_filter_get_prescriber_key_handles_dict_with_id() -> None:
    """Dict prescriber falls back to ``id`` when ``key`` is missing."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber({"id": "id-x"})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    expected = "id-x"
    assert result == expected


def test_action_filter_get_prescriber_key_handles_dict_empty() -> None:
    """An empty dict prescriber returns None (line 389 falsy key branch)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber({})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    assert result is None


def test_action_filter_get_prescriber_key_returns_none_for_unsupported_type() -> None:
    """Unsupported prescriber type (e.g. list) falls through to the final ``None`` (line 390)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeActionFilter

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(["unexpected"])

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeActionFilter.__new__(PrescribeActionFilter)
        tested.event = _make_action_filter_event()

        result = tested._get_prescriber_key()

    assert result is None


# ─────────────────────────────────────────────────────────────
# PrescribeValidation — error message display
# ─────────────────────────────────────────────────────────────

def _make_validation_event(command_id: str = "cmd-1") -> SimpleNamespace:
    """Build a validation event with patient context and no user."""
    return SimpleNamespace(
        target=SimpleNamespace(id=command_id),
        context={"patient": {"id": "pt-1"}},
    )


def test_validation_passes_silently_when_no_prescriber() -> None:
    """With no prescriber selected, the validation effect carries no errors."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(None)
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "empty-effect"

    with (
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested.compute()

    expected = ["empty-effect"]
    assert result == expected
    assert mock_effect_inst.add_error.mock_calls == []


def test_validation_warns_when_user_staff_key_missing(caplog: pytest.LogCaptureFixture) -> None:
    """No user key in context/cache hits the log.warning branch (lines 454-455)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
        patch("dea_prescriber_filter.protocols.prescriber_filter.log") as mock_log,
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        tested.compute()

    # No auth error appended, but log.warning was emitted.
    assert mock_effect_inst.add_error.mock_calls == []
    assert len(mock_log.warning.mock_calls) == 1


def test_validation_adds_auth_error_when_user_cached_and_unauthorized() -> None:
    """When the cache supplies a user and auth fails, the auth error is added."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-abc"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "error-effect"

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._is_authorized",
            return_value=False,
        ) as mock_auth,
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        tested.compute()

    exp_add_error_calls = [call("Not authorized to prescribe for this provider.")]
    exp_auth_calls = [call("user-abc", "prescriber-uuid")]
    assert mock_effect_inst.add_error.mock_calls == exp_add_error_calls
    assert mock_auth.mock_calls == exp_auth_calls


def test_validation_skips_auth_error_when_user_is_prescriber_by_same_staff_uuid() -> None:
    """User and prescriber share a Staff UUID — no auth error (even with no NPI)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-key"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-key")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_uuid",
            return_value="same-staff-uuid",
        ) as mock_uuid,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi",
            return_value=None,
        ),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        tested.compute()

    assert mock_effect_inst.add_error.mock_calls == []
    # _get_staff_uuid was used to identify both parties.
    assert mock_uuid.mock_calls == [call("user-key"), call("prescriber-key")]


def test_validation_skips_auth_error_when_user_is_prescriber_by_npi() -> None:
    """Shared NPI between user and prescriber skips the auth error."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = "user-abc"
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi",
            return_value="shared-npi",
        ),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        tested.compute()

    assert mock_effect_inst.add_error.mock_calls == []


def test_validation_adds_state_error_when_mismatch() -> None:
    """A pharmacy-state mismatch is reported even with no user cached."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # No user cached
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch.object(
            PrescribeValidation, "_check_pharmacy_state", return_value="State mismatch error"
        ),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        tested.compute()

    exp_add_error_calls = [call("State mismatch error")]
    assert mock_effect_inst.add_error.mock_calls == exp_add_error_calls


def test_validation_reads_user_from_event_context_when_present() -> None:
    """Primary path: user.staff is in POST_VALIDATION event context — cache is not consulted."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # cache is empty — proves we read from context
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-uuid")
    mock_effect_inst = MagicMock()
    mock_effect_inst.apply.return_value = "effect"

    event = SimpleNamespace(
        target=SimpleNamespace(id="cmd-1"),
        context={"patient": {"id": "pt-1"}, "user": {"staff": "user-from-context"}},
    )

    with (
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._is_authorized",
            return_value=False,
        ),
        patch.object(PrescribeValidation, "_check_pharmacy_state", return_value=None),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = event

        tested.compute()

    exp_add_error_calls = [call("Not authorized to prescribe for this provider.")]
    assert mock_effect_inst.add_error.mock_calls == exp_add_error_calls
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
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.get_cache",
            return_value=mock_cache,
        ),
        patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter.CommandValidationErrorEffect"
        ) as mock_effect,
        patch("dea_prescriber_filter.protocols.prescriber_filter._get_staff_npi") as mock_npi,
        patch(
            "dea_prescriber_filter.protocols.prescriber_filter._is_authorized",
            return_value=False,
        ),
        patch.object(
            PrescribeValidation,
            "_check_pharmacy_state",
            return_value="Prescriber state (AR) does not match pharmacy state (NC).",
        ),
    ):
        mock_command.objects = mock_command_qs
        mock_effect.return_value = mock_effect_inst
        mock_npi.side_effect = ["user-npi", "prescriber-npi"]

        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        tested.compute()

    exp_add_error_calls = [
        call("Not authorized to prescribe for this provider."),
        call("Prescriber state (AR) does not match pharmacy state (NC)."),
    ]
    assert mock_effect_inst.add_error.mock_calls == exp_add_error_calls


# ─────────────────────────────────────────────────────────────
# PrescribeValidation._get_prescriber_key — handles various input formats
# ─────────────────────────────────────────────────────────────

def test_get_prescriber_key_handles_string() -> None:
    """A string prescriber is passed through unchanged."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber("prescriber-abc")

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_key()

    expected = "prescriber-abc"
    assert result == expected


def test_get_prescriber_key_handles_int() -> None:
    """An int prescriber is coerced to string."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(123)

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_key()

    expected = "123"
    assert result == expected


def test_get_prescriber_key_handles_dict_with_key() -> None:
    """Dict with ``key`` returns that value."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber({"key": "prescriber-xyz"})

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_key()

    expected = "prescriber-xyz"
    assert result == expected


def test_get_prescriber_key_returns_none_when_missing() -> None:
    """A None prescriber returns None."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(None)

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_key()

    assert result is None


def test_validation_get_prescriber_key_returns_none_when_command_missing() -> None:
    """Missing Command in PrescribeValidation._get_prescriber_key (lines 454-455)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command = MagicMock()
    mock_command.objects.get.side_effect = _CommandDoesNotExist()
    mock_command.DoesNotExist = _CommandDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command", mock_command):
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_key()

    assert result is None


def test_validation_get_prescriber_key_returns_none_for_unsupported_type() -> None:
    """Unsupported prescriber type falls through to None (line 467)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = _make_command_with_prescriber(["unexpected"])

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_key()

    assert result is None


# ─────────────────────────────────────────────────────────────
# PrescribeValidation._get_pharmacy_state edge cases (lines 503, 516)
# ─────────────────────────────────────────────────────────────

def test_get_pharmacy_state_returns_none_when_no_ncpdp_id() -> None:
    """Pharmacy dict with no usable id field yields None (line 503)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    cmd = SimpleNamespace(data={"pharmacy": {"name": "no-id-here"}})
    mock_command_qs = MagicMock()
    mock_command_qs.get.return_value = cmd

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Command") as mock_command:
        mock_command.objects = mock_command_qs
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_pharmacy_state()

    assert result is None


def test_get_prescriber_license_states_by_dbid() -> None:
    """Digit staff_key hits the pk-lookup branch in _get_prescriber_license_states (line 516)."""
    from dea_prescriber_filter.protocols.prescriber_filter import PrescribeValidation

    lic1 = SimpleNamespace(state="NY")
    lic2 = SimpleNamespace(state="CA")
    excluded = MagicMock()
    excluded.exclude.return_value = [lic1, lic2]
    licenses_manager = MagicMock()
    licenses_manager.exclude.return_value = excluded
    staff = SimpleNamespace(licenses=licenses_manager)

    mock_staff = MagicMock()
    mock_staff.objects.get.return_value = staff
    mock_staff.DoesNotExist = _StaffDoesNotExist

    with patch("dea_prescriber_filter.protocols.prescriber_filter.Staff", mock_staff):
        tested = PrescribeValidation.__new__(PrescribeValidation)
        tested.event = _make_validation_event()

        result = tested._get_prescriber_license_states("42")

    assert set(result) == {"NY", "CA"}
    assert mock_staff.objects.mock_calls == [call.get(pk=42)]
