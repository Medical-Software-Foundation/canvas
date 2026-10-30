"""Work out one patient's screening cards, and when to look at them again.

This is the piece both triggers share. A patient's cards are recomputed when
something in their chart changes (``handlers.event_handlers``) and when a date
we predicted arrives (``handlers.sweep``), and both need exactly the same
answer, so the work lives here rather than in either handler.

**Protocol cards are stored state.** This was proved on the instance on
2026-09-19: a card written by one event was still on the chart when the chart
was reopened, and cards built during a chart-read event never appeared at all
because that event may not return ``ADD_OR_UPDATE_PROTOCOL_CARD``. Two
consequences shape this module:

* A card is emitted for **every** enabled screening, including satisfied and
  not-applicable ones. A screening that goes quiet has to be actively restated,
  or its last state sits on the chart forever.
* Nothing recomputes on chart open, so ``next_review`` is not an optimisation -
  it is the only thing that makes a card change as time passes.

The query cost is the same fixed handful the chart-open version had: one read
of the patient, then completions and exclusions batched by the kind of chart
record they live in, so twelve screenings reading imaging cost one query rather
than twelve.
"""

from datetime import date
from typing import NamedTuple

from canvas_sdk.effects import Effect
from canvas_sdk.v1.data import Patient

from preventive_screenings.services.attestations import Attestation, load_attestations
from preventive_screenings.services.cards import (
    build_card,
    build_not_applicable_card,
    build_retired_card,
    card_key,
)
from preventive_screenings.services.completion import SignalKey, latest_dates, snoozed_until
from preventive_screenings.services.screenings import (
    STATE_ORDERED,
    STATE_OVERDUE,
    STATE_SATISFIED,
    AttestedCompletion,
    ScreeningStatus,
    is_eligible,
    next_change_date,
    status_for,
)

KIND_COMPLETION = "completion"
KIND_EXCLUSION = "exclusion"


class ScreeningRow(NamedTuple):
    """Where one screening stands for one patient, before it becomes a card.

    The chart section renders these directly rather than recomputing, because
    two code paths deciding what a screening says would eventually disagree -
    and the card and the section sit inches apart on the same screen.
    """

    screening: dict
    # None when the screening does not apply to this patient at all, whether by
    # age, by sex, by an exclusion on their chart, or because a staff member
    # marked it not applicable.
    status: ScreeningStatus | None
    snoozed: bool
    # What a staff member recorded about this screening, if anything. Carried
    # on the row rather than folded away because the record app has to show it
    # - both so a clinician can see what "up to date" rests on, and so there is
    # something to undo. A row with `status is None` and an attestation is one
    # a person marked not applicable, which is the one not-applicable case the
    # app shows rather than hides.
    attestation: Attestation | None = None


class PatientReview(NamedTuple):
    """One patient's cards, and the next date any of them could change."""

    effects: list[Effect]
    # None means nothing but a chart change can alter these cards, so there is
    # no reason to schedule another look.
    next_review: date | None
    # Every screening's resolved state, for readers that want the data rather
    # than the cards. The sweep ignores this; it costs references, not copies.
    rows: list[ScreeningRow] = []


def _signals(screenings: list[dict], eligible: list[int]) -> list[tuple[SignalKey, dict]]:
    """Every signal worth asking the database about, for one batched read.

    Only age/sex-eligible screenings contribute: there is no reason to ask
    whether a 30-year-old's mammogram is current.
    """
    signals: list[tuple[SignalKey, dict]] = []
    for index in eligible:
        screening = screenings[index]
        for position, signal in enumerate(screening["completions"]):
            signals.append(((KIND_COMPLETION, index, position), signal))
        for position, signal in enumerate(screening["exclusions"]):
            signals.append(((KIND_EXCLUSION, index, position), signal))
    return signals


def review_patient(
    patient_id: str,
    screenings: list[dict],
    today: date,
    retired: list[str] | None = None,
) -> PatientReview:
    """Every card one patient should have, and when to revisit them.

    A chart change concerns exactly one patient, so this is what
    ``handlers.event_handlers`` calls. It is a batch of one over
    ``review_patients`` rather than a second implementation, because two code
    paths computing cards would eventually disagree about what a card says.
    """
    return review_patients([patient_id], screenings, today, retired)[patient_id]


