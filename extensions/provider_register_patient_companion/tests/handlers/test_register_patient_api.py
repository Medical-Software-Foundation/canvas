"""Tests for provider_register_patient_companion.handlers.register_patient_api."""
import json
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from provider_register_patient_companion.handlers import register_patient_api
from provider_register_patient_companion.handlers.register_patient_api import (
    RegisterPatientAPI,
    _describe_dob_match,
    _find_duplicates,
    _normalize_name,
    _normalize_phone,
    _parse_datetime,
    _parse_dob,
    _primary_phone,
    _serialize_duplicate,
    _validate_submission,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
EXISTING_PATIENT_UUID = "11111111-1111-1111-1111-111111111111"


def _make_api(
    query_params: dict | None = None,
    body: dict | None = None,
    headers: dict | None = None,
) -> RegisterPatientAPI:
    api = RegisterPatientAPI.__new__(RegisterPatientAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        json=lambda: body,
    )
    return api


def _make_patient(
    patient_id: str = EXISTING_PATIENT_UUID,
    first_name: str = "Jim Bob",
    last_name: str = "Jones",
    birth_date_value: date = date(1984, 3, 15),
    phones: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    """Build a stand-in for a canvas_sdk Patient instance."""
    telecom_items = [
        SimpleNamespace(system=system, value=value)
        for system, value in (phones or [("phone", "555-123-4567")])
    ]
    telecom_qs = MagicMock()
    telecom_qs.all.return_value = telecom_items
    telecom_qs.filter.return_value.order_by.return_value.first.return_value = (
        telecom_items[0] if telecom_items else None
    )

    primary = telecom_items[0] if telecom_items else None

    patient = SimpleNamespace(
        id=patient_id,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date_value,
        telecom=telecom_qs,
        primary_phone_number=primary,
    )
    return patient


class TestNormalizeHelpers:
    def test_normalize_name_strips_punctuation_and_case(self) -> None:
        assert _normalize_name("Jim-bob") == "jimbob"
        assert _normalize_name("Jim Bob") == "jimbob"
        assert _normalize_name("O'Neil") == "oneil"

    def test_normalize_name_handles_empty(self) -> None:
        assert _normalize_name("") == ""
        assert _normalize_name(None) == ""  # type: ignore[arg-type]

    def test_normalize_phone_keeps_digits(self) -> None:
        assert _normalize_phone("(555) 123-4567") == "5551234567"
        assert _normalize_phone("+1 555.123.4567") == "15551234567"
        assert _normalize_phone(None) == ""  # type: ignore[arg-type]


class TestParseHelpers:
    def test_parse_dob_valid(self) -> None:
        assert _parse_dob("1984-03-15") == date(1984, 3, 15)

    def test_parse_dob_invalid(self) -> None:
        assert _parse_dob("not-a-date") is None
        assert _parse_dob("") is None

    def test_parse_datetime_with_z(self) -> None:
        parsed = _parse_datetime("2026-04-19T12:00:00Z")
        assert parsed == datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_datetime_invalid(self) -> None:
        assert _parse_datetime("garbage") is None
        assert _parse_datetime("") is None


class TestDescribeDobMatch:
    def test_exact(self) -> None:
        d = date(1984, 3, 15)
        assert _describe_dob_match(d, d) == "name + dob"

    def test_one_day_off(self) -> None:
        assert _describe_dob_match(date(1984, 3, 15), date(1984, 3, 16)) == "name, dob off by 1 day"

    def test_multi_day_off(self) -> None:
        assert _describe_dob_match(date(1984, 3, 15), date(1984, 3, 20)) == "name, dob off by 5 days"

    def test_far_off(self) -> None:
        reason = _describe_dob_match(date(1984, 3, 15), date(1985, 3, 15))
        assert reason == "name, dob differs (1985-03-15)"


class TestPrimaryPhoneAndSerialize:
    def test_primary_phone_returns_value(self) -> None:
        patient = _make_patient()
        assert _primary_phone(patient) == "555-123-4567"

    def test_primary_phone_handles_no_phone(self) -> None:
        patient = _make_patient(phones=[])
        patient.primary_phone_number = None
        assert _primary_phone(patient) == ""

    def test_serialize_duplicate(self) -> None:
        patient = _make_patient()
        result = _serialize_duplicate(patient, ["phone"])
        assert result == {
            "id": EXISTING_PATIENT_UUID,
            "first_name": "Jim Bob",
            "last_name": "Jones",
            "birth_date": "1984-03-15",
            "phone": "555-123-4567",
            "reasons": ["phone"],
        }

    def test_serialize_duplicate_handles_missing_dob(self) -> None:
        patient = _make_patient()
        patient.birth_date = None
        result = _serialize_duplicate(patient, ["name + dob"])
        assert result["birth_date"] is None


class TestValidateSubmission:
    def _base(self) -> dict:
        return {
            "first_name": "Jim",
            "last_name": "Jones",
            "birth_date": "1984-03-15",
            "sex_at_birth": "M",
            "phone": "(555) 123-4567",
        }

    def test_valid(self) -> None:
        cleaned, errors = _validate_submission(self._base())
        assert errors == {}
        assert cleaned is not None
        assert cleaned["first_name"] == "Jim"
        assert cleaned["birth_date"] == date(1984, 3, 15)
        assert cleaned["phone_digits"] == "5551234567"

    def test_missing_fields(self) -> None:
        cleaned, errors = _validate_submission({})
        assert cleaned is None
        assert set(errors.keys()) == {
            "first_name",
            "last_name",
            "birth_date",
            "sex_at_birth",
            "phone",
        }

    def test_invalid_birth_date(self) -> None:
        body = self._base() | {"birth_date": "not-a-date"}
        cleaned, errors = _validate_submission(body)
        assert cleaned is None
        assert "valid date" in errors["birth_date"]

    def test_future_birth_date(self) -> None:
        future = date.today() + timedelta(days=1)
        body = self._base() | {"birth_date": future.isoformat()}
        cleaned, errors = _validate_submission(body)
        assert cleaned is None
        assert errors["birth_date"] == "Date of birth cannot be in the future."

    def test_invalid_sex(self) -> None:
        body = self._base() | {"sex_at_birth": "Z"}
        cleaned, errors = _validate_submission(body)
        assert cleaned is None
        assert "Sex at birth must be one of" in errors["sex_at_birth"]

    def test_short_phone(self) -> None:
        body = self._base() | {"phone": "555-12"}
        cleaned, errors = _validate_submission(body)
        assert cleaned is None
        assert "10 digits" in errors["phone"]


class TestFindDuplicates:
    def _cleaned(self, **overrides) -> dict:
        base = {
            "first_name": "Jim Bob",
            "last_name": "Jones",
            "birth_date": date(1984, 3, 15),
            "sex_at_birth": "M",
            "phone": "(555) 123-4567",
            "phone_digits": "5551234567",
        }
        base.update(overrides)
        return base

    def test_matches_on_normalized_name_and_exact_dob(self) -> None:
        candidate = _make_patient(first_name="Jim-bob", last_name="Jones")
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.side_effect = [
                [candidate],  # name pass
                MagicMock(distinct=MagicMock(return_value=[])),  # phone pass
            ]
            result = _find_duplicates(self._cleaned())

        assert len(result) == 1
        assert result[0]["reasons"] == ["name + dob"]
        assert result[0]["id"] == EXISTING_PATIENT_UUID

    def test_matches_with_close_dob(self) -> None:
        candidate = _make_patient(birth_date_value=date(1984, 3, 16))
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.side_effect = [
                [candidate],
                MagicMock(distinct=MagicMock(return_value=[])),
            ]
            result = _find_duplicates(self._cleaned())

        assert result[0]["reasons"] == ["name, dob off by 1 day"]

    def test_name_mismatch_excluded(self) -> None:
        candidate = _make_patient(first_name="Other", last_name="Person")
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.side_effect = [
                [candidate],
                MagicMock(distinct=MagicMock(return_value=[])),
            ]
            result = _find_duplicates(self._cleaned())

        assert result == []

    def test_phone_only_match(self) -> None:
        candidate = _make_patient(
            first_name="Totally",
            last_name="Different",
            birth_date_value=date(1970, 1, 1),
        )
        distinct_qs = MagicMock()
        distinct_qs.distinct.return_value = [candidate]
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.side_effect = [
                [],  # name pass returns nothing (outside window)
                distinct_qs,  # phone pass
            ]
            result = _find_duplicates(self._cleaned())

        assert len(result) == 1
        assert result[0]["reasons"] == ["phone"]

    def test_phone_candidate_filtered_when_digits_mismatch(self) -> None:
        candidate = _make_patient(phones=[("phone", "555-999-0000")])
        distinct_qs = MagicMock()
        distinct_qs.distinct.return_value = [candidate]
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.side_effect = [[], distinct_qs]
            result = _find_duplicates(self._cleaned())

        assert result == []

    def test_same_patient_matches_name_and_phone(self) -> None:
        candidate = _make_patient()
        distinct_qs = MagicMock()
        distinct_qs.distinct.return_value = [candidate]
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.side_effect = [[candidate], distinct_qs]
            result = _find_duplicates(self._cleaned())

        assert len(result) == 1
        assert result[0]["reasons"] == ["name + dob", "phone"]

    def test_short_phone_skips_phone_pass(self) -> None:
        cleaned = self._cleaned(phone_digits="123")
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.return_value = []
            result = _find_duplicates(cleaned)

        # Only one `filter` call should have happened (the name pass).
        assert mock_cls.objects.filter.call_count == 1
        assert result == []


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
    def test_returns_html_with_no_store(self) -> None:
        api = _make_api()
        with patch.object(
            register_patient_api, "render_to_string", return_value="<html/>"
        ) as mock_render:
            response = api.index()[0]
        assert mock_render.mock_calls == [
            call("static/index.html", {"cache_bust": register_patient_api._CACHE_BUST})
        ]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<html/>"
        assert response.headers.get("Cache-Control") == "no-store"


def _good_submission() -> dict:
    return {
        "first_name": "Jim",
        "last_name": "Jones",
        "birth_date": "1984-03-15",
        "sex_at_birth": "M",
        "phone": "(555) 123-4567",
    }


class TestCheckEndpoint:
    def test_validation_errors_returned(self) -> None:
        api = _make_api(body={})
        response = api.check()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        payload = json.loads(response.content)
        assert "errors" in payload

    def test_returns_duplicates(self) -> None:
        api = _make_api(body=_good_submission())
        with patch.object(register_patient_api, "_find_duplicates", return_value=[{"id": "x"}]) as mock_find:
            response = api.check()[0]
        assert mock_find.call_count == 1
        assert response.status_code == HTTPStatus.OK
        assert json.loads(response.content) == {"duplicates": [{"id": "x"}]}


class TestCreateEndpoint:
    def test_validation_errors_returned(self) -> None:
        api = _make_api(body={"first_name": ""})
        response = api.create()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_duplicates_without_ack_returns_409(self) -> None:
        api = _make_api(body=_good_submission())
        with patch.object(
            register_patient_api, "_find_duplicates", return_value=[{"id": "x"}]
        ):
            response = api.create()[0]
        assert response.status_code == HTTPStatus.CONFLICT
        payload = json.loads(response.content)
        assert payload["duplicates"] == [{"id": "x"}]

    def test_success_emits_effect_and_returns_202(self) -> None:
        api = _make_api(body=_good_submission() | {"acknowledged": True})
        with patch.object(register_patient_api, "_find_duplicates", return_value=[]):
            result = api.create()

        assert len(result) == 2
        effect = result[0]
        effect_payload = json.loads(effect.payload)
        data = effect_payload["data"]
        assert data["first_name"] == "Jim"
        assert data["last_name"] == "Jones"
        assert data["birthdate"] == "1984-03-15"
        assert data["sex_at_birth"] == "M"
        assert data["contact_points"][0]["system"] == "phone"
        assert data["contact_points"][0]["value"] == "(555) 123-4567"
        assert data["contact_points"][0]["use"] == "mobile"
        assert data["contact_points"][0]["rank"] == 1

        response = result[1]
        assert response.status_code == HTTPStatus.ACCEPTED
        body = json.loads(response.content)
        assert body["status"] == "submitted"
        assert body["lookup_params"] == {
            "first_name": "Jim",
            "last_name": "Jones",
            "birth_date": "1984-03-15",
        }
        assert "lookup_started_at" in body

    def test_success_with_ack_when_duplicates_exist(self) -> None:
        api = _make_api(body=_good_submission() | {"acknowledged": True})
        with patch.object(
            register_patient_api, "_find_duplicates", return_value=[{"id": "x"}]
        ):
            result = api.create()

        # Still 2-element response (effect + 202), duplicates were acknowledged
        assert len(result) == 2
        response = result[1]
        assert response.status_code == HTTPStatus.ACCEPTED


class TestFindEndpoint:
    def test_missing_params_returns_400(self) -> None:
        api = _make_api(query_params={})
        response = api.find()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_after_returns_400(self) -> None:
        api = _make_api(
            query_params={
                "first_name": "Jim",
                "last_name": "Jones",
                "birth_date": "1984-03-15",
                "after": "junk",
            }
        )
        response = api.find()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_returns_patient_id_when_found(self) -> None:
        api = _make_api(
            query_params={
                "first_name": "Jim",
                "last_name": "Jones",
                "birth_date": "1984-03-15",
                "after": "2026-04-19T12:00:00Z",
            }
        )
        candidate = _make_patient(patient_id="found-uuid")
        qs = MagicMock()
        qs.order_by.return_value.first.return_value = candidate
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.return_value = qs
            response = api.find()[0]

        assert response.status_code == HTTPStatus.OK
        assert json.loads(response.content) == {"patient_id": "found-uuid"}

        assert mock_cls.objects.filter.mock_calls[0] == call(
            first_name="Jim",
            last_name="Jones",
            birth_date=date(1984, 3, 15),
            created__gte=datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_returns_null_when_not_found(self) -> None:
        api = _make_api(
            query_params={
                "first_name": "Jim",
                "last_name": "Jones",
                "birth_date": "1984-03-15",
                "after": "2026-04-19T12:00:00Z",
            }
        )
        qs = MagicMock()
        qs.order_by.return_value.first.return_value = None
        with patch.object(register_patient_api, "Patient") as mock_cls:
            mock_cls.objects.filter.return_value = qs
            response = api.find()[0]

        assert json.loads(response.content) == {"patient_id": None}


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(
            register_patient_api, "render_to_string", return_value="// js"
        ) as mock_render:
            response = api.main_js()[0]
        assert mock_render.mock_calls == [call("static/main.js")]
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(
            register_patient_api, "render_to_string", return_value="body{}"
        ) as mock_render:
            response = api.styles_css()[0]
        assert mock_render.mock_calls == [call("static/styles.css")]
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
