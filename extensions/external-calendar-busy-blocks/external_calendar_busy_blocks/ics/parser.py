from external_calendar_busy_blocks.ics.types import IcsParseError


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
