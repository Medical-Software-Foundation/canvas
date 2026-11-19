"""Helpers for stamping Surescripts request status onto a note as metadata.

Canvas does not currently fire a webhook when a Surescripts response arrives,
so status remains "requested" once stamped. The accompanying timestamp lets a
provider tell, at a glance, when the most recent request went out.

NoteMetadata.key is capped at 32 characters (canvas_sdk_data_api_notemetadata_001).
The keys below are all <= 30 characters.
"""

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect


def request_metadata_effects(note_id: str, request_type: str) -> list[Effect]:
    """Build upsert metadata effects for a Surescripts request.

    Args:
        note_id: UUID/string id of the Note to stamp.
        request_type: "eligibility" or "med_history".

    Returns:
        Two upsert metadata effects (status + timestamp). Empty list when
        note_id is falsy so callers can blindly extend their effect list.
    """
    if not note_id:
        return []

    note = NoteEffect(instance_id=note_id)
    now_iso = arrow.utcnow().isoformat()
    return [
        note.upsert_metadata(
            key="surescripts_%s_status" % request_type,
            value="requested",
        ),
        note.upsert_metadata(
            key="surescripts_%s_at" % request_type,
            value=now_iso,
        ),
    ]
