"""Find, in batch, when each screening signal was last satisfied.

This is the only module that reads patients' charts, and it is the reason the
plugin stays cheap. It batches along **both** axes that would otherwise multiply
queries:

* **Across screenings.** Asking "has this one been done?" per screening would be
  several queries each. Every signal across every screening is grouped by the
  *kind* of record it lives in, and each kind is read once.
* **Across patients.** The scheduled sweep reviews a batch of patients per run.
  Reading one patient at a time made a run cost the whole set of reads per
  patient, so a 50-patient run ran up to 300 queries where 6 would do.

So the cost is one query per distinct source actually in use - at most six, and
in practice three or four - however many screenings are configured and however
many patients are in the batch. A value set can name several sources, because
Canvas can record a colonoscopy as a procedure, a referral report or an imaging
report; the latest date across them wins, and each is still one query.

Attribution happens in Python rather than in SQL: each query returns the code
and code system it matched alongside the date, and each signal then claims the
rows whose codes it owns. That keeps one query per source even when a dozen
screenings share it, and it is exact - a row is never credited to a signal whose
value set does not contain its code.
"""

from datetime import date, datetime
from typing import Any, NamedTuple

from canvas_sdk.v1.data import Condition, ImagingReport, Procedure, ReferralReport
from canvas_sdk.v1.data.lab import LabValue
from canvas_sdk.v1.data.protocol_override import ProtocolOverride
from canvas_sdk.v1.data.questionnaire import Interview
from logger import log

from preventive_screenings.services.catalog import (
    SOURCE_CONDITION,
    SOURCE_IMAGING,
    SOURCE_LAB,
    SOURCE_PROCEDURE,
    SOURCE_QUESTIONNAIRE,
    SOURCE_REFERRAL,
    extra_sources_for,
    value_set_for,
)

# Identifies one signal within the request: what it is for ("completion" or
# "exclusion"), which screening, and which of that screening's signals. The
# handler chooses the numbering; this module only hands it back untouched.
#
# Both kinds share one call on purpose. An exclusion asking about procedures and
# another screening's completion asking about procedures are then answered by
# the same single query.
SignalKey = tuple[str, int, int]

# Canvas does not record a snoozed card's `protocol_key` as the key we gave the
# card. It appends the plugin's name, so a card keyed
# `preventive_screening:<id>` is snoozed against
# `preventive_screening:<id>preventive_screenings`.
#
# Observed on the instance 2026-09-20; nothing in the SDK documents it, and two
# guesses were wrong before the row was printed. Stripping the suffix rather
# than constructing the full string means an instance that does *not* append it
# still matches.
_OVERRIDE_KEY_SUFFIX = "preventive_screenings"


# The one rejection reason that means something is wrong rather than something
# ordinary. Every other reason - inactive, expired, not a snooze - is a state a
# healthy instance produces all the time.
_UNKNOWN_KEY = "key does not match any card"


def _card_key_of(override_key: str) -> str:
    """The card key behind a `ProtocolOverride.protocol_key`."""
    if override_key.endswith(_OVERRIDE_KEY_SUFFIX):
        return override_key[: -len(_OVERRIDE_KEY_SUFFIX)]
    return override_key


class _SourceSpec(NamedTuple):
    """How to read one kind of chart record: where the patient, code and date live.

    ``patient_field`` points at the patient's integer ``dbid``, not the UUID.
    The SDK's own ``for_patient(uuid)`` filters ``patient__id``, which joins the
    patient table on every one of these reads; the dbid is the foreign key
    column already on the row, so filtering it is a keyed lookup with no join.
    The handler has the dbid in hand from the one patient read it already does.
    """

    model: Any
    patient_field: str
    system_field: str
    code_field: str
    date_field: str
    committed: bool
    # Questionnaires store the code system by name ("LOINC"); everything else
    # stores it by URL ("http://loinc.org"). The value set has to be expanded
    # the same way the record stores it or nothing matches.
    by_name: bool = False
    # Any further "ignore this row" column this source has of its own, as pairs
    # so the spec stays immutable. `deleted` is already handled for every model
    # by the SDK's own manager.
    filters: tuple[tuple[str, Any], ...] = ()


