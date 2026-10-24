"""Reading and writing what staff have said about a screening.

The only module that touches ``ScreeningAttestation``, for the same reason
``sweep_store`` is the only one that touches ``ScreeningReview``: custom-data
tables need their own handling, and keeping that surface in one small place
keeps the parts that can be tested properly honest.

Every function degrades rather than raises. These sit on the chart-side record
app and on the sweep's hot path, and a custom-data namespace that is not ready
must cost a missing row, not a broken chart.

**An attestation only ever adds.** It is merged with what the chart says rather
than replacing it, and ``status_for`` takes the latest coverage of the two, so
a real imaging report always wins if it is more recent. Nothing here can hide
evidence; it can only supply some where the chart had none.
"""

from datetime import date, timedelta
from typing import Any, NamedTuple

from canvas_sdk.v1.data import Staff
from logger import log

from preventive_screenings.models import ScreeningAttestation

# A screening was done, even though no record this plugin reads says so.
KIND_COMPLETED = "completed"
# This screening does not apply to this patient, for a reason the configured
# exclusions do not express.
KIND_NOT_APPLICABLE = "not_applicable"
# Ordered from the record app, and the result has not come back. Recorded by us
# at the moment the provider clicks, because nothing in the chart ties an order
# back to a screening: `ImagingOrder.imaging` is an opaque string and `Referral`
# carries no code at all, so reading the order tables could not tell a
# mammogram order from a knee x-ray. See `services.screenings.STATE_ORDERED`.
KIND_ORDERED = "ordered"

KINDS = (KIND_COMPLETED, KIND_NOT_APPLICABLE, KIND_ORDERED)

# How far back an effective date may be. A screening done more than this long
# ago has no bearing on anything - the longest interval the config can express
# is bounded by the same sanity - and an unbounded date lets a typo ("1026")
# store something that reads as valid forever.
MAX_BACKDATE_YEARS = 50


class Attestation(NamedTuple):
    """One stored statement, as the rest of the plugin reads it."""

    screening_id: str
    kind: str
    effective_date: date
    interval_quantity: int
    interval_unit: str
    label: str
    recorded_by: str
    recorded_at: date

    @property
    def completed(self) -> bool:
        """Whether this says the screening was done."""
        return self.kind == KIND_COMPLETED

    @property
    def not_applicable(self) -> bool:
        """Whether this says the screening does not apply to this patient."""
        return self.kind == KIND_NOT_APPLICABLE

    @property
    def ordered(self) -> bool:
        """Whether this says the screening has been ordered and is awaited."""
        return self.kind == KIND_ORDERED


def load_attestations(
    patient_keys: list[str], screening_ids: list[str]
) -> dict[str, dict[str, Attestation]]:
    """Every stored statement for a batch of patients, keyed patient then screening.

    One query for the whole batch, like every other read in this plugin: the
    sweep reviews up to a few hundred patients per run, and asking per patient
    would be the N+1 ``services.completion`` exists to avoid, on one more axis.

    Filtered on the screening ids actually in play as well as the patients, so
    a practice that stopped tracking a screening does not pay to read its old
    attestations on every run.
    """
    if not patient_keys or not screening_ids:
        return {}
    try:
        rows = list(
            ScreeningAttestation.objects.filter(
                patient_key__in=patient_keys, screening_id__in=screening_ids
            ).values_list(
                "patient_key",
                "screening_id",
                "kind",
                "effective_date",
                "interval_quantity",
                "interval_unit",
                "label",
                "recorded_by",
                "recorded_at",
            )
        )
    except Exception as exc:  # namespace not ready, or a column we cannot read
        log.warning(f"preventive_screenings: could not read attestations ({exc})")
        return {}

    found: dict[str, dict[str, Attestation]] = {}
    for key, screening_id, kind, effective, quantity, unit, label, by, at in rows:
        if kind not in KINDS:
            # A row written by a future version, or a hand-edited one. Ignoring
            # it is the safe direction: an unknown statement must not be read
            # as either "done" or "does not apply".
            continue
        found.setdefault(str(key), {})[str(screening_id)] = Attestation(
            screening_id=str(screening_id),
            kind=str(kind),
            effective_date=effective,
            interval_quantity=int(quantity or 0),
            interval_unit=str(unit or "years"),
            label=str(label or ""),
            recorded_by=str(by or ""),
            recorded_at=at,
        )
    return found


