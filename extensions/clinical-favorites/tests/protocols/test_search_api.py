"""Tests for medication, condition, and pharmacy search endpoints."""

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

from requests.exceptions import ConnectionError as RequestsConnectionError

from clinical_favorites.protocols.search_api import (
    ConditionSearchAPI,
    MedicationSearchAPI,
    PharmacySearchAPI,
    _medication_match_rank,
)


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_medication_search_returns_hydrated_results(mock_http: MagicMock) -> None:
    list_response = MagicMock()
    list_response.json.return_value = {
        "results": [{"med_medication_id": 123, "med_medication_description": "Wegovy 0.25"}]
    }
    detail_response = MagicMock()
    detail_response.json.return_value = {
        "clinical_quantities": [
            {
                "representative_ndc": "0001",
                "erx_ncpdp_script_quantity_qualifier_code": "C28254",
                "clinical_quantity_description": "0.5 mL syringe",
                "erx_quantity": "1.0",
            }
        ]
    }
    mock_http.get_json.side_effect = [list_response, detail_response]

    api = MedicationSearchAPI(MagicMock())
    api.request = MagicMock()
    api.request.query_params = {"q": "wegovy"}

    response_list = api.get()

    assert len(response_list) == 1
    body = json.loads(response_list[0].content)
    assert body["success"] is True
    assert body["results"][0]["fdb_code"] == "123"
    assert body["results"][0]["clinical_quantities"][0]["quantity_description"] == "0.5 mL syringe"


def test_medication_match_rank_orders_exact_prefix_token_contains_then_miss() -> None:
    query = "lisinopril"
    exact = _medication_match_rank("lisinopril", query)
    prefix = _medication_match_rank("lisinopril 10 mg tablet", query)
    token = _medication_match_rank("oral lisinopril solution", query)
    contains = _medication_match_rank("prelisinopril blend", query)
    miss = _medication_match_rank("prinivil tablet", query)
    empty = _medication_match_rank("", query)

    assert exact < prefix < token < contains < miss < empty


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_medication_search_ranks_typed_generic_ahead_of_brand(mock_http: MagicMock) -> None:
    # FDB returns the brand row first, the generic the clinician typed second.
    list_response = MagicMock()
    list_response.json.return_value = {
        "results": [
            {"med_medication_id": 1, "med_medication_description": "Prinivil 10 mg tablet"},
            {"med_medication_id": 2, "med_medication_description": "Lisinopril 10 mg tablet"},
        ]
    }
    empty_detail = MagicMock()
    empty_detail.json.return_value = {"clinical_quantities": []}
    mock_http.get_json.side_effect = [list_response, empty_detail, empty_detail]

    body = json.loads(_make_search_api(MedicationSearchAPI, "lisinopril").get()[0].content)

    assert body["success"] is True
    assert [r["display_name"] for r in body["results"]] == [
        "Lisinopril 10 mg tablet",
        "Prinivil 10 mg tablet",
    ]


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_condition_search_returns_icd10_rows(mock_http: MagicMock) -> None:
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {"icd10_code": "E11.9", "icd10_text": "Type 2 diabetes mellitus without complications"},
            {"icd10_code": "", "icd10_text": "garbage row"},
        ]
    }
    mock_http.get_json.return_value = response

    api = ConditionSearchAPI(MagicMock())
    api.request = MagicMock()
    api.request.query_params = {"q": "diab"}

    body = json.loads(api.get()[0].content)

    assert body["success"] is True
    assert len(body["results"]) == 1
    assert body["results"][0]["code"] == "E11.9"


@patch("clinical_favorites.protocols.search_api.pharmacy_http")
def test_pharmacy_search_returns_flattened_address(mock_http: MagicMock) -> None:
    mock_http.search_pharmacies.return_value = [
        {
            "ncpdp_id": "5919177",
            "organization_name": "Amazon Pharmacy",
            "address_line_1": "410 Terry Ave N",
            "address_line_2": "",
            "city": "Seattle",
            "state": "WA",
            "zip_code": "98109",
            "phone_primary": "555-0100",
        }
    ]

    api = PharmacySearchAPI(MagicMock())
    api.request = MagicMock()
    api.request.query_params = {"q": "amazon"}

    body = json.loads(api.get()[0].content)

    assert body["success"] is True
    assert body["results"][0]["ncpdp_id"] == "5919177"
    assert "Seattle" in body["results"][0]["address"]


