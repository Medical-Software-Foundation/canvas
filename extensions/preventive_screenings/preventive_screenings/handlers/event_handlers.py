"""Recompute a patient's screening cards when their chart changes.

Protocol cards are stored state, not something drawn on demand. A chart-read
event may not return ``ADD_OR_UPDATE_PROTOCOL_CARD`` - proved on the instance
on 2026-09-19, where cards built on every chart open were silently discarded -
so the cards have to be written when the answer changes and left on the chart
until it changes again.

This handler covers the half that is driven by the chart. The other half is
time: a patient ages in, an interval runs out, a due screening tips overdue.
Nothing fires an event for those, so ``handlers.sweep`` picks them up on the
dates ``services.review`` predicts.

The events below are the ones that can change an answer, one per kind of record
``services.completion`` reads:

===========================  =================================================
Source                        Event
===========================  =================================================
imaging                       IMAGING_REPORT_CREATED / _UPDATED
lab                           LAB_REPORT_CREATED / _UPDATED
questionnaire                 INTERVIEW_CREATED / _UPDATED
condition (exclusions)        CONDITION_CREATED / _UPDATED / _RESOLVED / _ASSESSED
procedure                     **no event exists** - see below
age, sex, deceased            PATIENT_CREATED / _UPDATED
snooze                        PROTOCOL_OVERRIDE_CREATED / _UPDATED
===========================  =================================================

**A snooze needs both events, and the reason is worth keeping.**

One snooze produces a `PROTOCOL_OVERRIDE_CREATED` and then about four
`PROTOCOL_OVERRIDE_UPDATED` inside a few hundred milliseconds. That burst was
first read as a feedback loop - our card writes provoking the updates - and
both events were dropped to stop it.

That was a misdiagnosis. A loop would not terminate, and this one stopped at
four every time.

**Snoozing is a command in a note, and it takes two clicks**: one on the card's
snooze button, which stages the command, and one on *Record* in the note, which
commits it. The override row exists from the first click but is
`status='inactive'` until the second. `CREATED` fires on the staging, so a
handler reading at that instant sees a snooze the provider has not recorded yet
- and ``services.completion.snoozed_until`` rightly refuses it. The `UPDATED`
that follows the commit is the only event that can see an active snooze.

So `CREATED` alone cannot work, and dropping both left the 0.7.0 quiet-title
feature with nothing to trigger it at all - a provider snoozed a card and
watched the old title sit there.

The cost is those few extra recomputations per snooze. They are bounded, they
only happen on an action a provider takes rarely, and each one writes the same
cards. **If this ever does start looping, the symptom is unbounded
`PROTOCOL_OVERRIDE_UPDATED` lines in the log** - and the answer is a change
guard in this handler, not dropping the subscription, because dropping it takes
the feature with it.

**There is no PROCEDURE_CREATED event**, and ``Procedure`` is the only
completion source without one - imaging, lab, interview, condition and referral
all have theirs. This file used to say ``NOTE_CLOSED`` covered the gap. **It
does not: signing a note does not emit it.** Proved on the instance 2026-09-20 -
three colonoscopies recorded and signed produced zero handler invocations in
eight minutes, and the colorectal cards stayed OVERDUE until an unrelated
config edit requeued the panel.

The consequence was the brief's own requirement failing: *"a screening should
stop showing as due once it has actually been done"*. Nothing noticed, so the
card waited for the sweep to revisit that patient on ``next_review`` - up to
``MAX_REVIEW_GAP_DAYS``, i.e. **90 days** of a card shouting OVERDUE at a
provider who had just done the test.

``PERFORM_COMMAND__POST_COMMIT`` is the trigger that actually covers it, with
``POST_ENTER_IN_ERROR`` and ``POST_DELETE`` for the same staleness in reverse -
a procedure recorded by mistake must stop satisfying the screening just as
promptly. Command events target the **command**, not a chart record, so the
patient is resolved from ``Command`` - which carries one directly, falling back
to its note's patient when it does not.

Only ``PATIENT_*`` events carry the patient on ``event.target.id``; the rest
target the record that changed, so the patient is resolved from it. That lookup
selects a single column and never hydrates the row - ``Note`` in particular
carries a large body that must not be dragged in to read one id.
"""

from datetime import UTC, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Command, Condition, ImagingReport, ReferralReport
from canvas_sdk.v1.data.lab import LabReport
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.protocol_override import ProtocolOverride
from canvas_sdk.v1.data.questionnaire import Interview
from logger import log

from preventive_screenings.services.config_store import carded_screenings, load_config
from preventive_screenings.services.review import review_patient

# Imported by name, never as `from ...services import sweep_store` followed by
# `sweep_store.clamp()`. The sandbox refuses attribute access on an imported
# module object, and does so at RUN time - see handlers/sweep.py.
from preventive_screenings.services.sweep_store import (
    clamp,
    fingerprint,
    load_reviews,
    record_all,
)

