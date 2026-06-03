from datetime import datetime, timedelta

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
            current.append(parse_property_line(line))

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
            overrides[(uid_prop[2], rid_prop[2])] = props
        else:
            base_events.append(props)

    out: list[ParsedEvent] = []
    for props in base_events:
        if _should_skip(props):
            continue
        uid_prop = _find_property(props, "UID")
        dtstart_prop = _find_property(props, "DTSTART")
        dtend_prop = _find_property(props, "DTEND")
        if not uid_prop or not dtstart_prop or not dtend_prop:
            continue

        starts = parse_ics_datetime(dtstart_prop[2], dtstart_prop[1], default_tz)
        ends = parse_ics_datetime(dtend_prop[2], dtend_prop[1], default_tz)
        duration = ends.moment - starts.moment

        seq_prop = _find_property(props, "SEQUENCE")
        sequence = int(seq_prop[2]) if seq_prop else 0

        rrule_prop = _find_property(props, "RRULE")
        if rrule_prop is None:
            if ends.moment <= now or starts.moment >= window_end:
                continue
            out.append(
                ParsedEvent(
                    uid=uid_prop[2],
                    recurrence_id=None,
                    starts_at=starts.moment,
                    ends_at=ends.moment,
                    is_all_day=starts.is_all_day,
                    sequence=sequence,
                )
            )
            continue

        try:
            rule = parse_rrule(rrule_prop[2])
        except RRuleUnsupported as exc:
            log.warning("Dropping VEVENT uid=%s: %s", uid_prop[2], exc)
            continue

        exdates = _collect_exdates(props, default_tz)

        for moment in expand_rrule(
            rule, starts.moment, now, window_end, cap=RRULE_CAP_PER_VEVENT,
        ):
            if moment in exdates:
                continue
            rid_key = _format_recurrence_id(moment, starts.is_all_day)
            override_props = overrides.get((uid_prop[2], rid_key))
            if override_props is not None:
                if _should_skip(override_props):
                    continue
                ovs_prop = _find_property(override_props, "DTSTART")
                ove_prop = _find_property(override_props, "DTEND")
                if ovs_prop is None or ove_prop is None:
                    continue
                ovs = parse_ics_datetime(ovs_prop[2], ovs_prop[1], default_tz)
                ove = parse_ics_datetime(ove_prop[2], ove_prop[1], default_tz)
                out.append(
                    ParsedEvent(
                        uid=uid_prop[2],
                        recurrence_id=rid_key,
                        starts_at=ovs.moment,
                        ends_at=ove.moment,
                        is_all_day=ovs.is_all_day,
                        sequence=sequence,
                    )
                )
                continue
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
