"""Tests for what staff have said about a screening.

These are the plugin's only writes that originate with a person rather than
with the chart, and the whole case for storing them outside the chart rests on
two properties this file holds:

* **An attestation adds, it never replaces.** A real result that is more recent
  always wins - see ``tests/services/test_screenings.py`` for that half.
* **Every statement carries its author**, in the row rather than in a log, so
  the record app can show whose say-so a screening's status rests on.

The table does not exist in the pytest database by default, so everything here
runs against the real one via the ``attestation_table`` fixture. Mocking the
model is what let an N+1 hide in the sweep's write path, and these reads sit on
the same hot path.
"""

from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.test_utils.factories import StaffFactory
from django.test.utils import CaptureQueriesContext
from django.db import connection

from preventive_screenings.models import ScreeningAttestation
from preventive_screenings.services.attestations import (
    KIND_COMPLETED,
    KIND_NOT_APPLICABLE,
    MAX_BACKDATE_YEARS,
    clear_attestation,
    load_attestations,
    parse_effective_date,
    record_attestation,
    recording_date,
    staff_names,
)

MODULE = "preventive_screenings.services.attestations"
TODAY = date(2026, 10, 5)


def store(patient: str, screening: str, **over: Any) -> None:
    fields: dict[str, Any] = {
        "patient_key": patient,
        "screening_id": screening,
        "kind": KIND_COMPLETED,
        "effective_date": TODAY,
        "interval_quantity": 2,
        "interval_unit": "years",
        "label": "",
        "recorded_by": "staff-1",
        "recorded_at": TODAY,
    }
    fields.update(over)
    ScreeningAttestation.objects.create(**fields)


# --- reading -----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_stored_statement_comes_back(attestation_table: None) -> None:
    store("p1", "s1")

    found = load_attestations(["p1"], ["s1"])

    assert found["p1"]["s1"].completed is True
    assert found["p1"]["s1"].not_applicable is False
    assert found["p1"]["s1"].effective_date == TODAY


@pytest.mark.django_db(transaction=True)
def test_a_not_applicable_statement_reads_as_one(attestation_table: None) -> None:
    store("p1", "s1", kind=KIND_NOT_APPLICABLE)

    found = load_attestations(["p1"], ["s1"])

    assert found["p1"]["s1"].not_applicable is True
    assert found["p1"]["s1"].completed is False


@pytest.mark.django_db(transaction=True)
def test_one_patients_statement_does_not_reach_another(attestation_table: None) -> None:
    """The batched read is what makes this a risk worth a test: a shared query
    that attributed rows wrongly would mark the wrong patient's screening
    done."""
    store("p1", "s1")

    found = load_attestations(["p1", "p2"], ["s1"])

    assert "p2" not in found


@pytest.mark.django_db(transaction=True)
def test_a_screening_not_asked_about_is_not_returned(attestation_table: None) -> None:
    store("p1", "s1")

    assert load_attestations(["p1"], ["s2"]) == {}


@pytest.mark.django_db(transaction=True)
def test_a_whole_batch_costs_one_query(attestation_table: None) -> None:
    """The sweep reads a few hundred patients a run. One query per patient
    here would be the same N+1 `services.completion` exists to avoid, on one
    more axis - and this is the axis nothing could measure until the table
    could be created in tests."""
    for index in range(30):
        store(f"p{index}", "s1")

    with CaptureQueriesContext(connection) as captured:
        found = load_attestations([f"p{index}" for index in range(30)], ["s1"])

    assert len(found) == 30
    reads = [q for q in captured.captured_queries if "screeningattestation" in q["sql"].lower()]
    assert len(reads) == 1


@pytest.mark.django_db(transaction=True)
def test_a_row_with_an_unrecognised_kind_is_ignored(attestation_table: None) -> None:
    """A row written by a later version, or edited by hand. Ignoring it is the
    safe direction: an unknown statement must not be read as either "done" or
    "does not apply"."""
    store("p1", "s1", kind="maybe")

    assert load_attestations(["p1"], ["s1"]) == {}


