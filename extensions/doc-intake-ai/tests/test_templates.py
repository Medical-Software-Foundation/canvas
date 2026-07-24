"""Tests for template matching and prefill building."""

import pytest
from unittest.mock import MagicMock, patch, call

from doc_intake_ai.models import DocumentExtraction
from doc_intake_ai.templates import (
    _is_valid_code,
    _to_list,
    _extract_codes,
    _extract_keywords,
    _keyword_bonus,
    _field_key,
    _normalize_value,
    _get_template_models,
    _build_code_template_map,
    _keyword_fallback,
    _build_field_schema,
    _build_prefill_fields,
    _build_prefill_effect,
    _score_candidates,
    score_and_match_templates,
    get_template_extraction_context,
    build_prefill_fields_for_candidate,
    build_prefill_effect,
)


class TestIsValidCode:
    """Test code validation."""

    @pytest.mark.parametrize("code,expected", [
        ("11580-8", True),
        ("SNOMED-123", True),
        ("abc123", True),
        ("", False),
        (None, False),
        ("N/A", False),
        ("NA", False),
        ("NONE", False),
        ("  ", False),
        ("n/a", False),
        ("na", False),
        ("none", False),
        ("  N/A  ", False),
    ])
    def test_validation(self, code: str | None, expected: bool) -> None:
        assert bool(_is_valid_code(code)) == expected  # type: ignore[arg-type]


class TestToList:
    """Test value to list conversion."""

    @pytest.mark.parametrize("value,expected", [
        (None, []),
        ("single", ["single"]),
        ("a, b, c", ["a", "b", "c"]),
        ("a; b; c", ["a", "b", "c"]),
        ("a\nb\nc", ["a", "b", "c"]),
        (["a", "b"], ["a", "b"]),
        (["a, b", "c"], ["a", "b", "c"]),
        ("  spaced  ", ["spaced"]),
        ("", []),
        (123, ["123"]),
    ])
    def test_conversion(self, value: object, expected: list[str]) -> None:
        assert _to_list(value) == expected


class TestExtractCodes:
    """Test code extraction by template type."""

    def test_lab_extracts_loinc_codes(self) -> None:
        extraction = DocumentExtraction(loinc_codes="11580-8, 3016-3")
        codes = _extract_codes("LabReportTemplate", extraction)
        assert codes == {"11580-8", "3016-3"}

    def test_imaging_extracts_snomed_codes(self) -> None:
        extraction = DocumentExtraction(snomed_codes="12345, 67890")
        codes = _extract_codes("ImagingReportTemplate", extraction)
        assert codes == {"12345", "67890"}

    def test_filters_invalid_codes(self) -> None:
        extraction = DocumentExtraction(loinc_codes="11580-8, N/A, , NONE")
        codes = _extract_codes("LabReportTemplate", extraction)
        assert codes == {"11580-8"}

    def test_handles_list_codes(self) -> None:
        extraction = DocumentExtraction(loinc_codes=["11580-8", "3016-3"])
        codes = _extract_codes("LabReportTemplate", extraction)
        assert codes == {"11580-8", "3016-3"}

    def test_handles_none(self) -> None:
        extraction = DocumentExtraction()
        codes = _extract_codes("LabReportTemplate", extraction)
        assert codes == set()


class TestExtractKeywords:
    """Test keyword extraction."""

    def test_extracts_all_fields(self) -> None:
        extraction = DocumentExtraction(
            test_names="CBC",
            study_names="MRI",
            modality="CT",
            body_part="Head",
        )
        keywords = _extract_keywords(extraction)
        assert set(keywords) == {"CBC", "MRI", "CT", "Head"}

    def test_handles_partial_fields(self) -> None:
        extraction = DocumentExtraction(test_names="CBC", modality="CT")
        keywords = _extract_keywords(extraction)
        assert set(keywords) == {"CBC", "CT"}

    def test_handles_none_values(self) -> None:
        extraction = DocumentExtraction()
        keywords = _extract_keywords(extraction)
        assert keywords == []

    def test_handles_list_values(self) -> None:
        extraction = DocumentExtraction(test_names=["CBC", "BMP"])
        keywords = _extract_keywords(extraction)
        assert set(keywords) == {"CBC", "BMP"}

    def test_strips_whitespace(self) -> None:
        extraction = DocumentExtraction(test_names="  CBC  , BMP  ")
        keywords = _extract_keywords(extraction)
        assert keywords == ["CBC", "BMP"]


