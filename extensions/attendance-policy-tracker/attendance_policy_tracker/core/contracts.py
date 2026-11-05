"""The small contracts the engine depends on.

The engine knows three things and nothing else. What an incident is, how to ask
a detector whether a transition produced one, and how to ask the attribution
chain who an incident counts against. It never names a concrete detector or a
concrete rule, so adding either is a new file plus one line in the composition
root.

Contracts here are structural rather than compiled. In a dynamic language that
is all an interface can be, so each one is stated as the set of methods a
collaborator must carry, and the composition root validates that they are
present rather than the language guaranteeing it.
"""

import datetime
from typing import Any

# Who an incident counts against. These two strings are the whole vocabulary,
# because the design deliberately has no third answer such as pending or
# unknown, every total is a definite number.
PATIENT = "patient"
CLINIC = "clinic"

ATTRIBUTIONS = (PATIENT, CLINIC)


class Incident:
    """One countable event against one appointment.

    Anchored to the appointment's start time rather than to the moment the state
    changed, because every window in the policy is expressed relative to the
    visit, the counting window, the lateness gap and the run window alike.
    """

    def __init__(
        self,
        appointment_id: str,
        patient_id: str,
        kind: str,
        anchor: datetime.datetime,
        occurred_at: datetime.datetime,
        provider_id: str,
        by_patient_portal: bool = False,
        labels: list[str] | None = None,
    ) -> None:
        self.appointment_id = appointment_id
        self.patient_id = patient_id
        # True when the person who performed the state change was the patient
        # themselves rather than a member of staff. Observed on a running
        # instance, the portal path resolves the actor to the patient while a
        # staff path resolves it to staff, so this is knowable without a tag.
        self.by_patient_portal = by_patient_portal
        # Label names on the appointment, read once by the detector so no
        # attribution rule has to touch the database.
        self.labels = list(labels or [])
        # A short string naming which detector produced this, so a
        # configuration that switches one kind off can filter without the
        # engine knowing what the kinds are.
        self.kind = kind
        # The appointment start time. All window arithmetic uses this.
        self.anchor = anchor
        # When the state change actually happened, kept for the lateness gap
        # and for the run rule.
        self.occurred_at = occurred_at
        self.provider_id = provider_id
        # Filled by the attribution chain, never by a detector.
        self.attribution: str | None = None
        # Filled by the engine. True while the incident is younger than the
        # holding period, meaning it is real and recorded but not counted yet. It
        # will start counting on its own once the period passes, so a surface
        # that hides it is lying about the next few minutes.
        self.pending: bool = False
        # Filled by the engine when the incident is pending. The moment it starts
        # counting, sent as an instant rather than a remaining duration so it never
        # goes stale on a page left open.
        self.counts_at: datetime.datetime | None = None

    def counts_against_patient(self) -> bool:
        """True when this incident belongs on the patient's total."""
        return self.attribution == PATIENT

    def __repr__(self) -> str:
        return (
            f"Incident(kind={self.kind}, appointment={self.appointment_id}, "
            f"anchor={self.anchor}, attribution={self.attribution})"
        )


# A detector must carry these. It is handed the transitions belonging to one
# appointment and returns an Incident or None. It never decides attribution.
DETECTOR_METHODS = ("kind", "detect")

# An attribution rule must carry these. It is handed an Incident and returns
# one of ATTRIBUTIONS to claim it, or None to pass it along the chain.
RULE_METHODS = ("resolve",)

# A settings store must carry these. It reads every stored setting as text and
# writes a batch of them back. The engine never sees a store, only the
# composition root does, so policy can come from the plugin's own storage on an
# instance and from a dictionary in a test without either knowing about the
# other.
STORE_METHODS = ("read", "write")

# A task reader must carry both of these. status_of answers what state the task
# with a derived identifier is in, or nothing when no such task exists, and that
# is what decides whether a task is created at all. title_of answers what title
# it currently stores, which is what lets a caller skip rewriting a title that
# has not changed. Both are required rather than one required and one optional,
# because a reader that cannot answer the second silently reintroduces a write
# on every sweep tick, and there is only one real reader to satisfy. Only the
# composition root names the concrete reader.
TASK_READER_METHODS = ("status_of", "title_of")


def validate(collaborator: Any, required: tuple[str, ...], role: str) -> Any:
    """Check a collaborator carries the methods its contract names.

    Called from the composition root only. A dynamic language cannot promise
    this at import time, so the wiring checks it once at startup rather than
    letting a missing method surface as an attribute error deep in a count.
    """
    missing = [name for name in required if not hasattr(collaborator, name)]
    if missing:
        joined = ", ".join(missing)
        raise TypeError(f"{role} {collaborator!r} is missing required members, {joined}")
    return collaborator
