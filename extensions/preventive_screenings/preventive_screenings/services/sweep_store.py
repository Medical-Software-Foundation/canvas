"""Reading and writing the sweep's own bookkeeping.

Every database call the sweep makes lives here, and nothing else does, for a
practical reason: CustomModel tables do not exist in the pytest test database,
so anything touching them can only be mock-tested. Keeping that surface small
and dumb keeps the part that *can* be tested properly - the scheduling decisions
in ``services.screenings`` and the orchestration in ``handlers.sweep`` - honest.

Every function here degrades rather than raises. The sweep runs unattended on a
schedule; a missing namespace or a bad row must cost one quiet cycle, not a
crash loop against the whole panel.
"""

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.v1.data import Patient
from logger import log

from preventive_screenings.models import ScreeningConfig, ScreeningReview

# No patient goes longer than this without being re-verified, whatever date was
# predicted for them. See models/screening_review.py: this clamp is what stops a
# wrong prediction being wrong forever.
MAX_REVIEW_GAP_DAYS = 90

# Where the backfill cursor and the config stamp live. Reuses the config table
# rather than adding a second one - it is already a keyed JSON store, and this
# is two fields.
_SWEEP_KEY = "sweep"


def fingerprint(effects: list[Effect]) -> str:
    """A hash of the cards about to be written.

    At panel scale the expensive half is writing, not reading, and most sweeps
    find most patients unchanged. Comparing this against the stored value turns
    those into no writes at all.
    """
    joined = "".join(str(effect.payload) for effect in effects)
    return hashlib.sha256(joined.encode()).hexdigest()


def clamp(next_review: date | None, today: date) -> date:
    """The date to actually store, never more than one cycle away.

    ``None`` from ``next_change_date`` means nothing time can do will change
    this patient's cards. That is a prediction, and a wrong prediction would
    otherwise strand them forever, so it still gets re-verified on the cycle.
    """
    ceiling = today + timedelta(days=MAX_REVIEW_GAP_DAYS)
    if next_review is None or next_review > ceiling:
        return ceiling
    return max(next_review, today + timedelta(days=1))


def load_state() -> dict[str, Any]:
    """The backfill cursor, the config stamp, and what has been retired."""
    blank: dict[str, Any] = {"cursor": 0, "stamp": "", "tracked": [], "retired": {}}
    try:
        row = ScreeningConfig.objects.filter(key=_SWEEP_KEY).first()
        if row and row.payload:
            state: dict[str, Any] = json.loads(row.payload)
            return {
                "cursor": int(state.get("cursor", 0)),
                "stamp": str(state.get("stamp", "")),
                "tracked": list(state.get("tracked", [])),
                "retired": dict(state.get("retired", {})),
            }
    except Exception as exc:  # namespace not ready, or a payload we cannot read
        log.warning(f"preventive_screenings: could not read sweep state ({exc})")
    return blank


def retire(state: dict[str, Any], active_ids: list[str], today: date) -> dict[str, Any]:
    """Note screenings that have stopped being tracked, and forget old ones.

    A screening that is switched off or deleted stops producing cards, and
    because no effect deletes a protocol card, its last state - possibly
    "OVERDUE" - would sit on every chart it ever reached. So it is remembered
    until the sweep has had time to overwrite it everywhere.

    Entries are dropped after a full review cycle, by which point every patient
    has been swept at least once, so the list cannot grow without bound.

    ⛔ **A screening that comes back is dropped from the list immediately.**
    This used to only ever add, and expire by age, which meant switching a card
    off and back on inside 90 days left the id in both lists at once - and
    `services.review` writes retractions *after* the real cards, under the same
    key, so the retraction overwrote the card that had just been turned back
    on. The provider saw nothing, for up to a full cycle, with the editor
    insisting the screening was carded.

    It was near-unreachable while enabling a screening was the only way in.
    Making the card a per-screening toggle turned it into the first thing
    anyone would try, and it was hit on a real instance within the hour of
    0.18.0 shipping - the sweep went on logging `retracting N screening(s)`
    for a screening that was carded again. Fixed in 0.18.1.
    """
    retired = dict(state.get("retired", {}))
    for screening_id in state.get("tracked", []):
        if screening_id not in active_ids and screening_id not in retired:
            retired[screening_id] = today.isoformat()

    cutoff = (today - timedelta(days=MAX_REVIEW_GAP_DAYS)).isoformat()
    retired = {
        key: when
        for key, when in retired.items()
        # Being carded now beats having been retracted before. The card is
        # what the practice is asking for today.
        if key not in active_ids and when > cutoff
    }

    return {**state, "tracked": list(active_ids), "retired": retired}


def save_state(
    cursor: int,
    stamp: str,
    tracked: list[str] | None = None,
    retired: dict[str, str] | None = None,
) -> None:
    """Record how far the backfill has walked, and under which config."""
    payload = json.dumps(
        {
            "cursor": cursor,
            "stamp": stamp,
            "tracked": tracked or [],
            "retired": retired or {},
        }
    )
    try:
        row = ScreeningConfig.objects.filter(key=_SWEEP_KEY).first()
        if row:
            row.payload = payload
            row.save()
        else:
            ScreeningConfig.objects.create(key=_SWEEP_KEY, payload=payload)
    except Exception as exc:
        log.warning(f"preventive_screenings: could not save sweep state ({exc})")


