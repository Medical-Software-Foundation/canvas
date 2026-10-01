"""Tests for the inline-edit metadata endpoint (T5).

POST /<patient_id>/metadata/<key> with form_data `value=...`. The handler
allows the write only if `METADATA_FIELDS` declares the key with
`editable: true`. Otherwise the response is 403 with no effect emitted.

No canvas_sdk mocking — we inspect the effect list directly.
"""

__is_plugin__ = True

import json
from http import HTTPStatus
from typing import Any

import pytest

from canvas_sdk.test_utils.factories import PatientFactory

from tests._helpers import build_api


pytestmark = pytest.mark.django_db


def _api(*, metadata_fields: list[dict[str, Any]], patient_id: str, key: str, value: str) -> Any:
    return build_api(
        secrets={"METADATA_FIELDS": json.dumps(metadata_fields)},
        path_params={"patient_id": patient_id, "key": key},
        form_data={"value": value},
    )


EDITABLE_RISK = [
    {"key": "risk_score", "label": "Risk", "type": "SELECT",
     "editable": True, "options": ["Low", "Medium", "High"]},
]
READONLY_SERVICES = [
    {"key": "services", "label": "Services", "type": "TEXT", "editable": False},
]


class TestUpdateMetadata:
    def test_editable_key_emits_upsert_effect(self) -> None:
        patient = PatientFactory.create()
        api = _api(
            metadata_fields=EDITABLE_RISK,
            patient_id=str(patient.id),
            key="risk_score",
            value="High",
        )
        result = api.update_metadata()
        # Response + 1 effect
        responses = [r for r in result if hasattr(r, "status_code")]
        effects = [r for r in result if not hasattr(r, "status_code")]
        assert responses[0].status_code == HTTPStatus.OK
        assert len(effects) == 1
        payload = json.loads(effects[0].payload)
        body_str = json.dumps(payload)
        assert str(patient.id) in body_str
        assert "High" in body_str

    def test_readonly_key_returns_403_no_effect(self) -> None:
        patient = PatientFactory.create()
        api = _api(
            metadata_fields=READONLY_SERVICES,
            patient_id=str(patient.id),
            key="services",
            value="Hospice",
        )
        result = api.update_metadata()
        responses = [r for r in result if hasattr(r, "status_code")]
        effects = [r for r in result if not hasattr(r, "status_code")]
        assert responses[0].status_code == HTTPStatus.FORBIDDEN
        assert effects == []

    def test_unknown_key_returns_403_no_effect(self) -> None:
        patient = PatientFactory.create()
        api = _api(
            metadata_fields=EDITABLE_RISK,
            patient_id=str(patient.id),
            key="not_in_config",
            value="anything",
        )
        result = api.update_metadata()
        responses = [r for r in result if hasattr(r, "status_code")]
        effects = [r for r in result if not hasattr(r, "status_code")]
        assert responses[0].status_code == HTTPStatus.FORBIDDEN
        assert effects == []

    def test_empty_value_is_accepted(self) -> None:
        # An empty submission clears the field — useful for "no selection".
        patient = PatientFactory.create()
        api = _api(
            metadata_fields=EDITABLE_RISK,
            patient_id=str(patient.id),
            key="risk_score",
            value="",
        )
        result = api.update_metadata()
        responses = [r for r in result if hasattr(r, "status_code")]
        effects = [r for r in result if not hasattr(r, "status_code")]
        assert responses[0].status_code == HTTPStatus.OK
        assert len(effects) == 1

    def test_missing_metadata_fields_secret_blocks_everything(self) -> None:
        patient = PatientFactory.create()
        api = build_api(
            secrets={},
            path_params={"patient_id": str(patient.id), "key": "risk_score"},
            form_data={"value": "High"},
        )
        result = api.update_metadata()
        responses = [r for r in result if hasattr(r, "status_code")]
        effects = [r for r in result if not hasattr(r, "status_code")]
        assert responses[0].status_code == HTTPStatus.FORBIDDEN
        assert effects == []

    def test_select_value_not_in_options_is_rejected(self) -> None:
        patient = PatientFactory.create()
        api = _api(
            metadata_fields=EDITABLE_RISK,
            patient_id=str(patient.id),
            key="risk_score",
            value="Critical",  # not in options
        )
        result = api.update_metadata()
        responses = [r for r in result if hasattr(r, "status_code")]
        effects = [r for r in result if not hasattr(r, "status_code")]
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert effects == []