def test_no_patients_is_no_query() -> None:
    assert load_attestations([], ["s1"]) == {}


def test_no_screenings_is_no_query() -> None:
    """A batch where nobody is eligible for anything skips this read entirely
    rather than issuing it and discarding the answer."""
    assert load_attestations(["p1"], []) == {}


@pytest.mark.django_db
def test_a_table_that_is_not_there_degrades_to_nothing() -> None:
    """No `attestation_table` fixture, so the table genuinely does not exist.
    A custom-data namespace that is not ready must cost a missing statement,
    not a broken chart."""
    assert load_attestations(["p1"], ["s1"]) == {}


# --- writing -----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_statement_is_stored_with_its_author(attestation_table: None) -> None:
    assert record_attestation(
        "p1", "s1", KIND_COMPLETED, date(2026, 4, 1),
        interval_quantity=10, interval_unit="years", label="colonoscopy",
        recorded_by="staff-9", today=TODAY,
    )

    row = ScreeningAttestation.objects.get(patient_key="p1")
    assert (row.kind, row.effective_date, row.recorded_by) == (
        KIND_COMPLETED, date(2026, 4, 1), "staff-9",
    )
    assert row.recorded_at == TODAY


@pytest.mark.django_db(transaction=True)
def test_writing_twice_replaces_rather_than_accumulates(attestation_table: None) -> None:
    """One row per patient per screening. Two live statements about the same
    screening would leave readers to pick between them."""
    record_attestation("p1", "s1", KIND_COMPLETED, TODAY, today=TODAY)
    record_attestation("p1", "s1", KIND_NOT_APPLICABLE, TODAY, today=TODAY)

    rows = list(ScreeningAttestation.objects.filter(patient_key="p1"))
    assert len(rows) == 1
    assert rows[0].kind == KIND_NOT_APPLICABLE


@pytest.mark.django_db
def test_a_write_that_cannot_land_returns_false() -> None:
    """No table. The caller has to be able to tell the clinician their click
    did not land - a write that silently does nothing is this plugin's
    recurring failure."""
    assert record_attestation("p1", "s1", KIND_COMPLETED, TODAY, today=TODAY) is False


@pytest.mark.django_db(transaction=True)
def test_undo_removes_the_row(attestation_table: None) -> None:
    store("p1", "s1")

    assert clear_attestation("p1", "s1") is True
    assert not ScreeningAttestation.objects.filter(patient_key="p1").exists()


@pytest.mark.django_db(transaction=True)
def test_undoing_nothing_is_not_an_error(attestation_table: None) -> None:
    """Two people with the panel open, one clicks Undo after the other. The
    second click has nothing to do and that is a success, not a failure."""
    assert clear_attestation("p1", "nothing-here") is True


@pytest.mark.django_db
def test_an_undo_that_cannot_run_returns_false() -> None:
    assert clear_attestation("p1", "s1") is False


# --- the author's name --------------------------------------------------------


@pytest.mark.django_db
def test_a_staff_members_name_is_resolved() -> None:
    """A raw staff key answers nobody. The point of storing the author is that
    a clinician can see whose statement they are reading."""
    staff = StaffFactory.create(first_name="Ada", last_name="Okafor")

    assert staff_names([str(staff.id)]) == {str(staff.id): "Ada Okafor"}


@pytest.mark.django_db
def test_several_authors_cost_one_query(
    django_assert_num_queries: Any,
) -> None:
    people = [StaffFactory.create(first_name=f"A{n}", last_name="X") for n in range(5)]

    with django_assert_num_queries(1):
        found = staff_names([str(person.id) for person in people])

    assert len(found) == 5


def test_no_authors_is_no_query() -> None:
    assert staff_names([]) == {}
    assert staff_names(["", ""]) == {}


