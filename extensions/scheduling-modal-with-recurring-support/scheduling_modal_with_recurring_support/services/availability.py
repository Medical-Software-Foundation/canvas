from datetime import date, datetime, timedelta, timezone
from typing import Any, NamedTuple

from canvas_sdk.utils import Http

from scheduling_modal_with_recurring_support.services.recurrence import (
    MAX_OCCURRENCES,
    RecurrenceRule,
    iter_candidate_first_dates,
    project_dates,
)

# MAX_OCCURRENCES is re-exported from .recurrence so existing call sites and
# tests that import it from this module continue to work during the
# transitional release.
__all__ = [
    "CandidateTimeAggregate",
    "FirstDateAggregate",
    "FirstDateSeriesScore",
    "FreeSlot",
    "MAX_OCCURRENCES",
    "RecurrenceAnalysis",
    "SeriesScore",
    "SlotAvailability",
    "aggregate_by_candidate_time",
    "aggregate_by_first_date",
    "analyse_recurrence",
    "best_series_availability",
    "iter_free_slots",
    "lookup_window",
    "series_scores_by_first_date",
]


DEFAULT_DURATION_MINUTES = 60


class FreeSlot(NamedTuple):
    start: str
    end: str


class SlotAvailability(NamedTuple):
    occurrence_date: date
    available_times: list[FreeSlot]
    is_available: bool


class RecurrenceAnalysis(NamedTuple):
    slots: list[SlotAvailability]
    available_count: int
    total_count: int
    availability_pct: float


class CandidateTimeAggregate(NamedTuple):
    hhmm: str
    available_count: int
    total_count: int
    availability_pct: float


class FirstDateAggregate(NamedTuple):
    first_date: date
    occurrence_dates: list[date]
    available_count: int
    total_count: int
    availability_pct: float


class SeriesScore(NamedTuple):
    available_count: int
    total_count: int
    best_hhmm: str


class FirstDateSeriesScore(NamedTuple):
    first_date: date
    available_count: int
    total_count: int
    best_hhmm: str


def analyse_recurrence(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    rule: RecurrenceRule,
    start_date: date,
    tz_offset_minutes: int = 0,
    now: datetime | None = None,
) -> RecurrenceAnalysis:
    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)
    target_dates = project_dates(start_date, rule)

    memo: dict[date, SlotAvailability] = {}
    _prefill_memo_for_range(
        memo, fhir_base_url, access_token, schedule_id, set(target_dates),
        tz_offset_minutes=tz_offset_minutes, now=now,
    )

    slots = [
        memo.get(d) or _check_slot(fhir_base_url, access_token, schedule_id, d)
        for d in target_dates
    ]

    available_count = sum(1 for s in slots if s.is_available)
    total = len(slots)
    pct = (available_count / total * 100) if total > 0 else 0.0

    return RecurrenceAnalysis(
        slots=slots,
        available_count=available_count,
        total_count=total,
        availability_pct=round(pct, 1),
    )


def aggregate_by_candidate_time(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    rule: RecurrenceRule,
    start_date: date,
    tz_offset_minutes: int = 0,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    now: datetime | None = None,
) -> list[CandidateTimeAggregate]:
    """Pivot recurrence availability by candidate start time on the start date.

    For each candidate time on start_date, count how many occurrence dates have
    a free slot at the same local hhmm. Returns one aggregate per candidate
    time, ordered by hhmm. Slot lookups run at duration_minutes so the count
    reflects the real appointment length rather than the default.
    """
    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)
    target_dates = project_dates(start_date, rule)

    memo: dict[date, SlotAvailability] = {}
    _prefill_memo_for_range(
        memo, fhir_base_url, access_token, schedule_id, set(target_dates),
        duration_minutes, tz_offset_minutes, now,
    )

    client_tz = timezone(timedelta(minutes=-tz_offset_minutes))

    per_date_hhmm: list[set[str]] = []
    candidate_hhmms_in_order: list[str] = []
    seen: set[str] = set()

    for i, d in enumerate(target_dates):
        slot_avail = memo.get(d) or _check_slot(
            fhir_base_url, access_token, schedule_id, d, duration_minutes
        )
        hhmm_set = {
            _fhir_to_local_hhmm(t.start, client_tz)
            for t in slot_avail.available_times
        }
        per_date_hhmm.append(hhmm_set)

        if i == 0:
            for t in slot_avail.available_times:
                hh = _fhir_to_local_hhmm(t.start, client_tz)
                if hh not in seen:
                    seen.add(hh)
                    candidate_hhmms_in_order.append(hh)

    total = len(target_dates)
    aggregates: list[CandidateTimeAggregate] = []
    for hh in candidate_hhmms_in_order:
        free = sum(1 for s in per_date_hhmm if hh in s)
        pct = (free / total * 100) if total > 0 else 0.0
        aggregates.append(
            CandidateTimeAggregate(
                hhmm=hh,
                available_count=free,
                total_count=total,
                availability_pct=round(pct, 1),
            )
        )
    return aggregates


