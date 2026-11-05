"""Tests for the chart-change trigger.

What a patient's cards say is tested in tests/services/test_review.py. What is
tested here is the half that is new and easy to get silently wrong: which
events fire this handler, and how the patient is found from the record that
changed.

Both halves fail quietly rather than loudly. A missing event means a screening
never updates for that kind of result, and a patient resolved as None means the
handler returns nothing at all - neither raises, and neither shows up anywhere
except as a card that is stale forever. So the event list is pinned against the
model map, and every entry in that map is exercised against the real database.
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import NoteFactory, PatientFactory
from canvas_sdk.v1.data import Command, Patient

from preventive_screenings.handlers import event_handlers
from preventive_screenings.handlers.event_handlers import (
    _PATIENT_EVENTS,
    _TARGET_MODELS,
    PreventiveScreeningCards,
)
from preventive_screenings.services.config_store import new_screening

MODULE = "preventive_screenings.handlers.event_handlers"

MakeImaging = Callable[..., Any]
MakeProcedure = Callable[..., Any]
MakeLab = Callable[..., Any]
MakeCondition = Callable[..., Any]
MakeReferral = Callable[..., Any]
MakeInterview = Callable[..., Any]

BORN = date(1976, 6, 15)


def mammogram(**over: Any) -> dict:
    """An enabled, carded mammogram screening: women 40-74, every 2 years."""
    fields: dict[str, Any] = {
        "enabled": True,
        # This handler writes protocol cards and nothing else, so a screening
        # without a card is one it has no work for. Carded explicitly here so
        # the tests below are about the chart events, not about the toggle -
        # `test_a_screening_without_a_card_is_not_this_handlers_work` is the
        # one that covers the toggle.
        "protocol_card": True,
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


def handler(
    event_name: str,
    target_id: Any,
    screenings: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> PreventiveScreeningCards:
    event = Mock()
    event.name = event_name
    event.target.id = target_id
    monkeypatch.setattr(event_handlers, "load_config", lambda: {"screenings": screenings})
    return PreventiveScreeningCards(event=event)


@pytest.fixture
def woman_of_50() -> Patient:
    return PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)


# --- which events fire this at all -------------------------------------------


def test_every_event_is_either_a_patient_event_or_has_a_model() -> None:
    """An event that is neither resolves to no patient and silently does
    nothing, which looks exactly like a screening that never comes due."""
    for name in PreventiveScreeningCards.RESPONDS_TO:
        assert name in _PATIENT_EVENTS or name in _TARGET_MODELS, name


def test_the_model_map_names_no_event_the_handler_ignores() -> None:
    """Dead entries in the map are a sign an event was renamed or dropped."""
    for name in _TARGET_MODELS:
        assert name in PreventiveScreeningCards.RESPONDS_TO, name


def test_every_kind_of_record_a_screening_reads_has_a_trigger() -> None:
    """The six sources in services.completion are what a screening can be
    satisfied or excluded by. **A source with no event never updates a card**,
    and the brief requires that a screening stop showing as due once it has
    actually been done.

    ⛔ This test used to assert that `NOTE_CLOSED` covered procedures. It does
    not - signing a note does not emit it, proved on the instance 2026-09-20
    when three signed colonoscopies produced zero handler invocations and the
    cards stayed OVERDUE. The wrong assertion is what let the gap ship, so the
    real trigger is named here explicitly.
    """
    triggers = " ".join(PreventiveScreeningCards.RESPONDS_TO)

    assert "IMAGING_REPORT_CREATED" in triggers
    assert "LAB_REPORT_CREATED" in triggers
    assert "INTERVIEW_CREATED" in triggers
    assert "CONDITION_CREATED" in triggers
    assert "REFERRAL_REPORT_CREATED" in triggers
    assert "PERFORM_COMMAND__POST_COMMIT" in triggers, (
        "there is no PROCEDURE_CREATED event; a committed Perform is the only "
        "way a procedure reaches this plugin"
    )


def test_a_procedure_undone_is_as_urgent_as_one_recorded() -> None:
    """Staleness runs both ways. A colonoscopy entered by mistake must stop
    satisfying the screening as promptly as a real one starts satisfying it,
    or the card stays quiet for up to MAX_REVIEW_GAP_DAYS on a patient who is
    genuinely overdue."""
    triggers = " ".join(PreventiveScreeningCards.RESPONDS_TO)

    assert "PERFORM_COMMAND__POST_ENTER_IN_ERROR" in triggers
    assert "PERFORM_COMMAND__POST_DELETE" in triggers


def test_a_snooze_retriggers_the_cards_on_both_of_its_events() -> None:
    """Snoozing is a command in a note and takes two clicks: one stages it, one
    records it. The ProtocolOverride row exists from the first click but is
    `status='inactive'` until the second, and `snoozed_until` will not honour an
    inactive override - correctly, since the provider has not recorded it yet.

    CREATED fires on the staging, so it can only ever see the inactive row.
    UPDATED fires on the commit, and is the only event that can see an active
    snooze. Subscribing to CREATED alone - which this plugin briefly did, having
    misread the burst of UPDATEs as a feedback loop - means the quiet title can
    never appear.

    Both were also dropped entirely at one point, which left the feature with no
    trigger at all. **If the updates ever do start looping, add a change guard
    to this handler; do not drop the subscription, because that takes the
    feature with it.**
    """
    for event in ("PROTOCOL_OVERRIDE_CREATED", "PROTOCOL_OVERRIDE_UPDATED"):
        assert EventType.Name(getattr(EventType, event)) in (
            PreventiveScreeningCards.RESPONDS_TO
        )


def test_the_chart_summary_event_is_gone() -> None:
    """It is the event that silently discarded every card (proved on the
    instance 2026-09-19). Reinstating it would waste a computation per chart
    open and render nothing."""
    assert EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION) not in (
        PreventiveScreeningCards.RESPONDS_TO
    )


def test_the_manifest_points_at_this_handler(manifest: dict[str, Any]) -> None:
    classes = [handler["class"] for handler in manifest["components"]["handlers"]]

    assert "preventive_screenings.handlers.event_handlers:PreventiveScreeningCards" in classes


# --- finding the patient from the record that changed ------------------------


@pytest.mark.django_db
def test_a_patient_event_targets_the_patient_directly(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = handler("PATIENT_UPDATED", str(woman_of_50.id), [mammogram()], monkeypatch)

    assert instance._patient_id() == str(woman_of_50.id)


@pytest.mark.django_db
def test_an_imaging_report_resolves_to_its_patient(
    woman_of_50: Patient, make_imaging: MakeImaging, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The event targets the report, not the patient."""
    report = make_imaging(woman_of_50, "24606-6", date(2024, 1, 1))
    instance = handler("IMAGING_REPORT_CREATED", str(report.id), [mammogram()], monkeypatch)

    assert instance._patient_id() == str(woman_of_50.id)


