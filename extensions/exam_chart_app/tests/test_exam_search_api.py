"""Unit tests for ExamSearchAPI."""
from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from exam_chart_app.api.exam_search_api import ExamSearchAPI


def _make_api(query: str = "", limit: str = "") -> ExamSearchAPI:
    api = ExamSearchAPI.__new__(ExamSearchAPI)
    api.request = MagicMock()
    api.request.query_params = {"q": query, "limit": limit} if limit else {"q": query}
    return api


@patch("exam_chart_app.api.exam_search_api.ReasonForVisitSettingCoding")
def test_rfv_codings_returns_results_for_matching_display(mock_model):
    row = MagicMock(code="A01", system="http://snomed.info/sct", display="Annual visit")
    qs = MagicMock()
    qs.__getitem__.return_value = [row]
    mock_model.objects.filter.return_value.distinct.return_value.order_by.return_value = qs

    api = _make_api(query="annual")
    responses = api.search_rfv_codings()
    body = json.loads(responses[0].content.decode())

    assert responses[0].status_code == HTTPStatus.OK
    assert body == {"results": [{"code": "A01", "system": "http://snomed.info/sct", "display": "Annual visit"}]}
    mock_model.objects.filter.assert_called_once()


@patch("exam_chart_app.api.exam_search_api.ReasonForVisitSettingCoding")
def test_rfv_codings_returns_empty_results_for_empty_query(mock_model):
    api = _make_api(query="")
    responses = api.search_rfv_codings()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": []}
    mock_model.objects.filter.assert_not_called()


@patch("exam_chart_app.api.exam_search_api.ReasonForVisitSettingCoding")
def test_rfv_codings_caps_limit_at_50(mock_model):
    qs = MagicMock()
    qs.__getitem__.return_value = []
    mock_model.objects.filter.return_value.distinct.return_value.order_by.return_value = qs

    api = _make_api(query="visit", limit="200")
    api.search_rfv_codings()
    qs.__getitem__.assert_called_once_with(slice(None, 50, None))


def _make_api_params(params: dict) -> ExamSearchAPI:
    api = ExamSearchAPI.__new__(ExamSearchAPI)
    api.request = MagicMock()
    api.request.query_params = params
    return api


@patch("exam_chart_app.api.exam_search_api.LabPartner")
def test_lab_partners_returns_active(mock_lp):
    row = MagicMock()
    row.id = "partner-1"
    row.name = "Quest Diagnostics"
    qs = MagicMock()
    qs.__getitem__.return_value = [row]
    mock_lp.objects.filter.return_value.order_by.return_value = qs
    responses = _make_api_params({"q": "quest"}).search_lab_partners()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": [{"id": "partner-1", "name": "Quest Diagnostics"}]}


@patch("exam_chart_app.api.exam_search_api.LabPartnerTest")
def test_lab_tests_filters_by_partner(mock_lpt):
    t = MagicMock(order_code="BMP", order_name="Basic Metabolic Panel")
    qs = MagicMock()
    qs.__getitem__.return_value = [t]
    mock_lpt.objects.filter.return_value.order_by.return_value = qs
    responses = _make_api_params({"partner_id": "partner-1", "q": "metabolic"}).search_lab_tests()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": [{"order_code": "BMP", "order_name": "Basic Metabolic Panel"}]}
    filter_kwargs = mock_lpt.objects.filter.call_args.kwargs
    assert filter_kwargs["lab_partner__id"] == "partner-1"


def test_lab_tests_no_partner_returns_empty():
    responses = _make_api_params({}).search_lab_tests()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": []}


@patch("exam_chart_app.api.exam_search_api.ontologies_http")
def test_medications_returns_empty_for_short_query(mock_http):
    responses = _make_api_params({"q": "x"}).search_medications()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": []}
    mock_http.get_json.assert_not_called()


@patch("exam_chart_app.api.exam_search_api.ontologies_http")
def test_medications_proxies_ontologies_fdb(mock_http):
    mock_http.get_json.return_value.json.return_value = {
        "results": [
            {
                "med_medication_id": "153666",
                "med_medication_description": "Lisinopril 10 mg oral tablet",
                "description_and_quantity": "Lisinopril 10 mg oral tablet (30 tablets)",
                "rxnorm_rxcui": "314076",
                "clinical_quantities": [
                    {
                        "representative_ndc": "00071-0941-23",
                        "erx_ncpdp_script_quantity_qualifier_code": "C48542",
                        "clinical_quantity_description": "Tablet",
                        "erx_quantity": "30",
                    }
                ],
            }
        ]
    }
    responses = _make_api_params({"q": "lisinopril"}).search_medications()
    body = json.loads(responses[0].content.decode())
    assert mock_http.get_json.call_count == 1
    url_arg = mock_http.get_json.call_args.args[0]
    assert url_arg.startswith("/fdb/grouped-medication/?search=")
    assert body["results"][0]["fdb_code"] == "153666"
    assert body["results"][0]["display"] == "Lisinopril 10 mg oral tablet"
    assert body["results"][0]["description_and_quantity"].startswith("Lisinopril")
    assert body["results"][0]["clinical_quantities"][0] == {
        "representative_ndc": "00071-0941-23",
        "ncpdp_quantity_qualifier_code": "C48542",
        "quantity_description": "Tablet",
        "erx_quantity": "30",
    }


