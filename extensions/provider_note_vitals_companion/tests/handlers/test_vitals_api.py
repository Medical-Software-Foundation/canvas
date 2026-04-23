"""Tests for provider_note_vitals_companion.handlers.vitals_api."""
import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from provider_note_vitals_companion.handlers import vitals_api
from provider_note_vitals_companion.handlers.vitals_api import (
    VitalsAPI,
    _coerce_payload,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
NOTE_UUID = "00000000-0000-0000-0000-00000000aaaa"


def _make_api(
    query_params: dict | None = None,
    body: dict | None = None,
    headers: dict | None = None,
) -> VitalsAPI:
    api = VitalsAPI.__new__(VitalsAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        json=lambda: body,
    )
    return api


class TestCoercePayload:
    def test_empty_returns_empty(self) -> None:
        assert _coerce_payload({}) == ({}, None)

    def test_skips_none_and_empty(self) -> None:
        fields, error = _coerce_payload(
            {"pulse": None, "weight_lbs": "", "note": None, "body_temperature": ""}
        )
        assert fields == {}
        assert error is None

    def test_coerces_ints(self) -> None:
        fields, error = _coerce_payload({"pulse": "72", "weight_lbs": 165})
        assert fields == {"pulse": 72, "weight_lbs": 165}
        assert error is None

    def test_invalid_int_returns_error(self) -> None:
        fields, error = _coerce_payload({"pulse": "abc"})
        assert fields == {}
        assert error == "pulse must be an integer"

    def test_coerces_floats(self) -> None:
        fields, error = _coerce_payload({"body_temperature": "98.6"})
        assert fields == {"body_temperature": 98.6}
        assert error is None

    def test_invalid_float_returns_error(self) -> None:
        fields, error = _coerce_payload({"body_temperature": "warm"})
        assert fields == {}
        assert error == "body_temperature must be a number"

    def test_coerces_str(self) -> None:
        fields, error = _coerce_payload({"note": "patient in distress"})
        assert fields == {"note": "patient in distress"}
        assert error is None

    def test_ignores_unknown_fields(self) -> None:
        fields, error = _coerce_payload({"foo": "bar", "pulse": 60})
        assert fields == {"pulse": 60}
        assert error is None


class TestAuthenticate:
    def test_staff_session_passes(self) -> None:
        api = _make_api()
        credentials = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Staff"})
        assert api.authenticate(credentials) is True

    def test_non_staff_session_rejected(self) -> None:
        api = _make_api()
        credentials = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Patient"})
        with pytest.raises(InvalidCredentialsError):
            api.authenticate(credentials)


class TestIndex:
    def test_returns_html_response(self) -> None:
        api = _make_api()
        with patch.object(
            vitals_api, "render_to_string", return_value="<html>x</html>"
        ) as mock_render:
            result = api.index()

        assert mock_render.mock_calls == [
            call("static/index.html", {"cache_bust": vitals_api._CACHE_BUST})
        ]
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<html>x</html>"
        assert response.headers["Content-Type"] == "text/html"


class TestSubmitVitals:
    def test_missing_note_id_returns_400(self) -> None:
        api = _make_api(query_params={}, body={"pulse": 72})
        response = api.submit_vitals()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"note_id" in response.content

    def test_blank_note_id_returns_400(self) -> None:
        api = _make_api(query_params={"note_id": "   "}, body={"pulse": 72})
        response = api.submit_vitals()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_empty_body_returns_400(self) -> None:
        api = _make_api(query_params={"note_id": NOTE_UUID}, body=None)
        response = api.submit_vitals()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"at least one vital" in response.content

    def test_no_recognized_fields_returns_400(self) -> None:
        api = _make_api(query_params={"note_id": NOTE_UUID}, body={"foo": "bar"})
        response = api.submit_vitals()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"at least one vital" in response.content

    def test_coerce_error_returns_400(self) -> None:
        api = _make_api(
            query_params={"note_id": NOTE_UUID}, body={"pulse": "not-a-number"}
        )
        response = api.submit_vitals()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"pulse must be an integer" in response.content

    def test_pydantic_validation_error_returns_400(self) -> None:
        api = _make_api(
            query_params={"note_id": NOTE_UUID}, body={"pulse": 9999}
        )
        response = api.submit_vitals()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        payload = json.loads(response.content)
        assert payload["error"] == "invalid vitals"
        assert isinstance(payload["detail"], list)

    def test_success_originates_command_and_returns_202(self) -> None:
        api = _make_api(
            query_params={"note_id": NOTE_UUID},
            body={
                "blood_pressure_systole": "120",
                "blood_pressure_diastole": 80,
                "pulse": 72,
                "body_temperature": "98.6",
                "note": " after a walk ",
            },
        )

        result = api.submit_vitals()

        assert len(result) == 2
        effect = result[0]
        effect_payload = json.loads(effect.payload)
        assert effect_payload["note"] == NOTE_UUID
        assert effect_payload["data"]["blood_pressure_systole"] == 120
        assert effect_payload["data"]["blood_pressure_diastole"] == 80
        assert effect_payload["data"]["pulse"] == 72
        assert effect_payload["data"]["body_temperature"] == 98.6
        assert effect_payload["data"]["note"] == " after a walk "
        assert effect_payload["data"]["note_uuid"] == NOTE_UUID

        json_response = result[1]
        assert json_response.status_code == HTTPStatus.ACCEPTED
        body = json.loads(json_response.content)
        assert body == {"status": "originated"}


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(
            vitals_api, "render_to_string", return_value="// js"
        ) as mock_render:
            response = api.main_js()[0]
        assert mock_render.mock_calls == [call("static/main.js")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(
            vitals_api, "render_to_string", return_value="body{}"
        ) as mock_render:
            response = api.styles_css()[0]
        assert mock_render.mock_calls == [call("static/styles.css")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
