"""Parse Ask-on-Order-Entry (AOE) answers out of a labOrder Command.data blob.

Canvas stores AOE answers in the lab order Command.data JSONField under keys
formatted as:

    aoes|{test_ontology_code}|{question_code}   ->   answer value

This module is pure (no I/O, no model access) so it is fully unit-testable.
The protocol reads Command.data and hands it here; the result is passed to the
payload builder.
"""

from __future__ import annotations

_AOE_PREFIX = "aoes"


def _is_blank(answer: object) -> bool:
    """True when an answer carries nothing worth sending."""
    if answer is None:
        return True
    if isinstance(answer, str) and not answer.strip():
        return True
    return False


def parse_aoe_answers(command_data: object) -> dict[str, list[tuple[str, str]]]:
    """Extract AOE answers from a labOrder Command.data blob.

    Accepts arbitrary input (Command.data is a free-form JSONField that may be
    None or, in corrupt/legacy rows, a non-dict): anything that is not a dict
    yields an empty result rather than raising.

    Returns {test_ontology_code: [(question_code, answer), ...]} preserving the
    insertion order of command_data. Keys that are not exactly
    'aoes|{test}|{question}' are ignored (never raises). Blank/None answers are
    skipped, and a test whose answers are all blank does not appear in the
    result. Non-string answers are coerced to str (ELLKAY's Answer is a string).
    """
    grouped: dict[str, list[tuple[str, str]]] = {}
    if not isinstance(command_data, dict):
        return grouped
    for key, answer in command_data.items():
        if not isinstance(key, str) or not key.startswith(_AOE_PREFIX + "|"):
            continue
        parts = key.split("|")
        if len(parts) != 3:
            continue
        _, test_code, question_code = parts
        if _is_blank(answer):
            continue
        grouped.setdefault(test_code, []).append((question_code, str(answer)))
    return grouped
