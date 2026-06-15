import json
import uuid

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data.prescription import Prescription

from logger import log


EVENT_STATUS_MAP = {
    EventType.Name(EventType.PRESCRIPTION_OPENED): "open",
    EventType.Name(EventType.PRESCRIPTION_PENDING): "pending",
    EventType.Name(EventType.PRESCRIPTION_ACCEPTED): "ultimately-accepted",
    EventType.Name(EventType.PRESCRIPTION_ERRORED): "error",
    EventType.Name(EventType.PRESCRIPTION_CANCEL_REQUESTED): "cancel-requested",
    EventType.Name(EventType.PRESCRIPTION_CANCELED): "canceled",
    EventType.Name(EventType.PRESCRIPTION_CANCEL_DENIED): "cancel-denied",
    EventType.Name(EventType.PRESCRIPTION_RECEIVED): "received",
    EventType.Name(EventType.PRESCRIPTION_SIGNED): "signed",
    EventType.Name(EventType.PRESCRIPTION_INQUEUE): "inqueue",
    EventType.Name(EventType.PRESCRIPTION_TRANSMITTED): "transmitted",
    EventType.Name(EventType.PRESCRIPTION_DELIVERED): "delivered",
}

CACHE_RULES_KEY = "rx_status_notification_rules"
CACHE_FIRED_KEY = "rx_status_fired_notifications"
CACHE_STATUS_TIMESTAMPS_KEY = "rx_status_status_timestamps"


class RxNotificationProtocol(BaseProtocol):
    """Responds to prescription status events and creates tasks for immediate notification rules."""

    RESPONDS_TO = list(EVENT_STATUS_MAP.keys())

    def compute(self) -> list[Effect]:
        event_name = EventType.Name(self.event.type)
        status = EVENT_STATUS_MAP.get(event_name)
        if not status:
            log.warning(f"RxNotification: No status mapping for event {event_name}")
            return []

        prescription_id = self.event.target.id
        patient_id = self.event.context.get("patient", {}).get("id")

        log.info(
            f"RxNotification: event={event_name} status={status} rx={prescription_id} patient={patient_id}"
        )

        if not patient_id:
            try:
                rx = Prescription.objects.select_related("patient").get(
                    id=prescription_id
                )
                if rx.patient:
                    patient_id = str(rx.patient.id)
            except Prescription.DoesNotExist:
                log.error(f"RxNotification: Prescription {prescription_id} not found")
                return []

        if not patient_id:
            log.error(
                f"RxNotification: Could not determine patient_id for Rx {prescription_id}"
            )
            return []

        cache = get_cache()

        self._record_status_timestamp(cache, prescription_id, status)

        rules = self._get_rules(cache)
        if not rules:
            return []

        effects = []
        for rule in rules:
            if rule.get("status") != status:
                continue
            if rule.get("duration_value", 0) > 0:
                continue
            if self._already_fired(cache, prescription_id, rule):
                continue

            task_effects = self._create_task(rule, patient_id, prescription_id)
            if task_effects:
                effects.extend(task_effects)
                self._mark_fired(cache, prescription_id, rule)

        return effects

    def _record_status_timestamp(self, cache, prescription_id, status):
        timestamps = cache.get(CACHE_STATUS_TIMESTAMPS_KEY) or {}
        if isinstance(timestamps, str):
            timestamps = json.loads(timestamps)
        existing = timestamps.get(prescription_id)
        if existing and existing.get("status") == status:
            return
        entry = {"status": status, "since": arrow.utcnow().isoformat()}
        timestamps = {**timestamps, prescription_id: entry}
        cache.set(CACHE_STATUS_TIMESTAMPS_KEY, timestamps)

    # Duplicated across modules — Canvas sandbox blocks cross-module relative imports,
    # so helpers can't live in a shared module. Keep these in sync with rx_cron.py.
    def _get_rules(self, cache):
        raw = cache.get(CACHE_RULES_KEY)
        if not raw:
            return []
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    def _already_fired(self, cache, prescription_id, rule):
        fired = cache.get(CACHE_FIRED_KEY) or {}
        if isinstance(fired, str):
            fired = json.loads(fired)
        key = f"{prescription_id}_{rule.get('id', '')}"
        return key in fired

    def _mark_fired(self, cache, prescription_id, rule):
        fired = cache.get(CACHE_FIRED_KEY) or {}
        if isinstance(fired, str):
            fired = json.loads(fired)
        key = f"{prescription_id}_{rule.get('id', '')}"
        fired = {**fired, key: arrow.utcnow().isoformat()}
        cache.set(CACHE_FIRED_KEY, fired)

    def _create_task(self, rule, patient_id, prescription_id):
        try:
            task_id = str(uuid.uuid4())

            task_kwargs = {
                "id": task_id,
                "patient_id": patient_id,
                "title": rule.get(
                    "task_title", f"Rx status alert: {rule.get('status')}"
                ),
                "status": TaskStatus.OPEN,
                "due": arrow.utcnow().shift(days=1).datetime,
            }

            assignee_type = rule.get("assignee_type")
            assignee_id = rule.get("assignee_id")
            if assignee_type == "staff" and assignee_id:
                task_kwargs["assignee_id"] = assignee_id
            elif assignee_type == "team" and assignee_id:
                task_kwargs["team_id"] = assignee_id

            label = rule.get("label")
            if label:
                task_kwargs["labels"] = [label]

            add_task = AddTask(**task_kwargs)
            log.info(
                f"RxNotification: Creating task for Rx {prescription_id} status={rule.get('status')}"
            )
            effects = [add_task.apply()]

            note_link = self._get_note_link(prescription_id, patient_id)
            if note_link:
                comment = AddTaskComment(task_id=task_id, body=note_link)
                effects.append(comment.apply())

            return effects
        except Exception as e:
            log.error(f"RxNotification: Failed to create task: {e}")
            return None

    def _get_note_link(self, prescription_id, patient_id):
        try:
            rx = Prescription.objects.select_related("note").get(id=prescription_id)
            if rx.note:
                note_dbid = rx.note.dbid
                base_url = self.secrets.get("INSTANCE_BASE_URL", "").rstrip("/")
                return f"{base_url}/patient/{patient_id}/note/{note_dbid}"
        except Prescription.DoesNotExist:
            pass
        return None
