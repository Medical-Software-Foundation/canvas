"""Tests for one patient's screening review.

These are the behaviour tests for the plugin's actual output: which cards a
patient gets, what they say, and in what order. They run against the test
database rather than a mocked ORM, because a mocked queryset never resolves a
field name and cannot count queries - which is exactly how a real shipped bug
(a value set expanded the wrong way for Interview) got through once already.

The trigger that calls this - which events, and resolving the patient from the
record that changed - is tested in tests/handlers/test_event_handlers.py.
"""

import json
from collections.abc import Callable
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Patient
from pytest_django import DjangoAssertNumQueries

from preventive_screenings.models import ScreeningAttestation
from preventive_screenings.services.cards import card_key
from preventive_screenings.services.review import review_patient, review_patients
from preventive_screenings.services.config_store import new_screening

MODULE = "preventive_screenings.services.review"

MakeImaging = Callable[..., Any]
MakeProcedure = Callable[..., Any]
MakeLab = Callable[..., Any]
MakeSnooze = Callable[..., Any]
MakeCondition = Callable[..., Any]

# Old enough for every shipped screening, and female, so the sex-specific ones
# apply. Age 50 as of the test run.
BORN = date(1976, 6, 15)


def mammogram(**over: Any) -> dict:
    """An enabled mammogram screening: women 40-74, every 2 years."""
    fields: dict[str, Any] = {
        "enabled": True,
        "name": "Mammogram",
        "sex": "female",
        "min_age": 40,
        "max_age": 74,
        "grace_days": 90,
        "completions": [
            {"value_set_key": "mammography", "source": "imaging_report", "codes": [],
             "label": "", "interval_quantity": 2, "interval_unit": "years"}
        ],
        "order_command": "imaging_order",
        "order_button": "Order mammogram",
        "order_code": "24606-6",
    }
    return new_screening(**{**fields, **over})


def review(patient: Patient, screenings: list[dict], today: date | None = None) -> Any:
    """One patient's review, as either trigger would compute it."""
    return review_patient(str(patient.id), screenings, today or date.today())


def payload(effect: Any) -> dict:
    """The card data block from an effect."""
    data: dict = json.loads(effect.payload)["data"]
    return data


@pytest.fixture
def woman_of_50() -> Patient:
    return PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)


# --- the core behaviour ------------------------------------------------------


@pytest.mark.django_db
def test_a_patient_with_no_history_gets_an_overdue_card(
    woman_of_50: Patient
) -> None:
    """Eligible since 40 with nothing on file reads as overdue, which is how
    patients whose history predates the install are handled with no backfill."""
    effects = review(woman_of_50, [mammogram()]).effects

    assert len(effects) == 1
    assert effects[0].type == EffectType.ADD_OR_UPDATE_PROTOCOL_CARD
    data = payload(effects[0])
    assert data["title"].startswith("Mammogram — OVERDUE by")
    assert data["status"] == "due"
    assert data["due_in"] < 0
    assert "No qualifying result on record." in data["narrative"]


@pytest.mark.django_db
def test_a_recent_mammogram_satisfies_the_screening(
    woman_of_50: Patient, make_imaging: MakeImaging
) -> None:
    """A screening stops showing as due once it has actually been done."""
    make_imaging(woman_of_50, "24606-6", date.today())

    data = payload(review(woman_of_50, [mammogram()]).effects[0])

    assert data["status"] == "satisfied"
    assert data["title"] == "Mammogram"
    assert data["recommendations"] == []


@pytest.mark.django_db
def test_the_last_completed_date_is_on_the_card(
    woman_of_50: Patient, make_imaging: MakeImaging
) -> None:
    """"We also need to see the last completed date, not only when it's due."""
    make_imaging(woman_of_50, "24606-6", date(2021, 4, 8))

    data = payload(review(woman_of_50, [mammogram()]).effects[0])

    assert "Last completed 8 Apr 2021." in data["narrative"]


@pytest.mark.django_db
def test_an_overdue_card_offers_the_order_prefilled(
    woman_of_50: Patient
) -> None:
    """A provider can order from the recommendation without leaving the chart."""
    data = payload(review(woman_of_50, [mammogram()]).effects[0])

    recommendation = data["recommendations"][0]
    assert recommendation["button"] == "Order mammogram"
    assert recommendation["commands"][0]["context"]["image_code"] == "24606-6"


