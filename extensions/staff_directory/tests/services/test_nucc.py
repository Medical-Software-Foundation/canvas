from unittest.mock import MagicMock, call, patch

from staff_directory.services.nucc import (
    _compose_display,
    get_nucc_by_code,
    search_nucc,
    seed_nucc_codes,
    serialize_nucc,
)


class TestComposeDisplay:
    def test_classification_and_specialization(self):
        assert _compose_display("Internal Medicine", "Cardiovascular Disease") == (
            "Internal Medicine — Cardiovascular Disease"
        )

    def test_classification_only(self):
        assert _compose_display("Family Medicine", "") == "Family Medicine"

    def test_specialization_only(self):
        assert _compose_display("", "Pediatric Cardiology") == "Pediatric Cardiology"

    def test_both_empty(self):
        assert _compose_display("", "") == ""

    def test_strips_whitespace(self):
        assert _compose_display("  Family  ", "  ") == "Family"


class TestSerializeNucc:
    def test_serializes_all_fields(self, mock_nucc_code):
        result = serialize_nucc(mock_nucc_code)
        assert result == {
            "code": "207R00000X",
            "grouping": "Allopathic & Osteopathic Physicians",
            "classification": "Internal Medicine",
            "specialization": "",
            "display_name": "Internal Medicine",
            "definition": "An internist...",
        }


class TestSearchNucc:
    def test_empty_query_returns_empty_list(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            result = search_nucc("")
            assert result == []
            assert mock_model.mock_calls == []

    def test_whitespace_query_returns_empty_list(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            result = search_nucc("   ")
            assert result == []
            assert mock_model.mock_calls == []

    def test_query_hits_queryset(self):
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.order_by.return_value = qs
        qs.__getitem__.return_value = ["row1", "row2"]

        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects = qs
            result = search_nucc("cardio", limit=10)

        assert result == ["row1", "row2"]
        assert qs.filter.called is True
        assert qs.order_by.called is True

    def test_limit_clamped_to_range(self):
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.order_by.return_value = qs
        captured = {}

        def _slice(key):
            captured["slice"] = key
            return []

        qs.__getitem__.side_effect = _slice
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects = qs
            search_nucc("x", limit=999)

        assert captured["slice"] == slice(None, 100, None)


class TestGetNuccByCode:
    def test_empty_code_returns_none(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            assert get_nucc_by_code("") is None
            assert mock_model.mock_calls == []

    def test_looks_up_by_code(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects.filter.return_value.first.return_value = "found"
            assert get_nucc_by_code("  207R00000X  ") == "found"
            calls = [
                call.objects.filter(code="207R00000X"),
                call.objects.filter().first(),
            ]
            assert mock_model.mock_calls == calls


class TestSeedNuccCodes:
    def test_empty_rows(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode"):
            assert seed_nucc_codes([]) == (0, 0)

    def test_creates_new_rows(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects.values_list.return_value = []

            rows = [
                {
                    "code": "207RC0000X",
                    "grouping": "Physicians",
                    "classification": "Internal Medicine",
                    "specialization": "Cardiology",
                    "definition": "defn",
                },
            ]
            created, skipped = seed_nucc_codes(rows)
            assert created == 1
            assert skipped == 0
            assert mock_model.objects.bulk_create.called is True

    def test_skips_existing_and_empty_codes(self):
        with patch("staff_directory.services.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects.values_list.return_value = ["DUP"]

            rows = [
                {"code": "DUP"},
                {"code": ""},
                {"code": None},
                {"code": "NEW", "classification": "New", "specialization": ""},
            ]
            created, skipped = seed_nucc_codes(rows)
            assert created == 1
            assert skipped == 3
