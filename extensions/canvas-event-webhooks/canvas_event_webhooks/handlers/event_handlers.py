"""
Canvas event-to-webhook handlers.

Each class below listens to a logical group of Canvas events and forwards
them to every enabled webhook that has that event selected. Handlers are
kept deliberately thin — all dispatch logic lives in
``WebhookDispatcherBase`` (``base.py``). ``RESPONDS_TO`` lists come from
``events_catalog.py`` so the UI, the handlers, and the docs stay in sync.
"""

from __future__ import annotations

from canvas_event_webhooks.events_catalog import event_type_names
from canvas_event_webhooks.handlers.base import WebhookDispatcherBase


class PatientWebhookHandler(WebhookDispatcherBase):
    """Forwards patient-record events to matching webhooks."""

    RESPONDS_TO = event_type_names("patients")

    def compute(self):
        return self._dispatch()


class AppointmentWebhookHandler(WebhookDispatcherBase):
    """Forwards appointment lifecycle events to matching webhooks."""

    RESPONDS_TO = event_type_names("appointments")

    def compute(self):
        return self._dispatch()


class NoteWebhookHandler(WebhookDispatcherBase):
    """Forwards note, note-state, and encounter events to matching webhooks."""

    RESPONDS_TO = event_type_names("notes")

    def compute(self):
        return self._dispatch()


class ClinicalWebhookHandler(WebhookDispatcherBase):
    """Forwards clinical-record events to matching webhooks."""

    RESPONDS_TO = event_type_names("clinical")

    def compute(self):
        return self._dispatch()


class MedicationWebhookHandler(WebhookDispatcherBase):
    """Forwards medication-list events to matching webhooks."""

    RESPONDS_TO = event_type_names("medications")

    def compute(self):
        return self._dispatch()


class PrescriptionWebhookHandler(WebhookDispatcherBase):
    """Forwards the e-prescribing lifecycle to matching webhooks."""

    RESPONDS_TO = event_type_names("prescriptions")

    def compute(self):
        return self._dispatch()


class LabWebhookHandler(WebhookDispatcherBase):
    """Forwards lab, imaging, and referral-report events to matching webhooks."""

    RESPONDS_TO = event_type_names("labs")

    def compute(self):
        return self._dispatch()


class TaskWebhookHandler(WebhookDispatcherBase):
    """Forwards task lifecycle events to matching webhooks."""

    RESPONDS_TO = event_type_names("tasks")

    def compute(self):
        return self._dispatch()


class StaffWebhookHandler(WebhookDispatcherBase):
    """Forwards staff created/updated/activated/deactivated events."""

    RESPONDS_TO = event_type_names("staff")

    def compute(self):
        return self._dispatch()


class DocumentWebhookHandler(WebhookDispatcherBase):
    """Forwards inbound document lifecycle events to matching webhooks."""

    RESPONDS_TO = event_type_names("documents")

    def compute(self):
        return self._dispatch()


class MessageWebhookHandler(WebhookDispatcherBase):
    """Forwards patient–provider message and letter events."""

    RESPONDS_TO = event_type_names("messages")

    def compute(self):
        return self._dispatch()


class CareTeamWebhookHandler(WebhookDispatcherBase):
    """Forwards care-team and patient-group membership events."""

    RESPONDS_TO = event_type_names("care_teams")

    def compute(self):
        return self._dispatch()


class BillingWebhookHandler(WebhookDispatcherBase):
    """Forwards billing, claim, coverage, and consent events."""

    RESPONDS_TO = event_type_names("billing")

    def compute(self):
        return self._dispatch()
