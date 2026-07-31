"""Behavior tests for the VisitConfirmed appointment-event connector.

These build a real ``canvas_sdk.events.Event`` from an ``EventRequest`` and pass
it through ``BaseHandler.__init__``, so the handler is exercised against the
SDK's actual contract rather than a hand-rolled stand-in. Only the two external
boundaries are patched: ``Http`` (outbound HTTP) and the ``Appointment``
queryset (the database).

The behavior locked in here is what the Canvas review criteria care about:
fail-closed on missing configuration, retracted appointments excluded, related
objects fetched in one query, an IDs-only payload with no PII, reschedule
detection, and no payload contents in logs.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType

from visit_confirmed.handlers import appointment_events
from visit_confirmed.handlers.appointment_events import AppointmentEvents

API_URL = "https://api.example.test/canvas/events"
API_KEY = "vc-test-key"
CONFIGURED = {"VISIT_CONFIRMED_API_URL": API_URL, "VISIT_CONFIRMED_API_KEY": API_KEY}


def make_handler(secrets, target, event_type):
    """Build an AppointmentEvents handler the way the plugin runner does."""
    event = Event(
        EventRequest(type=event_type, target=target, target_type="Appointment")
    )
    return AppointmentEvents(event, secrets)


def make_appointment(appointment_id, *, patient_id="pat-1", provider_id="prov-1",
                     rescheduled_from=None):
    return SimpleNamespace(
        id=appointment_id,
        patient=SimpleNamespace(id=patient_id) if patient_id else None,
        provider=SimpleNamespace(id=provider_id) if provider_id else None,
        start_time="2026-07-01T15:00:00+00:00",
        duration_minutes=30,
        appointment_rescheduled_from=(
            SimpleNamespace(id=rescheduled_from) if rescheduled_from else None
        ),
    )


@contextmanager
def boundaries(appointment=None, *, get_raises=None, ok=True, status_code=200):
    """Patch the two external boundaries: outbound HTTP and the Appointment query.

    The handler calls ``Appointment.objects.select_related(...).get(...)``, so the
    patch has to sit on ``select_related`` rather than on ``get``.
    """
    with patch.object(appointment_events, "Http") as http_cls, \
            patch.object(
                appointment_events.Appointment.objects, "select_related"
            ) as select_related:
        if get_raises is not None:
            select_related.return_value.get.side_effect = get_raises
        else:
            select_related.return_value.get.return_value = appointment
        http_cls.return_value.post.return_value = MagicMock(
            ok=ok, status_code=status_code
        )
        yield http_cls, select_related


def sent_payload(http_cls):
    _, kwargs = http_cls.return_value.post.call_args
    return kwargs


class AppointmentEventsTests(TestCase):
    def test_fails_closed_when_configuration_missing(self):
        handler = make_handler({}, "appt-1", EventType.APPOINTMENT_CREATED)
        with boundaries(make_appointment("appt-1")) as (http_cls, _):
            result = handler.compute()
        self.assertEqual(result, [])
        http_cls.assert_not_called()  # no outbound call without configuration

    def test_posts_ids_only_payload_with_bearer_auth(self):
        handler = make_handler(CONFIGURED, "appt-1", EventType.APPOINTMENT_CREATED)
        with boundaries(make_appointment("appt-1")) as (http_cls, _):
            handler.compute()

        kwargs = sent_payload(http_cls)
        self.assertEqual(kwargs["headers"], {"Authorization": f"Bearer {API_KEY}"})
        appointment = kwargs["json"]["appointment"]
        # IDs and scheduling metadata only: assert no PII keys leak in.
        self.assertEqual(set(appointment), {"id", "patient_id", "provider_id",
                                            "start_time", "duration_minutes"})
        self.assertEqual(kwargs["json"]["event_type"], "appointment_created")

    def test_reschedule_is_detected_from_linked_appointment(self):
        handler = make_handler(CONFIGURED, "appt-2", EventType.APPOINTMENT_CREATED)
        with boundaries(
            make_appointment("appt-2", rescheduled_from="appt-1")
        ) as (http_cls, _):
            handler.compute()

        kwargs = sent_payload(http_cls)
        self.assertEqual(kwargs["json"]["event_type"], "appointment_rescheduled")
        self.assertEqual(kwargs["json"]["appointment"]["rescheduled_from_id"], "appt-1")

    def test_cancellation_is_reported_as_its_own_event(self):
        handler = make_handler(CONFIGURED, "appt-3", EventType.APPOINTMENT_CANCELED)
        with boundaries(make_appointment("appt-3")) as (http_cls, _):
            handler.compute()

        self.assertEqual(sent_payload(http_cls)["json"]["event_type"],
                         "appointment_canceled")

    def test_missing_appointment_is_swallowed_quietly(self):
        handler = make_handler(CONFIGURED, "missing", EventType.APPOINTMENT_NO_SHOWED)
        with boundaries(
            get_raises=appointment_events.Appointment.DoesNotExist
        ) as (http_cls, _):
            result = handler.compute()
        self.assertEqual(result, [])
        http_cls.return_value.post.assert_not_called()

    def test_query_excludes_retracted_appointments(self):
        """A retracted appointment must never trigger patient outreach."""
        handler = make_handler(CONFIGURED, "appt-5", EventType.APPOINTMENT_CREATED)
        with boundaries(make_appointment("appt-5")) as (_, select_related):
            handler.compute()

        _, kwargs = select_related.return_value.get.call_args
        self.assertEqual(kwargs["id"], "appt-5")
        self.assertTrue(kwargs["entered_in_error__isnull"])
        # Related objects come back in the same query, not one apiece.
        self.assertEqual(select_related.call_args[0], ("patient", "provider"))

    def test_appointment_without_start_time_is_skipped(self):
        """arrow.get(None) raises TypeError, so a missing start time short-circuits."""
        handler = make_handler(CONFIGURED, "appt-6", EventType.APPOINTMENT_CREATED)
        appointment = make_appointment("appt-6")
        appointment.start_time = None
        with boundaries(appointment) as (http_cls, _):
            result = handler.compute()
        self.assertEqual(result, [])
        http_cls.return_value.post.assert_not_called()

    def test_failed_delivery_does_not_raise(self):
        handler = make_handler(CONFIGURED, "appt-4", EventType.APPOINTMENT_NO_SHOWED)
        with boundaries(make_appointment("appt-4"), ok=False, status_code=502):
            result = handler.compute()
        self.assertEqual(result, [])
