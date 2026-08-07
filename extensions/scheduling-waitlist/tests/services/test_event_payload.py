"""Reading an appointment identifier off an event.

Appointment events are known to carry the identifier on ``target`` with an empty
context. The context fallbacks exist because that is not guaranteed for every
appointment-shaped event, and a handler that raises on an unexpected payload
takes the whole event down with it.
"""

from unittest.mock import MagicMock

from scheduling_waitlist.services.event_payload import resolve_appointment_id


def event(target_id=None, context=None):
    record = MagicMock()
    record.target = MagicMock()
    record.target.id = target_id
    record.context = context
    return record


class TestTarget:
    def test_the_identifier_is_read_from_the_target(self):
        assert resolve_appointment_id(event(target_id="appt-key")) == "appt-key"

    def test_the_target_is_preferred_over_the_context(self):
        found = resolve_appointment_id(
            event(target_id="from-target", context={"appointment_id": "from-context"})
        )

        assert found == "from-target"

    def test_an_empty_target_identifier_is_not_used(self):
        assert resolve_appointment_id(event(target_id="", context={})) is None

    def test_a_non_string_target_identifier_is_not_used(self):
        assert resolve_appointment_id(event(target_id=1234, context={})) is None

    def test_an_event_with_no_target_at_all_is_tolerated(self):
        record = MagicMock()
        del record.target
        record.context = {}

        assert resolve_appointment_id(record) is None


class TestContextFallbacks:
    def test_a_nested_appointment_identifier_is_found(self):
        found = resolve_appointment_id(
            event(context={"appointment": {"id": "appt-key"}})
        )

        assert found == "appt-key"

    def test_a_flat_appointment_identifier_is_found(self):
        assert resolve_appointment_id(event(context={"appointment_id": "appt-key"})) == (
            "appt-key"
        )

    def test_an_empty_context_yields_nothing(self):
        assert resolve_appointment_id(event(context={})) is None

    def test_a_context_that_is_not_a_mapping_is_tolerated(self):
        # Appointment event fixtures ship an empty string here.
        assert resolve_appointment_id(event(context="")) is None

    def test_a_nested_appointment_that_is_not_a_mapping_is_tolerated(self):
        assert resolve_appointment_id(event(context={"appointment": "appt-key"})) is None

    def test_a_nested_appointment_without_an_identifier_is_tolerated(self):
        assert resolve_appointment_id(event(context={"appointment": {}})) is None

    def test_a_non_string_context_identifier_is_not_used(self):
        assert resolve_appointment_id(event(context={"appointment_id": 99})) is None

    def test_an_unrecognised_context_shape_yields_nothing_rather_than_raising(self):
        assert resolve_appointment_id(event(context={"something": "else"})) is None