class TestKeywordBonus:
    """Test keyword bonus calculation."""

    def test_no_keywords(self) -> None:
        class MockTemplate:
            name = "Lab Report"
            search_keywords = ""

        assert _keyword_bonus(MockTemplate(), []) == 0.0

    def test_single_match(self) -> None:
        class MockTemplate:
            name = "CBC Lab Report"
            search_keywords = ""

        bonus = _keyword_bonus(MockTemplate(), ["CBC"])
        assert bonus > 0

    def test_multiple_matches(self) -> None:
        class MockTemplate:
            name = "CBC Lab Report"
            search_keywords = "blood count"

        single = _keyword_bonus(MockTemplate(), ["CBC"])
        double = _keyword_bonus(MockTemplate(), ["CBC", "blood"])
        assert double > single

    def test_case_insensitive(self) -> None:
        class MockTemplate:
            name = "CBC Lab Report"
            search_keywords = ""

        upper = _keyword_bonus(MockTemplate(), ["CBC"])
        lower = _keyword_bonus(MockTemplate(), ["cbc"])
        assert upper == lower

    def test_matches_in_search_keywords(self) -> None:
        class MockTemplate:
            name = "Lab Report"
            search_keywords = "complete blood count"

        bonus = _keyword_bonus(MockTemplate(), ["blood"])
        assert bonus > 0


class TestFieldKey:
    """Test field key generation."""

    def test_valid_code(self) -> None:
        class MockField:
            code = "11580-8"
            label = "Test Name"

        assert _field_key(MockField()) == "11580-8"

    def test_code_with_whitespace(self) -> None:
        class MockField:
            code = "  11580-8  "
            label = "Test Name"

        assert _field_key(MockField()) == "11580-8"

    def test_invalid_code_falls_back_to_label(self) -> None:
        class MockField:
            code = "N/A"
            label = "Test Name"

        assert _field_key(MockField()) == "Test Name"

    def test_empty_code_falls_back_to_label(self) -> None:
        class MockField:
            code = ""
            label = "Test Name"

        assert _field_key(MockField()) == "Test Name"

    def test_none_code_falls_back_to_label(self) -> None:
        class MockField:
            code = None
            label = "Test Name"

        assert _field_key(MockField()) == "Test Name"

    def test_both_none_returns_none(self) -> None:
        class MockField:
            code = None
            label = None

        assert _field_key(MockField()) is None

    def test_both_empty_returns_none(self) -> None:
        class MockField:
            code = ""
            label = "  "

        assert _field_key(MockField()) is None

    def test_missing_attributes(self) -> None:
        class MockField:
            pass

        assert _field_key(MockField()) is None

    def test_label_with_whitespace(self) -> None:
        class MockField:
            code = None
            label = "  Test Name  "

        assert _field_key(MockField()) == "Test Name"


class TestNormalizeValue:
    """Test value normalization."""

    @pytest.mark.parametrize("value,expected", [
        (None, None),
        ("text", "text"),
        ("  spaced  ", "spaced"),
        ("", None),
        ([], None),
        (["a", "b"], "a, b"),
        (["single"], "single"),
        ({"value": "nested"}, "nested"),
        ({"value": "  spaced  "}, "spaced"),
        ({"value": None}, None),
        ({"other": "key"}, "{'other': 'key'}"),
        (123, "123"),
        ([None, "a", "", "b"], "a, b"),
        ({"value": ["a", "b"]}, "a, b"),
    ])
    def test_normalization(self, value: object, expected: str | None) -> None:
        assert _normalize_value(value) == expected


