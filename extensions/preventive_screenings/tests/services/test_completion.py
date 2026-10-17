"""Tests for the batched completion lookups.

These run against the test database rather than mocks. A mocked queryset never
resolves a field name, so it would pass with a typo'd lookup and could not count
queries - and the query budget is the whole point of this module.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Patient

from preventive_screenings.services.catalog import (
    SOURCE_CONDITION,
    SOURCE_IMAGING,
    SOURCE_LAB,
    SOURCE_PROCEDURE,
    SOURCE_QUESTIONNAIRE,
    value_set_for,
)
from preventive_screenings.services.completion import (
    _expand,
    latest_dates,
    snoozed_until,
)

MODULE = "preventive_screenings.services.completion"

MakeImaging = Callable[..., Any]
MakeProcedure = Callable[..., Any]
MakeLab = Callable[..., Any]
MakeReferral = Callable[..., Any]
MakeInterview = Callable[..., Any]
MakeCondition = Callable[..., Any]
DjangoAssertNumQueries = Callable[..., Any]

CPT_SYSTEM = "http://www.ama-assn.org/go/cpt"
SNOMED_SYSTEM = "http://snomed.info/sct"


def signal(value_set_key: str = "", source: str = SOURCE_PROCEDURE, **over: Any) -> dict:
    """A completion signal as the config store would have normalized it."""
    out = {
        "value_set_key": value_set_key,
        "source": source,
        "codes": [],
        "label": "",
        "interval_quantity": 1,
        "interval_unit": "years",
    }
    out.update(over)
    return out


def dates_for(patient_dbid: int, signals: list[Any]) -> dict[Any, date]:
    """One patient's dates out of the batched read.

    ``latest_dates`` takes a list of patients and returns a result per patient,
    because the sweep reviews them in batches. Most tests below are about which
    record matches which signal, not about batching, so they ask for one patient
    and unwrap. The batching itself is tested separately.
    """
    return latest_dates([patient_dbid], signals).get(patient_dbid, {})


@pytest.mark.django_db
def test_imaging_report_matches_its_value_set(
    patient: Patient, make_imaging: MakeImaging
) -> None:
    """A mammogram report satisfies a signal pointing at the Mammography value set."""
    make_imaging(patient, "24606-6", date(2024, 3, 12))

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]
    )

    assert found == {("completion", 0, 0): date(2024, 3, 12)}


@pytest.mark.django_db
def test_procedure_is_dated_by_its_notes_date_of_service(
    patient: Patient, make_procedure: MakeProcedure
) -> None:
    """A colonoscopy counts from when it was performed, not when it was recorded."""
    make_procedure(patient, "44388", date(2019, 8, 1))

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("colonoscopy", SOURCE_PROCEDURE))]
    )

    assert found == {("completion", 0, 0): date(2019, 8, 1)}


@pytest.mark.django_db
def test_lab_value_matches_through_its_report(patient: Patient, make_lab: MakeLab) -> None:
    """A stool test is found through the report that carries the patient and date."""
    make_lab(patient, "12503-9", date(2025, 1, 20))

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("fobt", SOURCE_LAB))])

    assert found == {("completion", 0, 0): date(2025, 1, 20)}


@pytest.mark.django_db
def test_questionnaire_matches_on_the_code_system_name(
    patient: Patient, make_interview: MakeInterview
) -> None:
    """Questionnaires store the system as "LOINC", not as a URL, and still match."""
    make_interview(patient, "52552-7", age_days=30)

    found = dates_for(
        patient.dbid,
        [(("completion", 0, 0), signal("falls_screening", SOURCE_QUESTIONNAIRE))],
    )

    assert list(found) == [("completion", 0, 0)]


@pytest.mark.django_db
def test_condition_matches_its_value_set(
    patient: Patient, make_condition: MakeCondition
) -> None:
    """An exclusion finds a condition on the problem list."""
    make_condition(patient, "428529004", date(2020, 2, 2))

    found = dates_for(
        patient.dbid,
        [(("exclusion", 0, 0), signal("history_bilateral_mastectomy", SOURCE_CONDITION))],
    )

    assert found == {("exclusion", 0, 0): date(2020, 2, 2)}


@pytest.mark.django_db
def test_custom_codes_match_on_the_code_alone(
    patient: Patient, make_procedure: MakeProcedure
) -> None:
    """A practice-specific screening is addressed by code without a terminology URL."""
    make_procedure(patient, "77080", date(2023, 5, 5), system="whatever-this-instance-uses")

    found = dates_for(
        patient.dbid,
        [(("completion", 0, 0), signal(codes=["77080", "77081"], source=SOURCE_PROCEDURE))],
    )

    assert found == {("completion", 0, 0): date(2023, 5, 5)}


@pytest.mark.django_db
def test_the_most_recent_qualifying_record_wins(
    patient: Patient, make_imaging: MakeImaging
) -> None:
    """Several mammograms resolve to the latest one."""
    make_imaging(patient, "24606-6", date(2021, 1, 1))
    make_imaging(patient, "24605-8", date(2024, 7, 9))
    make_imaging(patient, "24606-6", date(2022, 6, 6))

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]
    )

    assert found == {("completion", 0, 0): date(2024, 7, 9)}


@pytest.mark.django_db
def test_a_record_outside_the_value_set_is_not_credited(
    patient: Patient, make_procedure: MakeProcedure
) -> None:
    """A colectomy is not a colonoscopy, however similar the codes look."""
    make_procedure(patient, "44150", date(2022, 2, 2))

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("colonoscopy", SOURCE_PROCEDURE))]
    )

    assert found == {}


@pytest.mark.django_db
def test_a_matching_code_in_the_wrong_system_is_not_credited(
    patient: Patient, make_imaging: MakeImaging
) -> None:
    """A value-set signal matches the system too, so codes cannot collide across
    terminologies and be miscredited."""
    make_imaging(patient, "24606-6", date(2024, 3, 12), system=SNOMED_SYSTEM)

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]
    )

    assert found == {}


@pytest.mark.django_db
def test_another_patients_record_is_not_credited(
    patient: Patient, make_imaging: MakeImaging
) -> None:
    """Every source is scoped to the patient whose chart is open."""
    from canvas_sdk.test_utils.factories import PatientFactory

    other = PatientFactory.create(birth_date=date(1970, 1, 1), sex_at_birth="F", deceased=False)
    make_imaging(other, "24606-6", date(2024, 3, 12))

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]
    )

    assert found == {}


@pytest.mark.django_db
def test_an_unknown_value_set_key_matches_nothing(
    patient: Patient, make_imaging: MakeImaging
) -> None:
    """A rule naming a value set this version no longer ships reads as unmeasurable,
    never as "never done"."""
    make_imaging(patient, "24606-6", date(2024, 3, 12))

    found = dates_for(
        patient.dbid, [(("completion", 0, 0), signal("retired_key", SOURCE_IMAGING))]
    )

    assert found == {}


@pytest.mark.django_db
def test_a_signal_with_an_unknown_source_is_skipped(patient: Patient) -> None:
    """A source this version does not know how to read is left alone rather than guessed at."""
    assert dates_for(patient.dbid, [(("completion", 0, 0), signal(codes=["x"], source="ouija"))]) == {}


def test_no_signals_costs_no_queries() -> None:
    """The handler's common early exit never reaches the database."""
    assert dates_for(1, []) == {}


