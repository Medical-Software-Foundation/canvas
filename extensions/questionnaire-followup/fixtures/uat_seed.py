"""Seed the local SQLite database with one patient who exercises all four score rules.

Used by the fast UAT loop, which runs the real plugin runner rather than pytest:

    uv run canvas run-plugin ./questionnaire_followup \
        --reset-db --db-seed-file fixtures/uat_seed.py
    uv run canvas emit fixtures/PATIENT_PORTAL__GET_FORMS.ndjson

Five pairings are configured. Four should put a form in front of the patient and
two should stay silent, so the emitted effects are a positive AND a negative result.

This writes the plugin's own config row with raw SQL: `--reset-db` migrates and
seeds BEFORE the runner loads the plugin and creates `followupconfig`, so the
table has to be created here. The runner's CREATE TABLE IF NOT EXISTS is then a
no-op and this row survives.
"""

import json
from typing import Any
from uuid import uuid4

import django
from django.db import connection

django.setup()

from canvas_sdk.test_utils.factories import CanvasUserFactory, NoteFactory, PatientFactory  # noqa: E402
from canvas_sdk.v1.data import CurrentNoteStateEvent  # noqa: E402
from canvas_sdk.v1.data.note import NoteStates  # noqa: E402
from canvas_sdk.v1.data.questionnaire import (  # noqa: E402
    Interview,
    InterviewQuestionResponse,
    Questionnaire,
)


def questionnaire(code: str, name: str) -> Questionnaire:
    return Questionnaire.objects.create(
        status="AC", name=name, code=code, code_system="LOINC",
        expected_completion_time=1.0, can_originate_in_charting=True,
        use_case_in_charting="QUES", scoring_function_name="", scoring_code_system="",
        scoring_code="", search_tags="", use_in_shx=False, carry_forward="",
    )


def screen(patient: Any, form: Questionnaire, answers: list[str], note_id: int) -> None:
    interview = Interview.objects.create(
        deleted=False, committer=CanvasUserFactory.create(), status="AC", name=form.name,
        language_id=0, use_case_in_charting="QUES", patient=patient, note_id=note_id,
        appointment_id=0, progress_status="CO",
    )
    interview.questionnaires.add(form)
    for answer in answers:
        InterviewQuestionResponse.objects.create(
            interview=interview, questionnaire=form, response_option_value=answer
        )


def rule(
    name: str,
    trigger: str,
    followup: str,
    comparator: str,
    threshold: int,
    threshold_max: int = 0,
) -> dict[str, Any]:
    return {
        "id": uuid4().hex, "enabled": True, "name": name,
        "trigger_code": trigger, "followup_code": followup,
        "comparator": comparator, "threshold": threshold,
        "threshold_max": threshold_max or threshold,
        "trigger_lookback_days": 30, "suppression_days": 90,
    }


patient = PatientFactory.create()
note = NoteFactory.create(patient=patient)
CurrentNoteStateEvent.objects.create(note=note, state=NoteStates.NEW)

forms = {
    code: questionnaire(code, name)
    for code, name in [
        ("55758-7", "PHQ-2"), ("44249-1", "PHQ-9"),
        ("69736-7", "GAD-2"), ("69737-5", "GAD-7"),
        ("MINICOG", "Mini-Cog"), ("COG-FULL", "Full cognitive assessment"),
        ("AUDIT", "AUDIT"), ("AUDIT-BI", "Brief intervention"),
        ("TOB-1", "Tobacco use"), ("TOB-READY", "Readiness to quit"),
        ("PREFS", "Treatment preferences"),
    ]
}

screen(patient, forms["55758-7"], ["2", "2"], note.dbid)          # 4  -> at_least 3   FIRES
screen(patient, forms["69736-7"], ["0", "1"], note.dbid)          # 1  -> at_least 3   silent
screen(patient, forms["MINICOG"], ["1", "1"], note.dbid)          # 2  -> at_most 2    FIRES
screen(patient, forms["AUDIT"], ["4", "4", "4"], note.dbid)       # 12 -> 8..15        FIRES
screen(patient, forms["TOB-1"], ["every day", "yes"], note.dbid)  # unscoreable -> completed  FIRES

config = {
    "version": 1, "defaults_current_as_of": "2026-09-20", "defaults_reviewed": True,
    "rules": [
        rule("Depression", "55758-7", "44249-1", "at_least", 3),
        rule("Anxiety (below cutoff)", "69736-7", "69737-5", "at_least", 3),
        rule("Cognition", "MINICOG", "COG-FULL", "at_most", 2),
        rule("Hazardous drinking", "AUDIT", "AUDIT-BI", "between", 8, 15),
        rule("Tobacco", "TOB-1", "TOB-READY", "completed", 0),
        # Typed the wrong way round: 12 sits inside 10-14, but the rule is inert.
        rule("Backwards band", "55758-7", "PREFS", "between", 14, 10),
    ],
}

with connection.cursor() as cursor:
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS followupconfig "
        "(dbid integer PRIMARY KEY AUTOINCREMENT, key text, payload text)"
    )
    cursor.execute(
        "INSERT INTO followupconfig (key, payload) VALUES (%s, %s)",
        ["active", json.dumps(config)],
    )

print(f"SEEDED patient {patient.id}")
for code, form in sorted(forms.items()):
    print(f"  {code:10} {form.name:28} {form.id}")