# --- never show a screening to a patient it does not apply to ----------------


@pytest.mark.django_db
def test_a_man_is_not_shown_a_womens_screening() -> None:
    man = PatientFactory.create(birth_date=BORN, sex_at_birth="M", deceased=False)

    data = payload(review(man, [mammogram()]).effects[0])

    assert data["status"] == "not_applicable"
    assert data["recommendations"] == []


@pytest.mark.django_db
def test_a_patient_with_no_recorded_sex_is_not_shown_a_sex_specific_screening() -> None:
    """Unknown is never positive."""
    unknown = PatientFactory.create(birth_date=BORN, sex_at_birth="UNK", deceased=False)

    data = payload(review(unknown, [mammogram()]).effects[0])

    assert data["status"] == "not_applicable"


@pytest.mark.django_db
def test_a_patient_below_the_age_is_not_shown_the_screening() -> None:
    young = PatientFactory.create(birth_date=date(2000, 1, 1), sex_at_birth="F", deceased=False)

    data = payload(review(young, [mammogram()]).effects[0])

    assert data["status"] == "not_applicable"


@pytest.mark.django_db
def test_an_excluding_condition_removes_the_screening(
    woman_of_50: Patient, make_condition: MakeCondition
) -> None:
    """A recorded bilateral mastectomy makes the mammogram card go away."""
    make_condition(woman_of_50, "428529004", date(2020, 2, 2))
    rule = mammogram(
        exclusions=[{"value_set_key": "history_bilateral_mastectomy", "source": "condition",
                     "codes": [], "label": ""}]
    )

    data = payload(review(woman_of_50, [rule]).effects[0])

    assert data["status"] == "not_applicable"


@pytest.mark.django_db
def test_a_deceased_patient_gets_no_cards() -> None:
    dead = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=True)

    assert review(dead, [mammogram()]).effects == []


@pytest.mark.django_db
def test_a_patient_with_no_birth_date_gets_no_cards(
    woman_of_50: Patient
) -> None:
    """Without a date of birth no age rule can be evaluated, and an unknown age
    must never be read as eligible.

    Mocked rather than seeded: birth_date is non-null in the test database, so
    the row cannot be created. The guard still matters - a patient row that
    reaches the handler without one must produce nothing, not a card computed
    from a missing age.
    """
    with patch(f"{MODULE}.Patient") as patient_model:
        patient_model.objects.filter.return_value.values.return_value = [
            {
                "id": woman_of_50.id,
                "dbid": 1,
                "birth_date": None,
                "sex_at_birth": "F",
                "deceased": False,
            }
        ]
        assert review(woman_of_50, [mammogram()]).effects == []


# --- triage order ------------------------------------------------------------


@pytest.mark.django_db
def test_overdue_cards_come_before_due_ones(
    woman_of_50: Patient, make_imaging: MakeImaging
) -> None:
    """The top of the chart is already triaged, which is what "overdue must look
    different from merely due" is for."""
    # Due 40 days ago: inside the 90-day grace, so due rather than overdue.
    make_imaging(woman_of_50, "24606-6", date.today().replace(year=date.today().year - 2))
    due = mammogram(name="Just due")
    overdue = mammogram(name="Long overdue", completions=[
        {"value_set_key": "pap_test", "source": "lab_result", "codes": [], "label": "",
         "interval_quantity": 3, "interval_unit": "years"}
    ])

    effects = review(woman_of_50, [due, overdue]).effects

    titles = [payload(effect)["title"] for effect in effects]
    assert titles[0].startswith("Long overdue — OVERDUE")
    assert titles[1] == "Just due — due"


@pytest.mark.django_db
def test_satisfied_and_not_applicable_cards_come_last(
    woman_of_50: Patient, make_imaging: MakeImaging
) -> None:
    make_imaging(woman_of_50, "24606-6", date.today())
    overdue = mammogram(name="Overdue", completions=[
        {"value_set_key": "pap_test", "source": "lab_result", "codes": [], "label": "",
         "interval_quantity": 3, "interval_unit": "years"}
    ])

    effects = review(woman_of_50, [mammogram(name="Done"), overdue]).effects

    statuses = [payload(effect)["status"] for effect in effects]
    assert statuses == ["due", "satisfied"]


# --- the query budget --------------------------------------------------------