@pytest.mark.django_db
def test_a_referral_report_resolves_to_its_patient(
    woman_of_50: Patient, make_referral: MakeReferral, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Added with the referral source: we read referral reports now, so one
    arriving has to be able to move a card."""
    report = make_referral(woman_of_50, "44388", date(2024, 1, 1))
    instance = handler("REFERRAL_REPORT_CREATED", str(report.id), [mammogram()], monkeypatch)

    assert instance._patient_id() == str(woman_of_50.id)


@pytest.mark.django_db
def test_a_committed_perform_resolves_to_its_patient(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command event targets the **command**, not a chart record.

    This is the trigger that closes the 90-day staleness gap, so it has to
    resolve a patient or the whole subscription is decorative.
    """
    note = NoteFactory.create(patient=woman_of_50)
    command = Command.objects.create(
        patient=woman_of_50, note=note, state="committed", schema_key="perform", data={}, origination_source="", anchor_object_type="", anchor_object_dbid=0
    )
    instance = handler(
        "PERFORM_COMMAND__POST_COMMIT", str(command.id), [mammogram()], monkeypatch
    )

    assert instance._patient_id() == str(woman_of_50.id)


@pytest.mark.django_db
def test_a_perform_without_its_own_patient_falls_back_to_the_note(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Command.patient` is nullable. The note it was written in always has
    one, and both columns come back in the same query."""
    note = NoteFactory.create(patient=woman_of_50)
    command = Command.objects.create(
        patient=None, note=note, state="committed", schema_key="perform", data={}, origination_source="", anchor_object_type="", anchor_object_dbid=0
    )
    instance = handler(
        "PERFORM_COMMAND__POST_COMMIT", str(command.id), [mammogram()], monkeypatch
    )

    assert instance._patient_id() == str(woman_of_50.id)


@pytest.mark.django_db
def test_a_target_with_no_patient_anywhere_resolves_to_nothing(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every column came back empty. No patient means no cards, which is the
    right answer - writing cards for a patient we cannot name would assert
    something we do not know."""
    note = NoteFactory.create(patient=None)
    command = Command.objects.create(
        patient=None, note=note, state="committed", schema_key="perform", data={}, origination_source="", anchor_object_type="", anchor_object_dbid=0
    )
    instance = handler(
        "PERFORM_COMMAND__POST_COMMIT", str(command.id), [mammogram()], monkeypatch
    )

    assert instance._patient_id() is None
    assert instance.compute() == []


@pytest.mark.django_db
def test_a_condition_resolves_to_its_patient(
    woman_of_50: Patient, make_condition: MakeCondition, monkeypatch: pytest.MonkeyPatch
) -> None:
    condition = make_condition(woman_of_50, "428529004", date(2020, 2, 2))
    instance = handler("CONDITION_CREATED", str(condition.id), [mammogram()], monkeypatch)

    assert instance._patient_id() == str(woman_of_50.id)


@pytest.mark.django_db
def test_resolving_a_patient_costs_one_query_and_hydrates_nothing(
    woman_of_50: Patient,
    make_imaging: MakeImaging,
    django_assert_num_queries: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading one id must not drag the whole target row along. A closed Note
    carries its entire body, and this runs on every matching chart change.
    """
    report = make_imaging(woman_of_50, "24606-6", date(2024, 1, 1))
    instance = handler("IMAGING_REPORT_CREATED", str(report.id), [mammogram()], monkeypatch)

    with django_assert_num_queries(1):
        instance._patient_id()


@pytest.mark.django_db
def test_a_record_that_no_longer_exists_resolves_to_nothing(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deleted record must not raise on a hot path."""
    instance = handler(
        "IMAGING_REPORT_CREATED", "00000000000000000000000000000000",
        [mammogram()], monkeypatch,
    )

    assert instance._patient_id() is None
    assert instance.compute() == []


@pytest.mark.django_db
def test_an_unrecognised_event_resolves_to_nothing(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt and braces: if an event ever reaches this without a mapping, it must
    do nothing rather than guess at a patient."""
    instance = handler("SOMETHING_ELSE_CREATED", "abc", [mammogram()], monkeypatch)

    assert instance._patient_id() is None


@pytest.mark.django_db
def test_no_target_id_does_nothing(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = handler("PATIENT_UPDATED", "", [mammogram()], monkeypatch)

    assert instance._patient_id() is None
    assert instance.compute() == []


# --- what the handler does with what it finds --------------------------------


@pytest.mark.django_db
def test_a_chart_change_rewrites_the_patients_cards(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    effects = handler(
        "PATIENT_UPDATED", str(woman_of_50.id), [mammogram()], monkeypatch
    ).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.ADD_OR_UPDATE_PROTOCOL_CARD
    assert json.loads(effects[0].payload)["patient"] == str(woman_of_50.id)


@pytest.mark.django_db
def test_no_configured_screenings_costs_no_queries(
    woman_of_50: Patient, django_assert_num_queries: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A practice that has enabled nothing must not pay for the patient lookup
    on every chart change in the building."""
    instance = handler("PATIENT_UPDATED", str(woman_of_50.id), [], monkeypatch)

    with django_assert_num_queries(0):
        assert instance.compute() == []


@pytest.mark.django_db
def test_a_disabled_screening_produces_no_card(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = handler(
        "PATIENT_UPDATED", str(woman_of_50.id), [mammogram(enabled=False)], monkeypatch
    )

    assert instance.compute() == []


@pytest.mark.django_db
def test_a_screening_without_a_card_is_not_this_handlers_work(
    woman_of_50: Patient, django_assert_num_queries: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This handler writes protocol cards and nothing else. A tracked screening
    with its card switched off has nothing here to rewrite, and the record app
    computes it live on open, so the chart change costs nothing at all.

    Retraction is deliberately not this handler's job - `handlers.sweep` owns
    it, because it needs the memory of what was being carded before.
    """
    instance = handler(
        "PATIENT_UPDATED", str(woman_of_50.id), [mammogram(protocol_card=False)], monkeypatch
    )

    with django_assert_num_queries(0):
        assert instance.compute() == []


@pytest.mark.django_db
def test_an_unknown_patient_gets_no_cards(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = handler(
        "PATIENT_UPDATED", "00000000000000000000000000000000", [mammogram()], monkeypatch
    )

    assert instance.compute() == []


@pytest.mark.django_db
def test_now_is_read_in_utc(woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch) -> None:
    """django.utils is blocked in the plugin sandbox, so the handler uses
    datetime.now(UTC). This keeps that true."""
    assert datetime.now(UTC).tzinfo is UTC

    instance = handler("PATIENT_UPDATED", str(woman_of_50.id), [mammogram()], monkeypatch)
    with patch(f"{MODULE}.review_patient") as review:
        review.return_value.effects = []
        instance.compute()

    assert review.call_args.args[2] == datetime.now(UTC).date()


# --- writing nothing when nothing changed ------------------------------------


@pytest.mark.django_db
def test_an_unchanged_patient_is_not_rewritten(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The guard on the write amplification.** Several events routinely fire
    for one user action - a single snooze produces a PROTOCOL_OVERRIDE_CREATED
    and about four _UPDATEDs - and without this each one rewrote every card for
    that patient, twelve writes to change nothing.

    Patched by name, never as a module object: the sandbox refuses attribute
    access on an imported module at run time, so patching `event_handlers.X`
    would test a shape that cannot run in production.
    """
    instance = handler("PATIENT_UPDATED", str(woman_of_50.id), [mammogram()], monkeypatch)

    # What the cards fingerprint to on the first pass...
    monkeypatch.setattr(event_handlers, "load_reviews", lambda keys: {})
    recorded: list = []
    monkeypatch.setattr(
        event_handlers, "record_all", lambda entries, stored, today: recorded.append(entries)
    )
    first = instance.compute()

    assert first, "the first pass must write the cards"
    mark = recorded[0][0][2]

    # ...is what the stored row already says on the second.
    row = SimpleNamespace(fingerprint=mark)
    monkeypatch.setattr(event_handlers, "load_reviews", lambda keys: {str(woman_of_50.id): row})
    recorded.clear()

    assert instance.compute() == [], "identical cards must not be rewritten"
    assert recorded == [], "and nothing should be recorded either"


@pytest.mark.django_db
def test_a_changed_patient_is_rewritten_and_recorded(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stored fingerprint from a different set of cards must not suppress the
    write - that would strand the old cards on the chart permanently."""
    instance = handler("PATIENT_UPDATED", str(woman_of_50.id), [mammogram()], monkeypatch)
    row = SimpleNamespace(fingerprint="something-else-entirely")
    monkeypatch.setattr(event_handlers, "load_reviews", lambda keys: {str(woman_of_50.id): row})
    recorded: list = []
    monkeypatch.setattr(
        event_handlers, "record_all", lambda entries, stored, today: recorded.append(entries)
    )

    effects = instance.compute()

    assert effects, "changed cards must be written"
    assert len(recorded) == 1, "and the new fingerprint recorded"


@pytest.mark.django_db
def test_a_chart_change_keeps_the_next_review_fresh(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Until the guard existed only the sweep wrote ScreeningReview, so a chart
    change left the stored prediction stale until the sweep next reached that
    patient - and the sweep would then revisit on a date computed from cards
    that had since been replaced."""
    instance = handler("PATIENT_UPDATED", str(woman_of_50.id), [mammogram()], monkeypatch)
    monkeypatch.setattr(event_handlers, "load_reviews", lambda keys: {})
    recorded: list = []
    monkeypatch.setattr(
        event_handlers, "record_all", lambda entries, stored, today: recorded.append(entries)
    )

    instance.compute()

    (patient_key, next_review, _mark) = recorded[0][0]
    assert patient_key == str(woman_of_50.id)
    assert next_review > date.today(), "clamped to at least tomorrow"
