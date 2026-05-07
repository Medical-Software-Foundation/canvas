"""Tests for profile_api.ProfileAPI and its helper functions."""
import json
from datetime import date
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_generated.messages.effects_pb2 import EffectType

from provider_patient_profile_companion.handlers import profile_api
from provider_patient_profile_companion.handlers.profile_api import (
    ProfileAPI,
    _build_patient_effect,
    _parse_birthdate,
    _serialize_patient,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_UUID = "00000000-0000-0000-0000-0000000000aa"


def _make_api(
    query_params: dict | None = None,
    body: dict | None = None,
    headers: dict | None = None,
) -> ProfileAPI:
    api = ProfileAPI.__new__(ProfileAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        json=lambda: body,
    )
    return api


def _make_patient(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=PATIENT_UUID,
        first_name="Ada",
        middle_name="B",
        last_name="Lovelace",
        prefix="",
        suffix="",
        nickname="",
        birth_date=date(1980, 1, 2),
        sex_at_birth="F",
        social_security_number="123456789",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------- helpers ----------


class TestParseBirthdate:
    def test_valid(self) -> None:
        assert _parse_birthdate("1980-01-02") == (date(1980, 1, 2), None)

    def test_required(self) -> None:
        assert _parse_birthdate("")[1] == "birthdate is required"
        assert _parse_birthdate(None)[1] == "birthdate is required"

    def test_must_be_string(self) -> None:
        assert _parse_birthdate(19800102)[1] == "birthdate must be a string"

    def test_invalid_format(self) -> None:
        assert _parse_birthdate("not-a-date")[1] == "birthdate must be in YYYY-MM-DD format"


class TestSerializePatient:
    def test_minimal(self) -> None:
        out = _serialize_patient(_make_patient())
        assert out["patient_id"] == PATIENT_UUID
        assert out["fields"]["first_name"] == "Ada"
        assert out["fields"]["birthdate"] == "1980-01-02"
        assert out["fields"]["sex_at_birth"] == "F"
        # No fields the SDK can't write through. Pharmacies and provider/location
        # were dropped after we discovered platform gaps.
        assert "preferred_pharmacies" not in out["fields"]
        assert "default_provider" not in out["fields"]
        assert "default_location" not in out["fields"]
        # sex_at_birth options for the dropdown
        values = [c["value"] for c in out["options"]["sex_at_birth"]]
        assert "F" in values and "M" in values and "" in values

    def test_no_birthdate_emits_empty_string(self) -> None:
        patient = _make_patient(birth_date=None)
        assert _serialize_patient(patient)["fields"]["birthdate"] == ""


class TestBuildPatientEffect:
    def _base_fields(self, **overrides):
        fields = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "middle_name": "B",
            "prefix": "",
            "suffix": "",
            "nickname": "",
            "birthdate": "1980-01-02",
            "sex_at_birth": "F",
            "social_security_number": "123456789",
        }
        fields.update(overrides)
        return fields

    def test_happy_path(self) -> None:
        effect, err = _build_patient_effect(PATIENT_UUID, self._base_fields())
        assert err is None and effect is not None
        assert effect.patient_id == PATIENT_UUID
        assert effect.first_name == "Ada"
        assert effect.birthdate == date(1980, 1, 2)
        assert effect.sex_at_birth.value == "F"

    def test_first_name_required(self) -> None:
        _, err = _build_patient_effect(PATIENT_UUID, self._base_fields(first_name="  "))
        assert err == "first_name is required"

    def test_last_name_required(self) -> None:
        _, err = _build_patient_effect(PATIENT_UUID, self._base_fields(last_name=""))
        assert err == "last_name is required"

    def test_birthdate_required(self) -> None:
        _, err = _build_patient_effect(PATIENT_UUID, self._base_fields(birthdate=""))
        assert err == "birthdate is required"

    def test_sex_at_birth_must_be_valid_choice(self) -> None:
        _, err = _build_patient_effect(PATIENT_UUID, self._base_fields(sex_at_birth="Z"))
        assert err == "sex_at_birth must be one of F, M, O, UNK, or blank"

    def test_blank_sex_at_birth_allowed(self) -> None:
        effect, err = _build_patient_effect(PATIENT_UUID, self._base_fields(sex_at_birth=""))
        assert err is None and effect is not None
        assert effect.sex_at_birth.value == ""


# ---------- ProfileAPI endpoints ----------


class TestIndex:
    def test_returns_html(self) -> None:
        api = _make_api()
        with patch.object(profile_api, "render_to_string", return_value="<html></html>"):
            responses = api.index()
        assert len(responses) == 1
        assert responses[0].status_code == HTTPStatus.OK


class TestStatic:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(profile_api, "render_to_string", return_value="js"):
            responses = api.main_js()
        assert responses[0].headers["Content-Type"] == "text/javascript"
        assert responses[0].status_code == HTTPStatus.OK

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(profile_api, "render_to_string", return_value="css"):
            responses = api.styles_css()
        assert responses[0].headers["Content-Type"] == "text/css"


class TestData:
    def test_missing_patient_id_returns_400(self) -> None:
        api = _make_api(query_params={})
        responses = api.data()
        body = json.loads(responses[0].content)
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert "patient_id" in body["error"]

    def test_unknown_patient_returns_404(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        manager = MagicMock()
        manager.get.side_effect = profile_api.Patient.DoesNotExist
        with patch.object(profile_api.Patient, "objects", manager):
            responses = api.data()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_serialized_patient(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        patient = _make_patient()
        manager = MagicMock()
        manager.get.return_value = patient
        with patch.object(profile_api.Patient, "objects", manager):
            responses = api.data()
        body = json.loads(responses[0].content)
        assert body["patient_id"] == PATIENT_UUID
        assert body["fields"]["first_name"] == "Ada"


class TestSave:
    def _body(self, **overrides):
        return {
            "patient_id": PATIENT_UUID,
            "fields": {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "birthdate": "1980-01-02",
                "sex_at_birth": "F",
                **overrides,
            },
        }

    def test_missing_patient_id(self) -> None:
        api = _make_api(body={"fields": {}})
        responses = api.save()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_patient(self) -> None:
        api = _make_api(body=self._body())
        manager = MagicMock()
        manager.get.side_effect = profile_api.Patient.DoesNotExist
        with patch.object(profile_api.Patient, "objects", manager):
            responses = api.save()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_fields_must_be_dict(self) -> None:
        api = _make_api(body={"patient_id": PATIENT_UUID, "fields": "nope"})
        manager = MagicMock()
        manager.get.return_value = _make_patient()
        with patch.object(profile_api.Patient, "objects", manager):
            responses = api.save()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_validation_error_returns_400(self) -> None:
        api = _make_api(body=self._body(first_name=""))
        manager = MagicMock()
        manager.get.return_value = _make_patient()
        with patch.object(profile_api.Patient, "objects", manager):
            responses = api.save()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(responses[0].content)
        assert body["error"] == "first_name is required"

    def test_happy_path_returns_effect_and_ok(self) -> None:
        api = _make_api(body=self._body())
        manager = MagicMock()
        manager.get.return_value = _make_patient()
        with patch.object(profile_api.Patient, "objects", manager):
            responses = api.save()
        assert len(responses) == 2
        effect, ok_response = responses
        assert effect.type == EffectType.UPDATE_PATIENT
        assert json.loads(ok_response.content) == {"ok": True}

    def test_empty_body_handled(self) -> None:
        api = _make_api(body=None)
        responses = api.save()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
