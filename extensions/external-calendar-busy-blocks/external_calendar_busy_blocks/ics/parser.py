from external_calendar_busy_blocks.ics.types import IcsParseError


def unfold_lines(body: bytes) -> list[str]:
    """Decode and unfold an ICS body into logical lines."""
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
            # RFC 5545: strip the single leading WSP fold indicator.
            # Space continuations preserve the remaining content as-is
            # (the space is the fold indicator; content follows without
            # an additional separator).  Tab continuations strip the tab.
            folded[-1] += line[1:] if line[0] == "\t" else line
        else:
            folded.append(line)
    return folded