@pytest.mark.django_db
def test_a_staff_member_with_no_name_is_left_out() -> None:
    """Rather than returned as an empty string, which would render as "by " and
    read like a bug. The caller falls back to "a staff member"."""
    staff = StaffFactory.create(first_name="", last_name="")

    assert staff_names([str(staff.id)]) == {}


@pytest.mark.django_db
def test_names_that_cannot_be_read_degrade_to_none() -> None:
    """The statement and its date are the load-bearing part; the name is what
    makes it checkable. Losing the name must not lose the statement."""
    with patch(f"{MODULE}.Staff") as model:
        model.objects.filter.side_effect = RuntimeError("no staff table")

        assert staff_names(["staff-1"]) == {}


# --- the date a provider types -------------------------------------------------


def test_a_plain_date_is_accepted() -> None:
    assert parse_effective_date("2026-04-01", TODAY) == date(2026, 4, 1)


def test_today_is_accepted() -> None:
    assert parse_effective_date(TODAY.isoformat(), TODAY) == TODAY


def test_tomorrow_is_allowed_as_timezone_slack() -> None:
    """**One day, and it is timezone rather than laxity.** `TODAY` here is the
    server's UTC date, and a provider's is not: east of UTC an ordinary
    "today" is already tomorrow by this clock, so refusing it would deny a
    provider in Tokyo their own current date every morning."""
    assert parse_effective_date((TODAY + timedelta(days=1)).isoformat(), TODAY) == (
        TODAY + timedelta(days=1)
    )


def test_two_days_out_is_refused() -> None:
    """No timezone is two days from UTC, so this is a date somebody typed on
    purpose - and a screening cannot have been done the day after tomorrow."""
    assert parse_effective_date((TODAY + timedelta(days=2)).isoformat(), TODAY) is None


def test_a_date_long_before_any_patient_was_born_is_refused() -> None:
    """A typo'd year stores something that reads as valid forever."""
    assert parse_effective_date("1026-04-01", TODAY) is None


def test_the_backdate_limit_is_the_boundary() -> None:
    oldest = date(TODAY.year - MAX_BACKDATE_YEARS, 1, 1)

    assert parse_effective_date(oldest.isoformat(), TODAY) == oldest


def test_text_that_is_not_a_date_is_refused() -> None:
    assert parse_effective_date("sometime last year", TODAY) is None


def test_a_missing_date_is_refused() -> None:
    assert parse_effective_date(None, TODAY) is None


# --- whose "today" is it? ------------------------------------------------------
#
# `recorded_at` is read as "when somebody said so", and the frame that answers
# in is the provider's. The server's is UTC, which is a day ahead of a US
# evening - and that made one click produce two different days.


def test_the_providers_own_date_is_honoured() -> None:
    """Chicago at 9pm: the server has already rolled over to tomorrow, the
    provider has not, and the record should say what the provider would."""
    assert recording_date((TODAY - timedelta(days=1)).isoformat(), TODAY) == (
        TODAY - timedelta(days=1)
    )


def test_a_date_ahead_of_the_server_is_honoured_too() -> None:
    """East of UTC the skew runs the other way."""
    assert recording_date((TODAY + timedelta(days=1)).isoformat(), TODAY) == (
        TODAY + timedelta(days=1)
    )


def test_a_date_no_timezone_could_produce_is_refused() -> None:
    """The browser supplies this, so it is bounded: one day is the whole range
    any real timezone can produce. Beyond that the server's date stands, and a
    client cannot name an arbitrary day as the day something was recorded."""
    assert recording_date((TODAY - timedelta(days=30)).isoformat(), TODAY) == TODAY
    assert recording_date((TODAY + timedelta(days=30)).isoformat(), TODAY) == TODAY


def test_a_missing_or_unreadable_local_date_falls_back_to_the_server() -> None:
    assert recording_date(None, TODAY) == TODAY
    assert recording_date("not-a-date", TODAY) == TODAY