def best_series_availability(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    rule: RecurrenceRule,
    start_date: date,
    tz_offset_minutes: int = 0,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    now: datetime | None = None,
) -> SeriesScore:
    """Score the best achievable series for one provider on a fixed start date.

    A recurring series shares a single start time across its occurrences, so
    the best the provider can do is the candidate start time on the start date
    that the most occurrences are free at, at the real duration. When the start
    date itself has no open slot there is no candidate time to anchor on, the
    series cannot start, and the score is zero out of the projected occurrence
    count.

    This is the per provider card scorer. It reads the same prefilled memo and
    runs the same _series_score_from_memo core that backs the calendar badge
    through series_scores_by_first_date, so the card and the badge cannot
    disagree for one provider on one date.
    """
    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)
    occurrence_dates = project_dates(start_date, rule)

    memo: dict[date, SlotAvailability] = {}
    _prefill_memo_for_range(
        memo,
        fhir_base_url,
        access_token,
        schedule_id,
        set(occurrence_dates),
        duration_minutes,
        tz_offset_minutes,
        now,
    )

    client_tz = timezone(timedelta(minutes=-tz_offset_minutes))
    return _series_score_from_memo(memo, occurrence_dates, client_tz)


def _series_score_from_memo(
    memo: dict[date, SlotAvailability],
    occurrence_dates: list[date],
    client_tz: timezone,
) -> SeriesScore:
    """Compute the best achievable series for one provider from a filled memo.

    A recurring series shares a single start time, so the best the provider
    can do is the candidate time on the start date that the most occurrences
    are free at. This is the same logic as best_series_availability, but it
    reads pre fetched slots out of memo rather than issuing its own lookups,
    so a single provider window can be scored across many candidate first
    dates without re fetching. When the start date itself has no open slot
    there is no candidate time to anchor on and the score is zero out of the
    projected occurrence count.
    """
    total = len(occurrence_dates)
    if total == 0:
        return SeriesScore(available_count=0, total_count=0, best_hhmm="")

    start_avail = memo.get(occurrence_dates[0])
    start_times = start_avail.available_times if start_avail else []
    if not start_times:
        return SeriesScore(available_count=0, total_count=total, best_hhmm="")

    per_date_hhmm: list[set[str]] = []
    for d in occurrence_dates:
        avail = memo.get(d)
        times = avail.available_times if avail else []
        per_date_hhmm.append({_fhir_to_local_hhmm(t.start, client_tz) for t in times})

    best_count = 0
    best_hhmm = ""
    seen: set[str] = set()
    for t in start_times:
        hh = _fhir_to_local_hhmm(t.start, client_tz)
        if hh in seen:
            continue
        seen.add(hh)
        free = sum(1 for s in per_date_hhmm if hh in s)
        if free > best_count:
            best_count = free
            best_hhmm = hh

    return SeriesScore(available_count=best_count, total_count=total, best_hhmm=best_hhmm)


