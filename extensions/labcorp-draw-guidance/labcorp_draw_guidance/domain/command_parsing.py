"""Defensive parsing of a staged LabOrderCommand's `Command.data` JSON.

The exact shape of a lab order command's staged field data is one of the
plugin spec's open questions -- `tests_order_codes` is the Python-side field
name (see `canvas_sdk.commands.commands.lab_order.LabOrderCommand`), but the
front-end form posts field values keyed by `commands_api_name` ("tests"),
and the individual list entries could plausibly be raw strings (an order
code or a `LabPartnerTest` id) or dicts (e.g. `{"value": ..., "text": ...}`)
depending on how the front-end serializes a multi-select field. Rather than
guessing a single brittle shape, these helpers accept both and extract
whatever looks like a test identifier, mirroring the same
order-code-or-id matching `LabOrderCommand` itself uses for validation.
"""

from typing import Any

# Keys checked, in priority order, when a "tests" list entry is a dict.
_TEST_IDENTIFIER_KEYS = ("value", "code", "order_code", "id", "text")


def extract_lab_partner_name(command_data: dict[str, Any]) -> str | None:
    """Pull a human-readable lab partner name out of a staged command's data.

    The `lab_partner` field may be a plain string (name or id) or a dict
    (e.g. `{"value": ..., "text": "Labcorp"}`) depending on how the
    front-end serializes the field.
    """
    lab_partner = command_data.get("lab_partner")

    if isinstance(lab_partner, str):
        return lab_partner or None

    if isinstance(lab_partner, dict):
        for key in ("text", "label", "name", "value"):
            value = lab_partner.get(key)
            if isinstance(value, str) and value:
                return value

    return None


def extract_test_identifiers(command_data: dict[str, Any]) -> list[str]:
    """Pull test order-codes/ids out of a staged command's `tests` field.

    Returns a de-duplicated list of identifier strings, preserving order of
    first appearance. Entries that can't be resolved to a string identifier
    are skipped rather than raising, since this runs on every keystroke of
    an in-progress order.
    """
    raw_tests = command_data.get("tests")
    if not isinstance(raw_tests, list):
        return []

    identifiers: list[str] = []
    seen: set[str] = set()

    for entry in raw_tests:
        identifier: str | None = None

        if isinstance(entry, str):
            identifier = entry
        elif isinstance(entry, dict):
            for key in _TEST_IDENTIFIER_KEYS:
                value = entry.get(key)
                if isinstance(value, str) and value:
                    identifier = value
                    break

        if identifier and identifier not in seen:
            seen.add(identifier)
            identifiers.append(identifier)

    return identifiers