def _make_search_api(cls: Any, query: str) -> Any:
    api = cls(MagicMock())
    api.request = MagicMock()
    api.request.query_params = {"q": query}
    return api


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_medication_search_returns_503_when_upstream_unreachable(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = RequestsConnectionError("boom")

    response = _make_search_api(MedicationSearchAPI, "wegovy").get()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert body == {
        "results": [],
        "success": False,
        "error": "Medication search temporarily unavailable",
    }


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_medication_search_returns_500_on_unexpected_error(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = RuntimeError("bad day")

    response = _make_search_api(MedicationSearchAPI, "wegovy").get()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert body["error"] == "Medication search failed"


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_condition_search_returns_503_when_upstream_unreachable(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = RequestsConnectionError("boom")

    response = _make_search_api(ConditionSearchAPI, "diab").get()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert body == {
        "results": [],
        "success": False,
        "error": "Condition search temporarily unavailable",
    }


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_condition_search_returns_500_on_unexpected_error(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = RuntimeError("bad day")

    response = _make_search_api(ConditionSearchAPI, "diab").get()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert body["error"] == "Condition search failed"


@patch("clinical_favorites.protocols.search_api.pharmacy_http")
def test_pharmacy_search_returns_503_when_upstream_unreachable(mock_http: MagicMock) -> None:
    mock_http.search_pharmacies.side_effect = RequestsConnectionError("boom")

    response = _make_search_api(PharmacySearchAPI, "cvs").get()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert body == {
        "results": [],
        "success": False,
        "error": "Pharmacy search temporarily unavailable",
    }


@patch("clinical_favorites.protocols.search_api.pharmacy_http")
def test_pharmacy_search_returns_500_on_unexpected_error(mock_http: MagicMock) -> None:
    mock_http.search_pharmacies.side_effect = RuntimeError("bad day")

    response = _make_search_api(PharmacySearchAPI, "cvs").get()[0]
    body = json.loads(response.content)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert body["error"] == "Pharmacy search failed"


def test_medication_search_short_circuits_when_query_under_two_characters() -> None:
    body = json.loads(_make_search_api(MedicationSearchAPI, "a").get()[0].content)
    assert body == {"results": [], "success": True}


def test_condition_search_short_circuits_when_query_under_two_characters() -> None:
    body = json.loads(_make_search_api(ConditionSearchAPI, "a").get()[0].content)
    assert body == {"results": [], "success": True}


def test_pharmacy_search_short_circuits_when_query_under_two_characters() -> None:
    body = json.loads(_make_search_api(PharmacySearchAPI, "a").get()[0].content)
    assert body == {"results": [], "success": True}


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_medication_search_skips_rows_without_med_medication_id(
    mock_http: MagicMock,
) -> None:
    list_response = MagicMock()
    list_response.json.return_value = {
        "results": [
            {"med_medication_description": "missing id"},
            {"med_medication_id": 42, "med_medication_description": "Wegovy 0.25"},
        ]
    }
    detail_response = MagicMock()
    detail_response.json.return_value = {"clinical_quantities": []}
    mock_http.get_json.side_effect = [list_response, detail_response]

    body = json.loads(_make_search_api(MedicationSearchAPI, "wegovy").get()[0].content)

    assert body["success"] is True
    assert len(body["results"]) == 1
    assert body["results"][0]["fdb_code"] == "42"


@patch("clinical_favorites.protocols.search_api.ontologies_http")
def test_medication_search_handles_detail_hydration_failure_gracefully(
    mock_http: MagicMock,
) -> None:
    list_response = MagicMock()
    list_response.json.return_value = {
        "results": [{"med_medication_id": 99, "med_medication_description": "Boom med"}]
    }
    mock_http.get_json.side_effect = [list_response, RuntimeError("detail down")]

    body = json.loads(_make_search_api(MedicationSearchAPI, "boom").get()[0].content)

    assert body["success"] is True
    assert body["results"][0]["fdb_code"] == "99"
    assert body["results"][0]["clinical_quantities"] == []