@pytest.mark.django_db
def test_signals_sharing_a_source_cost_one_query(
    patient: Patient,
    make_imaging: MakeImaging,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Ten screenings that all look at one source cost one query, not ten.

    This is the guarantee the whole module exists for. **If this fails, fix the
    query rather than raising the number.**

    Mammography costs **two** queries, not one: since 2026-09-22 it is read from
    `Procedure` as well as `ImagingReport`, because a mammogram recorded with
    the Perform command lands there under a CPT code the LOINC-only SDK value
    set could never match. Two sources, ten screenings, two queries - the point
    of this test is that the count tracks *sources* and never screenings.
    """
    make_imaging(patient, "24606-6", date(2024, 3, 12))
    signals = [
        (("completion", index, 0), signal("mammography", SOURCE_IMAGING)) for index in range(10)
    ]

    with django_assert_num_queries(2):
        found = dates_for(patient.dbid, signals)

    assert len(found) == 10


@pytest.mark.django_db
def test_a_multi_source_value_set_costs_one_query_per_source_not_per_screening(
    patient: Patient,
    make_procedure: MakeProcedure,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """A colonoscopy is read in three places, and that is three queries for ten
    screenings just as it is for one.

    The cost of reading somewhere else is paid per *source*, never per
    screening and never per patient. **If this fails, fix the query rather than
    raising the number.**
    """
    make_procedure(patient, "44388", date(2019, 8, 1))
    signals = [
        (("completion", index, 0), signal("colonoscopy", SOURCE_PROCEDURE)) for index in range(10)
    ]

    with django_assert_num_queries(3):
        found = dates_for(patient.dbid, signals)

    assert len(found) == 10


@pytest.mark.django_db
def test_each_distinct_source_costs_one_query(
    patient: Patient,
    make_imaging: MakeImaging,
    make_procedure: MakeProcedure,
    make_lab: MakeLab,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Each kind of record costs one query, whatever asked for it.

    Five here, not three: the colonoscopy is also read from referral reports
    and the colectomy also from conditions, and those two extra sources are
    read once for everything that wants them rather than once per signal.
    """
    make_imaging(patient, "24606-6", date(2024, 3, 12))
    make_procedure(patient, "44388", date(2019, 8, 1))
    make_lab(patient, "12503-9", date(2025, 1, 20))
    signals = [
        (("completion", 0, 0), signal("mammography", SOURCE_IMAGING)),
        (("completion", 0, 1), signal("colonoscopy", SOURCE_PROCEDURE)),
        (("completion", 0, 2), signal("fobt", SOURCE_LAB)),
        (("completion", 1, 0), signal("mammography", SOURCE_IMAGING)),
        (("exclusion", 1, 0), signal("total_colectomy", SOURCE_PROCEDURE)),
    ]

    # imaging, lab, procedure, referral, condition
    with django_assert_num_queries(5):
        found = dates_for(patient.dbid, signals)

    assert len(found) == 4  # the colectomy exclusion has no matching record


@pytest.mark.django_db
def test_an_unreadable_source_is_absent_rather_than_never_done(patient: Patient) -> None:
    """A source that fails to read must not be reported as "never done".

    Reading a database error as "no record found" would put a recommendation in
    front of a provider on no evidence at all.
    """
    with patch(
        "preventive_screenings.services.completion.ImagingReport.objects.filter",
        side_effect=ValueError("boom"),
    ):
        found = dates_for(
            patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]
        )

    assert found == {}


