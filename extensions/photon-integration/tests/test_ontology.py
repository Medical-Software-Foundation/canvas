"""Tests for the NDC -> RxNorm ontology lookup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from photon_integration import ontology

MODULE = "photon_integration.ontology"


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    return r


def test_ndc_returns_rxcui_on_success():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.return_value = _resp(body={"rxnorm_rxcui": "198052"})
        assert ontology.ndc_to_rxcui("00781180501") == "198052"
    http.get_json.assert_called_once_with("/fdb/ndc-to-medication/00781180501/")


def test_fdb_returns_rxcui_on_success():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.return_value = _resp(body={"rxnorm_rxcui": "216092"})
        assert ontology.fdb_to_rxcui("216092") == "216092"
    http.get_json.assert_called_once_with("/fdb/grouped-medication/216092/")


def test_fdb_results_wrapper_shape():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.return_value = _resp(body={"results": [{"rxnorm_rxcui": "313782"}]})
        assert ontology.fdb_to_rxcui("436095") == "313782"


def test_fdb_list_shape():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.return_value = _resp(body=[{"rxnorm_rxcui": "999"}])
        assert ontology.fdb_to_rxcui("1") == "999"


def test_fdb_none_for_empty():
    with patch(f"{MODULE}.ontologies_http") as http:
        assert ontology.fdb_to_rxcui(None) is None
    http.get_json.assert_not_called()


def test_none_for_empty_ndc():
    with patch(f"{MODULE}.ontologies_http") as http:
        assert ontology.ndc_to_rxcui(None) is None
        assert ontology.ndc_to_rxcui("") is None
    http.get_json.assert_not_called()


def test_none_on_non_200():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.return_value = _resp(status=404)
        assert ontology.ndc_to_rxcui("x") is None


def test_none_when_no_rxcui_in_body():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.return_value = _resp(body={"med_medication_id": 1})
        assert ontology.ndc_to_rxcui("x") is None


def test_none_on_exception():
    with patch(f"{MODULE}.ontologies_http") as http:
        http.get_json.side_effect = RuntimeError("boom")
        assert ontology.ndc_to_rxcui("x") is None
