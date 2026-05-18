"""Tests for fhir_client.py."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from scheduling_with_rooms.utils.fhir_client import FHIRClient


@pytest.fixture
def secrets():
    return {
        "FHIR_BASE_URL": "https://fumage-instance.canvasmedical.com",
        "FHIR_CLIENT_ID": "client-id",
        "FHIR_CLIENT_SECRET": "client-secret",
    }


@pytest.fixture
def client(secrets):
    with patch("scheduling_with_rooms.utils.fhir_client.Http"):
        return FHIRClient(secrets)


def test_init_strips_trailing_slash():
    secrets = {
        "FHIR_BASE_URL": "https://fumage-instance.canvasmedical.com/",
        "FHIR_CLIENT_ID": "id",
        "FHIR_CLIENT_SECRET": "secret",
    }
    with patch("scheduling_with_rooms.utils.fhir_client.Http"):
        c = FHIRClient(secrets)
    assert c._base_url == "https://fumage-instance.canvasmedical.com"


def test_init_derives_auth_url_without_fumage_prefix(client):
    assert client._auth_base_url == "https://instance.canvasmedical.com"


def test_is_token_valid_when_no_token(client):
    assert client._is_token_valid() is False


def test_is_token_valid_when_expired(client):
    client._token = "abc"
    client._token_expires_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    assert client._is_token_valid() is False


def test_is_token_valid_when_active(client):
    client._token = "abc"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    assert client._is_token_valid() is True


def test_fetch_token_sets_token_and_expiry(client):
    fake_response = MagicMock()
    fake_response.json.return_value = {"access_token": "tok-1", "expires_in": 3600}
    client._http.post.return_value = fake_response

    client._fetch_token()

    assert client._token == "tok-1"
    assert client._token_expires_at is not None


def test_get_token_fetches_when_invalid(client):
    fake_response = MagicMock()
    fake_response.json.return_value = {"access_token": "new-tok", "expires_in": 3600}
    client._http.post.return_value = fake_response

    token = client._get_token()
    assert token == "new-tok"


def test_get_token_returns_cached_when_valid(client):
    client._token = "cached"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    assert client._get_token() == "cached"


def test_auth_headers_contains_bearer(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    headers = client._auth_headers()
    assert headers == {"Authorization": "Bearer tk"}


def test_fhir_quote_preserves_commas():
    result = FHIRClient._fhir_quote("a,b/c")
    assert "," in result


def test_get_no_params(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"resourceType": "Patient"}
    client._http.get.return_value = fake_resp

    result = client._get("/Patient/123")
    assert result == {"resourceType": "Patient"}


def test_get_with_params(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"data": []}
    client._http.get.return_value = fake_resp

    result = client._get("/Slot", params={"schedule": "abc"})
    assert result == {"data": []}


def test_extract_tz_finds_extension(client):
    patient = {
        "extension": [
            {"url": "http://example.com/other", "valueCode": "X"},
            {
                "url": "http://hl7.org/fhir/StructureDefinition/tz-code",
                "valueCode": "America/New_York",
            },
        ]
    }
    assert client._extract_tz(patient) == "America/New_York"


def test_extract_tz_no_extension(client):
    assert client._extract_tz({}) == ""
    assert client._extract_tz({"extension": []}) == ""


def test_get_patient_timezone_success(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "extension": [
            {
                "url": "http://hl7.org/fhir/StructureDefinition/tz-code",
                "valueCode": "America/Chicago",
            }
        ]
    }
    client._http.get.return_value = fake_resp

    assert client.get_patient_timezone("p1") == "America/Chicago"


def test_get_patient_timezone_handles_exception(client):
    client._http.get.side_effect = requests.RequestException("boom")
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    assert client.get_patient_timezone("p1") == ""


def test_get_patient_timezones_empty_list(client):
    assert client.get_patient_timezones([]) == {}


def test_get_patient_timezones_returns_dict(client):
    with patch.object(client, "get_patient_timezone") as mock_pt:
        mock_pt.side_effect = ["America/New_York", ""]
        result = client.get_patient_timezones(["p1", "p2"])
        # Only patients with timezones included
        assert result == {"p1": "America/New_York"}


def test_get_schedules_returns_resources(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "entry": [
            {"resource": {"id": "Location.l1-Staff.s1"}},
            {"resource": {"id": "Location.l2-Staff.s2"}},
            {"foo": "bar"},  # no resource key, skipped
        ]
    }
    client._http.get.return_value = fake_resp

    result = client.get_schedules()
    assert len(result) == 2


def test_get_staff_ids_for_location(client):
    with patch.object(client, "get_schedules") as mock_get:
        mock_get.return_value = [
            {"id": "Location.l1-Staff.s1"},
            {"id": "Location.l1-Staff.s2"},
            {"id": "Location.l2-Staff.s3"},  # different location
            {"id": ""},  # malformed
        ]
        result = client.get_staff_ids_for_location("l1")
        assert result == {"s1", "s2"}


def test_get_provider_appointments_returns_resources(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "entry": [
            {"resource": {"id": "appt-1", "status": "booked"}},
        ]
    }
    client._http.get.return_value = fake_resp

    result = client.get_provider_appointments("p1", "2026-05-07")
    assert len(result) == 1


def test_get_patient_appointments_handles_exception(client):
    client._http.get.side_effect = requests.RequestException("boom")
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    result = client.get_patient_appointments("p1", "2026-05-07")
    assert result == []


def test_get_patient_appointments_success(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "entry": [{"resource": {"id": "a1"}}]
    }
    client._http.get.return_value = fake_resp
    result = client.get_patient_appointments("p1", "2026-05-07")
    assert result == [{"id": "a1"}]


def test_get_slots(client):
    client._token = "tk"
    client._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "entry": [
            {"resource": {"id": "slot-1"}},
            {"resource": {"id": "slot-2"}},
        ]
    }
    client._http.get.return_value = fake_resp

    result = client.get_slots("loc1", "staff1", "2026-05-07", 30)
    assert len(result) == 2
