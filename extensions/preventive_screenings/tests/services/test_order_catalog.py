"""Tests for checking an order code against the practice's own catalogs.

Database-backed rather than mocked, because this is query code and a mocked
queryset never resolves a field name - the rule this repo learned the hard way
when an `Interview` lookup shipped matching nothing.

The behaviour worth pinning is mostly about *not* warning: an empty catalog and
a failed read both have to stay silent, because a warning that fires on
everything is one a practice learns to ignore.
"""

from datetime import date
from typing import Any
from uuid import uuid4
from unittest.mock import patch

import pytest
from canvas_sdk.v1.data import ChargeDescriptionMaster, LabPartner, LabPartnerTest
from pytest_django import DjangoAssertNumQueries

from preventive_screenings.services.catalog import ORDER_COMMANDS
from preventive_screenings.services.order_catalog import (
    _CATALOG_FOR_COMMAND,
    order_code_warnings,
    unresolvable_order_codes,
)

MODULE = "preventive_screenings.services.order_catalog"


def screening(**over: Any) -> dict:
    out: dict[str, Any] = {
        "id": "s1",
        "order_command": "imaging_order",
        "order_code": "77067",
    }
    out.update(over)
    return out


def charge(cpt_code: str, name: str = "A billable thing") -> ChargeDescriptionMaster:
    """A row in the practice's charge master, which backs imaging and Perform.

    `charge_amount` and `effective_date` are NOT NULL in the test database and
    have no factory, so they are supplied by hand.
    """
    return ChargeDescriptionMaster.objects.create(
        cpt_code=cpt_code, name=name, charge_amount=0, effective_date=date(2020, 1, 1)
    )


def lab_test(order_code: str, cpt_code: str = "", name: str = "A test") -> LabPartnerTest:
    """A row in the practice's lab compendium.

    `lab_partner` is NOT NULL and there is no factory for either model, so the
    partner is built by hand too.
    """
    partner = LabPartner.objects.create(
        id=uuid4(), name="A lab", active=True, electronic_ordering_enabled=True,
        keywords="", default_lab_account_number="",
    )
    return LabPartnerTest.objects.create(
        lab_partner=partner, order_code=order_code, order_name=name, cpt_code=cpt_code
    )


@pytest.mark.django_db
def test_a_code_the_catalog_carries_raises_nothing() -> None:
    charge("77067", "Screening mammogram")

    assert unresolvable_order_codes([screening()]) == []


@pytest.mark.django_db
def test_a_code_the_catalog_does_not_carry_is_reported() -> None:
    """**The five-deploy bug, made visible at configuration time.** A LOINC code
    against the imaging catalog resolves to nothing and stages an empty order."""
    charge("77067", "Screening mammogram")

    assert unresolvable_order_codes([screening(order_code="24606-6")]) == ["24606-6"]


@pytest.mark.django_db
def test_an_empty_catalog_means_cannot_tell_and_says_nothing() -> None:
    """**The load-bearing one.** With no rows at all - not loaded on this
    instance, or not readable from here - every code would look unresolvable and
    the editor would warn about all of them. A warning that fires on everything
    costs us the warnings that are real."""
    assert unresolvable_order_codes([screening(order_code="24606-6")]) == []


@pytest.mark.django_db
def test_an_empty_lab_compendium_is_also_cannot_tell() -> None:
    """The same rule as the charge master, and it needs its own test: an
    instance with no lab partner configured must not have every lab order in
    the practice flagged as broken."""
    charge("77067", "Screening mammogram")  # the other catalog is populated

    assert unresolvable_order_codes(
        [screening(order_command="lab_order", order_code="10524-7")]
    ) == []


@pytest.mark.django_db
def test_a_lab_order_is_checked_against_the_lab_compendium_not_the_charge_master() -> None:
    """They are different catalogs, and a code in one says nothing about the
    other."""
    charge("10524-7", "Cervical cytology")  # present here, absent from the compendium
    lab_test("SOMETHING-ELSE", "99999")  # so the compendium is not merely empty

    assert unresolvable_order_codes(
        [screening(order_command="lab_order", order_code="10524-7")]
    ) == ["10524-7"]