def record_attestation(
    patient_key: str,
    screening_id: str,
    kind: str,
    effective_date: date,
    *,
    interval_quantity: int = 0,
    interval_unit: str = "years",
    label: str = "",
    recorded_by: str = "",
    today: date,
) -> bool:
    """Store one statement, replacing whatever that patient had for this screening.

    Returns False rather than raising if custom data is unavailable, so the
    caller can tell the provider their click did not land. A write that
    silently does nothing is the failure mode this whole plugin keeps finding.
    """
    try:
        _, created = ScreeningAttestation.objects.update_or_create(
            patient_key=patient_key,
            screening_id=screening_id,
            defaults={
                "kind": kind,
                "effective_date": effective_date,
                "interval_quantity": interval_quantity,
                "interval_unit": interval_unit,
                "label": label,
                "recorded_by": recorded_by,
                "recorded_at": today,
            },
        )
        # No patient id, matching every other log line in this plugin: log
        # retention and log access are both wider than chart access. The staff
        # id is the operational signal and is already stored on the row itself,
        # where the people who need it can see it.
        log.info(
            f"preventive_screenings: attestation {kind} "
            f"{'created' if created else 'replaced'} for screening {screening_id}"
        )
        return True
    except Exception as exc:
        log.warning(f"preventive_screenings: could not record an attestation ({exc})")
        return False


def clear_attestation(patient_key: str, screening_id: str) -> bool:
    """Undo a statement, putting the screening back to what the chart says.

    Deleting rather than storing a third "retracted" state: an attestation that
    is not there and one that was taken back mean exactly the same thing to
    every reader, and the row carries no history worth keeping.
    """
    try:
        ScreeningAttestation.objects.filter(
            patient_key=patient_key, screening_id=screening_id
        ).delete()
        log.info(f"preventive_screenings: attestation cleared for screening {screening_id}")
        return True
    except Exception as exc:
        log.warning(f"preventive_screenings: could not clear an attestation ({exc})")
        return False


def staff_names(staff_ids: list[str]) -> dict[str, str]:
    """Readable names for the staff who recorded attestations, in one query.

    The point of storing ``recorded_by`` is that a clinician reading "up to
    date" can see whose say-so it rests on, and a raw staff key answers nobody.
    One query for the page, skipped entirely when nothing is attested.

    An unreadable staff table degrades to no names rather than to no record -
    the statement and its date are the load-bearing part.
    """
    wanted = {found for found in staff_ids if found}
    if not wanted:
        return {}
    try:
        rows = Staff.objects.filter(id__in=wanted).values_list("id", "first_name", "last_name")
    except Exception as exc:
        log.warning(f"preventive_screenings: could not read staff names ({exc})")
        return {}
    names = {}
    for staff_id, first, last in rows:
        full = " ".join(part for part in (str(first or ""), str(last or "")) if part).strip()
        if full:
            names[str(staff_id)] = full
    return names


def recording_date(raw: Any, today: date) -> date:
    """The provider's today, as the provider's own clock sees it.

    ``recorded_at`` is read by a clinician as *when somebody said so*, and the
    frame that answers in is the provider's, not the server's. UTC is a day
    ahead of a US evening, which made every evening attestation render as
    "Marked complete 13 Oct 2026 ..., recorded 14 Oct 2026" - two dates for one
    action, where that clause exists to show a **genuine backdate**.

    The browser supplies the date, but **only a one-day disagreement with the
    server is honoured**. That is the whole range any real timezone can
    produce, so it fixes the frame without letting a client name an arbitrary
    day as the day something was recorded.
    """
    try:
        claimed = date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return today
    return claimed if abs((claimed - today).days) <= 1 else today


def parse_effective_date(raw: Any, today: date) -> date | None:
    """Read the date a provider typed, or None if it is not a date we will store.

    Refuses the future. A screening cannot have been done tomorrow, and
    accepting one would make the screening read as satisfied on evidence that
    does not exist yet - the "unknown never means positive" rule in
    ``services.screenings``, on the one path where a person types the input.

    ⚠️ **"The future" is given one day of slack, and that is timezone, not
    laxity.** ``today`` here is UTC, and a provider's today is not: east of UTC
    a perfectly ordinary "today" is already tomorrow by this clock, so a strict
    comparison refuses a provider in Tokyo their own current date every
    morning. No timezone is more than about fourteen hours from UTC, so one day
    covers every real case while still refusing a date anybody typed on
    purpose.
    """
    try:
        parsed = date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed > today + timedelta(days=1):
        return None
    if parsed.year < today.year - MAX_BACKDATE_YEARS:
        return None
    return parsed