class TestGetTemplateModels:
    """Test template model lookup."""

    def test_lab_report(self) -> None:
        template_model, field_model = _get_template_models("LabReportTemplate")
        assert template_model is not None
        assert field_model is not None

    def test_imaging_report(self) -> None:
        template_model, field_model = _get_template_models("ImagingReportTemplate")
        assert template_model is not None

    def test_specialty_report(self) -> None:
        template_model, field_model = _get_template_models("SpecialtyReportTemplate")
        assert template_model is not None

    def test_unknown_type(self) -> None:
        template_model, field_model = _get_template_models("UnknownTemplate")
        assert template_model is None
        assert field_model is None


class TestBuildCodeTemplateMap:
    """Test code-to-template mapping builder."""

    def test_builds_mapping(self) -> None:
        f1 = MagicMock(code="11580-8", report_template_id=1)
        f2 = MagicMock(code="3016-3", report_template_id=1)
        f3 = MagicMock(code="11580-8", report_template_id=2)
        result = _build_code_template_map([f1, f2, f3])
        assert result == {"11580-8": {1, 2}, "3016-3": {1}}

    def test_skips_invalid_codes(self) -> None:
        f1 = MagicMock(code="11580-8", report_template_id=1)
        f2 = MagicMock(code="N/A", report_template_id=2)
        f3 = MagicMock(code="", report_template_id=3)
        f4 = MagicMock(code=None, report_template_id=4)
        result = _build_code_template_map([f1, f2, f3, f4])
        assert result == {"11580-8": {1}}

    def test_empty_list(self) -> None:
        assert _build_code_template_map([]) == {}


class TestKeywordFallback:
    """Test keyword fallback search."""

    def test_empty_keywords_returns_empty(self) -> None:
        mock_model = MagicMock()
        assert _keyword_fallback(mock_model, []) == []

    def test_returns_results(self) -> None:
        mock_model = MagicMock()
        mock_model.objects.active.return_value.search.return_value.values_list.return_value.__getitem__ = (
            lambda self, key: [(1, "CBC Panel"), (2, "Blood Count")]
        )
        result = _keyword_fallback(mock_model, ["CBC"])
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["score"] == 0.1
        assert result[0]["codes"] == []


class TestBuildFieldSchema:
    """Test extraction schema building from template fields."""

    def test_builds_schema_with_code_and_units(self) -> None:
        f1 = MagicMock(code="11580-8", label="TSH", units="mIU/L", sequence=1)
        schema, key_map = _build_field_schema([f1], {"11580-8"})

        assert "11580-8" in schema["schema"]["properties"]
        prop = schema["schema"]["properties"]["11580-8"]
        assert "code=11580-8" in prop["description"]
        assert "units=mIU/L" in prop["description"]
        assert key_map["11580-8"] == f1

    def test_preferred_codes_sorted_first(self) -> None:
        f1 = MagicMock(code="AAA", label="First", units=None, sequence=1)
        f2 = MagicMock(code="BBB", label="Second", units=None, sequence=2)
        schema, key_map = _build_field_schema([f1, f2], {"BBB"})

        keys = list(schema["schema"]["properties"].keys())
        assert keys[0] == "BBB"

    def test_skips_duplicate_keys(self) -> None:
        f1 = MagicMock(code="11580-8", label="TSH", units=None, sequence=1)
        f2 = MagicMock(code="11580-8", label="TSH Dup", units=None, sequence=2)
        schema, key_map = _build_field_schema([f1, f2], set())

        assert len(schema["schema"]["properties"]) == 1

    def test_field_without_code_uses_label(self) -> None:
        f1 = MagicMock(code="N/A", label="Free Text", units=None, sequence=1)
        schema, key_map = _build_field_schema([f1], set())

        assert "Free Text" in schema["schema"]["properties"]

    def test_schema_structure(self) -> None:
        f1 = MagicMock(code="11580-8", label="TSH", units=None, sequence=1)
        schema, _ = _build_field_schema([f1], set())

        assert schema["type"] == "EXTRACT"
        assert schema["baseProcessor"] == "extraction_performance"
        assert schema["advancedOptions"]["citationsEnabled"] is True


