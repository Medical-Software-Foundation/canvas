"""Tests for the document component -> FHIR category mapping."""

from unittest.mock import patch

from portal_content.content_types import documents


@patch("portal_content.content_types.documents.search_documents", return_value=[{"report_id": "d1"}])
def test_list_documents_delegates_with_mapped_category(search):
    out = documents.list_documents("inst", "cid", "sec", "patient-1", "labs")
    assert out == [{"report_id": "d1"}]
    search.assert_called_once_with("inst", "cid", "sec", "patient-1", "labreport")


def test_category_codes_cover_all_document_components():
    assert set(documents.CATEGORY_CODES) == {"labs", "imaging", "letters"}
    assert documents.CATEGORY_CODES["labs"] == "labreport"
    assert documents.CATEGORY_CODES["imaging"] == "imagingreport"
    assert documents.CATEGORY_CODES["letters"] == "correspondence"
