"""Pre-fill aggregator for the Intake form.

Each function returns plain dicts (not ORM instances) so the API/render layer
can serialise rows directly to HTML data without juggling ORM lifecycles.

All clinical queries filter ``deleted=False`` AND ``entered_in_error__isnull=True``
per CLAUDE.md guidance — retracted or soft-deleted records must never appear
in the UI.
"""
from __future__ import annotations

import re
from typing import Any

# Some plugins stash a round-trip of their form state inside the visible
# ``note`` text using a markdown-style hidden comment of the form
# ``[//]: # (FORM_STATE::section::{...giant JSON...})``. That blob would
# leak straight into the Intake modal's read-only summary if left in
# place, so this regex strips any ``[//]: # (...)`` segment (greedy across
# the trailing close-paren is fine because the form-state payload doesn't
# contain unbalanced parens at the top level).
_MARKDOWN_HIDDEN_COMMENT_RE = re.compile(r"\[//\]:\s*#\s*\([^)]*\)\s*", re.DOTALL)


def _strip_hidden_comments(text: str) -> str:
    """Remove ``[//]: # (...)`` markdown-comment payloads and collapse the
    resulting whitespace."""
    if not text:
        return ""
    cleaned = _MARKDOWN_HIDDEN_COMMENT_RE.sub("", text)
    return " ".join(cleaned.split()).strip()

from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication

# Schema keys for the history-style command types we pre-fill from. Source
# of truth: each Canvas command class's ``Meta.key``. These are the values
# stored in ``Command.schema_key`` for committed instances.
SCHEMA_MEDICAL_HISTORY = "medicalHistory"
SCHEMA_SURGICAL_HISTORY = "surgicalHistory"

# Only "committed" commands should pre-fill the form. Staged/draft commands on
# other notes belong to the in-flight workflow that originated them.
COMMITTED_STATE = "committed"

# Hard cap on rows returned by any pre-fill query. Chronic-care patients can
# accumulate hundreds of conditions / medications / history rows; the modal
# is meant for human review at point-of-care, not exhaustive enumeration.
# Every queryset in this module is ordered most-recent-first, so the slice
# keeps the most clinically relevant rows.
MAX_PREFILL_ROWS = 200


def _first_coding(obj: Any) -> Any:
    """Return the first coding on `obj` from the prefetch cache.

    Calling ``obj.codings.first()`` issues a per-object ``LIMIT 1`` query
    even when ``prefetch_related("codings")`` is in play; iterating
    ``codings.all()`` reads from the cached list.
    """
    codings = getattr(obj, "codings", None)
    if codings is None:
        return None
    if not hasattr(codings, "all"):
        return codings.first() if hasattr(codings, "first") else None
    cached = list(codings.all())
    return cached[0] if cached else None


def _coding_fields(coding: Any) -> dict[str, str]:
    if coding is None:
        return {"code": "", "system": "", "display": ""}
    return {
        "code": (getattr(coding, "code", "") or "").strip(),
        "system": (getattr(coding, "system", "") or "").strip(),
        "display": (getattr(coding, "display", "") or "").strip(),
    }


def active_conditions(patient_id: str) -> list[dict[str, Any]]:
    """Active conditions for the Problems reference panel.

    Returns rows of ``{id, code, system, display}`` keyed off the first
    coding on each condition; conditions with no codings or empty display
    are dropped.

    ``committer__isnull=False`` excludes Conditions whose underlying Diagnose
    command was staged but never committed — those rows exist in the table
    but don't appear in the chart sidebar's Conditions list, so they
    shouldn't appear here either.
    """
    if not patient_id:
        return []
    qs = (
        Condition.objects.for_patient(patient_id)
        .filter(
            clinical_status="active",
            deleted=False,
            entered_in_error__isnull=True,
            committer__isnull=False,
        )
        .order_by("-onset_date")
        .prefetch_related("codings")
    )[:MAX_PREFILL_ROWS]
    out: list[dict[str, Any]] = []
    for c in qs:
        coding = _coding_fields(_first_coding(c))
        if not coding["display"]:
            continue
        out.append({"id": str(c.id), **coding})
    return out