class TestBuildPrefillFields:
    """Test prefill field building from extraction data."""

    def test_basic_extraction(self) -> None:
        extraction_data = {"11580-8": "4.5"}
        field_mock = MagicMock()
        field_mock.units = "mIU/L"
        key_map = {"11580-8": field_mock}

        result = _build_prefill_fields(extraction_data, None, key_map, 0.9)

        assert "11580-8" in result
        assert result["11580-8"]["value"] == "4.5"
        assert result["11580-8"]["unit"] == "mIU/L"

    def test_with_metadata_confidence(self) -> None:
        extraction_data = {"11580-8": "4.5"}
        metadata = {"11580-8": {"ocrConfidence": 0.85}}
        key_map = {"11580-8": MagicMock(units=None)}

        result = _build_prefill_fields(extraction_data, metadata, key_map, 0.9)

        assert result["11580-8"]["annotations"][0]["text"] == "AI 85%"

    def test_fallback_confidence(self) -> None:
        extraction_data = {"11580-8": "4.5"}
        key_map = {"11580-8": MagicMock(units=None)}

        result = _build_prefill_fields(extraction_data, None, key_map, 0.75)

        assert result["11580-8"]["annotations"][0]["text"] == "AI 75%"

    def test_skips_none_values(self) -> None:
        extraction_data = {"11580-8": None, "3016-3": "1.2"}
        key_map = {"11580-8": MagicMock(units=None), "3016-3": MagicMock(units=None)}

        result = _build_prefill_fields(extraction_data, None, key_map, None)

        assert "11580-8" not in result
        assert "3016-3" in result

    def test_none_extraction_returns_empty(self) -> None:
        result = _build_prefill_fields(None, None, {}, None)
        assert result == {}

    def test_no_confidence_no_annotations(self) -> None:
        extraction_data = {"11580-8": "4.5"}
        key_map = {"11580-8": MagicMock(units=None)}

        result = _build_prefill_fields(extraction_data, None, key_map, None)

        assert "annotations" not in result["11580-8"]

    def test_field_not_in_key_map_still_included(self) -> None:
        extraction_data = {"unknown_key": "value"}
        key_map: dict[str, str] = {}

        result = _build_prefill_fields(extraction_data, None, key_map, None)

        assert "unknown_key" in result
        assert result["unknown_key"]["value"] == "value"


class TestBuildPrefillEffect:
    """Test prefill effect construction."""

    @patch("doc_intake_ai.templates.PrefillDocumentFields")
    def test_success(self, mock_prefill: MagicMock) -> None:
        mock_effect = MagicMock()
        mock_prefill.return_value.apply.return_value = mock_effect

        templates = [{"template_id": 1, "template_name": "CBC", "fields": {"a": {"value": "1"}}}]
        result = _build_prefill_effect("doc-123", templates, 0.9)

        assert result == mock_effect
        mock_prefill.assert_called_once()

    @patch("doc_intake_ai.templates.PrefillDocumentFields")
    def test_validation_error_returns_none(self, mock_prefill: MagicMock) -> None:
        from pydantic import ValidationError

        mock_prefill.side_effect = ValidationError.from_exception_data(
            "PrefillDocumentFields", []
        )
        result = _build_prefill_effect("doc-123", [], None)
        assert result is None


