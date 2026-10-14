"""Shared fixtures for building questionnaires and interviews in the test database.

Each test runs inside a transaction that is rolled back at the end.
See https://docs.canvasmedical.com/sdk/testing-utils/
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from canvas_sdk.test_utils.factories import CanvasUserFactory
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.questionnaire import (
    Interview,
    InterviewQuestionResponse,
    Questionnaire,
)

import questionnaire_followup


@pytest.fixture
def manifest() -> dict[str, Any]:
    """The plugin's CANVAS_MANIFEST.json, to check the code against what Canvas is told."""
    path = Path(questionnaire_followup.__file__).parent / "CANVAS_MANIFEST.json"
    manifest: dict[str, Any] = json.loads(path.read_text())
    return manifest


@pytest.fixture
def make_questionnaire() -> Callable[..., Questionnaire]:
    """Build an active questionnaire addressed by `code`."""

    def _make(code: str, name: str, can_originate: bool = True) -> Questionnaire:
        return Questionnaire.objects.create(
            status="AC",
            name=name,
            code=code,
            code_system="LOINC",
            expected_completion_time=1.0,
            can_originate_in_charting=can_originate,
            use_case_in_charting="QUES",
            scoring_function_name="",
            scoring_code_system="",
            scoring_code="",
            search_tags="",
            use_in_shx=False,
            carry_forward="",
        )

    return _make


@pytest.fixture
def make_interview() -> Callable[..., Interview]:
    """Build a committed interview for a questionnaire with the given ordinal answers."""

    def _make(
        patient: Patient,
        questionnaire: Questionnaire,
        answers: list[str],
        age_days: int = 0,
        note_id: int = 0,
    ) -> Interview:
        interview = Interview.objects.create(
            deleted=False,
            committer=CanvasUserFactory.create(),
            status="AC",
            name=questionnaire.name,
            language_id=0,
            use_case_in_charting="QUES",
            patient=patient,
            note_id=note_id,
            appointment_id=0,
            progress_status="CO",
        )
        interview.questionnaires.add(questionnaire)
        for answer in answers:
            InterviewQuestionResponse.objects.create(
                interview=interview,
                questionnaire=questionnaire,
                response_option_value=answer,
            )
        if age_days:
            # `created` is auto_now_add, so it can only be backdated with an update().
            Interview.objects.filter(pk=interview.pk).update(
                created=datetime.now(UTC) - timedelta(days=age_days)
            )
            interview.refresh_from_db()
        return interview

    return _make
