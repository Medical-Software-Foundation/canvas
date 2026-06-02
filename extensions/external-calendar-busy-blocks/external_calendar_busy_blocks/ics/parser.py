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
