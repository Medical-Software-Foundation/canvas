"""Shared helpers for the prescribe formulary/benefits workflow.

The flow spans three plugin-runner events that don't share state, so we use the
SDK cache to thread a small amount of context across them:

    PRESCRIBE/REFILL/ADJUST __POST_UPDATE   (medication chosen)
        -> SendSurescriptsEligibilityRequestEffect (correlation_id A)
    SURESCRIPTS_ELIGIBILITY_RESPONSE (correlation_id A)
        -> SendSurescriptsBenefitsRequestEffect    (correlation_id B)
    SURESCRIPTS_BENEFITS_RESPONSE (correlation_id B)
        -> command.set_custom_html(<formulary detail>)

Each request effect carries a ``correlation_id`` that the home-app interpreter
echoes back on the matching response event. We stash the per-command context
under that id so the response handler can find the command to write HTML to,
and so we only act on responses that this plugin originated.
"""

from __future__ import annotations

import json
from typing import Any

from canvas_sdk.commands import (
    AdjustPrescriptionCommand,
    PrescribeCommand,
    RefillCommand,
)

from logger import log

# How long the cross-event context lives. A prescriber may take a little while
# between selecting a medication and the responses returning, but this only
# needs to outlive a single editing session, not persist indefinitely.
CACHE_TTL_SECONDS = 900

# Cache key prefixes (get_cache() is already namespaced per-plugin).
_CORRELATION_PREFIX = "corr:"
_FINGERPRINT_PREFIX = "cmd_fp:"

# Maps the command kind we derive from the event name to the SDK command class
# used to emit the custom-html effect. set_custom_html() only needs command_uuid,
# but using the right class keeps the effect semantically correct.
COMMAND_CLASSES: dict[str, type] = {
    "prescribe": PrescribeCommand,
    "refill": RefillCommand,
    "adjust_prescription": AdjustPrescriptionCommand,
}

# Maps the command-event name prefix to a command kind.
_EVENT_PREFIX_TO_KIND = {
    "PRESCRIBE_COMMAND__": "prescribe",
    "REFILL_COMMAND__": "refill",
    "ADJUST_PRESCRIPTION_COMMAND__": "adjust_prescription",
}

# Field keys, in priority order, that hold the medication being prescribed.
# Adjust Prescription exposes "change_medication_to" when the provider is
# switching the drug; otherwise the original prescription sits in "prescribe".
_MEDICATION_FIELD_KEYS = ("change_medication_to", "prescribe")


def command_kind_for_event(event_name: str) -> str | None:
    """Return the command kind ('prescribe'/'refill'/'adjust_prescription') for an event name."""
    for prefix, kind in _EVENT_PREFIX_TO_KIND.items():
        if event_name.startswith(prefix):
            return kind
    return None


def correlation_key(correlation_id: str) -> str:
    """Cache key for a correlation_id -> context mapping."""
    return f"{_CORRELATION_PREFIX}{correlation_id}"


def fingerprint_key(command_uuid: str) -> str:
    """Cache key for the last medication fingerprint we acted on for a command."""
    return f"{_FINGERPRINT_PREFIX}{command_uuid}"


def store_context(cache: Any, correlation_id: str, context: dict[str, Any]) -> None:
    """Persist the cross-event context under a correlation id."""
    cache.set(correlation_key(correlation_id), json.dumps(context), timeout_seconds=CACHE_TTL_SECONDS)


def load_context(cache: Any, correlation_id: str) -> dict[str, Any] | None:
    """Load and remove the cross-event context for a correlation id.

    Returns None when the id is unknown (e.g. a response to a request this
    plugin did not originate), which the response handlers treat as "not mine".
    """
    raw = cache.get(correlation_key(correlation_id))
    if raw is None:
        return None
    cache.delete(correlation_key(correlation_id))
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        log.warning("prescribe_formulary_benefits: could not decode cached context")
        return None


def _coding_list(field: dict[str, Any]) -> list[dict[str, Any]]:
    extra = field.get("extra") or {}
    coding = extra.get("coding")
    return coding if isinstance(coding, list) else []


def _looks_like_ndc(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    digits = value.replace("-", "")
    return digits.isdigit() and 10 <= len(digits) <= 11


def _deep_find_ndc(node: Any) -> str | None:
    """Recursively hunt for an NDC value within a command field structure.

    Prescribe stores the dispensable NDC under type_to_dispense's
    ``representative_ndc``; some payloads also carry an NDC-systemed coding. We
    search defensively rather than hard-coding one path so the lookup survives
    minor shape differences across command types.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = key.lower()
            if lowered in ("representative_ndc", "ndc", "national_drug_code") and _looks_like_ndc(
                value
            ):
                return str(value)
            # NDC-systemed coding entry: {"system": ".../ndc", "code": "..."}
            if lowered == "system" and isinstance(value, str) and "ndc" in value.lower():
                code = node.get("code")
                if _looks_like_ndc(code):
                    return str(code)
            found = _deep_find_ndc(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _deep_find_ndc(item)
            if found:
                return found
    return None


def extract_medication(fields: dict[str, Any]) -> tuple[str, str] | None:
    """Pull (description, ndc) for the chosen medication out of a command's fields.

    Returns None until both a human-readable description and an NDC are
    available — the benefits request requires an NDC, which only materializes
    once the medication (and its dispensable form) is selected.
    """
    medication_field: dict[str, Any] | None = None
    for key in _MEDICATION_FIELD_KEYS:
        candidate = fields.get(key)
        if isinstance(candidate, dict) and candidate.get("value"):
            medication_field = candidate
            break

    if medication_field is None:
        return None

    description = (medication_field.get("text") or "").strip()
    if not description:
        for coding in _coding_list(medication_field):
            display = (coding.get("display") or "").strip()
            if display:
                description = display
                break
    if not description:
        return None

    # The NDC can live on the medication field or on the related
    # type_to_dispense field, so search the whole fields blob.
    ndc = _deep_find_ndc(medication_field) or _deep_find_ndc(fields.get("type_to_dispense")) or (
        _deep_find_ndc(fields)
    )
    if not ndc:
        return None

    return description, ndc


def select_plan_name(plans: list[Any]) -> str | None:
    """Return the `pbm_name` to send as the benefits request's `plan` field.

    This MUST be the plan's `pbm_name`. The home-app benefits lookup matches the
    `plan` value against each eligibility plan's `pbm_name`
    (`if plan["pbm_name"] != plan_name: continue`) — sending a description or
    formulary number matches nothing and yields an empty benefits response.
    """
    for plan in plans:
        if getattr(plan, "rejected", False):
            continue
        if plan.pbm_name:
            return plan.pbm_name
    return None