def config_stamp(doc: dict[str, Any]) -> str:
    """A hash of the screening rules, to notice when they change.

    Changing an interval or enabling a screening invalidates every stored
    prediction at once, and there is no event for it.
    """
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:32]


def invalidate_all(today: date) -> int:
    """Mark every patient for review, after the rules themselves changed.

    One update rather than a recomputation: the sweep then drains the panel in
    bounded batches instead of trying to do it in a single run.
    """
    try:
        updated: int = ScreeningReview.objects.update(next_review=today)
        return updated
    except Exception as exc:
        log.warning(f"preventive_screenings: could not invalidate reviews ({exc})")
        return 0


def invalidate_patient(patient_key: str, today: date) -> int:
    """Put one patient at the front of the review queue.

    Used when something outside the event stream changed what this patient's
    cards should say - today, a staff member marking a screening complete or
    not applicable from the record app. No Canvas event fires for that, because
    it is this plugin's own data that moved.

    **The fingerprint is deliberately left alone.** The record route also
    returns the recomputed cards directly, and that does work - measured on a
    real chart 2026-10-06, inside a window with no sweep activity. This is the
    backstop for the case where it does not: an effect dropped on another
    instance or another Canvas version would be invisible from here, exactly as
    the 2026-09-19 protocol-card failure was. The stale fingerprint is what
    makes the sweep notice the mismatch and write the cards itself a minute
    later; storing the new one would make it agree they were already correct
    and skip them.

    The cost is one redundant rewrite per action, which is the right trade
    against a silent wrong card.
    """
    try:
        updated: int = ScreeningReview.objects.filter(patient_key=patient_key).update(
            next_review=today
        )
        return updated
    except Exception as exc:
        log.warning(f"preventive_screenings: could not requeue a patient ({exc})")
        return 0


def patients_due(today: date, limit: int) -> list[str]:
    """Patients whose predicted review date has arrived, oldest first."""
    try:
        return list(
            ScreeningReview.objects.filter(next_review__lte=today)
            .order_by("next_review")
            .values_list("patient_key", flat=True)[:limit]
        )
    except Exception as exc:
        log.warning(f"preventive_screenings: could not read the review queue ({exc})")
        return []


def patients_unseen(cursor: int, limit: int) -> list[tuple[str, int]]:
    """Patients with no review row yet, walked in dbid order from the cursor.

    This is the backfill: on a fresh install nobody has a row, and the panel is
    taken in bounded batches rather than in one pass. Walking a cursor rather
    than asking which patients are missing keeps it a single indexed range scan
    instead of an anti-join against the whole panel.
    """
    try:
        return [
            (str(found["id"]), int(found["dbid"]))
            for found in Patient.objects.filter(dbid__gt=cursor, deceased=False)
            .order_by("dbid")
            .values("id", "dbid")[:limit]
        ]
    except Exception as exc:
        log.warning(f"preventive_screenings: could not read the patient list ({exc})")
        return []


def load_reviews(patient_keys: list[str]) -> dict[str, ScreeningReview]:
    """Every stored review row for a batch, in one query, keyed by patient.

    Returns the rows themselves rather than just their fingerprints, because
    the sweep needs both halves of each row: the fingerprint, to decide whether
    the cards actually changed, and the row itself, to write back without
    reading it a second time. Reading them twice is what made the write path
    below an N+1.
    """
    if not patient_keys:
        return {}
    try:
        return {
            row.patient_key: row
            for row in ScreeningReview.objects.filter(patient_key__in=patient_keys)
        }
    except Exception as exc:
        log.warning(f"preventive_screenings: could not read the review rows ({exc})")
        return {}


def record_all(
    entries: list[tuple[str, date, str]],
    stored: dict[str, ScreeningReview],
    today: date,
) -> int:
    """Store a whole batch's bookkeeping in two queries, whatever its size.

    ``entries`` is ``(patient_key, next_review, fingerprint)`` per patient, and
    ``stored`` is what ``load_reviews`` already read for the same batch.

    **This used to be one call per patient**, each costing a SELECT and then an
    INSERT or UPDATE: 226 queries for a default batch, 800 at BATCH_CEILING,
    against the <=6 the chart reads cost for the very same run. It is the same
    N+1 services/completion.py was written to avoid, on the axis nothing
    measured - CustomModel tables do not exist in the pytest database, so the
    sweep's store is mocked and a mock cannot count queries. See
    tests/services/test_sweep_store.py for the fixture that makes it countable.

    Every patient reached does need a write: clamp() guarantees the new
    next_review is at least tomorrow, and a patient is only swept once their
    stored date has arrived, so the date always moves. There is nothing to skip
    here - only a round trip per patient to stop paying.
    """
    if not entries:
        return 0
    try:
        updates = []
        creates = []
        for patient_key, next_review, mark in entries:
            row = stored.get(patient_key)
            if row is None:
                creates.append(
                    ScreeningReview(
                        patient_key=patient_key,
                        next_review=next_review,
                        last_reviewed=today,
                        fingerprint=mark,
                    )
                )
            else:
                row.next_review = next_review
                row.last_reviewed = today
                row.fingerprint = mark
                updates.append(row)
        if updates:
            ScreeningReview.objects.bulk_update(
                updates, ["next_review", "last_reviewed", "fingerprint"]
            )
        if creates:
            ScreeningReview.objects.bulk_create(creates)
        return len(updates) + len(creates)
    except Exception as exc:
        log.warning(f"preventive_screenings: could not record the reviews ({exc})")
        return 0