def series_scores_by_first_date(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    rule: RecurrenceRule,
    window_start: date,
    window_end: date,
    tz_offset_minutes: int = 0,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    now: datetime | None = None,
) -> list[FirstDateSeriesScore]:
    """For each candidate first date in the window, the best series this
    provider can take starting that day.

    Unlike aggregate_by_first_date, which counts occurrence dates with any
    open slot, this scores the series the way a real booking works, the most
    occurrences free at one shared start time. It backs the provider agnostic
    calendar badge, can this provider cover the full series from this day. The
    whole window is fetched into one memo, the union of every candidate's
    occurrence dates, so a provider is scored across all candidate first dates
    for one or a few range Slot calls rather than per date.
    """
    if window_end < window_start:
        return []

    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)

    candidate_first_dates = list(
        iter_candidate_first_dates(rule, window_start, window_end)
    )
    occurrence_sets = [project_dates(fd, rule) for fd in candidate_first_dates]
    unique_dates: set[date] = {d for occ in occurrence_sets for d in occ}

    memo: dict[date, SlotAvailability] = {}
    _prefill_memo_for_range(
        memo, fhir_base_url, access_token, schedule_id, unique_dates,
        duration_minutes, tz_offset_minutes, now,
    )

    client_tz = timezone(timedelta(minutes=-tz_offset_minutes))

    scores: list[FirstDateSeriesScore] = []
    for first_date, occurrence_dates in zip(candidate_first_dates, occurrence_sets):
        score = _series_score_from_memo(memo, occurrence_dates, client_tz)
        scores.append(
            FirstDateSeriesScore(
                first_date=first_date,
                available_count=score.available_count,
                total_count=score.total_count,
                best_hhmm=score.best_hhmm,
            )
        )
    return scores


def aggregate_by_first_date(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    rule: RecurrenceRule,
    window_start: date,
    window_end: date,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    tz_offset_minutes: int = 0,
    now: datetime | None = None,
) -> list[FirstDateAggregate]:
    """Pivot recurrence availability by candidate first date across the window.

    For each date in [window_start, window_end] that the rule allows as a
    starting date, project the occurrences and score how many of the
    occurrence slots are free. Slot lookups are memoised within the request
    so overlapping occurrence sets across candidates only hit FHIR once per
    unique date.
    """
    if window_end < window_start:
        return []

    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)

    candidate_first_dates = list(
        iter_candidate_first_dates(rule, window_start, window_end)
    )
    occurrence_sets = [project_dates(fd, rule) for fd in candidate_first_dates]
    unique_dates: set[date] = {d for occ in occurrence_sets for d in occ}

    memo: dict[date, SlotAvailability] = {}
    _prefill_memo_for_range(
        memo, fhir_base_url, access_token, schedule_id, unique_dates,
        duration_minutes, tz_offset_minutes, now,
    )

    def slot_for(d: date) -> SlotAvailability:
        if d not in memo:
            memo[d] = _check_slot(
                fhir_base_url, access_token, schedule_id, d, duration_minutes
            )
        return memo[d]

    aggregates: list[FirstDateAggregate] = []
    for first_date, occurrence_dates in zip(candidate_first_dates, occurrence_sets):
        slots = [slot_for(d) for d in occurrence_dates]
        available = sum(1 for s in slots if s.is_available)
        total = len(occurrence_dates)
        pct = (available / total * 100) if total > 0 else 0.0
        aggregates.append(
            FirstDateAggregate(
                first_date=first_date,
                occurrence_dates=occurrence_dates,
                available_count=available,
                total_count=total,
                availability_pct=round(pct, 1),
            )
        )
    return aggregates


def iter_free_slots(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    window_start: date,
    window_end: date,
    limit: int,
):
    """Yield free slots for the provider across the date span, ordered.

    Walks each date in [window_start, window_end] one day at a time, queries
    the slot bundle for that date, and yields each free slot in start-time
    order. Stops as soon as `limit` slots have been yielded or the window is
    exhausted. Returns immediately on an inverted window without making any
    HTTP calls.
    """
    if window_end < window_start or limit <= 0:
        return

    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)

    yielded = 0
    current = window_start
    while current <= window_end and yielded < limit:
        slot_avail = _check_slot(fhir_base_url, access_token, schedule_id, current)
        for free in slot_avail.available_times:
            yield free
            yielded += 1
            if yielded >= limit:
                return
        current = current + timedelta(days=1)


