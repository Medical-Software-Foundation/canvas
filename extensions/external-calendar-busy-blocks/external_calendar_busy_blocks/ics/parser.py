from datetime import datetime, timedelta, timezone

from external_calendar_busy_blocks.ics.datetimes import parse_ics_datetime
from external_calendar_busy_blocks.ics.rrule import (
    RRuleUnsupported,
    expand_rrule,
    parse_rrule,
)
from logger import log

from external_calendar_busy_blocks.ics.types import IcsParseError, ParsedEvent

RRULE_CAP_PER_VEVENT = 1000


def unfold_lines(body: bytes) -> list[str]:
    """Decode and unfold an ICS body into logical lines.

    RFC 5545 §3.1: long lines may be folded by inserting CRLF followed by
    one linear whitespace character. The entire fold sequence (CRLF + WSP)
    is removed during unfolding.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IcsParseError(f"feed is not valid UTF-8: {exc}") from exc

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    folded: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        if line[0] in (" ", "\t") and folded:
            folded[-1] += line[1:]
        else:
            folded.append(line)
    return folded


Property = tuple[str, dict[str, str], str]


def parse_property_line(line: str) -> Property:
    """Parse one content line into (name, params, value).

    Handles:
        SUMMARY:hello
        DTSTART;TZID=America/New_York:20260601T090000
        ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:x@y.com
    """
    colon_idx = -1
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon_idx = i
            break
    if colon_idx == -1:
        raise IcsParseError(f"malformed property line (no colon): {line!r}")

    head = line[:colon_idx]
    value = line[colon_idx + 1 :]

    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        params[k.upper()] = v.strip('"')
    return name, params, value


def extract_vevents(lines: list[str]) -> list[list[Property]]:
    """Return one list of properties per VEVENT block."""
    if not lines or lines[0].upper() != "BEGIN:VCALENDAR":
        raise IcsParseError("body does not begin with BEGIN:VCALENDAR")

    events: list[list[Property]] = []
    current: list[Property] | None = None
    in_vevent = False

    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            in_vevent = True
            current = []
            continue
        if upper == "END:VEVENT":
            in_vevent = False
            if current is not None:
                events.append(current)
            current = None
            continue
        if in_vevent and current is not None:
            try:
                current.append(parse_property_line(line))
            except IcsParseError as exc:
                # A single malformed line must not kill the whole feed. Poison
                # this VEVENT and skip the rest of its lines until END:VEVENT;
                # other VEVENTs in the body still parse.
                log.warning("Dropping VEVENT with malformed line: %s", exc)
                current = None
                in_vevent = False

    return events


def _find_property(props: list[Property], name: str) -> Property | None:
    name = name.upper()
    for prop in props:
        if prop[0] == name:
            return prop
    return None


def _calendar_default_tz(lines: list[str]) -> str:
    for line in lines:
        if line.upper().startswith("X-WR-TIMEZONE:"):
            return line.split(":", 1)[1].strip()
    return "UTC"


def _should_skip(props: list[Property]) -> bool:
    status_prop = _find_property(props, "STATUS")
    if status_prop and status_prop[2].upper() in ("CANCELLED", "TENTATIVE"):
        return True
    transp_prop = _find_property(props, "TRANSP")
    if transp_prop and transp_prop[2].upper() == "TRANSPARENT":
        return True
    return False


def _collect_exdates(props: list[Property], default_tz: str) -> set[datetime]:
    out: set[datetime] = set()
    for name, params, value in props:
        if name != "EXDATE":
            continue
        for piece in value.split(","):
            dv = parse_ics_datetime(piece, params, default_tz)
            out.add(dv.moment)
    return out


def _build_override_event(
    override_props: list[Property],
    uid: str,
    rid_key: str,
    base_duration: timedelta,
    sequence: int,
    default_tz: str,
) -> "ParsedEvent | None":
    """Build a ParsedEvent from a RECURRENCE-ID override VEVENT.

    Returns None when the override is unusable (missing DTSTART, or DTSTART/
    DTEND that cannot be parsed) so the caller can fall back to the base
    occurrence rather than dropping it — and, critically, rather than letting a
    parse error escape and discard the whole recurring series. A missing DTEND
    inherits the base occurrence's duration, matching real calendar clients.
    """
    ovs_prop = _find_property(override_props, "DTSTART")
    if ovs_prop is None:
        return None
    try:
        ovs = parse_ics_datetime(ovs_prop[2], ovs_prop[1], default_tz)
        ove_prop = _find_property(override_props, "DTEND")
        if ove_prop is not None:
            ends_at = parse_ics_datetime(ove_prop[2], ove_prop[1], default_tz).moment
        else:
            ends_at = ovs.moment + base_duration
    except IcsParseError:
        return None
    return ParsedEvent(
        uid=uid,
        recurrence_id=rid_key,
        starts_at=ovs.moment,
        ends_at=ends_at,
        is_all_day=ovs.is_all_day,
        sequence=sequence,
    )


def _format_recurrence_id(moment: datetime, is_all_day: bool) -> str:
    if is_all_day:
        return moment.strftime("%Y%m%d")
    return moment.strftime("%Y%m%dT%H%M%SZ")


def parse_ics(
    body: bytes,
    now: datetime,
    lookahead_days: int,
) -> list[ParsedEvent]:
    """Parse an ICS body to ParsedEvents within [now, now+lookahead_days].

    Recurring events are expanded via RRULE (capped at RRULE_CAP_PER_VEVENT),
    EXDATE moments are excluded, and RECURRENCE-ID overrides are applied.
    """
    lines = unfold_lines(body)
    default_tz = _calendar_default_tz(lines)
    vevents = extract_vevents(lines)

    window_end = now + timedelta(days=lookahead_days)

    # First pass: index overrides by (uid, recurrence_id) so we can apply them
    # while expanding the base RRULE in the second pass.
    overrides: dict[tuple[str, str], list[Property]] = {}
    base_events: list[list[Property]] = []
    for props in vevents:
        uid_prop = _find_property(props, "UID")
        rid_prop = _find_property(props, "RECURRENCE-ID")
        if uid_prop and rid_prop:
            # Normalize the RECURRENCE-ID key the same way the expansion lookup
            # does, so feeds that express RECURRENCE-ID in a local TZID (Google,
            # Outlook, Apple) match the UTC-normalized key produced during
            # expansion. Indexing by the raw string would only match feeds that
            # happen to emit UTC Zulu.
            try:
                rid_dv = parse_ics_datetime(rid_prop[2], rid_prop[1], default_tz)
            except IcsParseError as exc:
                log.warning(
                    "Dropping RECURRENCE-ID override uid=%s: %s", uid_prop[2], exc
                )
                continue
            rid_key = _format_recurrence_id(rid_dv.moment, rid_dv.is_all_day)
            overrides[(uid_prop[2], rid_key)] = props
        else:
            base_events.append(props)

    out: list[ParsedEvent] = []
    for props in base_events:
        uid_prop = _find_property(props, "UID")
        # Isolate per-VEVENT failures: a single event with an unrecognized TZID
        # (e.g. Outlook's "Eastern Standard Time") or malformed date must not
        # discard every other valid event in the feed. Drop it and continue,
        # matching the RRuleUnsupported handling below.
        try:
            out.extend(
                _parse_base_event(props, overrides, default_tz, now, window_end)
            )
        except IcsParseError as exc:
            uid = uid_prop[2] if uid_prop else "<unknown>"
            log.warning("Dropping VEVENT uid=%s: %s", uid, exc)
            continue
    return out


def _parse_base_event(
    props: list[Property],
    overrides: dict[tuple[str, str], list[Property]],
    default_tz: str,
    now: datetime,
    window_end: datetime,
) -> list[ParsedEvent]:
    """Expand one base VEVENT into its in-window ParsedEvents.

    Raises IcsParseError on unparseable dates/timezones so the caller can drop
    just this event. Returns an empty list for events that are filtered out
    (skipped status, missing fields, unsupported recurrence, out of window).
    """
    if _should_skip(props):
        return []
    uid_prop = _find_property(props, "UID")
    dtstart_prop = _find_property(props, "DTSTART")
    dtend_prop = _find_property(props, "DTEND")
    if not uid_prop or not dtstart_prop or not dtend_prop:
        return []

    starts = parse_ics_datetime(dtstart_prop[2], dtstart_prop[1], default_tz)
    ends = parse_ics_datetime(dtend_prop[2], dtend_prop[1], default_tz)
    duration = ends.moment - starts.moment

    seq_prop = _find_property(props, "SEQUENCE")
    try:
        sequence = int(seq_prop[2]) if seq_prop else 0
    except ValueError as exc:
        # Convert to IcsParseError so the per-VEVENT guard drops just this
        # event instead of letting a ValueError abort the whole cron tick.
        raise IcsParseError(f"invalid SEQUENCE: {seq_prop[2]!r}") from exc

    rrule_prop = _find_property(props, "RRULE")
    if rrule_prop is None:
        if ends.moment <= now or starts.moment >= window_end:
            return []
        return [
            ParsedEvent(
                uid=uid_prop[2],
                recurrence_id=None,
                starts_at=starts.moment,
                ends_at=ends.moment,
                is_all_day=starts.is_all_day,
                sequence=sequence,
            )
        ]

    try:
        rule = parse_rrule(rrule_prop[2])
    except RRuleUnsupported as exc:
        log.warning("Dropping VEVENT uid=%s: %s", uid_prop[2], exc)
        return []

    exdates = _collect_exdates(props, default_tz)

    # Expand from `now - duration` so an occurrence that is currently in
    # progress (started before now, ends after now) is still produced — the
    # same guarantee the non-recurring branch gives via `ends.moment <= now`.
    # Without this, the cron's diff would delete an in-progress recurrence's
    # Busy block mid-meeting (its row survives the ends_at>=now filter but the
    # parser wouldn't re-emit it). Each yielded moment is then filtered to drop
    # instances that have already fully ended.
    # Expand against the LOCAL (tz-aware) DTSTART so BYDAY / BYMONTHDAY land on
    # the correct local calendar day; convert each occurrence back to UTC at the
    # boundary. Window bounds stay in UTC — comparing tz-aware datetimes across
    # zones compares absolute instants, which is correct.
    out: list[ParsedEvent] = []
    for moment_local in expand_rrule(
        rule, starts.local, now - duration, window_end, cap=RRULE_CAP_PER_VEVENT,
    ):
        moment = moment_local.astimezone(timezone.utc)
        if moment + duration <= now:
            continue
        if moment in exdates:
            continue
        rid_key = _format_recurrence_id(moment, starts.is_all_day)
        override_props = overrides.get((uid_prop[2], rid_key))
        if override_props is not None:
            if _should_skip(override_props):
                # The override cancels/declines this specific instance.
                continue
            override_event = _build_override_event(
                override_props, uid_prop[2], rid_key, duration, sequence, default_tz
            )
            if override_event is not None:
                out.append(override_event)
                continue
            # Override unparseable or missing DTSTART -> fall through to the
            # base occurrence rather than dropping the instance or the series.
            log.warning(
                "Override for uid=%s rid=%s unusable; using base time",
                uid_prop[2],
                rid_key,
            )
        out.append(
            ParsedEvent(
                uid=uid_prop[2],
                recurrence_id=rid_key,
                starts_at=moment,
                ends_at=moment + duration,
                is_all_day=starts.is_all_day,
                sequence=sequence,
            )
        )
    return out
