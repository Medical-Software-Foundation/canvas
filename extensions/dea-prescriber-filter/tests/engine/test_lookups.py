"""Tests for engine/lookups.py — Staff lookup helpers for admin UI."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch


def _make_staff(id: str, first_name: str, last_name: str, npi_number: str = "") -> SimpleNamespace:
    """Build a lightweight staff stub with the attributes lookups.py reads."""
    return SimpleNamespace(id=id, first_name=first_name, last_name=last_name, npi_number=npi_number)


def test_get_active_providers_returns_all_with_unique_npi() -> None:
    """Returns one dict per provider when every NPI is unique."""
    staff_a = _make_staff("id-a", "Alice", "Anderson", "1111111111")
    staff_b = _make_staff("id-b", "Bob", "Brown", "2222222222")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [staff_a, staff_b]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        tested = get_active_providers
        result = tested()

    expected = [
        {"id": "id-a", "name": "Alice Anderson", "npi_number": "1111111111"},
        {"id": "id-b", "name": "Bob Brown", "npi_number": "2222222222"},
    ]
    exp_qs_calls = [
        call.filter(active=True, roles__role_type="PROVIDER"),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]
    exp_staff_calls = [
        call.objects.filter(active=True, roles__role_type="PROVIDER"),
        call.objects.filter().distinct(),
        call.objects.filter().distinct().order_by("last_name", "first_name"),
    ]
    assert result == expected
    assert mock_qs.mock_calls == exp_qs_calls
    assert mock_staff.mock_calls == exp_staff_calls


def test_get_active_providers_deduplicates_shared_npi() -> None:
    """Skips duplicate providers that share the same non-default NPI."""
    staff_a = _make_staff("id-a", "Alice", "Anderson", "1111111111")
    staff_a_dup = _make_staff("id-a2", "Alice", "Anderson", "1111111111")
    staff_b = _make_staff("id-b", "Bob", "Brown", "2222222222")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [
        staff_a,
        staff_a_dup,
        staff_b,
    ]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        tested = get_active_providers
        result = tested()

    exp_len = 2
    exp_first_id = "id-a"
    exp_second_id = "id-b"
    exp_qs_calls = [
        call.filter(active=True, roles__role_type="PROVIDER"),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]
    exp_staff_calls = [
        call.objects.filter(active=True, roles__role_type="PROVIDER"),
        call.objects.filter().distinct(),
        call.objects.filter().distinct().order_by("last_name", "first_name"),
    ]
    assert len(result) == exp_len
    assert result[0]["id"] == exp_first_id
    assert result[1]["id"] == exp_second_id
    assert mock_qs.mock_calls == exp_qs_calls
    assert mock_staff.mock_calls == exp_staff_calls


def test_get_active_providers_does_not_dedup_default_npi() -> None:
    """Keeps multiple providers sharing the placeholder DEFAULT_NPI value."""
    staff_a = _make_staff("id-a", "Alice", "Anderson", "1111155556")
    staff_b = _make_staff("id-b", "Bob", "Brown", "1111155556")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [staff_a, staff_b]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        tested = get_active_providers
        result = tested()

    expected = 2
    exp_qs_calls = [
        call.filter(active=True, roles__role_type="PROVIDER"),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]
    exp_staff_calls = [
        call.objects.filter(active=True, roles__role_type="PROVIDER"),
        call.objects.filter().distinct(),
        call.objects.filter().distinct().order_by("last_name", "first_name"),
    ]
    assert len(result) == expected
    assert mock_qs.mock_calls == exp_qs_calls
    assert mock_staff.mock_calls == exp_staff_calls


def test_get_active_providers_handles_empty_npi() -> None:
    """Includes a provider whose NPI is the empty string."""
    staff_a = _make_staff("id-a", "Alice", "Anderson", "")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [staff_a]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        tested = get_active_providers
        result = tested()

    expected = [{"id": "id-a", "name": "Alice Anderson", "npi_number": ""}]
    exp_qs_calls = [
        call.filter(active=True, roles__role_type="PROVIDER"),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]
    exp_staff_calls = [
        call.objects.filter(active=True, roles__role_type="PROVIDER"),
        call.objects.filter().distinct(),
        call.objects.filter().distinct().order_by("last_name", "first_name"),
    ]
    assert result == expected
    assert mock_qs.mock_calls == exp_qs_calls
    assert mock_staff.mock_calls == exp_staff_calls


def test_get_active_staff_returns_deduped_by_npi() -> None:
    """Returns active staff deduped by non-default NPI, preserving empty-NPI rows."""
    staff_a = _make_staff("id-a", "Alice", "Anderson", "1111111111")
    staff_a_dup = _make_staff("id-a2", "Alice", "Anderson", "1111111111")
    staff_b = _make_staff("id-b", "Bob", "Brown", "")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [
        staff_a,
        staff_a_dup,
        staff_b,
    ]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_staff

        tested = get_active_staff
        result = tested()

    expected = [
        {"id": "id-a", "name": "Alice Anderson"},
        {"id": "id-b", "name": "Bob Brown"},
    ]
    exp_qs_calls = [
        call.filter(active=True),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]
    exp_staff_calls = [
        call.objects.filter(active=True),
        call.objects.filter().distinct(),
        call.objects.filter().distinct().order_by("last_name", "first_name"),
    ]
    assert result == expected
    assert mock_qs.mock_calls == exp_qs_calls
    assert mock_staff.mock_calls == exp_staff_calls


def test_get_staff_name_returns_full_name_when_found() -> None:
    """Returns 'first last' for a staff UUID that exists."""
    staff_obj = _make_staff("id-a", "Alice", "Anderson")
    mock_qs = MagicMock()
    mock_qs.get.return_value = staff_obj

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_staff_name

        tested = get_staff_name
        result = tested("id-a")

    expected = "Alice Anderson"
    exp_qs_calls = [call.get(id="id-a")]
    exp_staff_calls = [call.objects.get(id="id-a")]
    assert result == expected
    assert mock_qs.mock_calls == exp_qs_calls
    assert mock_staff.mock_calls == exp_staff_calls


def test_get_staff_name_returns_id_when_not_found() -> None:
    """Falls back to the raw id when Staff.DoesNotExist is raised."""

    class _DoesNotExist(Exception):
        pass

    mock_qs = MagicMock()
    mock_qs.get.side_effect = _DoesNotExist()

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        mock_staff.DoesNotExist = _DoesNotExist
        from dea_prescriber_filter.engine.lookups import get_staff_name

        tested = get_staff_name
        result = tested("missing-id")

    expected = "missing-id"
    exp_qs_calls = [call.get(id="missing-id")]
    assert result == expected
    assert mock_qs.mock_calls == exp_qs_calls