def review_patients(
    patient_ids: list[str],
    screenings: list[dict],
    today: date,
    retired: list[str] | None = None,
) -> dict[str, PatientReview]:
    """Every card a batch of patients should have, and when to revisit each.

    Every id passed in gets an entry, including ids that match no patient, so a
    caller can record a result for each one without checking.

    A patient who cannot be assessed gets no cards at all - rather than
    not-applicable ones - because an unknown age or a deceased patient must
    never be read as eligible, and writing cards for them would be asserting
    something we do not know. They still get retractions: taking back what we
    previously wrote asserts nothing.

    ``retired`` names screenings the practice has stopped tracking. There is no
    effect that deletes a protocol card, so their cards have to be overwritten
    or they stay on the chart forever - see ``cards.build_retired_card``.
    """
    wanted = [patient_id for patient_id in patient_ids if patient_id]
    reviews: dict[str, PatientReview] = {
        patient_id: PatientReview([], None) for patient_id in patient_ids
    }

    if not wanted or not (screenings or retired):
        return reviews

    # A screening cannot be both carded and retracted, and if a caller says it
    # is, the card wins. Retractions are written *after* the cards and under the
    # same key, so a screening in both lists has its own card overwritten by its
    # own retraction - the provider sees nothing while the editor says it is on.
    #
    # `sweep_store.retire` now keeps the two lists disjoint, so this should
    # never fire. It is here anyway because the failure is invisible: the cards
    # are computed correctly, returned, and then quietly undone a few list
    # entries later. Enforcing it where the conflict is actually resolvable
    # also means an instance whose stored state predates that fix heals on the
    # next review rather than waiting out the 90-day expiry.
    #
    # After the early return rather than before, which costs nothing: `carded`
    # is empty exactly when `screenings` is, so the filter can never change
    # that condition's answer.
    carded = {screening["id"] for screening in screenings}
    retired = [key for key in retired or [] if key not in carded]

    # One read for the whole batch. `dbid` comes back with the rest: every chart
    # read below filters on it rather than on the UUID, which keeps them keyed
    # lookups instead of joining the patient table five times over.
    patients = {
        str(found["id"]): found
        for found in Patient.objects.filter(id__in=wanted).values(
            "id", "dbid", "birth_date", "sex_at_birth", "deceased"
        )
    }

    assessable = {
        patient_id: found
        for patient_id, found in patients.items()
        if found["birth_date"] and not found["deceased"]
    }
    eligibility = {
        patient_id: [
            index
            for index, screening in enumerate(screenings)
            if is_eligible(screening, found["sex_at_birth"], found["birth_date"], today)
        ]
        for patient_id, found in assessable.items()
    }

    # The union across the batch, so every source is read once for everyone
    # rather than once per patient. A patient receiving a signal for a screening
    # they are not eligible for is harmless: the loop below tests eligibility
    # first and writes a not-applicable card either way.
    union = sorted({index for indices in eligibility.values() for index in indices})
    dbids = [found["dbid"] for found in assessable.values()]
    by_patient = latest_dates(dbids, _signals(screenings, union))
    # One more batched read, on the same key, for the cards a provider has
    # deferred. Only the eligible screenings can be showing a card worth
    # snoozing, so only their keys are asked about.
    snoozes = snoozed_until(dbids, [card_key(screenings[index]) for index in union], today)
    # And one for what staff have said themselves. Keyed by the patient UUID
    # rather than the dbid, because a CustomModel cannot hold a foreign key
    # into a Canvas table. One query for the batch, like every read above.
    #
    # Only the eligible screenings, for the same reason the snooze read asks
    # only about their card keys: age, sex and chart exclusions are checked
    # before any attestation below, so a statement about a screening this batch
    # cannot be eligible for could not change an answer. A batch where nobody
    # is eligible for anything skips this read entirely.
    attestations = load_attestations(
        list(assessable), [screenings[index]["id"] for index in union]
    )

    for patient_id in patient_ids:
        if not patient_id:
            continue
        found = assessable.get(patient_id)
        if found is None:
            reviews[patient_id] = PatientReview(
                [build_retired_card(patient_id, key).apply() for key in retired or []],
                None,
            )
            continue
        reviews[patient_id] = _review_one(
            patient_id,
            screenings,
            today,
            retired,
            found["birth_date"],
            eligibility[patient_id],
            by_patient.get(found["dbid"], {}),
            snoozes.get(found["dbid"], {}),
            attestations.get(patient_id, {}),
        )
    return reviews