# The model each event targets, so the patient can be resolved from it. Events
# absent from this map target the patient directly.
_TARGET_MODELS = {
    "IMAGING_REPORT_CREATED": ImagingReport,
    "IMAGING_REPORT_UPDATED": ImagingReport,
    "LAB_REPORT_CREATED": LabReport,
    "LAB_REPORT_UPDATED": LabReport,
    "INTERVIEW_CREATED": Interview,
    "INTERVIEW_UPDATED": Interview,
    "CONDITION_CREATED": Condition,
    "CONDITION_UPDATED": Condition,
    "CONDITION_RESOLVED": Condition,
    "CONDITION_ASSESSED": Condition,
    "NOTE_CLOSED": Note,
    "PROTOCOL_OVERRIDE_CREATED": ProtocolOverride,
    "PROTOCOL_OVERRIDE_UPDATED": ProtocolOverride,
    "REFERRAL_REPORT_CREATED": ReferralReport,
    "REFERRAL_REPORT_UPDATED": ReferralReport,
    "PERFORM_COMMAND__POST_COMMIT": Command,
    "PERFORM_COMMAND__POST_ENTER_IN_ERROR": Command,
    "PERFORM_COMMAND__POST_DELETE": Command,
}

# Where the patient sits on the target, when it is not simply `patient__id`.
# A `Command` carries the patient directly, but the column is nullable, so the
# note it was written in is the fallback. Both come back in the one query.
_TARGET_PATIENT_FIELDS = {
    "PERFORM_COMMAND__POST_COMMIT": ("patient__id", "note__patient__id"),
    "PERFORM_COMMAND__POST_ENTER_IN_ERROR": ("patient__id", "note__patient__id"),
    "PERFORM_COMMAND__POST_DELETE": ("patient__id", "note__patient__id"),
}

_PATIENT_EVENTS = ("PATIENT_CREATED", "PATIENT_UPDATED")


class PreventiveScreeningCards(BaseHandler):
    """Rewrite a patient's screening cards when something in their chart moves."""

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.IMAGING_REPORT_CREATED),
        EventType.Name(EventType.IMAGING_REPORT_UPDATED),
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.INTERVIEW_CREATED),
        EventType.Name(EventType.INTERVIEW_UPDATED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.NOTE_CLOSED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_CREATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_UPDATED),
        EventType.Name(EventType.REFERRAL_REPORT_CREATED),
        EventType.Name(EventType.REFERRAL_REPORT_UPDATED),
        # The only way a committed procedure reaches this plugin.
        EventType.Name(EventType.PERFORM_COMMAND__POST_COMMIT),
        EventType.Name(EventType.PERFORM_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.PERFORM_COMMAND__POST_DELETE),
    ]

    def _patient_id(self) -> str | None:
        """The patient this event concerns, or None if it cannot be resolved.

        Reads one column. ``select_related`` here would hydrate the whole target
        row - a closed Note drags its entire body along - to read a single id.
        """
        target_id = self.event.target.id
        if not target_id:
            return None
        if self.event.name in _PATIENT_EVENTS:
            return str(target_id)

        model = _TARGET_MODELS.get(self.event.name)
        if model is None:
            return None
        fields = _TARGET_PATIENT_FIELDS.get(self.event.name, ("patient__id",))
        row = model.objects.filter(id=target_id).values_list(*fields).first()
        for found in row or ():
            if found:
                return str(found)
        return None

    def compute(self) -> list[Effect]:
        """Rewrite every card for this patient, overdue ones first."""
        # Carded screenings only. A screening the practice tracks without
        # carding has nothing to rewrite here, and the record app computes it
        # live anyway. Retraction is deliberately not this handler's job -
        # `handlers.sweep` owns it, because it needs the memory of what was
        # being carded before, and that lives in the sweep's state row.
        screenings = carded_screenings(load_config())
        if not screenings:
            return []

        patient_id = self._patient_id()
        if not patient_id:
            return []

        today = datetime.now(UTC).date()
        review = review_patient(patient_id, screenings, today)
        if not review.effects:
            return []

        # Write nothing when the cards would be identical to the ones already on
        # the chart. Several events routinely fire for one user action - a single
        # snooze produces a PROTOCOL_OVERRIDE_CREATED and about four _UPDATEDs -
        # and without this each one rewrote every card for that patient, twelve
        # writes to change nothing.
        #
        # This is the guard `handlers.sweep` has always had, reusing the same
        # fingerprint on the same row, so the two agree about what "unchanged"
        # means. Recording here also keeps `next_review` fresh after a chart
        # change; until now only the sweep wrote it, so a chart change left the
        # stored prediction stale until the sweep next reached that patient.
        stored = load_reviews([patient_id])
        row = stored.get(patient_id)
        mark = fingerprint(review.effects)
        if row is not None and row.fingerprint == mark:
            return []

        record_all([(patient_id, clamp(review.next_review, today), mark)], stored, today)

        # No patient identifier. This fires on every one of the events above,
        # for every patient, and log retention and log access are both wider
        # than chart access. The counts are the operational signal; the id only
        # adds a person to a line that does not need one. services.completion
        # and handlers.sweep log the same way.
        log.info(
            f"preventive_screenings: [{self.event.name}] {len(review.effects)} cards, "
            f"next review {review.next_review}"
        )
        return review.effects
