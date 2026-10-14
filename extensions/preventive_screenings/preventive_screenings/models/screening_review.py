"""When each patient's screening cards were last written, and when to look again.

Protocol cards are stored state: nothing recomputes when a chart opens, so a
card only changes when this plugin rewrites it. Chart changes arrive as events,
but the other half - a patient ageing in, an interval running out, a due
screening tipping overdue - has no event at all. This table is how those are
found without re-examining the whole panel every night.

One row per patient:

* ``next_review`` is the date something about this patient could next change,
  predicted by ``services.screenings.next_change_date`` when the cards were
  written. The sweep takes only the rows that have come due, which in steady
  state is a small slice of the panel rather than all of it.
* ``fingerprint`` is a hash of the cards last written. At panel scale the
  expensive half is writing, not reading, and most nights most cards are
  identical, so an unchanged fingerprint means the writes are skipped.
* ``last_reviewed`` is for diagnosis: it answers "when did this patient last get
  looked at" without re-deriving it.

``next_review`` is deliberately **never null**, even for a patient nothing can
change for. ``services.sweep_store`` clamps it to at most
``MAX_REVIEW_GAP_DAYS`` ahead, so every patient is re-verified periodically
whatever the prediction said. That clamp is the safety net: a queue of
predicted dates is a cache, and a cache that is wrong is wrong *silently and
forever*. Re-verifying on a slow rolling basis turns "wrong forever" into
"wrong for at most one cycle", and it costs one clamp rather than a second
query path.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField, DateField, Index, UniqueConstraint


class ScreeningReview(CustomModel):
    """One patient's last screening review, and when the next one is due."""

    # The patient's UUID. Stored rather than a foreign key because a CustomModel
    # cannot point at a Canvas table, and because the sweep hands this straight
    # back to review_patient, which takes the UUID.
    patient_key: CharField = CharField(max_length=64)
    next_review: DateField = DateField()
    last_reviewed: DateField = DateField()
    fingerprint: CharField = CharField(max_length=64, default="")

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_key"], name="uq_preventive_screenings_review_patient"
            )
        ]
        # `patients_due` opens every sweep run with
        # `filter(next_review__lte=today).order_by("next_review")`, and that
        # ran 288 times a day against an unindexed column - a full scan and
        # sort of one row per patient, to return a few hundred. The unique
        # constraint above indexes `patient_key`, so the batched reads and
        # writes were already keyed; this was the one hot column with nothing
        # behind it.
        #
        # Composite rather than `next_review` alone: `patient_key` is the only
        # column that query selects, so the index covers it outright and the
        # table is never touched.
        indexes = [
            Index(
                fields=["next_review", "patient_key"],
                name="ix_preventive_screenings_due",
            )
        ]