def active_allergies(patient_id: str) -> list[dict[str, Any]]:
    """Active allergies. Returns ``{id, allergen, narrative, severity}``.

    Like ``active_conditions``, filters ``committer__isnull=False`` so
    only allergies whose underlying Allergy command was committed appear.
    """
    if not patient_id:
        return []
    qs = (
        AllergyIntolerance.objects.for_patient(patient_id)
        .filter(
            status="active",
            deleted=False,
            entered_in_error__isnull=True,
            committer__isnull=False,
        )
        .prefetch_related("codings")
    )[:MAX_PREFILL_ROWS]
    out: list[dict[str, Any]] = []
    for a in qs:
        coding = _coding_fields(_first_coding(a))
        narrative = (getattr(a, "narrative", "") or "").strip()
        allergen = coding["display"] or narrative
        if not allergen:
            continue
        out.append({
            "id": str(a.id),
            "allergen": allergen,
            "narrative": narrative,
            "severity": (getattr(a, "severity", "") or "").strip(),
        })
    return out


def active_medications(patient_id: str) -> list[dict[str, Any]]:
    """Active medications matching the chart's Medications sidebar.

    Uses the canonical ``Medication.objects.for_patient(p).active()`` pattern
    used by ``portal_request_refill`` and similar Canvas SDK example
    plugins — the ``.active()`` queryset method handles the date/status
    logic that a raw ``filter(status="active")`` does not.

    Returns ``{id, display, sig}``.
    """
    if not patient_id:
        return []
    qs = (
        Medication.objects.for_patient(patient_id)
        .active()
        .filter(
            deleted=False,
            entered_in_error__isnull=True,
            committer__isnull=False,
        )
        .prefetch_related("codings")
    )[:MAX_PREFILL_ROWS]
    out: list[dict[str, Any]] = []
    for m in qs:
        coding = _coding_fields(_first_coding(m))
        display = coding["display"]
        if not display:
            continue
        sig = (
            (getattr(m, "clinical_quantity_description", "") or "").strip()
            or (getattr(m, "quantity_qualifier_description", "") or "").strip()
        )
        out.append({"id": str(m.id), "display": display, "sig": sig})
    return out


# ---------------------------------------------------------------------------
# History-command pre-fill (PMH / Surgical / Family / Social).
#
# Pattern: query the patient's committed Commands by schema_key, extract the
# free-text/coded fields from each command's JSON ``data`` payload, return
# plain dicts. Output format per row: ``{id, summary, data}`` — ``summary`` is
# a best-effort human label for the read-only panel; ``data`` is the raw
# payload so the commit-path logic can reuse it.
# ---------------------------------------------------------------------------


