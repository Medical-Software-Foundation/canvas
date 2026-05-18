"""Per-note draft state for the Exam tab.

When the provider types into the Exam form, the JS debounces a POST to
/exam/state with the full form blob. We persist it here keyed by
note_uuid so reopening the tab restores the same draft. On finalize the
state is kept (not cleared) but flagged `finalized`, which the frontend
uses to disable the Finalize button and render a banner explaining
that the chart's command UI is now the source of truth for edits.

Storage shape:
  AttributeHub(type=NAMESPACE, id=f"draft:{note_uuid}")
    .set_attribute("payload", <json string of form state>)
    .set_attribute("finalized", "1" | "0")

  AttributeHub(type=NAMESPACE, id=f"meta:{note_uuid}")
    .set_attribute("ever_finalized", "1")

The `meta:` row is kept separate from `draft:` so that
`clear_draft` (called by the delete-lifecycle handler) does NOT wipe
the "this plugin previously finalized this note" marker. That marker
is what the frontend's orphan-commands banner relies on to distinguish
"the chart has commands from THIS plugin that the form no longer
reflects" from "the chart has commands from some other plugin /
manual entry" — a distinction needed when another plugin also
finalizes commands on the same note.
"""
from __future__ import annotations

import json
from typing import Any

from canvas_sdk.v1.data import AttributeHub

NAMESPACE = "canvas__exam_chart_app"
PAYLOAD_KEY = "payload"
FINALIZED_KEY = "finalized"
EVER_FINALIZED_KEY = "ever_finalized"

# Cap the serialized draft at 1 MB. A complex visit (10+ diagnoses,
# long narratives, many orders) realistically lands well under 100 KB;
# anything past 1 MB is almost certainly a buggy frontend, a
# copy-pasted history dump, or an adversarial client. The /exam/state/save
# handler catches DraftTooLargeError and returns 413.
DRAFT_MAX_BYTES = 1_000_000


class DraftTooLargeError(ValueError):
    """Raised by set_draft when the serialized payload exceeds DRAFT_MAX_BYTES."""


def _hub_id(note_uuid: str) -> str:
    return f"draft:{note_uuid}"


def _meta_hub_id(note_uuid: str) -> str:
    return f"meta:{note_uuid}"


def set_draft(note_uuid: str, state: dict[str, Any]) -> None:
    """Persist (replace) the form state blob for a note.

    Raises DraftTooLargeError if the serialized payload exceeds the cap.
    """
    if not note_uuid:
        return
    serialized = json.dumps(state)
    if len(serialized) > DRAFT_MAX_BYTES:
        raise DraftTooLargeError(
            f"draft payload {len(serialized)} bytes exceeds cap {DRAFT_MAX_BYTES}"
        )
    hub, _ = AttributeHub.objects.get_or_create(
        type=NAMESPACE, id=_hub_id(note_uuid)
    )
    hub.set_attribute(PAYLOAD_KEY, serialized)


def get_draft(note_uuid: str) -> tuple[dict[str, Any], bool]:
    """Return (state, finalized) for a note.

    Returns ({}, False) when no draft has been saved yet. Malformed
    payload (older format, hand-edited DB row) decodes to {} so the
    frontend treats it as an empty draft rather than crashing.
    """
    if not note_uuid:
        return {}, False
    hub = AttributeHub.objects.filter(
        type=NAMESPACE, id=_hub_id(note_uuid)
    ).first()
    if hub is None:
        return {}, False
    raw_payload = hub.get_attribute(PAYLOAD_KEY)
    state: dict[str, Any] = {}
    if isinstance(raw_payload, str) and raw_payload.strip():
        try:
            decoded = json.loads(raw_payload)
            if isinstance(decoded, dict):
                state = decoded
        except (ValueError, TypeError):
            state = {}
    finalized_raw = hub.get_attribute(FINALIZED_KEY)
    finalized = str(finalized_raw or "").strip() == "1"
    return state, finalized


def mark_finalized(note_uuid: str) -> None:
    """Flag a note's saved draft as finalized (commands have been emitted)."""
    if not note_uuid:
        return
    hub, _ = AttributeHub.objects.get_or_create(
        type=NAMESPACE, id=_hub_id(note_uuid)
    )
    hub.set_attribute(FINALIZED_KEY, "1")


def clear_draft(note_uuid: str) -> None:
    """Delete the draft row entirely (called by the note-lifecycle handler).

    The `meta:` row is intentionally left in place so the
    orphan-commands banner can fire after a delete/undelete cycle —
    see module docstring.
    """
    if not note_uuid:
        return
    AttributeHub.objects.filter(
        type=NAMESPACE, id=_hub_id(note_uuid)
    ).delete()


def mark_ever_finalized(note_uuid: str) -> None:
    """Stamp the `meta:` row so we remember this plugin finalized this note.

    Survives `clear_draft` (which only deletes `draft:<note_uuid>`).
    """
    if not note_uuid:
        return
    hub, _ = AttributeHub.objects.get_or_create(
        type=NAMESPACE, id=_meta_hub_id(note_uuid)
    )
    hub.set_attribute(EVER_FINALIZED_KEY, "1")


def was_ever_finalized(note_uuid: str) -> bool:
    """Has this plugin previously finalized this note?

    Used by `/exam/state` to drive the orphan-commands banner only when
    THIS plugin emitted the commands — sibling plugins (intake, etc.)
    that finalize on the same note should not trigger our banner.
    """
    if not note_uuid:
        return False
    hub = AttributeHub.objects.filter(
        type=NAMESPACE, id=_meta_hub_id(note_uuid)
    ).first()
    if hub is None:
        return False
    return str(hub.get_attribute(EVER_FINALIZED_KEY) or "").strip() == "1"
