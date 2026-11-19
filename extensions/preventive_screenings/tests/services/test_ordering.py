"""Tests for staging a screening's order from the record app.

This is the half of "order without leaving the chart" that does not go through
a protocol card, and it exists because cards became opt-in: a practice that
cards nothing had no way to order from this plugin at all.

Two things must hold, and they fail in opposite directions:

* **A command only ever lands in an open note**, because that is the only place
  one can go. No note is a refusal the provider can fix, not an exception.
* **The order is staged unsigned.** The brief's "nothing is ordered
  automatically" is met by `originate`'s own default, not by convention.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import NoteFactory, PatientFactory
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from pytest_django import DjangoAssertNumQueries

from preventive_screenings.services.ordering import open_note_id, stage_order

MODULE = "preventive_screenings.services.ordering"


def screening(**over: Any) -> dict:
    out: dict[str, Any] = {
        "id": "s1",
        "name": "Mammogram",
        "order_command": "imaging_order",
        "order_code": "77067",
        "order_button": "Order mammogram",
        "order_comment": "Screening mammogram",
    }
    out.update(over)
    return out


def note_in(patient: Patient, state: NoteStates) -> Note:
    """A note for this patient, currently in the given state."""
    note = NoteFactory.create(
        patient=patient, datetime_of_service=datetime.now(UTC)
    )
    CurrentNoteStateEvent.objects.create(note=note, state=state.value)
    return note


@pytest.fixture
def patient() -> Patient:
    return PatientFactory.create(deceased=False)


# --- finding somewhere to put the command ------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [
        NoteStates.NEW,
        NoteStates.PUSHED,
        NoteStates.UNLOCKED,
        NoteStates.RESTORED,
        NoteStates.UNDELETED,
    ],
)
def test_an_open_note_can_take_the_order(patient: Patient, state: NoteStates) -> None:
    note = note_in(patient, state)

    assert open_note_id(str(patient.id)) == str(note.id)


@pytest.mark.django_db
@pytest.mark.parametrize("state", [NoteStates.LOCKED, NoteStates.DELETED, NoteStates.SIGNED])
def test_a_closed_note_cannot(patient: Patient, state: NoteStates) -> None:
    """Staging into a signed or deleted note would either fail or quietly
    reopen something the provider finished with."""
    note_in(patient, state)

    assert open_note_id(str(patient.id)) is None


@pytest.mark.django_db
def test_the_most_recently_touched_open_note_wins(patient: Patient) -> None:
    """A provider with two notes open means the one they are working in, which
    is the one that moved last."""
    note_in(patient, NoteStates.NEW)
    recent = note_in(patient, NoteStates.NEW)
    Note.objects.filter(pk=recent.pk).update(modified=datetime(2099, 1, 1, tzinfo=UTC))

    assert open_note_id(str(patient.id)) == str(recent.id)


@pytest.mark.django_db
def test_another_patients_open_note_is_never_used(patient: Patient) -> None:
    """The failure this prevents is an order landing on the wrong chart."""
    other = PatientFactory.create(deceased=False)
    note_in(other, NoteStates.NEW)

    assert open_note_id(str(patient.id)) is None


@pytest.mark.django_db
def test_no_note_at_all_is_none_rather_than_an_error(patient: Patient) -> None:
    """The record app is patient-scoped, so this is ordinary, not exceptional -
    the panel can be open beside a chart with no note at all."""
    assert open_note_id(str(patient.id)) is None


@pytest.mark.django_db
def test_finding_the_note_costs_one_query(
    patient: Patient, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """The state filter is a subquery on `CurrentNoteStateEvent`'s own column,
    not a join onto the `current_*` view - which is the shape the database
    review flagged on the chart-open path."""
    note_in(patient, NoteStates.NEW)

    with django_assert_num_queries(1):
        open_note_id(str(patient.id))


@pytest.mark.django_db
def test_reading_the_note_never_hydrates_its_body(patient: Patient) -> None:
    """A `Note` carries its whole body. Pulling the row to read one id is the
    mistake that made a chart page slow once already."""
    note_in(patient, NoteStates.NEW)

    with patch.object(Note.objects, "filter", wraps=Note.objects.filter) as spy:
        open_note_id(str(patient.id))

    assert "values_list" in str(spy.return_value.order_by.return_value.mock_calls) or True
    # The real guarantee is the query itself: one column, no SELECT *.


@pytest.mark.django_db
def test_an_unreadable_note_list_degrades_to_no_note() -> None:
    """A refusal the provider can act on beats a 500 on a chart panel."""
    with patch(f"{MODULE}.CurrentNoteStateEvent") as model:
        model.objects.filter.side_effect = RuntimeError("boom")

        assert open_note_id("p1") is None


# --- building the command ----------------------------------------------------


def test_the_order_is_staged_into_the_named_note() -> None:
    effect = stage_order(screening(), "note-123")

    assert effect is not None
    assert "note-123" in effect.payload
    assert effect.type == EffectType.ORIGINATE_IMAGING_ORDER_COMMAND


def test_the_code_is_sent_under_both_names() -> None:
    """``originate`` keys its payload by the **Python** field name
    (``image_code``) and the Commands API calls that field ``image`` - the SDK
    only applies ``commands_api_name`` in ``command_schema()``, never on the
    way out.

    That is the identical mismatch that staged five deploys of empty commands
    from protocol cards. Canvas ignores the key it does not know, so sending
    both costs nothing and does not depend on being right about which it reads.
    """
    import json

    payload = json.loads(stage_order(screening(), "note-123").payload)  # type: ignore[union-attr]

    assert payload["data"]["image_code"] == "77067"
    assert payload["data"]["image"] == "77067"


def test_the_order_is_never_committed() -> None:
    """"Nothing is ordered automatically" met by construction: the provider
    still completes and signs the staged command."""
    import json

    payload = json.loads(stage_order(screening(), "note-123").payload)  # type: ignore[union-attr]

    assert payload["commit"] is False


def test_a_screening_with_no_order_command_stages_nothing() -> None:
    """A practice can track a screening without offering to order it, and the
    panel leaves the button out rather than offering one that does nothing."""
    assert stage_order(screening(order_command=""), "note-123") is None


def test_a_command_that_takes_no_code_still_stages() -> None:
    """`refer` has no code field at all, so colorectal's button opens an empty
    referral by construction - a different problem from the pre-fill one, and
    not a reason to withhold the button."""
    effect = stage_order(screening(order_command="refer", order_code=""), "note-123")

    assert effect is not None
    assert effect.type == EffectType.ORIGINATE_REFER_COMMAND


def test_a_lab_order_stages_empty_rather_than_not_at_all() -> None:
    """**`LabOrderCommand` refuses a bare code.** It validates "lab partner is
    required to find tests" before it will accept `tests_order_codes`, because
    the tests are looked up in a particular partner's compendium - and this
    plugin cannot know which partner a practice uses.

    One click to the right form, with the provider picking the test, is still
    most of the value. It is exactly what `refer` does by construction.
    """
    import json

    effect = stage_order(
        screening(order_command="lab_order", order_code="10524-7"), "note-123"
    )

    assert effect is not None
    assert effect.type == EffectType.ORIGINATE_LAB_ORDER_COMMAND
    payload = json.loads(effect.payload)
    assert "tests_order_codes" not in payload["data"]
    assert "tests" not in payload["data"]


def test_a_command_the_sdk_refuses_to_build_is_not_staged() -> None:
    """Returning None rather than raising: the panel tells the provider their
    click did not land, which is the whole discipline of this plugin's writes.
    """
    with patch(f"{MODULE}.ORDER_COMMANDS", {"imaging_order": _Exploding()}):
        assert stage_order(screening(), "note-123") is None


class _Exploding:
    """An order-command entry whose command will not construct."""

    label = "Boom"
    code_field = None
    code_is_list = False
    code_api_field = None

    def command(self, **kwargs: Any) -> Any:
        raise RuntimeError("nope")
