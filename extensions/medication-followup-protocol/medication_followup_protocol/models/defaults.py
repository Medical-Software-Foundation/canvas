"""The practice wide starting point for a new medication class.

Almost every class a practice builds sends as the same role account and is owned by the
same team, so choosing both on every class is asking the same question repeatedly. This
holds the answer once, for the whole practice, and a new class starts from it.

It is a starting point rather than a live default. A class keeps its own sender and its own
owning team, and the walk reads them off the class when a step fires. Changing what is
stored here never reaches a class that already exists, which is the property that makes it
safe to update whenever somebody makes a choice.
"""

from __future__ import annotations

from django.db.models import CharField, DateTimeField

from canvas_sdk.v1.data.base import CustomModel


class ProgramDefaults(CustomModel):
    """One row for the whole practice, holding what a new class starts from."""

    created = DateTimeField(auto_now_add=True)
    modified = DateTimeField(auto_now=True)

    sender_staff_id = CharField(max_length=64, default="", blank=True)
    owner_team_id = CharField(max_length=64, default="", blank=True)

    def __str__(self) -> str:
        return "the practice defaults for a new medication class"


def current_defaults() -> ProgramDefaults:
    """The one row, created empty on first read.

    The row is found by taking the oldest rather than by a unique key, because a unique
    constraint on a constant is ceremony and two rows racing into existence would still
    leave every reader agreeing on which one counts.
    """
    existing = ProgramDefaults.objects.order_by("dbid").first()
    if existing is not None:
        return existing
    return ProgramDefaults.objects.create()
