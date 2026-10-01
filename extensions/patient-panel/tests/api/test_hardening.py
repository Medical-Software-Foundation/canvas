"""Tests for defensive-hardening fixes from the code review.

Covers: UUID validation on metadata-write endpoints, 404s on unknown/
malformed path ids, page-param clamping, and SELECT-options validation. No
canvas_sdk mocking — effect/response lists are inspected directly.
"""

__is_plugin__ = True

import json
from http import HTTPStatus

import pytest

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Response

from tests._helpers import build_api


pytestmark = pytest.mark.django_db

_UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"

EDITABLE_RISK = [
    {"key": "risk_score", "label": "Risk", "type": "SELECT",
     "editable": True, "options": ["Low", "Medium", "High"]},
]


def _statuses_and_effects(
    result: list[Response | Effect],
) -> tuple[list[Response], list[Effect]]:
    responses = [r for r in result if hasattr(r, "status_code")]
    effects = [r for r in result if not hasattr(r, "status_code")]
    return responses, effects


class TestPatientIdValidation:
    def test_set_flag_rejects_non_uuid(self) -> None:
        api = build_api(
            path_params={"patient_id": "not-a-uuid"},
            form_data={"color": "red"},
        )
        responses, effects = _statuses_and_effects(api.set_flag())
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert effects == []

    def test_update_metadata_rejects_non_uuid(self) -> None:
        api = build_api(
            secrets={"METADATA_FIELDS": json.dumps(EDITABLE_RISK)},
            path_params={"patient_id": "bogus", "key": "risk_score"},
            form_data={"value": "High"},
        )
        responses, effects = _statuses_and_effects(api.update_metadata())
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert effects == []

    def test_save_clinical_notes_rejects_non_uuid(self) -> None:
        api = build_api(
            path_params={"patient_id": "bogus"},
            form_data={"clinical_note": "hello"},
        )
        responses, effects = _statuses_and_effects(api.save_clinical_notes())
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert effects == []


class TestPathParamNotFound:
    def test_get_clinical_notes_non_uuid_404(self) -> None:
        api = build_api(path_params={"patient_id": "bad"})
        responses, _ = _statuses_and_effects(api.get_clinical_notes())
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_get_clinical_notes_unknown_patient_404(self) -> None:
        api = build_api(path_params={"patient_id": _UNKNOWN_UUID})
        responses, _ = _statuses_and_effects(api.get_clinical_notes())
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_view_clinical_notes_unknown_patient_404(self) -> None:
        api = build_api(path_params={"patient_id": _UNKNOWN_UUID})
        responses, _ = _statuses_and_effects(api.view_clinical_notes())
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_post_task_comment_non_uuid_404(self) -> None:
        api = build_api(
            path_params={"task_id": "bad"},
            headers={"canvas-logged-in-user-id": _UNKNOWN_UUID},
            form_data={"comment_content": "hi"},
        )
        responses, _ = _statuses_and_effects(api.post_task_comment())
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_post_task_comment_unknown_task_404(self) -> None:
        api = build_api(
            path_params={"task_id": _UNKNOWN_UUID},
            headers={"canvas-logged-in-user-id": _UNKNOWN_UUID},
            form_data={"comment_content": "hi"},
        )
        responses, _ = _statuses_and_effects(api.post_task_comment())
        assert responses[0].status_code == HTTPStatus.NOT_FOUND


class TestPageClamping:
    def test_non_numeric_page_does_not_crash(self) -> None:
        api = build_api(query_params={"page": "abc"})
        result = api.get_table()
        responses, _ = _statuses_and_effects(result)
        assert responses[0].status_code == HTTPStatus.OK

    def test_negative_page_does_not_crash(self) -> None:
        api = build_api(query_params={"page": "-5"})
        result = api.get_table()
        responses, _ = _statuses_and_effects(result)
        assert responses[0].status_code == HTTPStatus.OK

    def test_zero_page_does_not_crash(self) -> None:
        api = build_api(query_params={"page": "0"})
        result = api.get_table()
        responses, _ = _statuses_and_effects(result)
        assert responses[0].status_code == HTTPStatus.OK


class TestSelectOptionsValidation:
    def test_dict_options_rejects_non_empty_value(self) -> None:
        from patient_panel.services.columns import is_valid_metadata_value

        field = {"type": "SELECT", "options": {"a": 1, "b": 2}}
        assert is_valid_metadata_value(field, "a") is False
        # Empty always clears regardless of type.
        assert is_valid_metadata_value(field, "") is True