_SPECS: dict[str, _SourceSpec] = {
    SOURCE_IMAGING: _SourceSpec(
        model=ImagingReport,
        patient_field="patient_id",
        system_field="codings__system",
        code_field="codings__code",
        date_field="result_date",
        committed=False,
    ),
    SOURCE_LAB: _SourceSpec(
        model=LabValue,
        patient_field="report__patient_id",
        system_field="codings__system",
        code_field="codings__code",
        date_field="report__date_performed",
        committed=False,
    ),
    SOURCE_PROCEDURE: _SourceSpec(
        model=Procedure,
        patient_field="patient_id",
        system_field="codings__system",
        code_field="codings__code",
        # When the procedure was performed, not when somebody typed it in. A
        # colonoscopy imported from an outside record would otherwise date from
        # the day it reached this chart and read as far more recent than it is.
        date_field="note__datetime_of_service",
        committed=True,
    ),
    SOURCE_QUESTIONNAIRE: _SourceSpec(
        model=Interview,
        patient_field="patient_id",
        system_field="questionnaires__code_system",
        code_field="questionnaires__code",
        date_field="created",
        committed=True,
        # Questionnaires are the one source storing the system by name.
        by_name=True,
    ),
    SOURCE_CONDITION: _SourceSpec(
        model=Condition,
        patient_field="patient_id",
        system_field="codings__system",
        code_field="codings__code",
        date_field="onset_date",
        committed=True,
    ),
    SOURCE_REFERRAL: _SourceSpec(
        model=ReferralReport,
        patient_field="patient_id",
        system_field="codings__system",
        code_field="codings__code",
        # The date the outside report carries, which is what the native
        # CMS130v6 reads too (`record["originalDate"]`). `created` would date a
        # colonoscopy from the day its report reached this chart.
        date_field="original_date",
        # ReferralReport has no committer - it is an inbound document, not
        # something a provider signs. `junked` is its own "ignore this".
        committed=False,
        filters=(("junked", False),),
    ),
}