class TestScoreCandidates:
    """Test template scoring logic."""

    def test_scores_by_code_overlap(self) -> None:
        template1 = MagicMock(id=1, name="CBC Panel", search_keywords="")
        f1 = MagicMock(code="11580-8", report_template_id=1, report_template=template1)
        f2 = MagicMock(code="3016-3", report_template_id=1, report_template=template1)

        field_model = MagicMock()
        field_model.objects.filter.return_value.select_related.return_value = [f1, f2]

        results = _score_candidates(
            field_model, MagicMock(), {"11580-8", "3016-3"}, [], "LabReportTemplate",
        )

        assert len(results) == 1
        assert results[0]["id"] == 1
        assert results[0]["score"] == 1.0

    def test_no_fields_triggers_keyword_fallback(self) -> None:
        field_model = MagicMock()
        field_model.objects.filter.return_value.select_related.return_value = []

        template_model = MagicMock()
        template_model.objects.active.return_value.search.return_value.values_list.return_value.__getitem__ = (
            lambda self, key: [(1, "CBC Panel")]
        )

        results = _score_candidates(
            field_model, template_model, {"11580-8"}, ["CBC"], "LabReportTemplate",
        )
        assert len(results) == 1

    def test_imaging_filters_by_snomed(self) -> None:
        field_model = MagicMock()
        filter_mock = MagicMock()
        field_model.objects.filter.return_value = filter_mock
        filter_mock.filter.return_value.select_related.return_value = []

        template_model = MagicMock()
        template_model.objects.active.return_value.search.return_value.values_list.return_value.__getitem__ = (
            lambda self, key: []
        )

        _score_candidates(
            field_model, template_model, {"12345"}, [], "ImagingReportTemplate",
        )

        filter_mock.filter.assert_called_once_with(code_system__icontains="snomed")

    def test_multiple_templates_ranked_by_score(self) -> None:
        t1 = MagicMock(id=1, name="Template A", search_keywords="")
        t2 = MagicMock(id=2, name="Template B", search_keywords="")

        f1 = MagicMock(code="AAA", report_template_id=1, report_template=t1)
        f2 = MagicMock(code="BBB", report_template_id=2, report_template=t2)
        f3 = MagicMock(code="CCC", report_template_id=2, report_template=t2)

        field_model = MagicMock()
        field_model.objects.filter.return_value.select_related.return_value = [f1, f2, f3]

        results = _score_candidates(
            field_model, MagicMock(), {"AAA", "BBB", "CCC"}, [], "LabReportTemplate",
        )

        assert len(results) == 2
        assert results[0]["id"] == 2
        assert results[0]["score"] > results[1]["score"]


class TestScoreAndMatchTemplates:
    """Test score_and_match_templates orchestrator."""

    @patch("doc_intake_ai.templates._score_candidates")
    def test_returns_candidates(self, mock_score: MagicMock) -> None:
        mock_score.return_value = [{"id": 1, "name": "CBC", "score": 0.8, "codes": ["11580-8"]}]
        extraction = DocumentExtraction(loinc_codes="11580-8")

        result = score_and_match_templates("LabReportTemplate", extraction, "https://s3/doc.pdf")

        assert result is not None
        candidates, field_model, codes = result
        assert len(candidates) == 1
        assert "11580-8" in codes

    def test_unknown_template_type_returns_none(self) -> None:
        extraction = DocumentExtraction(loinc_codes="11580-8")
        result = score_and_match_templates("UnknownTemplate", extraction, "url")
        assert result is None

    @patch("doc_intake_ai.templates._score_candidates")
    def test_no_codes_returns_none(self, mock_score: MagicMock) -> None:
        extraction = DocumentExtraction()
        result = score_and_match_templates("LabReportTemplate", extraction, "url")
        assert result is None
        mock_score.assert_not_called()

    @patch("doc_intake_ai.templates._score_candidates")
    def test_no_candidates_returns_none(self, mock_score: MagicMock) -> None:
        mock_score.return_value = []
        extraction = DocumentExtraction(loinc_codes="11580-8")
        result = score_and_match_templates("LabReportTemplate", extraction, "url")
        assert result is None


