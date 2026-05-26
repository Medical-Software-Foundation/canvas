"""Tests for the CDM validation predicate and helpers.

The predicate _is_currently_active is the core decision: when is a CDM row
considered usable today? We test boundary cases directly with simple objects
(no DB needed) and integration through validate_cpt_code/filter_valid_cpt_codes
using real ChargeDescriptionMaster rows.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from canvas_sdk.v1.data import ChargeDescriptionMaster

from curated_cpt_picker.lib.cdm_validation import (
    _is_currently_active,
    filter_valid_cpt_codes,
    validate_cpt_code,
)


TODAY = date(2026, 5, 22)


@pytest.mark.parametrize(
    "effective_date,end_date,expected_active",
    [
        # Happy path: today inside the window
        (date(2020, 1, 1), date(2030, 1, 1), True),
        # Both bounds inclusive: today == effective_date
        (TODAY, date(2030, 1, 1), True),
        # Both bounds inclusive: today == end_date
        (date(2020, 1, 1), TODAY, True),
        # effective_date in the future
        (TODAY + timedelta(days=1), None, False),
        # end_date in the past
        (date(2020, 1, 1), TODAY - timedelta(days=1), False),
        # NULL effective_date — required, so always invalid
        (None, None, False),
        (None, date(2030, 1, 1), False),
        # NULL end_date — open-ended, OK if effective_date is past
        (date(2020, 1, 1), None, True),
    ],
)
def test_is_currently_active_boundary_cases(
    effective_date: date | None, end_date: date | None, expected_active: bool
) -> None:
    row = SimpleNamespace(effective_date=effective_date, end_date=end_date)
    assert _is_currently_active(row, TODAY) is expected_active


def test_validate_cpt_code_returns_invalid_when_not_in_cdm() -> None:
    result = validate_cpt_code("NONEXISTENT", today=TODAY)
    assert result.is_valid is False
    assert result.reason is not None
    assert "not in the ChargeDescriptionMaster" in result.reason


def test_validate_cpt_code_returns_valid_when_active_row_exists() -> None:
    ChargeDescriptionMaster.objects.create(
        cpt_code="99213",
        name="Office visit",
        short_name="Office visit", charge_amount=0,
        effective_date=TODAY - timedelta(days=365),
        end_date=None,
    )
    result = validate_cpt_code("99213", today=TODAY)
    assert result.is_valid is True
    assert result.reason is None


def test_validate_cpt_code_returns_invalid_when_only_expired_row_exists() -> None:
    ChargeDescriptionMaster.objects.create(
        cpt_code="99214",
        name="Old visit",
        short_name="Old visit", charge_amount=0,
        effective_date=TODAY - timedelta(days=400),
        end_date=TODAY - timedelta(days=30),
    )
    result = validate_cpt_code("99214", today=TODAY)
    assert result.is_valid is False
    assert result.reason is not None
    assert "not currently active" in result.reason


def test_validate_cpt_code_picks_active_row_when_multiple_exist() -> None:
    """If at least one CDM row is currently active, the code is valid even if
    another row for the same CPT is expired."""
    ChargeDescriptionMaster.objects.create(
        cpt_code="99215",
        name="Old version",
        short_name="Old version", charge_amount=0,
        effective_date=TODAY - timedelta(days=400),
        end_date=TODAY - timedelta(days=200),
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="99215",
        name="Current version",
        short_name="Current version", charge_amount=0,
        effective_date=TODAY - timedelta(days=100),
        end_date=None,
    )
    result = validate_cpt_code("99215", today=TODAY)
    assert result.is_valid is True


def test_filter_valid_cpt_codes_returns_only_active() -> None:
    ChargeDescriptionMaster.objects.create(
        cpt_code="A001", name="Active", short_name="A", charge_amount=0,
        effective_date=TODAY - timedelta(days=1), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="A002", name="Expired", short_name="X", charge_amount=0,
        effective_date=TODAY - timedelta(days=100), end_date=TODAY - timedelta(days=1),
    )
    # A003 is not in CDM at all

    result = filter_valid_cpt_codes(["A001", "A002", "A003"], today=TODAY)
    assert result == {"A001"}


def test_filter_valid_cpt_codes_handles_empty_input() -> None:
    assert filter_valid_cpt_codes([], today=TODAY) == set()


# --- Description-length guard (Canvas BillingLineItem.description is varchar(255)) ---

LONG_TEXT = "x" * 300  # exceeds the 255-char BillingLineItem.description limit


def test_validate_rejects_cpt_with_too_long_cdm_name() -> None:
    """Canvas's effect interpreter copies CDM name into a 255-char column
    without truncating. We must reject these at admin save so providers
    don't hit a silent AddBillingLineItem failure later."""
    ChargeDescriptionMaster.objects.create(
        cpt_code="99349",
        name=LONG_TEXT,
        short_name="Home visit short",
        charge_amount=0,
        effective_date=TODAY - timedelta(days=30),
        end_date=None,
    )
    result = validate_cpt_code("99349", today=TODAY)
    assert result.is_valid is False
    assert result.reason is not None
    assert "too long" in result.reason
    assert "Settings" in result.reason  # actionable guidance for the admin


def test_validate_rejects_cpt_with_too_long_short_name() -> None:
    ChargeDescriptionMaster.objects.create(
        cpt_code="99349",
        name="OK name",
        short_name=LONG_TEXT,
        charge_amount=0,
        effective_date=TODAY - timedelta(days=30),
        end_date=None,
    )
    result = validate_cpt_code("99349", today=TODAY)
    assert result.is_valid is False
    assert "too long" in result.reason  # type: ignore[operator]


def test_validate_accepts_when_at_least_one_active_row_fits() -> None:
    """If a CPT has two active CDM rows and only one has a short-enough
    description, that's still usable — validation passes."""
    ChargeDescriptionMaster.objects.create(
        cpt_code="99349", name=LONG_TEXT, short_name=LONG_TEXT, charge_amount=0,
        effective_date=TODAY - timedelta(days=100), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="99349", name="Short", short_name="Short", charge_amount=0,
        effective_date=TODAY - timedelta(days=10), end_date=None,
    )
    assert validate_cpt_code("99349", today=TODAY).is_valid is True


def test_filter_silently_skips_codes_with_too_long_description() -> None:
    """Picker should not raise on long-description curated entries — it
    silently drops them so the modal opens normally with the safe codes."""
    ChargeDescriptionMaster.objects.create(
        cpt_code="LONG", name=LONG_TEXT, short_name=LONG_TEXT, charge_amount=0,
        effective_date=TODAY - timedelta(days=10), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="OK", name="Fits", short_name="Fits", charge_amount=0,
        effective_date=TODAY - timedelta(days=10), end_date=None,
    )
    result = filter_valid_cpt_codes(["LONG", "OK"], today=TODAY)
    assert result == {"OK"}