def _as_date(value: Any) -> date | None:
    """Normalize whatever a source's date column holds to a plain date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _expand(value_set: Any, by_name: bool) -> set[tuple[str, str]]:
    """Every (code system, code) pair a value set covers, as the records store it.

    This mirrors the SDK's own ``ValueSetLookupQuerySetMixin.codings`` and its
    by-name variant. Those live on queryset mixins the plugin sandbox does not
    export, and the logic is four lines, so it is restated here rather than
    reached for through a private path. ``CODE_SYSTEM_MAPPING`` maps a system's
    name ("LOINC") to its URL ("http://loinc.org"); ``values`` holds the codes
    under the name.
    """
    values = value_set.values
    return {
        (name if by_name else url, code)
        for name, url in value_set.CODE_SYSTEM_MAPPING.items()
        if name in values
        for code in values[name]
    }


def _signal_matcher(signal: dict, by_name: bool) -> tuple[set[tuple[str, str]], set[str]]:
    """What this signal matches: (system, code) pairs, or bare codes.

    A signal naming a catalog value set matches on the system too, so a code
    that happens to collide across terminologies is not miscredited. A signal
    carrying its own codes matches on the code alone - an admin adding a
    practice-specific screening types a CPT code, not a terminology URL.
    """
    value_set = value_set_for(signal["value_set_key"]) if signal["value_set_key"] else None
    if value_set is not None:
        return _expand(value_set, by_name), set()
    return set(), set(signal["codes"])


def latest_dates(
    patient_dbids: list[int], signals: list[tuple[SignalKey, dict]]
) -> dict[int, dict[SignalKey, date]]:
    """The most recent date each signal was satisfied, per patient.

    Takes a *list* of patients on purpose. The scheduled sweep reviews a batch
    of them per run, and asking per patient made a run cost one set of these
    reads per patient - the same N+1 this module already avoids across
    screenings, reintroduced along the other axis. Batching both ways means a
    run of any size costs one query per distinct source in use.

    Signals with no qualifying record are simply absent from the result, as are
    patients with no qualifying record at all. A source that fails to read is
    logged and left absent too: an unreadable chart must never be reported as
    "never done", because that would put a recommendation in front of a
    provider on no evidence.
    """
    if not patient_dbids:
        return {}

    # A signal can name more than one source - a colonoscopy lives in the
    # procedure, referral or imaging table depending on how the result reached
    # the chart. It joins every one of those groups, and each group is still
    # one query for the whole batch.
    by_source: dict[str, list[tuple[SignalKey, dict]]] = {}
    for key, signal in signals:
        wanted = dict.fromkeys((signal["source"], *extra_sources_for(signal["value_set_key"])))
        for source in wanted:
            if source in _SPECS:
                by_source.setdefault(source, []).append((key, signal))

    # The latest date across every source wins. Merging with `update` would
    # have let whichever source happened to be read last overwrite a more
    # recent date from another - silently, and differently as sources came and
    # went from the config.
    found: dict[int, dict[SignalKey, date]] = {}
    for source, group in by_source.items():
        for dbid, dates in _read_source(patient_dbids, _SPECS[source], group).items():
            for_patient = found.setdefault(dbid, {})
            for key, when in dates.items():
                if key not in for_patient or when > for_patient[key]:
                    for_patient[key] = when
    return found


def _read_source(
    patient_dbids: list[int], spec: _SourceSpec, group: list[tuple[SignalKey, dict]]
) -> dict[int, dict[SignalKey, date]]:
    """Read one kind of record once for the whole batch, then attribute its rows.

    The patient column is selected alongside the code and date so rows can be
    handed back to the patient they belong to; without it a batched read could
    not tell one patient's colonoscopy from another's.
    """
    matchers = {key: _signal_matcher(signal, spec.by_name) for key, signal in group}
    wanted: set[str] = set()
    for pairs, codes in matchers.values():
        wanted.update(code for _system, code in pairs)
        wanted.update(codes)
    if not wanted:
        return {}

    try:
        queryset = spec.model.objects.filter(**{f"{spec.patient_field}__in": patient_dbids})
        if spec.committed:
            queryset = queryset.committed()
        if spec.filters:
            queryset = queryset.filter(**dict(spec.filters))
        rows = list(
            queryset.filter(**{f"{spec.code_field}__in": wanted}).values_list(
                spec.patient_field, spec.system_field, spec.code_field, spec.date_field
            )
        )
    except Exception as exc:  # an unreadable source must not become a false "never done"
        log.warning(
            f"preventive_screenings could not read {spec.model.__name__} "
            f"for {len(patient_dbids)} patient(s): {exc}"
        )
        return {}

    latest: dict[int, dict[SignalKey, date]] = {}
    # A row the query returned but nothing claimed is the quietest failure this
    # module has. The database matched the *code*; attribution also demands the
    # *system*, and a value set expanded to a system string the records do not
    # use matches nothing at all while looking perfectly healthy. That shipped
    # once already - `Interview` stores the system by name where everything
    # else stores a URL - and it was found only by printing the row.
    unclaimed: set[tuple[str, str]] = set()
    undated = 0
    for dbid, system, code, raw_date in rows:
        when = _as_date(raw_date)
        if when is None:
            undated += 1
            continue
        claimed = False
        for key, (pairs, codes) in matchers.items():
            if (system, code) in pairs or code in codes:
                claimed = True
                for_patient = latest.setdefault(dbid, {})
                if key not in for_patient or when > for_patient[key]:
                    for_patient[key] = when
        if not claimed:
            unclaimed.add((system, code))

    if unclaimed:
        log.info(
            f"preventive_screenings: {spec.model.__name__} returned "
            f"{len(unclaimed)} (system, code) pair(s) no signal claimed - the code "
            f"matched but the system did not: {sorted(unclaimed)[:5]}"
        )
    if undated:
        log.info(
            f"preventive_screenings: {spec.model.__name__} dropped {undated} row(s) "
            f"with no usable {spec.date_field}"
        )
    return latest


def snoozed_until(
    patient_dbids: list[int], card_keys: list[str], today: date
) -> dict[int, dict[str, date]]:
    """Which of our cards each patient has snoozed, and until when.

    A provider snoozing a card is saying "not this one, not now". Canvas already
    honours that by collapsing the card to a stub, but the stub keeps our title,
    and our title is where overdue lives - so a deferred screening went on
    shouting ``OVERDUE by 15 years`` at the person who had just deferred it.
    Reading the snooze lets the title say ``Snoozed`` instead.

    One query for the whole batch, like every other read here: filtered on the
    patient dbid column and on the card keys actually in use.

    **Not ``.committed()``.** That requires ``committer_id`` to be set, and if
    Canvas ever writes an override row without one, every snooze would silently
    stop registering - a failure with no symptom except the loud title coming
    back. ``deleted`` and ``entered_in_error`` are the real "ignore this"
    signals, and ``status`` is the override's own lifecycle; those are what is
    filtered.

    Expired snoozes are excluded in SQL rather than in Python, so a snooze that
    has run out simply does not come back and the card returns to normal on its
    own. ``services.screenings.next_change_date`` is what schedules the sweep to
    notice, since nothing fires an event when a date passes.
    """
    if not patient_dbids or not card_keys:
        return {}

    wanted = set(card_keys)
    try:
        rows = list(
            ProtocolOverride.objects.filter(patient_id__in=patient_dbids)
            .order_by("snooze_date")
            .values_list(
                "patient_id",
                "protocol_key",
                "snooze_date",
                "is_snooze",
                "status",
                "entered_in_error_id",
            )
        )
    except Exception as exc:  # a snooze we cannot read must not hide the card
        log.warning(
            f"preventive_screenings could not read snoozes "
            f"for {len(patient_dbids)} patient(s): {exc}"
        )
        return {}

    # Every condition is applied here rather than in SQL, on purpose and for now.
    #
    # Nothing in the SDK says what Canvas writes onto the override row when a
    # provider snoozes a *plugin's* card - not the `protocol_key` format, and
    # not which of these flags it sets. Two guesses have already been wrong, and
    # each cost a deploy to disprove because a row rejected in SQL is a row you
    # cannot see. Rejecting in Python means the reason is printable.
    #
    # Only an *unexpected* rejection is logged. `inactive` in particular is a
    # normal, transient state - snoozing is a command in a note, and the row
    # sits inactive between staging it and recording it - so reporting it made
    # four lines of noise on every single snooze. A key matching no card is the
    # one reason that means something is actually wrong.
    # `deleted` is not checked here, and must not be: the SDK's own
    # BaseModelManager.get_queryset already filters deleted=False, so a deleted
    # row never arrives and a check for one would be unreachable. `snooze_date`
    # is likewise non-null on the model.
    unexpected: list[str] = []
    found: dict[int, dict[str, date]] = {}
    for dbid, key, when, is_snooze, status, in_error in rows:
        why = None
        if not is_snooze:
            why = "not a snooze"
        elif in_error is not None:
            why = "entered in error"
        elif str(status) != "active":
            why = f"status={status!r}"
        elif when < today:
            why = f"expired {when}"
        elif _card_key_of(str(key)) not in wanted:
            why = _UNKNOWN_KEY

        if why is None:
            found.setdefault(int(dbid), {})[_card_key_of(str(key))] = when
        elif why == _UNKNOWN_KEY:
            unexpected.append(repr(key))

    if unexpected:
        log.info(
            f"preventive_screenings: snooze against a key matching no card - "
            f"present={unexpected} asked={sorted(wanted)}"
        )
    return found