def test_expand_covers_every_system_in_a_multi_system_value_set() -> None:
    """Colonoscopy spans CPT, HCPCS and SNOMED, and all three must be searchable."""
    from canvas_sdk.value_set.v2026.procedure import Colonoscopy

    by_url = _expand(Colonoscopy, by_name=False)
    by_name = _expand(Colonoscopy, by_name=True)

    assert {system for system, _code in by_name} == {"CPT", "HCPCSLEVELII", "SNOMEDCT"}
    assert (CPT_SYSTEM, "44388") in by_url
    assert len(by_url) == len(by_name)


def test_as_date_normalizes_whatever_a_source_column_holds() -> None:
    """Sources differ: imaging stores a date, labs a datetime. Anything else is
    not a date at all and must not be guessed at."""
    from preventive_screenings.services.completion import _as_date

    assert _as_date(date(2024, 3, 12)) == date(2024, 3, 12)
    assert _as_date(datetime(2024, 3, 12, 9, 30, tzinfo=UTC)) == date(2024, 3, 12)
    assert _as_date(None) is None
    assert _as_date("2024-03-12") is None


@pytest.mark.django_db
def test_a_record_with_no_date_is_not_credited(patient: Patient) -> None:
    """An undated record cannot say when the screening was done, so it does not
    count - the alternative is dating it wrongly and clearing a real card."""
    # (patient dbid, system, code, date) - the patient column leads now that one
    # read covers a batch and rows have to be handed back to their owner.
    rows = [(patient.dbid, "http://loinc.org", "24606-6", None)]
    with patch(
        "preventive_screenings.services.completion.ImagingReport.objects.filter"
    ) as filtered:
        filtered.return_value.filter.return_value.values_list.return_value = rows
        found = dates_for(
            patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]
        )

    assert found == {}


