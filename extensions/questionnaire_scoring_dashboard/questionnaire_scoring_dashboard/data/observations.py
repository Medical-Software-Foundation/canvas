"""Thin database access for scored survey Observations.

Returns plain dicts so the pure services can be tested without a DB.
Mirrors the base scoring_visualizer query and filters entered_in_error.
"""

from __future__ import annotations

from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.observation import Observation


def fetch_survey_rows(patient_id: str) -> list[dict]:
    """Return scored survey-Observation rows for a patient as plain dicts.

    Attaches each row's note date-of-service (`note_dos`) so the trend can date
    a score by when it was administered. Questionnaire-result observations often
    have no `effective_datetime`, so the note DOS is the reliable clinical date.

    Also pulls the observation's coding `code` (`codings__code`) in the same
    query (one LEFT JOIN, no N+1). The code is the version-stable questionnaire
    identifier: when a questionnaire is edited, Canvas appends a "(vN)" suffix to
    its name but leaves the code unchanged, so the scoring service groups on the
    code to keep every version of an instrument on a single trend.
    """
    rows = list(
        Observation.objects.for_patient(patient_id)
        .filter(category="survey")
        .exclude(entered_in_error__isnull=False)
        .values("note_id", "value", "effective_datetime", "created", "name", "codings__code")
    )
    note_ids = {row["note_id"] for row in rows if row["note_id"]}
    dos_by_note: dict[int, object] = {}
    if note_ids:
        dos_by_note = dict(
            Note.objects.filter(dbid__in=note_ids).values_list(
                "dbid", "datetime_of_service"
            )
        )
    for row in rows:
        dos = dos_by_note.get(row["note_id"])
        row["note_dos"] = dos.isoformat() if dos else None
        row["code"] = row.get("codings__code")
    return rows
