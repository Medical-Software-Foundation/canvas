from __future__ import annotations

import json

from chart_command_search.context.serialization import serialize_results


class TestSerializeResults:
    def test_empty_results(self) -> None:
        assert serialize_results([]) == "[]"

    def test_single_result_full(self) -> None:
        result = {
            "category": "command",
            "type_label": "Prescribe",
            "date": "2024-01-15",
            "summary": "Lisinopril 10mg",
            "state": "Committed",
            "source": "Office Visit",
            "details": [{"label": "Sig", "value": "take daily"}],
            "state_class": "committed",
            "permalink": "/patient/1#noteId=2",
        }
        output = json.loads(serialize_results([result]))
        assert len(output) == 1
        entry = output[0]
        assert entry["i"] == 0
        assert entry["cat"] == "command"
        assert entry["type"] == "Prescribe"
        assert entry["date"] == "2024-01-15"
        assert entry["summary"] == "Lisinopril 10mg"
        assert entry["state"] == "Committed"
        assert entry["source"] == "Office Visit"
        assert entry["details"] == {"Sig": "take daily"}

    def test_result_without_optional_fields(self) -> None:
        result = {
            "category": "note",
            "type_label": "Note",
            "date": "",
            "summary": "",
            "state": "",
            "source": "",
            "details": [],
            "state_class": "",
            "permalink": "",
        }
        output = json.loads(serialize_results([result]))
        entry = output[0]
        assert "summary" not in entry
        assert "state" not in entry
        assert "source" not in entry
        assert "details" not in entry

    def test_multiple_results_indexed(self) -> None:
        results = [
            {"category": "command", "type_label": "Prescribe", "date": "2024-01-15",
             "summary": "Med A", "state": "", "source": "", "details": [],
             "state_class": "", "permalink": ""},
            {"category": "lab", "type_label": "Lab Report", "date": "2024-01-16",
             "summary": "CBC", "state": "", "source": "", "details": [],
             "state_class": "", "permalink": ""},
        ]
        output = json.loads(serialize_results(results))
        assert output[0]["i"] == 0
        assert output[1]["i"] == 1
        assert output[0]["cat"] == "command"
        assert output[1]["cat"] == "lab"

    def test_details_empty_values_excluded(self) -> None:
        result = {
            "category": "command",
            "type_label": "Prescribe",
            "date": "",
            "summary": "Med",
            "state": "",
            "source": "",
            "details": [
                {"label": "Sig", "value": "take daily"},
                {"label": "Empty", "value": ""},
            ],
            "state_class": "",
            "permalink": "",
        }
        output = json.loads(serialize_results([result]))
        assert output[0]["details"] == {"Sig": "take daily"}

    def test_compact_json_no_spaces(self) -> None:
        result = {
            "category": "note",
            "type_label": "Note",
            "date": "2024-01-15",
            "summary": "Test",
            "state": "",
            "source": "",
            "details": [],
            "state_class": "",
            "permalink": "",
        }
        raw = serialize_results([result])
        assert ": " not in raw
        assert ", " not in raw
