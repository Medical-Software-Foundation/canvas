"""What a staff member has said about a screening that the chart does not say.

Two things a provider can record from the chart-side record app:

* **Marked complete.** The screening was done, but no discrete record this
  plugin can read says so - done elsewhere, on paper, or recorded under a code
  the configured value set does not carry.
* **Not applicable.** This screening does not apply to this patient, for a
  reason the configured exclusions do not express.

**Why these live here rather than in the chart.** Marking something complete is
a clinical claim and the chart is where a clinical claim belongs, so this was
weighed carefully. Two things decided it:

1. Writing to the chart means originating a command, and a command needs an
   open note. This app is patient-scoped, not note-scoped: a provider can open
   the record beside a chart with no note open at all, and a button that works
   only sometimes is worse than one that works consistently.
2. "Not applicable" has no chart representation at all. It is a statement about
   *this practice's screening rule*, not about the patient's care, so there is
   nothing in the chart it could honestly be written as.

What makes that defensible is **provenance, carried in the record rather than
in a log**. Every row says who recorded it and when, and the record app shows
that beside the screening, so a clinician reading "up to date" can always see
whether that came from an imaging report or from a colleague's say-so. That is
the chart's own standard for an attestation, and it is deliberately *not* the
staff+patient audit log CLAUDE.md rules out - this is data the people who need
it can read, not an operational log nobody looks at.

One row per patient per screening, replaced each time. The plugin only ever
uses the most recent completion anyway - ``services.screenings.status_for``
takes the latest date - so keeping history here would store rows nothing reads.

``interval_quantity`` / ``interval_unit`` are **copied from the completion
signal at the time it was recorded**, not looked up later. A screening can be
satisfied several ways for different lengths of time, so the provider says
which one they are attesting to; storing the answer rather than a pointer to it
means an admin reordering or deleting that signal later cannot silently change
what a past attestation meant.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField, DateField, IntegerField, UniqueConstraint


class ScreeningAttestation(CustomModel):
    """One staff member's statement about one screening for one patient."""

    # The patient's UUID, as in ScreeningReview: a CustomModel cannot hold a
    # foreign key into a Canvas table.
    patient_key: CharField = CharField(max_length=64)
    screening_id: CharField = CharField(max_length=64)
    # "completed" or "not_applicable" - services.attestations owns the values.
    kind: CharField = CharField(max_length=16)
    # When the screening was done. Not the same as when it was recorded: a
    # mammogram done last March and typed in today is due from last March, and
    # dating it today would push the next one a year late.
    effective_date: DateField = DateField()
    # How long this completion covers, copied from the signal it attests to.
    interval_quantity: IntegerField = IntegerField(default=0)
    interval_unit: CharField = CharField(max_length=16, default="years")
    # What the provider said they were attesting to ("mammography"), so the
    # record can say what was done and not only that something was.
    label: CharField = CharField(max_length=200, default="")
    # The staff id from the session that recorded it, and the date. Shown in
    # the record app - see the module docstring on why that is the point.
    recorded_by: CharField = CharField(max_length=64, default="")
    recorded_at: DateField = DateField()

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_key", "screening_id"],
                name="uq_preventive_screenings_attestation",
            )
        ]
        # No separate index. The unique constraint above leads on
        # `patient_key`, which is the column every read filters on, so a second
        # one would be maintained on every write and chosen by nothing.
