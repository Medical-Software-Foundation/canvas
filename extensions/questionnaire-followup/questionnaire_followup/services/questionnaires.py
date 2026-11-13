"""Resolve and list the instance's questionnaires.

Everything keys off the stable questionnaire ``code`` and resolves to the current
``id`` at runtime. Loading a new version of a questionnaire changes its id but
never its code, so a configured pairing keeps working across versions - and the
same config document stays portable between instances.
"""

from typing import Any

from canvas_sdk.v1.data import Questionnaire
from logger import log

# Canvas marks the active status as "AC"; anything else is retired or draft and
# must not be offered in the picker or resolved for a patient.
_ACTIVE = "AC"


def list_questionnaires() -> list[dict[str, Any]]:
    """Active questionnaires for the admin pickers, with the codes rules store.

    Both sides of a pairing come from this list. The follow-up side additionally
    needs ``can_originate_in_charting`` when the response is committed into a
    note, so that flag is reported rather than filtered on - the admin page shows
    it, so a questionnaire that cannot be charted is visible instead of silently
    failing later.
    """
    out: list[dict[str, Any]] = []
    try:
        rows = Questionnaire.objects.filter(status=_ACTIVE).values(
            "name", "code", "code_system", "use_case_in_charting", "can_originate_in_charting"
        )
        for row in rows:
            code = (row.get("code") or "").strip()
            if not code:
                continue  # unaddressable: a rule could never point at it
            out.append(
                {
                    "name": row.get("name") or "",
                    "code": code,
                    "code_system": row.get("code_system") or "",
                    "use_case": row.get("use_case_in_charting") or "",
                    "can_originate_in_charting": bool(row.get("can_originate_in_charting")),
                }
            )
    except (AttributeError, ValueError) as exc:
        log.warning(f"questionnaire list failed: {exc}")
    out.sort(key=lambda q: q["name"].lower())
    return out


def resolve_names(names: set[str]) -> dict[str, str]:
    """Map each questionnaire name to the code the one active questionnaire with it carries.

    Used **only when seeding the default pairings**, to point them at what this
    instance actually loaded rather than at a code guessed in advance. The shipped
    panel codes turned out to be wrong for both short screeners on the first real
    instance this was checked against; see CLAUDE.md, open question 1.

    Matching is exact, but case- and whitespace-insensitive, which is as loose as
    this gets: a near-match on a clinical instrument is a wrong instrument. A name
    carried by more than one active questionnaire resolves to nothing, for the same
    reason ``resolve_codes`` refuses an ambiguous code.

    Filtering happens here rather than in SQL because the comparison is case-folded.
    That is affordable precisely because this runs once, at seed, and never on the
    portal's hot path.
    """
    requested = {name.strip().casefold(): name for name in names if name.strip()}
    if not requested:
        return {}
    try:
        rows = list(Questionnaire.objects.filter(status=_ACTIVE).values_list("name", "code"))
    except (AttributeError, ValueError) as exc:
        log.warning(f"questionnaire name lookup failed for names={sorted(requested.values())}: {exc}")
        return {}

    found: dict[str, set[str]] = {}
    for name, code in rows:
        key = (name or "").strip().casefold()
        code = (code or "").strip()
        if key in requested and code:
            found.setdefault(key, set()).add(code)

    resolved: dict[str, str] = {}
    for key, codes in sorted(found.items()):
        if len(codes) > 1:
            log.warning(
                f"questionnaire name='{requested[key]}' matches active questionnaires with "
                f"different codes {sorted(codes)}; not seeding a pairing from it"
            )
            continue
        resolved[requested[key]] = next(iter(codes))
    return resolved


def resolve_codes(codes: set[str]) -> dict[str, Questionnaire]:
    """Map each stable code to its current active Questionnaire, in one query.

    A code with no active questionnaire is left out. So is a code that matches more
    than one: Canvas would pick one arbitrarily, so this refuses instead and logs,
    rather than quietly assigning the wrong instrument.

    Only the fields the portal handler reads are loaded - this runs on its hot path.
    """
    wanted = {code for code in codes if code}
    if not wanted:
        return {}
    matches: dict[str, list[Questionnaire]] = {}
    try:
        rows = Questionnaire.objects.filter(code__in=wanted, status=_ACTIVE).only(
            "dbid", "id", "code", "name", "can_originate_in_charting"
        )
        for questionnaire in rows:
            matches.setdefault(questionnaire.code, []).append(questionnaire)
    except (AttributeError, ValueError) as exc:
        log.warning(f"questionnaire resolve failed for codes={sorted(wanted)}: {exc}")
        return {}

    resolved: dict[str, Questionnaire] = {}
    for code, found in sorted(matches.items()):
        if len(found) > 1:
            log.warning(
                f"questionnaire code={code} matches multiple active questionnaires; "
                "refusing to guess which one a pairing meant"
            )
            continue
        resolved[code] = found[0]
    return resolved