class TestGetTemplateExtractionContext:
    """Test get_template_extraction_context."""

    def test_returns_schema_and_key_map(self) -> None:
        field_model = MagicMock()
        f1 = MagicMock(code="11580-8", label="TSH", units="mIU/L", sequence=1)
        field_model.objects.filter.return_value.order_by.return_value = [f1]

        candidate = {"id": 1, "name": "CBC", "score": 0.8, "codes": ["11580-8"]}
        result = get_template_extraction_context(
            candidate, {"11580-8"}, set(), field_model, False,
        )

        assert result is not None
        schema, key_map = result
        assert "11580-8" in schema["schema"]["properties"]

    def test_below_threshold_returns_none(self) -> None:
        field_model = MagicMock()
        candidate = {"id": 1, "name": "Low", "score": 0.01, "codes": ["11580-8"]}

        result = get_template_extraction_context(
            candidate, {"11580-8"}, set(), field_model, False,
        )
        assert result is None

    def test_no_new_codes_returns_none(self) -> None:
        field_model = MagicMock()
        candidate = {"id": 1, "name": "Dup", "score": 0.8, "codes": ["11580-8"]}

        result = get_template_extraction_context(
            candidate, {"11580-8"}, {"11580-8"}, field_model, False,
        )
        assert result is None

    def test_no_fields_returns_none(self) -> None:
        field_model = MagicMock()
        field_model.objects.filter.return_value.order_by.return_value = []

        candidate = {"id": 1, "name": "Empty", "score": 0.8, "codes": ["11580-8"]}
        result = get_template_extraction_context(
            candidate, {"11580-8"}, set(), field_model, False,
        )
        assert result is None

    def test_gap_fill_uses_lower_threshold(self) -> None:
        field_model = MagicMock()
        f1 = MagicMock(code="11580-8", label="TSH", units=None, sequence=1)
        field_model.objects.filter.return_value.order_by.return_value = [f1]

        candidate = {"id": 1, "name": "Gap", "score": 0.04, "codes": ["11580-8"]}

        # Below gap fill threshold (0.05), returns None even in gap fill mode
        result = get_template_extraction_context(
            candidate, {"11580-8"}, set(), field_model, True,
        )
        assert result is None

        candidate_above = {"id": 1, "name": "Gap", "score": 0.06, "codes": ["11580-8"]}
        result = get_template_extraction_context(
            candidate_above, {"11580-8"}, set(), field_model, True,
        )
        assert result is not None


class TestBuildPrefillFieldsForCandidate:
    """Test build_prefill_fields_for_candidate."""

    def test_builds_template_dict(self) -> None:
        key_map = {"11580-8": MagicMock(units="mIU/L")}
        candidate = {"id": 1, "name": "CBC", "score": 0.8, "codes": ["11580-8"]}

        result = build_prefill_fields_for_candidate(
            {"11580-8": "4.5"}, None, key_map, candidate, 0.9,
        )

        assert result is not None
        assert result["template_id"] == 1
        assert result["template_name"] == "CBC"
        assert "11580-8" in result["fields"]

    def test_no_fields_returns_none(self) -> None:
        candidate = {"id": 1, "name": "CBC", "score": 0.8, "codes": []}
        result = build_prefill_fields_for_candidate({}, None, {}, candidate, 0.9)
        assert result is None

    def test_none_extraction_returns_none(self) -> None:
        candidate = {"id": 1, "name": "CBC", "score": 0.8, "codes": []}
        result = build_prefill_fields_for_candidate(None, None, {}, candidate, 0.9)
        assert result is None


class TestBuildPrefillEffectPublic:
    """Test build_prefill_effect public wrapper."""

    @patch("doc_intake_ai.templates._build_prefill_effect")
    def test_delegates_to_internal(self, mock_internal: MagicMock) -> None:
        mock_internal.return_value = MagicMock()
        templates = [{"template_id": 1, "template_name": "CBC", "fields": {"a": {"value": "1"}}}]

        result = build_prefill_effect("doc-123", templates, 0.9)

        assert result is not None
        mock_internal.assert_called_once_with("doc-123", templates, 0.9)