def _review_one(
    patient_id: str,
    screenings: list[dict],
    today: date,
    retired: list[str] | None,
    birth_date: date,
    eligible: list[int],
    dates: dict[SignalKey, date],
    snoozes: dict[str, date],
    attestations: dict[str, Attestation],
) -> PatientReview:
    """Turn one patient's already-read chart data into their cards.

    Every query has happened by the time this runs, which is what lets the
    batch above pay for a source once rather than once per patient.
    """
    excluded = {key[1] for key in dates if key[0] == KIND_EXCLUSION}

    due: list[tuple[ScreeningStatus, Effect]] = []
    others: list[Effect] = []
    revisits: list[date] = []
    rows: list[ScreeningRow] = []

    for index, screening in enumerate(screenings):
        attestation = attestations.get(screening["id"])
        # Age, sex and the chart's own exclusions are checked first, and they
        # win. A patient who has aged out of a screening does not need to be
        # told somebody once marked it not applicable - it does not apply
        # either way, and surfacing the statement would invite undoing it to no
        # effect.
        if index not in eligible or index in excluded:
            others.append(build_not_applicable_card(patient_id, screening).apply())
            status = None
            rows.append(ScreeningRow(screening, None, False))
        elif attestation is not None and attestation.not_applicable:
            others.append(
                build_not_applicable_card(
                    patient_id, screening, attested=True
                ).apply()
            )
            status = None
            # The attestation rides along so the record app can show it and
            # offer to undo it. Nothing else in the plugin can retract this:
            # no chart change makes a person's "does not apply" untrue.
            rows.append(ScreeningRow(screening, None, False, attestation))
        else:
            completions = {
                key[2]: when
                for key, when in dates.items()
                if key[0] == KIND_COMPLETION and key[1] == index
            }
            attested = None
            ordered = None
            if attestation is not None and attestation.completed:
                attested = AttestedCompletion(
                    on=attestation.effective_date,
                    interval_quantity=attestation.interval_quantity,
                    interval_unit=attestation.interval_unit,
                )
            elif attestation is not None and attestation.ordered:
                ordered = attestation.effective_date
            status = status_for(
                screening, completions, birth_date, today, attested, ordered
            )
            snoozed = snoozes.get(card_key(screening))
            card = build_card(
                patient_id, screening, status, snoozed=snoozed is not None
            ).apply()
            rows.append(
                ScreeningRow(screening, status, snoozed is not None, attestation)
            )
            if status.state in (STATE_SATISFIED, STATE_ORDERED):
                # Ordered goes with satisfied rather than with due: the
                # practice has already done what the card was asking for, so it
                # is not part of the triage list at the top of the chart.
                others.append(card)
            else:
                due.append((status, card))

        when = next_change_date(
            screening, status, birth_date, today, snoozes.get(card_key(screening))
        )
        if when is not None:
            revisits.append(when)

    # Retractions go last: they are housekeeping, not something to read.
    for screening_id in retired or []:
        others.append(build_retired_card(patient_id, screening_id).apply())

    # Overdue first, then the rest by how long they have been due, so the top
    # of the chart is already triaged.
    due.sort(key=lambda item: (item[0].state != STATE_OVERDUE, item[0].due_in))

    return PatientReview(
        effects=[card for _status, card in due] + others,
        next_review=min(revisits) if revisits else None,
        rows=rows,
    )
