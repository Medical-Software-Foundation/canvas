from canvas_sdk.v1.data.command import Command
from logger import log


def _coding_values(data: dict) -> list[str]:
    """Extract all coding 'value'/'code' strings from an RFV command's data.

    The stored shape varies: `data["coding"]` may be a dict, a list of dicts,
    and the code may live under 'value' or 'code'. Pull every candidate so the
    trigger match works regardless of which shape the instance uses."""
    values: list[str] = []
    coding = data.get("coding")
    candidates = []
    if isinstance(coding, dict):
        candidates = [coding]
    elif isinstance(coding, list):
        candidates = [c for c in coding if isinstance(c, dict)]
    for c in candidates:
        for key in ("value", "code"):
            v = c.get(key)
            if isinstance(v, str) and v:
                values.append(v)
    return values


def note_matches_trigger(note_dbid, trigger_code: str) -> bool:
    """True when the note has a reason-for-visit command whose coding matches
    trigger_code. `note_dbid` is the note's integer dbid from the application
    event context. Fails closed (returns False) on any read problem."""
    if not note_dbid:
        return False
    try:
        commands = list(
            Command.objects.filter(note__dbid=note_dbid, schema_key="reasonForVisit")
        )
    except (ValueError, TypeError) as exc:
        log.info("sleep_screening: RFV read failed for note " + str(note_dbid) + ": " + str(exc))
        return False

    for command in commands:
        data = command.data if isinstance(command.data, dict) else {}
        if trigger_code in _coding_values(data):
            return True
    return False