def lookup_window(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    window_start: date,
    window_end: date,
    tz_offset_minutes: int = 0,
    duration_minutes: int | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Fetch the FHIR Slot bundle for a date window in one call and bucket by
    local date. Used by the row level date combobox in the scheduling modal
    so that twelve recurrence rows do not each fan out their own per day
    Slot lookup.

    Returns a mapping of `date_iso -> [{"hhmm", "start", "end"}, ...]` with
    times ordered as Fumage returned them. Returns an empty dict on a non
    OK response or on an empty bundle.
    """
    duration = duration_minutes if duration_minutes is not None else DEFAULT_DURATION_MINUTES
    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)
    http = Http()
    url = (
        f"{fhir_base_url}/Slot"
        f"?schedule={schedule_id}"
        f"&start={window_start.isoformat()}"
        f"&end={window_end.isoformat()}"
        f"&duration={duration}"
        f"&_count=500"
    )
    resp = http.get(url, headers=_auth_headers(access_token))
    if not getattr(resp, "ok", False):
        return {}

    client_tz = timezone(timedelta(minutes=-tz_offset_minutes))
    bundle: dict = resp.json()
    by_date: dict[str, list[dict[str, str]]] = {}

    for entry in bundle.get("entry", []) or []:
        resource = entry.get("resource", {}) or {}
        start_iso = resource.get("start", "")
        end_iso = resource.get("end", "")
        if not start_iso or not end_iso:
            continue
        local_dt = _to_local_datetime(start_iso, client_tz)
        date_key = local_dt.date().isoformat()
        hhmm = local_dt.strftime("%H:%M")
        by_date.setdefault(date_key, []).append(
            {"hhmm": hhmm, "start": start_iso, "end": end_iso}
        )

    return by_date


def _fhir_to_local_hhmm(iso_str: str, client_tz: timezone) -> str:
    """Convert a FHIR ISO datetime to HH:MM in the client's timezone.

    Handles UTC ('Z'), offset aware ('+00:00', '-04:00'), and naive formats.
    Naive datetimes are assumed to already be in client local time.
    """
    if "T" not in iso_str:
        return iso_str[:5]
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(client_tz)
    return dt.strftime("%H:%M")


def _to_local_datetime(iso_str: str, client_tz: timezone) -> datetime:
    """Parse a FHIR ISO datetime to a datetime in the client's timezone.

    Same offset handling as _fhir_to_local_hhmm. Naive datetimes are
    interpreted as already in client local time. The bucketing helper
    needs both the local date and the local time, so it parses once here
    rather than calling _fhir_to_local_hhmm twice.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(client_tz)
    return dt


def _resolve_schedule_id(fhir_base_url: str, access_token: str, provider_id: str) -> str:
    http = Http()
    url = f"{fhir_base_url}/Schedule?actor=Practitioner/{provider_id}"
    resp = http.get(url, headers=_auth_headers(access_token))

    if not resp.ok:
        raise RuntimeError(f"FHIR Schedule lookup failed: {resp.status_code} {resp.text}")

    bundle: dict = resp.json()
    entries = bundle.get("entry", [])

    for entry in entries:
        sid = entry.get("resource", {}).get("id", "")
        if provider_id in sid:
            return sid

    if not entries:
        raise ValueError(f"No FHIR Schedule found for provider {provider_id}")

    return entries[0]["resource"]["id"]


# Worst case headroom for monthly N=4 rules, which can project occurrences
# up to roughly 90 days from the displayed window. Sets the cap for one
# range Slot lookup so a single bundle stays under the SDK 30 second budget.
MAX_RANGE_DAYS = 90


def _fetch_slots_by_date_range(
    fhir_base_url: str,
    access_token: str,
    schedule_id: str,
    window_start: date,
    window_end: date,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    tz_offset_minutes: int = 0,
    now: datetime | None = None,
) -> dict[date, list[FreeSlot]]:
    """Fetch the FHIR Slot bundle for a date range in one call and bucket
    the entries by their local date in the client timezone.

    Fumage stamps each Slot `start` in the clinic's own zone, for example
    `2026-06-18T09:00:00-07:00`, so the bare `start[:10]` prefix is the clinic
    date, not the scheduler's local date. The scorer then localises the time of
    day to the browser through `_fhir_to_local_hhmm`, and the row date combobox
    buckets by the localised date through `lookup_window`. Bucketing here on the
    same localised date keeps the calendar badge and the provider cards on the
    same day a slot belongs to in the scheduler's timezone, so they cannot
    disagree across a midnight boundary when the browser zone differs from the
    clinic zone. Returns an empty dict on a non OK response.
    """
    http = Http()
    url = (
        f"{fhir_base_url}/Slot"
        f"?schedule={schedule_id}"
        f"&start={window_start.isoformat()}"
        f"&end={window_end.isoformat()}"
        f"&duration={duration_minutes}"
        f"&_count=500"
    )
    resp = http.get(url, headers=_auth_headers(access_token))
    if not getattr(resp, "ok", False):
        return {}

    client_tz = timezone(timedelta(minutes=-tz_offset_minutes))
    bundle: dict = resp.json()
    by_date: dict[date, list[FreeSlot]] = {}

    for entry in bundle.get("entry", []) or []:
        resource = entry.get("resource", {}) or {}
        start_iso = resource.get("start", "")
        end_iso = resource.get("end", "")
        if not start_iso or not end_iso:
            continue
        try:
            bucket = _to_local_datetime(start_iso, client_tz).date()
        except ValueError:
            continue
        by_date.setdefault(bucket, []).append(FreeSlot(start=start_iso, end=end_iso))

    def _finalize(slots: list[FreeSlot]) -> list[FreeSlot]:
        kept = _filter_non_overlapping(slots)
        if now is not None:
            kept = _drop_elapsed_slots(kept, now)
        return kept

    return {d: _finalize(slots) for d, slots in by_date.items()}


def _prefill_memo_for_range(
    memo: dict[date, SlotAvailability],
    fhir_base_url: str,
    access_token: str,
    schedule_id: str,
    dates: set[date],
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    tz_offset_minutes: int = 0,
    now: datetime | None = None,
) -> None:
    """Bulk fetch the union date set in one or more range calls and write
    a `SlotAvailability` entry for every requested date into `memo`.

    Splits into consecutive chunks of at most `MAX_RANGE_DAYS` days when
    the span exceeds the cap. Dates absent from the bundle get an empty
    `SlotAvailability` so the memo answer matches `_check_slot` returning
    zero entries for that day.

    The fetch window is padded one day on each side of the requested span.
    The server filters Slots by the clinic date, while the bundle is bucketed
    by the localised date, so a slot whose clinic date sits just outside the
    requested span can still land on a requested local date once the browser
    offset is applied. The pad makes those boundary slots reachable, and the
    write loop below keeps only the requested dates, so the pad never widens
    the answer set.
    """
    if not dates:
        return

    lo = min(dates)
    hi = max(dates)
    fetch_lo = lo - timedelta(days=1)
    fetch_hi = hi + timedelta(days=1)
    span = (fetch_hi - fetch_lo).days + 1

    by_date: dict[date, list[FreeSlot]] = {}
    if span <= MAX_RANGE_DAYS:
        by_date = _fetch_slots_by_date_range(
            fhir_base_url, access_token, schedule_id, fetch_lo, fetch_hi,
            duration_minutes, tz_offset_minutes, now,
        )
    else:
        chunk_start = fetch_lo
        while chunk_start <= fetch_hi:
            chunk_end = chunk_start + timedelta(days=MAX_RANGE_DAYS - 1)
            if chunk_end > fetch_hi:
                chunk_end = fetch_hi
            chunk = _fetch_slots_by_date_range(
                fhir_base_url, access_token, schedule_id, chunk_start, chunk_end,
                duration_minutes, tz_offset_minutes, now,
            )
            for d, free_slots in chunk.items():
                by_date.setdefault(d, []).extend(free_slots)
            chunk_start = chunk_end + timedelta(days=1)

    for d in dates:
        free_slots = by_date.get(d, [])
        memo[d] = SlotAvailability(
            occurrence_date=d,
            available_times=free_slots,
            is_available=bool(free_slots),
        )


def _check_slot(
    fhir_base_url: str,
    access_token: str,
    schedule_id: str,
    target_date: date,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
) -> SlotAvailability:
    http = Http()
    target_iso = target_date.isoformat()

    url = (
        f"{fhir_base_url}/Slot"
        f"?schedule={schedule_id}"
        f"&start={target_iso}"
        f"&end={target_iso}"
        f"&duration={duration_minutes}"
        f"&_count=500"
    )

    resp = http.get(url, headers=_auth_headers(access_token))
    day_slots = _extract_slots(resp)

    return SlotAvailability(
        occurrence_date=target_date,
        available_times=day_slots,
        is_available=len(day_slots) > 0,
    )


def _extract_slots(response: Any) -> list[FreeSlot]:
    if not getattr(response, "ok", False):
        return []
    bundle: dict = response.json()
    entries = bundle.get("entry", [])
    slots = [
        FreeSlot(
            start=entry["resource"]["start"],
            end=entry["resource"]["end"],
        )
        for entry in entries
        if "resource" in entry and "start" in entry["resource"] and "end" in entry["resource"]
    ]
    return _filter_non_overlapping(slots)


def _filter_non_overlapping(slots: list[FreeSlot]) -> list[FreeSlot]:
    """Collapse one day's slots to a greedy non overlapping series.

    Fumage returns the union of a fixed fifteen minute base grid and a
    duration stepped grid anchored at the clinic window start, so any
    requested duration that is not a multiple of fifteen interleaves the two
    grids and yields overlapping appointment windows. Two overlapping slots
    cannot both be booked, yet both otherwise render as bookable time pills.
    Sorting by start and keeping a slot only when it begins at or after the
    previous kept slot's end leaves a clean back to back series at the real
    appointment length, every offered time genuinely bookable alongside the
    others. The fumage `end` already encodes the requested duration, so it is
    the slot's true occupied window. Slots with an unparseable start or end are
    dropped. Applied at the extraction boundary so the calendar badge, the
    provider cards, and the time pills all read the same slot set.
    """
    parsed: list[tuple[datetime, datetime, FreeSlot]] = []
    for slot in slots:
        try:
            start_dt = datetime.fromisoformat(slot.start)
            end_dt = datetime.fromisoformat(slot.end)
        except ValueError:
            continue
        parsed.append((start_dt, end_dt, slot))

    parsed.sort(key=lambda item: item[0])

    kept: list[FreeSlot] = []
    last_end: datetime | None = None
    for start_dt, end_dt, slot in parsed:
        if last_end is None or start_dt >= last_end:
            kept.append(slot)
            last_end = end_dt
    return kept


def _utcnow() -> datetime:
    """Current UTC instant. Extracted for test mockability."""
    return datetime.now(timezone.utc)


def _drop_elapsed_slots(slots: list[FreeSlot], now: datetime) -> list[FreeSlot]:
    """Drop slots whose start instant is at or before now.

    A slot start is an absolute instant, so this needs no timezone math, only a
    comparison. Only today is ever affected, past dates are blocked by route
    validation and a future date carries no elapsed slots. The compare is strict
    greater than, so a slot starting exactly now is treated as already gone.
    Slots with an unparseable start are dropped, matching _filter_non_overlapping.
    """
    kept: list[FreeSlot] = []
    for s in slots:
        try:
            start_dt = datetime.fromisoformat(s.start)
        except ValueError:
            continue
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=now.tzinfo)
        if start_dt > now:
            kept.append(s)
    return kept


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _count_free_slots(
    fhir_base_url: str,
    access_token: str,
    provider_id: str,
    location_id: str,
    start_date: date,
    end_date: date,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
) -> int:
    """Count FHIR slots returned for the provider over the window."""
    schedule_id = _resolve_schedule_id(fhir_base_url, access_token, provider_id)
    http = Http()
    url = (
        f"{fhir_base_url}/Slot"
        f"?schedule={schedule_id}"
        f"&start={start_date.isoformat()}"
        f"&end={end_date.isoformat()}"
        f"&duration={duration_minutes}"
        f"&_count=500"
    )
    resp = http.get(url, headers=_auth_headers(access_token))
    if not resp.ok:
        return 0
    bundle: dict = resp.json()
    return len(bundle.get("entry", []))
