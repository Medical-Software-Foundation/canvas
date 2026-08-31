"""Reads the state of a task the plugin has already raised.

Everywhere else in this plugin nothing is read back, an effect is fired once
because its identifier makes a second attempt collide rather than duplicate.
This is the one deliberate relaxation of that rule. A task is itself the
record of what has already fired, so asking Canvas what state it is in costs
nothing new, there is no extra storage anywhere and no second source of truth
to keep in step with the first.

Both questions here are the contract the composition root validates. status_of
is the one that decides whether a task is created at all. title_of is read only
when a caller already has an open task and wants to know whether a fresh title
actually differs from what is stored before writing it again. Both share one
lookup so asking the second costs no more than asking the first.
"""

from uuid import UUID

from canvas_sdk.v1.data.task import Task


class CanvasTaskReader:
    """Answers what state, if any, a derived task identifier currently names."""

    def _task(self, task_id: UUID) -> Task | None:
        """The stored task at this identifier, or nothing."""
        return Task.objects.filter(id=task_id).first()

    def status_of(self, task_id: UUID) -> str | None:
        """The stored status of the task with this identifier, or nothing.

        Nothing means no task has ever been created at this identifier, which
        is exactly the case where the caller should go on to create one.
        """
        task = self._task(task_id)
        if task is None:
            return None
        return f"{task.status}"

    def title_of(self, task_id: UUID) -> str | None:
        """The stored title of the task with this identifier, or nothing.

        Nothing means the same as it does above, no task at this identifier.
        A caller only ever asks this after status_of has already answered
        that a task exists and is still open, the one moment it matters
        whether a fresh title actually changes anything worth writing.
        """
        task = self._task(task_id)
        if task is None:
            return None
        return f"{task.title}"
