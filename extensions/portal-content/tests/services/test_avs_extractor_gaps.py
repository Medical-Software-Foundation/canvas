"""Targeted AVS extractor tests for the lab data-model path and date-parse fallback."""

from unittest.mock import MagicMock, patch

from portal_content.services.avs_data_extractor import AVSDataExtractor


def _extractor():
    with patch("portal_content.services.avs_data_extractor.Note") as note_model:
        note = MagicMock()
        note_model.objects.select_related.return_value.get.return_value = note
        extractor = AVSDataExtractor("note-1")
    return extractor


def test_todo_uses_lab_orders_from_data_model(_stub_lab_order):
    extractor = _extractor()
    extractor.fetch_all_commands_data_in_note_by_type = MagicMock(return_value=[])

    test = MagicMock()
    test.ontology_test_name = "Complete Blood Count"
    order = MagicMock()
    order.tests.all.return_value = [test]
    # Override the autouse stub so the data-model branch yields a test.
    _stub_lab_order.objects.filter.return_value.prefetch_related.return_value = [order]

    todo = extractor._extract_todo_list()
    assert todo["lab_orders"] == ["Complete Blood Count"]


def test_followup_with_unparseable_date_falls_back_to_raw_string():
    extractor = _extractor()

    def fake_fetch(schema_key):
        if schema_key == "followUp":
            return [{"requested_date": {"date": "not-a-real-date"}, "comment": "recheck"}]
        return []

    extractor.fetch_all_commands_data_in_note_by_type = fake_fetch
    todo = extractor._extract_todo_list()
    assert todo["follow_ups"][0]["appointment_date"] == "not-a-real-date"
