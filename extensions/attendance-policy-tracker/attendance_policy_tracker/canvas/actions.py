"""The effects the plugin emits.

Two tasks and one tag, which is everything the plugin ever creates. Nothing here
decides policy, it is handed a decision and turns it into an effect.

A task fires once and then follows its own state rather than the plugin
remembering anything. Each task is created with an identifier derived from
the patient and the line it belongs to, so the same evaluation always names
the same row, and asking the task reader what that row currently holds is
what tells this class whether to create, to update, or to do nothing at all.
That survives an uninstall and reinstall, because the task rows outlive the
plugin while any storage the plugin kept would not.
"""

from hashlib import sha256
from typing import Any
from uuid import UUID

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import AddAppointmentLabel
from canvas_sdk.effects.task import AddTask, TaskPriority, UpdateTask

from attendance_policy_tracker.core.engine import DISCHARGE_REVIEW, WARNING

# What each task says. Deliberately plain, because a task is read by whoever
# picks it up and it should make sense without any context about the plugin.
TITLES = {
    WARNING: "Attendance policy, patient has reached the warning threshold",
    DISCHARGE_REVIEW: "Attendance policy, patient has reached the review threshold",
}

# Canvas offers three priorities, stat, urgent and routine. A warning is
# ordinary desk work so it goes in as routine, while a discharge review asks
# somebody to make a decision about a patient's care and is raised as urgent.
# There is no middle priority to reach for.
PRIORITIES = {
    WARNING: TaskPriority.ROUTINE,
    DISCHARGE_REVIEW: TaskPriority.URGENT,
}


def task_id_for(patient_id: str, line: str) -> UUID:
    """A stable identifier for one patient's task at one line.

    Derived rather than random, so the same patient at the same line always
    produces the same identifier. That is what makes creating the task twice
    impossible without the plugin storing a record of what it has already done.
    """
    digest = sha256(f"attendance-policy-tracker:{patient_id}:{line}".encode()).hexdigest()
    return UUID(digest[:32])


# A task in either of these stored states was a decision somebody already
# made, by finishing the work or by dismissing it, and raising it again would
# relitigate that decision rather than respect it.
SETTLED_STATUSES = ("COMPLETED", "CLOSED")


class CanvasActions:
    """Turns decisions into Canvas effects."""

    def __init__(self, config: Any, task_reader: Any) -> None:
        self._config = config
        self._task_reader = task_reader

    def task_for(self, patient_id: str, line: str, count: int) -> Effect | None:
        """The task for one patient reaching one line, or nothing.

        Nothing when no team is configured to receive it, because a task nobody
        owns sits in a list forever and is worse than no task at all. The
        configuration surface is where that gets fixed, not here. The team guard
        runs first, before the task reader is even consulted, so a line nobody
        owns is refused before anything is read.

        Otherwise the derived identifier is read before it is written. No task
        there yet means this is the first time the line has been crossed, so a
        task is created exactly as before. A settled task means somebody has
        already finished or dismissed it, so nothing is emitted. Anything else
        is an open task from an earlier evaluation, and it is updated in place
        with a fresh title, but only when that title actually differs from
        what is already stored. A patient sitting at an unchanged count earns
        no write at all, so a run that finds nothing new leaves the task
        exactly as somebody last saw it rather than writing the same title
        again on every tick that happens to recompute them.
        """
        team_id = self._config.team_for(line)
        if not team_id:
            return None
        title = TITLES.get(line)
        if title is None:
            return None

        task_id = task_id_for(patient_id, line)
        fresh_title = f"{title}, {count} counted visits in the counting window"
        status = self._task_reader.status_of(task_id)

        if status is None:
            return AddTask(
                id=task_id,
                patient_id=patient_id,
                team_id=team_id,
                title=fresh_title,
                priority=PRIORITIES.get(line, TaskPriority.ROUTINE),
                labels=self._config.labels_for(line),
            ).apply()

        if status in SETTLED_STATUSES:
            return None

        # Asked only here, because this is the one branch that can write a
        # title, and a title identical to the stored one is a write worth
        # nothing. Without this the sweep reissues the same update on every
        # tick a patient stays inside its lookback window.
        if self._task_reader.title_of(task_id) == fresh_title:
            return None

        return UpdateTask(id=f"{task_id}", title=fresh_title).apply()

    def tasks_for(self, total: Any) -> list[Effect]:
        """Every task a total has earned.

        Both lines are raised when a total clears both at once, rather than only
        the higher one, so a patient who arrived at the review line in a single
        step does not skip the warning silently.
        """
        effects = []
        for line in total.lines_reached:
            effect = self.task_for(total.patient_id, line, total.count)
            if effect is not None:
                effects.append(effect)
        return effects

    def tag_as_clinic(self, appointment_id: str) -> Effect:
        """Mark one cancellation as the clinic's.

        The label is created by the platform if the instance does not have it yet,
        and labels are named rather than identified here, which is the opposite of
        the reschedule path where raw identifiers are required.
        """
        return AddAppointmentLabel(
            appointment_id=appointment_id,
            labels={self._config.clinic_tag},
        ).apply()

    def tag_runs(self, runs: list[dict[str, Any]]) -> list[Effect]:
        """Tag every cancellation in every run as the clinic's."""
        effects = []
        for run in runs:
            for history in run.get("appointments") or []:
                if self._config.clinic_tag in history.labels:
                    continue
                effects.append(self.tag_as_clinic(history.appointment_id))
        return effects
