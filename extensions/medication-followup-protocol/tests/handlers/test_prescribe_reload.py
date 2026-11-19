"""Pushing a header reload when a prescribe command commits.

Without this the note header control would stay exactly as it was when the note mounted.
An action button set is asked for once, on mount, and after that only reacts to a pushed
reload, so a provider committing a prescription would see no control until they reloaded
the page themselves, which is a long way from what the feedback asked for.
"""

import json

from tests.conftest import make, make_event


def payload(effect):
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


def _command(note=None, patient=None):
    """A committed prescribe command, optionally attached to a note."""
    from canvas_sdk.v1.data import Command

    return make(
        Command,
        note=note,
        patient=patient,
        schema_key="prescribe",
        state="committed",
        data={},
    )


def test_committing_a_prescribe_command_reloads_that_note(patient):
    """Covers scenario: AC22, committing a prescribe command reloads the note's action buttons. Covers criterion: AC22."""
    from canvas_sdk.test_utils.factories import NoteFactory
    from medication_followup_protocol.handlers.prescribe_reload import PrescribeCommandReload

    note = NoteFactory(patient=patient)
    command = _command(note=note, patient=patient)

    effects = PrescribeCommandReload(make_event("PRESCRIBE_COMMAND__POST_COMMIT", target=str(command.id))).compute()

    assert len(effects) == 1


def test_the_reload_names_the_notes_own_external_id(patient):
    """Covers scenario: AC22, committing a prescribe command reloads the note's action buttons. Covers criterion: AC22.

    The note's external id rather than its database id. The show event's own context
    carries the database id instead, so the two are easy to interchange and doing so would
    reload nothing while raising nothing either.
    """
    from canvas_sdk.test_utils.factories import NoteFactory
    from medication_followup_protocol.handlers.prescribe_reload import PrescribeCommandReload

    note = NoteFactory(patient=patient)
    command = _command(note=note, patient=patient)

    effects = PrescribeCommandReload(make_event("PRESCRIBE_COMMAND__POST_COMMIT", target=str(command.id))).compute()

    # The effect delegates to the platform reload, whose payload names the note as note_id.
    assert payload(effects[0])["note_id"] == str(note.id)


def test_a_command_that_does_not_resolve_emits_nothing(patient):
    """Covers criterion: AC22.

    A target naming no command emits nothing rather than raising. This handler runs on
    every prescribe commit on the instance, so raising here would surface as a plugin
    error on an ordinary clinical action.
    """
    import uuid

    from medication_followup_protocol.handlers.prescribe_reload import PrescribeCommandReload

    event = make_event("PRESCRIBE_COMMAND__POST_COMMIT", target=str(uuid.uuid4()))

    assert PrescribeCommandReload(event).compute() == []