@pytest.mark.django_db
def test_a_lab_test_is_orderable_by_its_partner_code_or_its_cpt_code() -> None:
    """The picker finds it either way, so either match has to count."""
    lab_test("PARTNER-1", "88175", "Pap")

    for code in ("PARTNER-1", "88175"):
        assert unresolvable_order_codes(
            [screening(order_command="lab_order", order_code=code)]
        ) == [], code


@pytest.mark.django_db
def test_a_command_with_no_code_field_is_never_warned_about() -> None:
    """`refer` has nothing to pre-fill, so there is nothing to resolve. Warning
    about it would be noise about a thing that cannot be fixed."""
    assert unresolvable_order_codes(
        [screening(order_command="refer", order_code="anything")]
    ) == []


@pytest.mark.django_db
def test_a_screening_with_no_order_code_is_never_warned_about() -> None:
    assert unresolvable_order_codes([screening(order_code="")]) == []
    assert unresolvable_order_codes([screening(order_code="   ")]) == []


@pytest.mark.django_db
def test_an_unreadable_catalog_is_silent_rather_than_wrong() -> None:
    """This runs on the page that edits the rules. It must never be the reason
    that page cannot load."""
    with patch(f"{MODULE}.ChargeDescriptionMaster") as model:
        model.objects.filter.side_effect = RuntimeError("no such table")
        assert unresolvable_order_codes([screening()]) == []


@pytest.mark.django_db
def test_the_check_costs_one_query_per_catalog_not_one_per_screening(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Twenty screenings sharing a catalog cost one query, not twenty. The same
    guarantee the completion reads carry, on the admin path."""
    charge("77067", "Screening mammogram")
    screenings = [screening(id=f"s{index}") for index in range(20)]

    with django_assert_num_queries(1):
        assert unresolvable_order_codes(screenings) == []


@pytest.mark.django_db
def test_ruling_out_an_empty_catalog_costs_a_query_only_when_something_is_missing(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """The emptiness question is only worth asking when we are about to warn."""
    charge("77067", "Screening mammogram")

    with django_assert_num_queries(2):  # the lookup, then the emptiness check
        assert unresolvable_order_codes([screening(order_code="24606-6")]) == ["24606-6"]


@pytest.mark.django_db
def test_two_screenings_on_different_catalogs_are_each_checked_in_their_own() -> None:
    charge("77067", "Screening mammogram")
    lab_test("PARTNER-1", "88175", "Pap")

    assert unresolvable_order_codes(
        [
            screening(id="a", order_code="77067"),
            screening(id="b", order_command="lab_order", order_code="88175"),
            screening(id="c", order_code="24606-6"),
        ]
    ) == ["24606-6"]


@pytest.mark.django_db
def test_the_document_level_helper_tolerates_a_malformed_config() -> None:
    """`load_config` degrades to defaults rather than raising, so this must
    survive whatever it hands over."""
    assert order_code_warnings({}) == []
    assert order_code_warnings({"screenings": None}) == []
    assert order_code_warnings({"screenings": []}) == []


def test_every_command_that_takes_a_code_knows_which_catalog_resolves_it() -> None:
    """The mapping is what decides whether a code is checked at all, so a new
    order command that takes a code would otherwise be silently unchecked -
    which is the failure this whole module exists to surface.

    Held here rather than by a run-time branch: the two are a pair, and a pair
    that must agree is a test, not a fallback.
    """
    for key, entry in ORDER_COMMANDS.items():
        takes_code = entry.code_field is not None
        mapped = key in _CATALOG_FOR_COMMAND
        assert takes_code == mapped, (
            f"{key} takes_code={takes_code} but mapped={mapped}; a command that "
            "stages a code needs a catalog to resolve it against"
        )