@pytest.mark.django_db
def test_a_batch_of_patients_costs_the_same_as_one(
    make_imaging: MakeImaging,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Twenty patients cost one query, not twenty.

    The sweep reviews a batch of patients per run. Reading them one at a time
    made a run cost a full set of source queries per patient, which is what
    capped ``BATCH`` - the same N+1 this module avoids across screenings,
    reintroduced along the other axis. **If this fails, fix the query rather
    than raising the number.**

    Two queries rather than one only because mammography now reads `Procedure`
    too. That this moved by exactly one at the same time as the single-patient
    guard above is the evidence the new read is per-run: a per-patient read
    would have moved this one by twenty.
    """
    from canvas_sdk.test_utils.factories import PatientFactory

    patients = [
        PatientFactory.create(birth_date=date(1976, 6, 15), sex_at_birth="F", deceased=False)
        for _ in range(20)
    ]
    for person in patients:
        make_imaging(person, "24606-6", date(2024, 3, 12))

    with django_assert_num_queries(2):
        found = latest_dates(
            [person.dbid for person in patients],
            [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))],
        )

    assert len(found) == 20


@pytest.mark.django_db
def test_each_patients_rows_are_attributed_to_that_patient(
    make_imaging: MakeImaging, make_procedure: MakeProcedure
) -> None:
    """A batched read must not credit one patient's mammogram to another.

    This is the risk the batching introduces: the rows come back in one set, so
    the patient column has to be carried through and grouped on.
    """
    from canvas_sdk.test_utils.factories import PatientFactory

    early, late, none = (
        PatientFactory.create(birth_date=date(1976, 6, 15), sex_at_birth="F", deceased=False)
        for _ in range(3)
    )
    make_imaging(early, "24606-6", date(2021, 1, 1))
    make_imaging(late, "24606-6", date(2025, 5, 5))
    make_procedure(none, "44388", date(2019, 8, 1))  # a different source entirely

    found = latest_dates(
        [early.dbid, late.dbid, none.dbid],
        [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))],
    )

    assert found[early.dbid] == {("completion", 0, 0): date(2021, 1, 1)}
    assert found[late.dbid] == {("completion", 0, 0): date(2025, 5, 5)}
    assert none.dbid not in found


def test_no_patients_costs_no_queries() -> None:
    """An empty batch is a real case: every patient in it was unassessable."""
    assert latest_dates([], [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))]) == {}


# --- snoozes -----------------------------------------------------------------


@pytest.mark.django_db
def test_a_snooze_is_found_for_the_card_it_was_made_against(
    patient: Patient, make_snooze: Any
) -> None:
    make_snooze(patient, "preventive_screening:s1", date(2026, 12, 1))

    found = snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20))

    assert found == {patient.dbid: {"preventive_screening:s1": date(2026, 12, 1)}}


@pytest.mark.django_db
def test_an_expired_snooze_does_not_come_back(patient: Patient, make_snooze: Any) -> None:
    """The card returns to normal on its own when the snooze runs out, rather
    than needing anything to clear it."""
    make_snooze(patient, "preventive_screening:s1", date(2026, 9, 19))

    assert snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20)) == {}


@pytest.mark.django_db
def test_a_snooze_covers_its_own_last_day(patient: Patient, make_snooze: Any) -> None:
    """Snoozed *until* the 20th means still snoozed on the 20th. next_change_date
    schedules the revisit for the 21st, and the two must agree or the card either
    un-snoozes a day early or sticks a day late."""
    make_snooze(patient, "preventive_screening:s1", date(2026, 9, 20))

    assert snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "inactive"},
        {"entered_in_error": True},
        {"is_snooze": False},
    ],
    ids=["inactive", "entered-in-error", "an adjustment, not a snooze"],
)
@pytest.mark.django_db
def test_a_snooze_that_should_not_count_is_ignored(
    patient: Patient, make_snooze: Any, kwargs: dict
) -> None:
    make_snooze(patient, "preventive_screening:s1", date(2026, 12, 1), **kwargs)

    assert snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20)) == {}


@pytest.mark.django_db
def test_the_later_of_two_snoozes_wins(patient: Patient, make_snooze: Any) -> None:
    """Snoozing twice defers to the later date, not whichever row came back first."""
    make_snooze(patient, "preventive_screening:s1", date(2026, 11, 1))
    make_snooze(patient, "preventive_screening:s1", date(2027, 1, 1))

    found = snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20))

    assert found[patient.dbid]["preventive_screening:s1"] == date(2027, 1, 1)


@pytest.mark.django_db
def test_one_patients_snooze_does_not_silence_anothers_card(make_snooze: Any) -> None:
    """The risk batching introduces: a shared read has to be attributed back per
    patient, or one provider's deferral quiets someone else's overdue card."""
    one = PatientFactory.create(birth_date=date(1975, 1, 1), sex_at_birth="F", deceased=False)
    two = PatientFactory.create(birth_date=date(1975, 1, 1), sex_at_birth="F", deceased=False)
    make_snooze(one, "preventive_screening:s1", date(2026, 12, 1))

    found = snoozed_until(
        [one.dbid, two.dbid], ["preventive_screening:s1"], date(2026, 9, 20)
    )

    assert one.dbid in found
    assert two.dbid not in found


@pytest.mark.django_db
def test_a_whole_batch_of_snoozes_costs_one_query(
    make_snooze: Any, django_assert_num_queries: Any
) -> None:
    """Same rule as every other read here: one query for the batch, not one per
    patient and not one per screening."""
    people = [
        PatientFactory.create(birth_date=date(1975, 1, 1), sex_at_birth="F", deceased=False)
        for _ in range(20)
    ]
    keys = [f"preventive_screening:s{index}" for index in range(10)]
    for person in people:
        for key in keys:
            make_snooze(person, key, date(2026, 12, 1))

    with django_assert_num_queries(1):
        found = snoozed_until([person.dbid for person in people], keys, date(2026, 9, 20))

    assert len(found) == 20
    assert all(len(cards) == 10 for cards in found.values())


@pytest.mark.django_db
def test_no_patients_or_no_keys_asks_nothing(patient: Patient) -> None:
    assert snoozed_until([], ["preventive_screening:s1"], date(2026, 9, 20)) == {}
    assert snoozed_until([patient.dbid], [], date(2026, 9, 20)) == {}


def test_an_unreadable_snooze_leaves_the_card_loud() -> None:
    """Failing closed here means the card keeps shouting, which is the safe
    direction: a missed snooze is noise, a wrongly-applied one hides an overdue
    screening from the provider who needs to see it."""
    with patch(f"{MODULE}.ProtocolOverride") as model, patch(f"{MODULE}.log"):
        model.objects.filter.side_effect = RuntimeError("boom")

        assert snoozed_until([1], ["preventive_screening:s1"], date(2026, 9, 20)) == {}


@pytest.mark.django_db
def test_a_snooze_against_an_unknown_key_is_ignored_and_reported(
    patient: Patient, make_snooze: Any, caplog: Any
) -> None:
    """Canvas may not record `protocol_key` as our card key - nothing in the SDK
    says what it writes for a plugin's card, and the first assumption matched
    nothing on a real instance.

    An unmatched row must never be applied to a card it may not belong to, and
    must not be silently dropped either, or the next person is left guessing the
    same way. It is ignored and logged with what was actually on it.
    """
    make_snooze(patient, "something-canvas-chose", date(2026, 12, 1))

    with caplog.at_level("INFO"):
        found = snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20))

    assert found == {}, "a key we do not recognise must not quieten a card"
    assert "something-canvas-chose" in caplog.text
    assert "preventive_screening:s1" in caplog.text


@pytest.mark.django_db
def test_a_matching_snooze_beside_an_unknown_one_still_counts(
    patient: Patient, make_snooze: Any
) -> None:
    """The unmatched row is noise, not a reason to drop the good one."""
    make_snooze(patient, "something-canvas-chose", date(2026, 12, 1))
    make_snooze(patient, "preventive_screening:s1", date(2026, 11, 1))

    found = snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20))

    assert found == {patient.dbid: {"preventive_screening:s1": date(2026, 11, 1)}}


@pytest.mark.django_db
def test_a_deleted_snooze_never_reaches_us_at_all(patient: Patient, make_snooze: Any) -> None:
    """`snoozed_until` does not check `deleted`, and must not start to: the
    SDK's BaseModelManager.get_queryset already filters deleted=False, so the
    row never arrives. A check here would be unreachable code that looks like a
    safeguard."""
    make_snooze(patient, "preventive_screening:s1", date(2026, 12, 1), deleted=True)

    assert snoozed_until([patient.dbid], ["preventive_screening:s1"], date(2026, 9, 20)) == {}


@pytest.mark.django_db
def test_canvas_appends_the_plugin_name_to_the_card_key(
    patient: Patient, make_snooze: Any
) -> None:
    """**The format, measured on the instance 2026-09-20.** Canvas does not
    record a snoozed card's protocol_key as the key we gave the card - it
    appends the plugin's name. Nothing in the SDK says so, and two guesses were
    wrong before the row was printed.
    """
    # An obviously synthetic id. This was a real screening id copied off
    # the build instance, which is exactly the kind of thing that must not
    # reach another practice's copy of this plugin.
    card = "preventive_screening:0123456789abcdef0123456789abcdef"
    make_snooze(patient, f"{card}preventive_screenings", date(2026, 12, 1))

    found = snoozed_until([patient.dbid], [card], date(2026, 9, 20))

    assert found == {patient.dbid: {card: date(2026, 12, 1)}}, (
        "the snooze must come back under OUR card key, not Canvas's"
    )


@pytest.mark.django_db
def test_a_key_without_the_suffix_still_matches(patient: Patient, make_snooze: Any) -> None:
    """The suffix is stripped rather than the full string constructed, so an
    instance that does not append it keeps working."""
    card = "preventive_screening:s1"
    make_snooze(patient, card, date(2026, 12, 1))

    assert snoozed_until([patient.dbid], [card], date(2026, 9, 20)) == {
        patient.dbid: {card: date(2026, 12, 1)}
    }


@pytest.mark.django_db
def test_a_staged_but_unrecorded_snooze_does_not_quieten_the_card(
    patient: Patient, make_snooze: Any
) -> None:
    """Snoozing takes two clicks - stage, then Record - and the override row
    exists as `inactive` in between. A card must not go quiet on a snooze the
    provider has not recorded: they may yet not record it.
    """
    card = "preventive_screening:s1"
    make_snooze(patient, f"{card}preventive_screenings", date(2026, 12, 1), status="inactive")

    assert snoozed_until([patient.dbid], [card], date(2026, 9, 20)) == {}


@pytest.mark.django_db
def test_a_mammogram_recorded_with_the_perform_command_is_found(
    patient: Patient, make_procedure: MakeProcedure
) -> None:
    """**The bug this catches shipped, and UAT found it.**

    Recording a mammogram through the Perform command writes a `Procedure`
    carrying a **CPT** code. The SDK's `Mammography` value set is 92 LOINC
    codes and not one CPT code, and the catalog read it from `ImagingReport`
    only - so out of the box the screening card never cleared, however many
    mammograms were recorded. The only way a practice could find out was to
    record one and watch nothing happen.

    Confirmed against the instance 2026-09-22: the three mammogram options
    Perform offers write CPT 77065, 77066 and 77067.
    """
    make_procedure(patient, "77067", date(2025, 2, 10), system=CPT_SYSTEM)

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))])

    assert found == {("completion", 0, 0): date(2025, 2, 10)}


def test_a_mammogram_report_still_counts_after_the_procedure_codes_were_added(
    patient: Patient, make_imaging: MakeImaging
) -> None:
    """The half that must not have regressed. Extending the value set has to add
    a way to satisfy the screening, never replace the one that worked."""
    make_imaging(patient, "24606-6", date(2025, 3, 1))

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))])

    assert found == {("completion", 0, 0): date(2025, 3, 1)}


def test_a_diagnostic_mammogram_satisfies_a_screening_recommendation(
    patient: Patient, make_procedure: MakeProcedure
) -> None:
    """77065/77066 are diagnostic rather than screening codes, and they count
    deliberately: the breast was imaged, so that patient is in active workup
    rather than overdue for a look. Adding a code can only make an
    already-screened patient read as done - it removes false overdue cards and
    cannot create one."""
    make_procedure(patient, "77066", date(2025, 6, 2), system=CPT_SYSTEM)

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("mammography", SOURCE_IMAGING))])

    assert found == {("completion", 0, 0): date(2025, 6, 2)}


def test_the_sdk_value_sets_are_not_mutated_by_extending_them(
    patient: Patient
) -> None:
    """The extended sets subclass rather than edit, because other entries share
    those classes. If `Mammography` itself ever gained CPT codes, every plugin
    importing it would silently change behaviour."""
    from canvas_sdk.value_set.v2026.diagnostic_study import Mammography
    from canvas_sdk.value_set.v2026.laboratory_test import PapTest

    assert "CPT" not in Mammography.values
    assert "CPT" not in PapTest.values


def test_a_colonoscopy_recorded_as_a_referral_report_is_found(
    patient: Patient, make_referral: MakeReferral
) -> None:
    """**The reason the referral source exists.**

    The instance's own CMS130v6 reads a colonoscopy from `referral_reports` or
    `imaging_reports` and never from `Procedure`, which is the only place this
    plugin used to look. A report in the wrong table is not a cosmetic miss:
    the patient reads as never screened and gets chased for a test they have
    had, which is the noise that teaches providers to ignore these cards.
    """
    make_referral(patient, "44388", date(2021, 5, 4), system=CPT_SYSTEM)

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("colonoscopy"))])

    assert found == {("completion", 0, 0): date(2021, 5, 4)}


@pytest.mark.django_db
def test_a_junked_referral_report_does_not_count(
    patient: Patient, make_referral: MakeReferral
) -> None:
    """`junked` is this model's "ignore this" - it has no committer to check,
    because an inbound report is not something a provider signs."""
    make_referral(patient, "44388", date(2021, 5, 4), system=CPT_SYSTEM, junked=True)

    assert dates_for(patient.dbid, [(("completion", 0, 0), signal("colonoscopy"))]) == {}


@pytest.mark.django_db
def test_the_most_recent_date_across_sources_wins(
    patient: Patient, make_referral: MakeReferral, make_procedure: MakeProcedure
) -> None:
    """A signal read in several places takes the latest date, not whichever
    source happened to be read last.

    Merging with `dict.update` would have let the read order decide, silently,
    and differently as sources came and went from the config. Here the
    procedure is the older record, so the referral must win.
    """
    make_procedure(patient, "44388", date(2015, 1, 1))
    make_referral(patient, "44388", date(2021, 5, 4), system=CPT_SYSTEM)

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("colonoscopy"))])

    assert found == {("completion", 0, 0): date(2021, 5, 4)}


@pytest.mark.django_db
def test_the_older_source_does_not_overwrite_the_newer_one(
    patient: Patient, make_referral: MakeReferral, make_procedure: MakeProcedure
) -> None:
    """The same assertion with the dates swapped, because a merge bug that
    takes the last source read would pass the test above half the time."""
    make_procedure(patient, "44388", date(2022, 9, 9))
    make_referral(patient, "44388", date(2016, 2, 2), system=CPT_SYSTEM)

    found = dates_for(patient.dbid, [(("completion", 0, 0), signal("colonoscopy"))])

    assert found == {("completion", 0, 0): date(2022, 9, 9)}


@pytest.mark.django_db
def test_a_mastectomy_on_the_problem_list_excludes(
    patient: Patient, make_condition: MakeCondition
) -> None:
    """Surgical history is where the native protocols look for these, and an
    exclusion missed puts a mammogram card on the chart of a patient who
    cannot have one - the wrong-patient recommendation the brief calls the
    highest-stakes failure."""
    value_set = value_set_for("bilateral_mastectomy")
    assert value_set is not None
    code = sorted(value_set.values["SNOMEDCT"])[0]
    make_condition(patient, code, date(2018, 3, 1))

    found = dates_for(
        patient.dbid, [(("exclusion", 0, 0), signal("bilateral_mastectomy"))]
    )

    assert ("exclusion", 0, 0) in found


@pytest.mark.django_db
def test_a_signals_own_codes_are_read_only_where_the_admin_pointed_them(
    patient: Patient, make_referral: MakeReferral
) -> None:
    """Nothing knows where else a practice's own codes might live, so a custom
    signal is read in the one source it names and no others."""
    make_referral(patient, "99999", date(2021, 5, 4), system=CPT_SYSTEM)
    custom = signal("", SOURCE_PROCEDURE, codes=["99999"])

    assert dates_for(patient.dbid, [(("completion", 0, 0), custom)]) == {}


@pytest.mark.django_db
def test_a_row_whose_system_does_not_match_is_reported_not_swallowed(
    patient: Patient, make_procedure: MakeProcedure, caplog: Any
) -> None:
    """**The quietest failure this module has.**

    The query matches on the code alone; attribution also demands the system.
    A value set expanded to a system string the records do not use matches
    nothing while looking perfectly healthy - which is exactly how the
    `Interview`-stores-the-system-by-name bug shipped. Say it out loud.
    """
    make_procedure(patient, "45380", date(2026, 9, 20), system="urn:something-else")

    with caplog.at_level("INFO"):
        found = dates_for(patient.dbid, [(("completion", 0, 0), signal("colonoscopy"))])

    assert found == {}
    assert "no signal claimed" in caplog.text
    assert "urn:something-else" in caplog.text
