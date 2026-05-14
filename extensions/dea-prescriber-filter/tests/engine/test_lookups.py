"""Tests for engine/lookups.py — Staff lookup helpers for admin UI."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


def _make_staff(id_val: str, first: str, last: str, npi: str = "") -> MagicMock:
    staff = MagicMock()
    staff.id = id_val
    staff.first_name = first
    staff.last_name = last
    staff.npi_number = npi
    return staff


def test_get_active_providers_returns_all_with_unique_npi() -> None:
    mock_staff_a = _make_staff("id-a", "Alice", "Anderson", "1111111111")
    mock_staff_b = _make_staff("id-b", "Bob", "Brown", "2222222222")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [mock_staff_a, mock_staff_b]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        result = get_active_providers()

    assert result == [
        {"id": "id-a", "name": "Alice Anderson", "npi_number": "1111111111"},
        {"id": "id-b", "name": "Bob Brown", "npi_number": "2222222222"},
    ]
    assert mock_qs.mock_calls == [
        call.filter(active=True, roles__role_type="PROVIDER"),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]


def test_get_active_providers_deduplicates_shared_npi() -> None:
    mock_staff_a = _make_staff("id-a", "Alice", "Anderson", "1111111111")
    mock_staff_a_dup = _make_staff("id-a2", "Alice", "Anderson", "1111111111")
    mock_staff_b = _make_staff("id-b", "Bob", "Brown", "2222222222")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [mock_staff_a, mock_staff_a_dup, mock_staff_b]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        result = get_active_providers()

    assert len(result) == 2
    assert result[0]["id"] == "id-a"
    assert result[1]["id"] == "id-b"


def test_get_active_providers_does_not_dedup_default_npi() -> None:
    mock_staff_a = _make_staff("id-a", "Alice", "Anderson", "1111155556")
    mock_staff_b = _make_staff("id-b", "Bob", "Brown", "1111155556")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [mock_staff_a, mock_staff_b]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        result = get_active_providers()

    assert len(result) == 2


def test_get_active_providers_handles_empty_npi() -> None:
    mock_staff_a = _make_staff("id-a", "Alice", "Anderson", "")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [mock_staff_a]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_providers

        result = get_active_providers()

    assert result == [{"id": "id-a", "name": "Alice Anderson", "npi_number": ""}]


def test_get_active_staff_returns_deduped_by_npi() -> None:
    mock_staff_a = _make_staff("id-a", "Alice", "Anderson", "1111111111")
    mock_staff_a_dup = _make_staff("id-a2", "Alice", "Anderson", "1111111111")
    mock_staff_b = _make_staff("id-b", "Bob", "Brown", "")

    mock_qs = MagicMock()
    mock_qs.filter.return_value.distinct.return_value.order_by.return_value = [mock_staff_a, mock_staff_a_dup, mock_staff_b]

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_active_staff

        result = get_active_staff()

    assert result == [
        {"id": "id-a", "name": "Alice Anderson"},
        {"id": "id-b", "name": "Bob Brown"},
    ]
    assert mock_qs.mock_calls == [
        call.filter(active=True),
        call.filter().distinct(),
        call.filter().distinct().order_by("last_name", "first_name"),
    ]


def test_get_staff_name_returns_full_name_when_found() -> None:
    mock_staff_obj = _make_staff("id-a", "Alice", "Anderson")
    mock_qs = MagicMock()
    mock_qs.get.return_value = mock_staff_obj

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        from dea_prescriber_filter.engine.lookups import get_staff_name

        result = get_staff_name("id-a")

    assert result == "Alice Anderson"
    assert mock_qs.mock_calls == [call.get(id="id-a")]


def test_get_staff_name_returns_id_when_not_found() -> None:
    class _DoesNotExist(Exception):
        pass

    mock_qs = MagicMock()
    mock_qs.get.side_effect = _DoesNotExist()

    with patch("dea_prescriber_filter.engine.lookups.Staff") as mock_staff:
        mock_staff.objects = mock_qs
        mock_staff.DoesNotExist = _DoesNotExist
        from dea_prescriber_filter.engine.lookups import get_staff_name

        result = get_staff_name("missing-id")

    assert result == "missing-id"
