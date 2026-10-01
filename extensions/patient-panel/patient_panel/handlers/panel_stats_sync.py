"""Event handlers that keep PatientPanelStats fresh.

Each handler resolves the affected patient and delegates to the recompute
service (direct ORM write — returns no effects). The nightly reconciliation
cron is the correctness backstop; these are the freshness optimization.

The shared logic lives in mixins that deliberately do NOT inherit BaseHandler,
so the plugin-runner's handler discovery never flags them as unregistered
handlers. Each concrete handler inherits a mixin AND BaseHandler.
"""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.events import Event, EventType
from canvas_sdk.handlers import BaseHandler
from logger import log

from patient_panel.services.stats_recompute import recompute_stats_for_patient_uuid


def _patient_uuid_from_context(event: Any) -> str | None:
    ctx = getattr(event, "context", None) or {}
    pid = ctx.get("patient_id")
    if pid:
        return str(pid)
    patient = ctx.get("patient")
    if isinstance(patient, dict):
        inner = patient.get("id")
        return str(inner) if inner else None
    return str(patient) if patient else None


class _PanelStatsMixin:
    """Shared recompute logic. NOT a BaseHandler subclass — so it is not
    discovered as a handler — concrete handlers inherit this AND BaseHandler.
    Subclasses set RESPONDS_TO; override `_patient_uuid` for events whose
    context does not carry the patient UUID."""

    event: Event  # supplied by BaseHandler at runtime

    def _patient_uuid(self) -> str | None:
        return _patient_uuid_from_context(self.event)

    def compute(self) -> list[Effect]:
        try:
            uuid = self._patient_uuid()
            if uuid:
                recompute_stats_for_patient_uuid(uuid)
        except Exception:
            log.exception("[panel_stats] recompute failed for %s", self.__class__.__name__)
        return []


class _PanelStatsPatientTargetMixin(_PanelStatsMixin):
    """For PATIENT_* events: the target id IS the patient UUID."""

    def _patient_uuid(self) -> str | None:
        return _patient_uuid_from_context(self.event) or getattr(self.event.target, "id", None)


class PanelStatsOnNoteCreated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.NOTE_CREATED)

class PanelStatsOnNoteUpdated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.NOTE_UPDATED)

class PanelStatsOnNoteStateCreated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

class PanelStatsOnNoteStateUpdated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_UPDATED)

class PanelStatsOnTaskCreated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.TASK_CREATED)

class PanelStatsOnTaskUpdated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.TASK_UPDATED)

class PanelStatsOnTaskClosed(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.TASK_CLOSED)

class PanelStatsOnTaskCompleted(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.TASK_COMPLETED)

class PanelStatsOnAddressCreated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_ADDRESS_CREATED)

class PanelStatsOnAddressUpdated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_ADDRESS_UPDATED)

class PanelStatsOnAddressDeleted(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_ADDRESS_DELETED)

class PanelStatsOnPatientCreated(_PanelStatsPatientTargetMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_CREATED)

class PanelStatsOnProtocolOverrideCreated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PROTOCOL_OVERRIDE_CREATED)

class PanelStatsOnProtocolOverrideUpdated(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PROTOCOL_OVERRIDE_UPDATED)

class PanelStatsOnProtocolOverrideDeleted(_PanelStatsMixin, BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PROTOCOL_OVERRIDE_DELETED)
