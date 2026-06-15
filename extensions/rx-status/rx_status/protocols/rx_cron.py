import json
import uuid

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data.prescription import Prescription

from logger import log


CACHE_RULES_KEY = "rx_status_notification_rules"
CACHE_FIRED_KEY = "rx_status_fired_notifications"
CACHE_STATUS_TIMESTAMPS_KEY = "rx_status_status_timestamps"

FIRED_CACHE_RETENTION_DAYS = 30


class RxNotificationCron(CronTask):
    """Hourly cron to check duration-based notification rules."""

    SCHEDULE = "0 * * * *"

    def execute(self) -> list[Effect]:
        cache = get_cache()

        self._prune_fired_cache(cache)

        rules = self._get_rules(cache)
        duration_rules = [r for r in rules if r.get("duration_value", 0) > 0]
        if not duration_rules:
            return []

        timestamps = cache.get(CACHE_STATUS_TIMESTAMPS_KEY) or {}
        if isinstance(timestamps, str):
            timestamps = json.loads(timestamps)

        effects = []
        for rule in duration_rules:
            status = rule.get("status")
            duration_value = rule.get("duration_value", 0)
            duration_unit = rule.get("duration_unit", "h")

            if duration_unit == "h":
                threshold = arrow.utcnow().shift(hours=-duration_value)
            elif duration_unit == "d":
                threshold = arrow.utcnow().shift(days=-duration_value)
            else:
                continue

            prescriptions = (
                Prescription.objects.filter(status=status)
                .select_related("patient")
            )

            for rx in prescriptions:
                if not rx.patient:
                    continue

                rx_id = str(rx.id)
                since = self._status_since(timestamps, rx_id, status, rx)
                if since is None or since > threshold:
                    continue

                if self._already_fired(cache, rx_id, rule):
                    continue

                task_effects = self._create_task(rule, str(rx.patient.id), rx_id)
                if task_effects:
                    effects.extend(task_effects)
                    self._mark_fired(cache, rx_id, rule)

        return effects

    def _status_since(self, timestamps, prescription_id, status, rx):
        entry = timestamps.get(prescription_id)
        if entry and entry.get("status") == status:
            try:
                return arrow.get(entry["since"])
            except (ValueError, KeyError):
                pass
        # Fallback for prescriptions that pre-date the status-timestamp cache
        if rx.modified:
            return arrow.get(rx.modified)
        return None

    def _prune_fired_cache(self, cache):
        fired = cache.get(CACHE_FIRED_KEY) or {}
        if isinstance(fired, str):
            fired = json.loads(fired)
        if not fired:
            return
        cutoff = arrow.utcnow().shift(days=-FIRED_CACHE_RETENTION_DAYS)
        pruned = {
            key: ts
            for key, ts in fired.items()
            if self._parse_iso(ts) and self._parse_iso(ts) >= cutoff
        }
        if len(pruned) != len(fired):
            cache.set(CACHE_FIRED_KEY, pruned)

    def _parse_iso(self, value):
        try:
            return arrow.get(value)
        except (ValueError, TypeError):
            return None

    # Duplicated across modules — Canvas sandbox blocks cross-module relative imports,
    # so helpers can't live in a shared module. Keep these in sync with rx_notifications.py.
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
                f"RxCron: Creating task for Rx {prescription_id} status={rule.get('status')} "
                f"after {rule.get('duration_value')}{rule.get('duration_unit')}"
            )
            effects = [add_task.apply()]

            note_link = self._get_note_link(prescription_id, patient_id)
            if note_link:
                comment = AddTaskComment(task_id=task_id, body=note_link)
                effects.append(comment.apply())

            return effects
        except Exception as e:
            log.error(f"RxCron: Failed to create task: {e}")
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