def _coerce_text(value: Any) -> str:
    """Best-effort string coercion for a command-data field that might be a
    raw string, a coding dict (``{"text"|"display"|"code": ...}``), or
    something else. Returns ``""`` for empty/unrecognised."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "display", "name", "label", "value"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Fall back to whatever string-like values we can find.
        for v in value.values():
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(value).strip()


def _committed_commands(patient_id: str, schema_key: str) -> Any:
    """Build the base queryset for a patient's committed commands of a kind.

    Uses ``patient__id=`` (relationship traversal) since ``Command.patient`` is
    a FK whose direct column (``patient_id``) stores the integer PK, not the
    UUID we receive. ``patient__id=`` matches the related ``Patient.id`` UUID.
    """
    return (
        Command.objects.filter(
            patient__id=patient_id,
            schema_key=schema_key,
            state=COMMITTED_STATE,
            entered_in_error__isnull=True,
        )
        .order_by("-created")
    )[:MAX_PREFILL_ROWS]


def _condition_rows(patient_id: str, surgical: bool) -> list[dict[str, Any]]:
    """Return rows from the SDK Condition model for one half of the chart's
    history sidebar. Conditions with ``surgical=True`` back the chart's
    Surgical & Procedure History; ``surgical=False`` backs Past Medical
    History. We filter out retracted/uncommitted rows the same way the
    sidebar does.

    Output shape matches the Command-row helpers: ``{id, summary, data}``."""
    if not patient_id:
        return []
    out: list[dict[str, Any]] = []
    queryset = (
        Condition.objects.filter(
            patient__id=patient_id,
            surgical=surgical,
            entered_in_error__isnull=True,
            deleted=False,
            committer__isnull=False,
        )
        .prefetch_related("codings")
        .order_by("-onset_date")
    )[:MAX_PREFILL_ROWS]
    for cond in queryset:
        coding = _first_coding(cond)
        display = (getattr(coding, "display", None) or "").strip() if coding else ""
        code = (getattr(coding, "code", None) or "").strip() if coding else ""
        onset = cond.onset_date.isoformat() if cond.onset_date else ""
        resolution = cond.resolution_date.isoformat() if cond.resolution_date else ""
        if not any((display, code, onset, resolution)):
            continue
        bits = [display or code or "(no condition recorded)"]
        if onset:
            bits.append(f"(since {onset})")
        if resolution:
            bits.append(f"(until {resolution})")
        out.append({
            "id": str(cond.id),
            "summary": " ".join(bits),
            "data": {
                "display": display, "code": code,
                "onset_date": onset, "resolution_date": resolution,
            },
        })
    return out


def _display_key(text: str) -> str:
    """Lower-cased, whitespace-collapsed key for display-text dedup.

    The Command and Condition tables can store the same condition under two
    different row ids (a plugin originated the Command and Canvas also persisted
    a Condition record, or two distinct Conditions share a display). Dedup by
    display label keeps the modal from showing the same row twice.
    """
    return " ".join(text.lower().split()) if text else ""


def prior_medical_history(patient_id: str) -> list[dict[str, Any]]:
    """Return prior medical-history rows from both the Command table and the
    SDK Condition table (surgical=False half). Dedupes by row id AND by
    normalised display label so the same condition doesn't appear twice when
    it exists in both tables."""
    if not patient_id:
        return []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    out: list[dict[str, Any]] = []
    for cmd in _committed_commands(patient_id, SCHEMA_MEDICAL_HISTORY):
        data = cmd.data if isinstance(cmd.data, dict) else {}
        condition_text = _strip_hidden_comments(_coerce_text(data.get("past_medical_history")))
        approx_start = _strip_hidden_comments(_coerce_text(data.get("approximate_start_date")))
        approx_end = _strip_hidden_comments(_coerce_text(data.get("approximate_end_date")))
        comments = _strip_hidden_comments(_coerce_text(data.get("comments")))
        if not any((condition_text, approx_start, approx_end, comments)):
            continue
        bits = [condition_text or "(no condition recorded)"]
        if approx_start:
            bits.append(f"(since {approx_start})")
        if approx_end:
            bits.append(f"(until {approx_end})")
        if comments:
            bits.append(f"— {comments}")
        row_id = str(cmd.id)
        if row_id in seen_ids:
            continue
        label_key = _display_key(condition_text)
        if label_key and label_key in seen_labels:
            continue
        seen_ids.add(row_id)
        if label_key:
            seen_labels.add(label_key)
        out.append({"id": row_id, "summary": " ".join(bits), "data": data})
    for row in _condition_rows(patient_id, surgical=False):
        if row["id"] in seen_ids:
            continue
        label_key = _display_key((row.get("data") or {}).get("display", ""))
        if label_key and label_key in seen_labels:
            continue
        seen_ids.add(row["id"])
        if label_key:
            seen_labels.add(label_key)
        out.append(row)
    return out


def prior_surgical_history(patient_id: str) -> list[dict[str, Any]]:
    """Return prior surgical-history rows from both the Command table and
    the SDK Condition table (surgical=True half). Dedupes by row id AND by
    normalised display label."""
    if not patient_id:
        return []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    out: list[dict[str, Any]] = []
    for cmd in _committed_commands(patient_id, SCHEMA_SURGICAL_HISTORY):
        data = cmd.data if isinstance(cmd.data, dict) else {}
        proc_text = _strip_hidden_comments(_coerce_text(data.get("past_surgical_history")))
        approx_date = _strip_hidden_comments(_coerce_text(data.get("approximate_date")))
        comment = _strip_hidden_comments(_coerce_text(data.get("comment")))
        if not any((proc_text, approx_date, comment)):
            continue
        bits = [proc_text or "(no procedure recorded)"]
        if approx_date:
            bits.append(f"({approx_date})")
        if comment:
            bits.append(f"— {comment}")
        row_id = str(cmd.id)
        if row_id in seen_ids:
            continue
        label_key = _display_key(proc_text)
        if label_key and label_key in seen_labels:
            continue
        seen_ids.add(row_id)
        if label_key:
            seen_labels.add(label_key)
        out.append({"id": row_id, "summary": " ".join(bits), "data": data})
    for row in _condition_rows(patient_id, surgical=True):
        if row["id"] in seen_ids:
            continue
        label_key = _display_key((row.get("data") or {}).get("display", ""))
        if label_key and label_key in seen_labels:
            continue
        seen_ids.add(row["id"])
        if label_key:
            seen_labels.add(label_key)
        out.append(row)
    return out


# Family History pre-fill no longer lives in this module. Canvas's chart
# Family History sidebar reads from the FHIR ``FamilyMemberHistory`` resource
# set, which is disjoint from the Command table (sidebar rows from FHIR
# imports never create a Canvas Command). See
# ``intake_chart_app.data.family_history_fhir.fetch_family_member_history``
# for the OAuth-authenticated fumage fetch the modal uses.


