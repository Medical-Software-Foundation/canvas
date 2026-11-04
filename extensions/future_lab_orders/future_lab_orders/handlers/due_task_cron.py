"""Daily job: create a staff task for each future lab order that is due.

It never places or sends the lab order. A person opens the task and orders
the lab in a note, which needs a provider signature.
"""

from collections import defaultdict
from datetime import UTC, date, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import PatientMetadata as PatientMetadataEffect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.patient import PatientMetadata
from canvas_sdk.v1.data.team import Team
from logger import log

from future_lab_orders.fields import (
    ALL_KEYS,
    DUE_DATE_KEY,
    LAB_KEY,
    TASKED_FOR_KEY,
    TESTS_KEY,
    parse_due_date,
    task_title,
)

TEAM_SETTING = "FUTURE_LAB_TASK_TEAM"
TASK_LABEL = "future lab order"

# Each task is two small effects. Capping the batch keeps one run far below
# the effect-batch size limit; anything left over is still due tomorrow.
MAX_TASKS_PER_RUN = 500


def due_orders(today: date) -> list[dict[str, str]]:
    """Return the future lab orders due on or before ``today`` with no task yet.

    Two queries total: the patients with a due date, then every future lab
    order key for those patients.
    """
    patient_ids = list(
        PatientMetadata.objects.filter(key=DUE_DATE_KEY, patient__active=True)
        .exclude(value="")
        .values_list("patient__id", flat=True)
    )
    if not patient_ids:
        return []

    values: dict[str, dict[str, str]] = defaultdict(dict)
    for patient_id, key, value in PatientMetadata.objects.filter(
        patient__id__in=patient_ids, key__in=ALL_KEYS
    ).values_list("patient__id", "key", "value"):
        values[str(patient_id)][key] = value or ""

    orders = []
    for patient_id, fields in values.items():
        raw_due = fields.get(DUE_DATE_KEY, "").strip()
        due = parse_due_date(raw_due)
        if due is None:
            if raw_due:
                log.warning(
                    f"future_lab_orders: unreadable due date for patient {patient_id}"
                )
            continue
        if due > today or fields.get(TASKED_FOR_KEY, "").strip() == raw_due:
            continue
        orders.append(
            {
                "patient_id": patient_id,
                "due_raw": raw_due,
                "lab": fields.get(LAB_KEY, ""),
                "tests": fields.get(TESTS_KEY, ""),
            }
        )
    orders.sort(
        key=lambda order: (
            parse_due_date(order["due_raw"]) or today,
            order["patient_id"],
        )
    )
    return orders


class FutureLabOrderDueTasks(CronTask):
    """Every day at 12:00 UTC, make a task due today for each due future lab order."""

    SCHEDULE = "0 12 * * *"

    def execute(self) -> list[Effect]:
        """Create the tasks and mark each order as tasked."""
        now = datetime.now(UTC)
        orders = due_orders(now.date())
        if len(orders) > MAX_TASKS_PER_RUN:
            log.warning(
                f"future_lab_orders: {len(orders)} orders due, creating {MAX_TASKS_PER_RUN} "
                "today and the rest on the next run"
            )
            orders = orders[:MAX_TASKS_PER_RUN]

        team_id = self._team_id()
        effects: list[Effect] = []
        for order in orders:
            effects.append(
                AddTask(
                    patient_id=order["patient_id"],
                    team_id=team_id,
                    title=task_title(order["lab"], order["tests"]),
                    due=now,
                    status=TaskStatus.OPEN,
                    labels=[TASK_LABEL],
                ).apply()
            )
            effects.append(
                PatientMetadataEffect(
                    patient_id=order["patient_id"], key=TASKED_FOR_KEY
                ).upsert(order["due_raw"])
            )
        if orders:
            log.info(f"future_lab_orders: created {len(orders)} task(s)")
        return effects

    def _team_id(self) -> str | None:
        name = (self.secrets.get(TEAM_SETTING) or "").strip()
        if not name:
            return None
        team_id = Team.objects.filter(name=name).values_list("id", flat=True).first()
        if team_id is None:
            log.warning(
                f"future_lab_orders: team {name!r} not found; tasks are unassigned"
            )
            return None
        return str(team_id)