@pytest.mark.django_db
def test_chart_open_costs_a_fixed_number_of_queries(
    woman_of_50: Patient,
    make_imaging: MakeImaging,
    make_procedure: MakeProcedure,
    make_lab: MakeLab,
    django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """Twelve screenings across three kinds of record cost one patient read, one
    read per kind of record, and one snooze read - not one per screening.

    The snooze read was added deliberately in 0.7.0 so a deferred screening stops
    shouting OVERDUE from its stub; it is one query for the whole batch, not one
    per screening or per patient, which is why this number went 4 -> 5 and not
    4 -> 4 + screenings.

    It went 5 -> 6 in 0.11.0 for the referral-report read, on the same terms: a
    colonoscopy is recorded as a referral report on this instance's own native
    protocol, so looking only at `Procedure` reported screened patients as
    overdue. One more source, read once for the whole batch.

    And 6 -> 7 in 0.18.0 for the attestation read, which is what a staff member
    marking a screening complete or not applicable from the record app writes.
    Same terms again: one query for the whole batch, filtered on the patients
    in it and the screenings they are eligible for.

    **If this fails, fix the query rather than raising the number.** Raising it
    is only ever right alongside a new read that is itself batched, and the
    batching is what the other two budget tests below prove - both of them moved
    by exactly one at the same time, which is the evidence that the new read is
    per-run and not per-patient.
    """
    make_imaging(woman_of_50, "24606-6", date(2024, 1, 1))
    make_procedure(woman_of_50, "44388", date(2019, 8, 1))
    make_lab(woman_of_50, "10524-7", date(2024, 6, 1))

    sources = [
        ("mammography", "imaging_report"),
        ("colonoscopy", "procedure"),
        ("pap_test", "lab_result"),
    ]
    screenings = [
        mammogram(
            name=f"S{index}",
            sex="any",
            completions=[{"value_set_key": key, "source": source, "codes": [], "label": "",
                          "interval_quantity": 2, "interval_unit": "years"}],
        )
        for index in range(12)
        for key, source in [sources[index % 3]]
    ]

    # 1 patient + 4 sources (colonoscopy is read from referrals too) + 1 snooze
    # + 1 attestation. load_config is monkeypatched; in production it adds one,
    # for 8 per run.
    with django_assert_num_queries(7):
        effects = review(woman_of_50, screenings).effects

    assert len(effects) == 12


@pytest.mark.django_db
def test_a_patient_eligible_for_nothing_costs_one_query( django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """A man in a practice tracking only women's screenings never reaches the
    chart at all.

    **Still one query after the attestation read was added**, and that is the
    point of the number: nobody in this batch is eligible for anything, so
    there is no screening an attestation could change an answer for, and the
    read is skipped rather than issued and discarded.
    """
    man = PatientFactory.create(birth_date=BORN, sex_at_birth="M", deceased=False)

    with django_assert_num_queries(1):
        effects = review(man, [mammogram(), mammogram(name="Cervical")]).effects

    assert [payload(effect)["status"] for effect in effects] == [
        "not_applicable",
        "not_applicable",
    ]


@pytest.mark.django_db
def test_screenings_sharing_a_source_do_not_multiply_queries(
    woman_of_50: Patient,
    make_imaging: MakeImaging,
    django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """Twenty screenings that all read the same value set still cost one query
    per source and one snooze query - not twenty of either.

    Mammography spans two sources since 2026-09-22 (imaging and procedure), so
    this is 4 rather than 3, and 5 with the attestation read. The number tracks
    sources; the guarantee is that it never tracks screenings."""
    make_imaging(woman_of_50, "24606-6", date(2024, 1, 1))
    screenings = [mammogram(name=f"S{index}") for index in range(20)]

    # 1 patient + imaging + procedure + 1 snooze + 1 attestation
    with django_assert_num_queries(5):
        effects = review(woman_of_50, screenings).effects

    assert len(effects) == 20


# --- the card key ------------------------------------------------------------


@pytest.mark.django_db
def test_each_screening_gets_its_own_stable_card_key(
    woman_of_50: Patient
) -> None:
    """Keys must be distinct per screening and stable across chart opens, or
    cards overwrite each other or stack up."""
    screenings = [mammogram(name="A"), mammogram(name="B", sex="any")]

    first = review(woman_of_50, screenings).effects
    second = review(woman_of_50, screenings).effects

    keys = [json.loads(effect.payload)["key"] for effect in first]
    assert len(set(keys)) == 2
    assert keys == [json.loads(effect.payload)["key"] for effect in second]


@pytest.mark.django_db
def test_the_card_names_the_patient_it_is_for(
    woman_of_50: Patient
) -> None:
    effects = review(woman_of_50, [mammogram()]).effects

    assert json.loads(effects[0].payload)["patient"] == str(woman_of_50.id)




@pytest.mark.django_db
def test_the_review_says_when_to_look_again(woman_of_50: Patient) -> None:
    """The next-review date is what makes a card change as time passes: nothing
    recomputes on chart open, so without it an overdue card would freeze."""
    outcome = review(woman_of_50, [mammogram()])

    assert outcome.next_review is not None
    assert outcome.next_review > date.today()


@pytest.mark.django_db
def test_a_patient_nothing_can_change_for_is_never_rescheduled(
    make_imaging: MakeImaging, woman_of_50: Patient
) -> None:
    """A patient past the upper age has nothing time can alter, so scheduling
    another look at them would be pure waste at panel scale."""
    aged_out = PatientFactory.create(
        birth_date=date(1940, 1, 1), sex_at_birth="F", deceased=False
    )

    assert review(aged_out, [mammogram()]).next_review is None


@pytest.mark.parametrize(
    ("patient_id", "screenings"),
    [("", [1]), ("abc", []), ("", [])],
)
def test_nothing_to_do_costs_no_queries(
    patient_id: str, screenings: list, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """Both triggers call this, and the sweep calls it in a loop, so the
    do-nothing path must not reach the database at all."""
    with django_assert_num_queries(0):
        outcome = review_patient(patient_id, screenings, date.today())

    assert outcome.effects == []
    assert outcome.next_review is None


# --- retracting a screening the practice stopped tracking --------------------


@pytest.mark.django_db
def test_a_retired_screening_gets_its_card_overwritten(woman_of_50: Patient) -> None:
    """There is no effect that deletes a protocol card - only ADD_OR_UPDATE - so
    a screening switched off would otherwise leave its last state, very possibly
    OVERDUE, on every chart it ever reached."""
    effects = review_patient(
        str(woman_of_50.id), [mammogram()], date.today(), ["old-screening"]
    ).effects

    retraction = [e for e in effects if json.loads(e.payload)["key"].endswith("old-screening")]
    assert len(retraction) == 1
    assert payload(retraction[0])["status"] == "not_applicable"


@pytest.mark.django_db
def test_a_retraction_uses_the_same_key_the_original_card_had(
    woman_of_50: Patient,
) -> None:
    """A different key would add a second card instead of replacing the first."""
    rule = mammogram()
    original = review(woman_of_50, [rule]).effects[0]

    retraction = review_patient(
        str(woman_of_50.id), [], date.today(), [rule["id"]]
    ).effects[0]

    assert json.loads(retraction.payload)["key"] == json.loads(original.payload)["key"]


@pytest.mark.django_db
def test_a_retraction_still_happens_for_a_patient_who_gets_no_cards(
    woman_of_50: Patient,
) -> None:
    """A deceased patient is asserted nothing about, but a retraction asserts
    nothing - it only takes back what was already written to their chart."""
    dead = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=True)

    effects = review_patient(str(dead.id), [mammogram()], date.today(), ["old"]).effects

    assert len(effects) == 1
    assert payload(effects[0])["status"] == "not_applicable"


@pytest.mark.django_db
def test_nothing_enabled_but_something_retired_still_does_the_retraction(
    woman_of_50: Patient,
) -> None:
    """Switching off the last screening is exactly when retraction matters."""
    effects = review_patient(str(woman_of_50.id), [], date.today(), ["old"]).effects

    assert len(effects) == 1


# --- the batch query budget --------------------------------------------------


@pytest.mark.django_db
def test_a_batch_of_patients_costs_the_same_as_one_patient(
    make_imaging: MakeImaging,
    make_procedure: MakeProcedure,
    make_lab: MakeLab,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Thirty patients cost the same six queries one patient costs.

    This is what makes the sweep's BATCH a free parameter. Reviewing patients
    one at a time cost a patient read plus a read per source *each*, so a
    50-patient run ran up to 300 queries - and nothing caught it, because every
    other budget test in this file reviews a single patient.

    Both reads added since are inside this guarantee, and the proof each time is
    that this number and the single-patient one moved together, by exactly one:
    4 -> 5 for the snooze read in 0.7.0, 5 -> 6 for the referral-report read in
    0.11.0. A number that moved here *without* moving there would mean a
    per-patient read had crept back in.

    **If this fails, fix the query rather than raising the number.**
    """
    people = [
        PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
        for _ in range(30)
    ]
    for person in people:
        make_imaging(person, "24606-6", date(2024, 1, 1))
        make_procedure(person, "44388", date(2019, 8, 1))
        make_lab(person, "10524-7", date(2024, 6, 1))

    sources = [
        ("mammography", "imaging_report"),
        ("colonoscopy", "procedure"),
        ("pap_test", "lab_result"),
    ]
    screenings = [
        mammogram(
            name=f"S{index}",
            sex="any",
            completions=[{"value_set_key": key, "source": source, "codes": [], "label": "",
                          "interval_quantity": 2, "interval_unit": "years"}],
        )
        for index in range(12)
        for key, source in [sources[index % 3]]
    ]

    # 1 patient read + 4 source reads + 1 snooze read + 1 attestation read, for
    # all thirty together. This moved 6 -> 7 at the same time as the
    # single-patient guard above, by exactly one, which is the evidence the
    # attestation read is per-run and not per-patient.
    with django_assert_num_queries(7):
        reviews = review_patients(
            [str(person.id) for person in people], screenings, date.today()
        )

    assert len(reviews) == 30
    assert all(len(review.effects) == 12 for review in reviews.values())


@pytest.mark.django_db
def test_every_id_asked_about_gets_an_answer(woman_of_50: Patient) -> None:
    """The sweep records a result for every key it took, so a missing entry
    would raise mid-run and cost the whole batch."""
    missing = "00000000-0000-4000-8000-000000000000"

    reviews = review_patients([str(woman_of_50.id), missing, ""], [mammogram()], date.today())

    assert set(reviews) == {str(woman_of_50.id), missing, ""}
    assert reviews[missing].effects == []
    assert reviews[""].effects == []


@pytest.mark.django_db
def test_one_patients_history_does_not_leak_into_another(
    make_imaging: MakeImaging,
) -> None:
    """The risk the batching introduces: a shared read must still answer
    per patient, or a woman with no mammogram is told she has had one."""
    had_one = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    had_none = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    make_imaging(had_one, "24606-6", date.today())

    reviews = review_patients(
        [str(had_one.id), str(had_none.id)], [mammogram()], date.today()
    )

    assert payload(reviews[str(had_one.id)].effects[0])["status"] == "satisfied"
    assert payload(reviews[str(had_none.id)].effects[0])["status"] == "due"


@pytest.mark.django_db
def test_an_unassessable_patient_does_not_stop_the_others(
    make_imaging: MakeImaging,
) -> None:
    """A deceased patient in the batch must not cost the living ones their cards."""
    dead = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=True)
    alive = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    make_imaging(alive, "24606-6", date.today())

    reviews = review_patients([str(dead.id), str(alive.id)], [mammogram()], date.today())

    assert reviews[str(dead.id)].effects == []
    assert payload(reviews[str(alive.id)].effects[0])["status"] == "satisfied"


# --- a snoozed screening, end to end -----------------------------------------


@pytest.mark.django_db
def test_a_snoozed_screening_gets_the_quiet_title(
    woman_of_50: Patient, make_snooze: MakeSnooze
) -> None:
    """The whole point, joined up: a provider snoozes our overdue card, and the
    next time we write it the stub reads "Snoozed" instead of shouting."""
    rule = mammogram(name="Mammogram")
    make_snooze(woman_of_50, card_key(rule), date(2026, 12, 1))

    effects = review(woman_of_50, [rule], today=date(2026, 9, 20)).effects

    assert payload(effects[0])["title"] == "Mammogram — Snoozed"


@pytest.mark.django_db
def test_an_unsnoozed_screening_still_shouts(woman_of_50: Patient) -> None:
    """The control for the test above - without the snooze, nothing is quiet."""
    effects = review(woman_of_50, [mammogram(name="Mammogram")], today=date(2026, 9, 20)).effects

    assert "OVERDUE" in payload(effects[0])["title"]


@pytest.mark.django_db
def test_a_snooze_on_one_screening_does_not_quiet_another(
    woman_of_50: Patient, make_snooze: MakeSnooze
) -> None:
    """Snoozes are matched per card key. Snoozing the mammogram must not silence
    the colorectal card sitting beside it."""
    snoozed = mammogram(name="Mammogram", id="s1")
    other = mammogram(name="Cervical", id="s2")
    make_snooze(woman_of_50, card_key(snoozed), date(2026, 12, 1))

    effects = review(woman_of_50, [snoozed, other], today=date(2026, 9, 20)).effects
    titles = {payload(effect)["title"] for effect in effects}

    assert "Mammogram — Snoozed" in titles
    assert any(title.startswith("Cervical") and "OVERDUE" in title for title in titles)


@pytest.mark.django_db
def test_the_review_is_scheduled_for_the_day_the_snooze_ends(
    woman_of_50: Patient, make_snooze: MakeSnooze
) -> None:
    """Without this the card would read "Snoozed" indefinitely: no event fires
    when a snooze expires, so the sweep has to be told when to look."""
    rule = mammogram(name="Mammogram")
    make_snooze(woman_of_50, card_key(rule), date(2026, 12, 1))

    outcome = review(woman_of_50, [rule], today=date(2026, 9, 20))

    assert outcome.next_review == date(2026, 12, 2)


@pytest.mark.django_db
def test_an_expired_snooze_lets_the_card_shout_again(
    woman_of_50: Patient, make_snooze: MakeSnooze
) -> None:
    """Nothing clears the snooze; it just stops being returned once its date has
    passed, and the card comes back on its own."""
    rule = mammogram(name="Mammogram")
    make_snooze(woman_of_50, card_key(rule), date(2026, 9, 19))

    effects = review(woman_of_50, [rule], today=date(2026, 9, 20)).effects

    assert "OVERDUE" in payload(effects[0])["title"]


# --- what a staff member said -------------------------------------------------
#
# The end-to-end half of the attestation feature: a statement stored by the
# record app, read back here, and changing the card the provider sees. The
# merge rules themselves are tested exhaustively in test_screenings.py; these
# are about the statement actually reaching the card.


def attest(patient: Patient, screening_id: str, **over: Any) -> None:
    fields: dict[str, Any] = {
        "patient_key": str(patient.id),
        "screening_id": screening_id,
        "kind": "completed",
        "effective_date": date.today(),
        "interval_quantity": 2,
        "interval_unit": "years",
        "label": "",
        "recorded_by": "staff-1",
        "recorded_at": date.today(),
    }
    fields.update(over)
    ScreeningAttestation.objects.create(**fields)


@pytest.mark.django_db(transaction=True)
def test_marking_a_screening_complete_clears_its_overdue_card(
    attestation_table: None,
) -> None:
    """The case the feature exists for. The mammogram happened somewhere this
    plugin cannot read, and the card was shouting OVERDUE at the provider who
    knew that perfectly well."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    rule = mammogram(id="s1")
    attest(woman, "s1")

    data = payload(review(woman, [rule]).effects[0])

    assert data["status"] == "satisfied"
    assert data["title"] == "Mammogram"


@pytest.mark.django_db(transaction=True)
def test_the_card_says_the_completion_was_a_statement_not_a_result(
    attestation_table: None,
) -> None:
    """A provider reading "last completed" has to be able to tell a result in
    the chart from a colleague's statement that one exists somewhere else. The
    two carry different weight when deciding whether to re-screen."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    attest(woman, "s1", effective_date=date(2026, 3, 4))

    data = payload(review(woman, [mammogram(id="s1")]).effects[0])

    assert "Marked complete 4 Mar 2026 by staff." in data["narrative"]
    assert "Last completed" not in data["narrative"]


@pytest.mark.django_db(transaction=True)
def test_marking_a_screening_not_applicable_takes_its_card_off_the_chart(
    attestation_table: None,
) -> None:
    """Canvas renders no NOT_APPLICABLE card at all, so this is what makes the
    card disappear rather than merely change."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    attest(woman, "s1", kind="not_applicable")

    data = payload(review(woman, [mammogram(id="s1")]).effects[0])

    assert data["status"] == "not_applicable"
    assert "Marked not applicable to this patient by staff." in data["narrative"]


@pytest.mark.django_db(transaction=True)
def test_a_not_applicable_statement_is_carried_on_the_row_so_it_can_be_undone(
    attestation_table: None,
) -> None:
    """Nothing in the plugin can retract this on its own - no chart change
    makes a person's "does not apply" untrue - so the record app has to be able
    to show it and offer to take it back."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    attest(woman, "s1", kind="not_applicable")

    row = review(woman, [mammogram(id="s1")]).rows[0]

    assert row.status is None
    assert row.attestation is not None
    assert row.attestation.not_applicable is True


@pytest.mark.django_db(transaction=True)
def test_the_rule_beats_a_statement_about_a_patient_it_never_applied_to(
    attestation_table: None,
) -> None:
    """A man marked complete for a women's screening is still not eligible for
    it. Letting a statement grant eligibility would be the brief's highest
    stakes failure - a screening shown to a patient it does not apply to -
    reached from the other direction."""
    man = PatientFactory.create(birth_date=BORN, sex_at_birth="M", deceased=False)
    attest(man, "s1")

    row = review(man, [mammogram(id="s1")]).rows[0]

    assert row.status is None
    assert row.attestation is None


@pytest.mark.django_db(transaction=True)
def test_a_real_result_beats_a_statement_on_the_card_too(
    attestation_table: None, make_imaging: MakeImaging
) -> None:
    """Merged, never substituted - end to end. The imaging report is better
    evidence and the card has to say so."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    make_imaging(woman, "24606-6", date.today())
    attest(woman, "s1", effective_date=date(2020, 1, 1))

    data = payload(review(woman, [mammogram(id="s1")]).effects[0])

    assert "Last completed" in data["narrative"]
    assert "Marked complete" not in data["narrative"]


@pytest.mark.django_db(transaction=True)
def test_one_patients_statement_does_not_clear_anothers_card(
    attestation_table: None,
) -> None:
    """The batched read is what makes this worth a test. A shared query that
    attributed rows wrongly would mark the wrong patient's screening done -
    silently, and the cards look identical either way."""
    marked = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    other = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    attest(marked, "s1")

    reviews = review_patients(
        [str(marked.id), str(other.id)], [mammogram(id="s1")], date.today()
    )

    assert payload(reviews[str(marked.id)].effects[0])["status"] == "satisfied"
    assert payload(reviews[str(other.id)].effects[0])["status"] == "due"


# --- a screening that is carded and retired at once ---------------------------


@pytest.mark.django_db
def test_a_carded_screening_is_never_retracted_in_the_same_run(
    woman_of_50: Patient,
) -> None:
    """**The 0.18.0 bug, from the side a provider saw it.**

    Retractions are written after the cards and under the same key, so a
    screening in both lists overwrote its own card: the chart went blank while
    the editor said the card was on, and the record panel went on saying the
    patient was due.

    `sweep_store.retire` keeps the lists disjoint now, so this should be
    unreachable. It is enforced here too because the failure is invisible - the
    card is computed correctly, returned, and quietly undone a few list entries
    later - and because an instance whose stored state predates that fix heals
    on the next review rather than waiting out the 90-day expiry.
    """
    rule = mammogram(id="s1")

    effects = review_patients(
        [str(woman_of_50.id)], [rule], date.today(), ["s1"]
    )[str(woman_of_50.id)].effects

    assert len(effects) == 1
    assert payload(effects[0])["status"] == "due"
    assert "no longer shows" not in payload(effects[0])["narrative"]


@pytest.mark.django_db
def test_a_screening_that_is_only_retired_is_still_retracted(
    woman_of_50: Patient,
) -> None:
    """The guard above must not swallow a real retraction - that would strand
    the card it exists to take back."""
    effects = review_patients(
        [str(woman_of_50.id)], [mammogram(id="s1")], date.today(), ["s2"]
    )[str(woman_of_50.id)].effects

    narratives = [payload(effect)["narrative"] for effect in effects]
    assert any("no longer shows" in narrative for narrative in narratives)


@pytest.mark.django_db
def test_an_unassessable_patient_is_not_retracted_for_a_carded_screening(
    woman_of_50: Patient,
) -> None:
    """The same conflict reaches the other branch - a patient with no birth
    date or a deceased one gets retractions and nothing else."""
    dead = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=True)

    effects = review_patients(
        [str(dead.id)], [mammogram(id="s1")], date.today(), ["s1"]
    )[str(dead.id)].effects

    assert effects == []