@patch("exam_chart_app.api.exam_search_api.ontologies_http")
def test_medications_returns_empty_on_ontologies_network_error(mock_http):
    """Network failures degrade to empty results so the UI stays usable."""
    from requests.exceptions import RequestException  # type: ignore[import-untyped]
    mock_http.get_json.side_effect = RequestException("ontologies down")
    responses = _make_api_params({"q": "lisinopril"}).search_medications()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": []}


@patch("exam_chart_app.api.exam_search_api.ontologies_http")
def test_medications_returns_empty_on_ontologies_decode_error(mock_http):
    """JSON decode failures (malformed response) degrade to empty results.

    ValueError is the parent of JSONDecodeError; the narrow catch lists
    both explicitly for documentation."""
    from json import JSONDecodeError
    mock_http.get_json.return_value.json.side_effect = JSONDecodeError(
        "bad payload", "{", 0,
    )
    responses = _make_api_params({"q": "lisinopril"}).search_medications()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": []}


@patch("exam_chart_app.api.exam_search_api.ontologies_http")
def test_medications_propagates_programming_bug(mock_http):
    """Locks the narrowed-catch invariant: AttributeError / TypeError from
    a renamed SDK method or wrong-shape response must NOT be swallowed.
    Those need to reach Sentry, not silently degrade to empty results."""
    import pytest
    mock_http.get_json.side_effect = AttributeError("ontologies_http renamed")
    with pytest.raises(AttributeError):
        _make_api_params({"q": "lisinopril"}).search_medications()


@patch("exam_chart_app.api.exam_search_api.ServiceProvider")
def test_service_providers_filters_by_name(mock_sp):
    r = MagicMock()
    r.id = "sp-1"
    r.first_name = "Jane"
    r.last_name = "Doe"
    r.specialty = "Gastroenterology"
    r.practice_name = "Apex GI"
    qs = MagicMock()
    qs.__getitem__.return_value = [r]
    # Endpoint now starts from .all() then .filter() / .order_by(), so
    # walk the chain through .all() too.
    mock_sp.objects.all.return_value.filter.return_value.order_by.return_value = qs
    responses = _make_api_params({"q": "doe"}).search_service_providers()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": [{
        "id": "sp-1",
        "first_name": "Jane",
        "last_name": "Doe",
        "specialty": "Gastroenterology",
        "practice_name": "Apex GI",
    }]}
    mock_sp.objects.all.return_value.filter.assert_called_once()


@patch("exam_chart_app.api.exam_search_api.ServiceProvider")
def test_service_providers_returns_all_when_q_empty(mock_sp):
    """Empty query → no .filter() call; preload pattern returns all rows."""
    qs = MagicMock()
    qs.__getitem__.return_value = []
    mock_sp.objects.all.return_value.order_by.return_value = qs
    responses = _make_api_params({}).search_service_providers()
    body = json.loads(responses[0].content.decode())
    assert body == {"results": []}
    mock_sp.objects.all.return_value.filter.assert_not_called()


@patch("exam_chart_app.api.exam_search_api.Staff")
def test_staff_search_filters_active_and_provider_role(mock_staff):
    s = MagicMock()
    s.id = "staff-1"
    s.first_name = "Jane"
    s.last_name = "Doe"
    s.npi_number = "1234567890"
    qs = MagicMock()
    qs.__getitem__.return_value = [s]
    # Chain: .filter(active, roles__role_type).distinct().filter(name).order_by()[:limit]
    mock_staff.objects.filter.return_value.distinct.return_value.filter.return_value.order_by.return_value = qs
    responses = _make_api_params({"q": "jane"}).search_staff()
    body = json.loads(responses[0].content.decode())
    assert body["results"][0]["first_name"] == "Jane"
    assert body["results"][0]["last_name"] == "Doe"
    first_filter_kwargs = mock_staff.objects.filter.call_args_list[0].kwargs
    assert first_filter_kwargs["active"] is True
    assert first_filter_kwargs["roles__role_type"] == "PROVIDER"
