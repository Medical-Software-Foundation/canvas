"""Tests for CPT/CVX code extraction from command coding fields."""

from patient_visit_summary.services import code_utils as cu


# Real coding-field shapes captured from committed commands.
IMMUNIZE_CODING = {
    "text": "DTaP-Haemophilus influenzae type b conjugate vaccine (CPT: 90721)",
    "extra": {
        "sort": False,
        "coding": [
            {"code": "90721", "system": "http://www.ama-assn.org/go/cpt", "display": "DTaP-Hib"},
            {"code": "50", "system": "http://hl7.org/fhir/sid/cvx", "display": "DTaP-Hib vaccine"},
        ],
    },
    "value": 32,
}

PERFORM_CODING = {
    "text": "Biopsy floor mouth (CPT: 41108)",
    "extra": {"coding": [
        {"code": "41108", "system": "http://www.ama-assn.org/go/cpt", "display": "Biopsy floor mouth"},
    ]},
    "value": "41108",
}


class TestExtractBillingCodes:
    def test_cpt_and_cvx_cpt_first(self):
        assert cu.extract_billing_codes(IMMUNIZE_CODING) == [("CPT", "90721"), ("CVX", "50")]

    def test_cpt_only(self):
        assert cu.extract_billing_codes(PERFORM_CODING) == [("CPT", "41108")]

    def test_orders_cpt_before_cvx_even_if_cvx_listed_first(self):
        field = {"extra": {"coding": [
            {"code": "50", "system": "http://hl7.org/fhir/sid/cvx"},
            {"code": "90721", "system": "http://www.ama-assn.org/go/cpt"},
        ]}}
        assert cu.extract_billing_codes(field) == [("CPT", "90721"), ("CVX", "50")]

    def test_dedupes_preserving_order(self):
        field = {"extra": {"coding": [
            {"code": "90721", "system": "CPT"},
            {"code": "90721", "system": "http://www.ama-assn.org/go/cpt"},
        ]}}
        assert cu.extract_billing_codes(field) == [("CPT", "90721")]

    def test_short_system_names(self):
        field = {"extra": {"coding": [
            {"code": "90721", "system": "cpt"},
            {"code": "50", "system": "CVX"},
        ]}}
        assert cu.extract_billing_codes(field) == [("CPT", "90721"), ("CVX", "50")]

    def test_unknown_system_ignored(self):
        field = {"extra": {"coding": [
            {"code": "E11.9", "system": "http://hl7.org/fhir/sid/icd-10"},
        ]}}
        assert cu.extract_billing_codes(field) == []

    def test_blank_code_skipped(self):
        # Blank-code entry is skipped; a following valid entry still resolves.
        field = {"extra": {"coding": [
            {"code": "  ", "system": "cpt"},
            {"code": "90721", "system": "cpt"},
        ]}}
        assert cu.extract_billing_codes(field) == [("CPT", "90721")]

    def test_non_dict_coding_entry_skipped(self):
        field = {"extra": {"coding": ["nope", {"code": "90721", "system": "cpt"}]}}
        assert cu.extract_billing_codes(field) == [("CPT", "90721")]

    def test_not_a_dict(self):
        assert cu.extract_billing_codes("x") == []
        assert cu.extract_billing_codes(None) == []

    def test_no_extra(self):
        assert cu.extract_billing_codes({"text": "x"}) == []

    def test_extra_not_dict(self):
        assert cu.extract_billing_codes({"extra": "x"}) == []

    def test_coding_not_list(self):
        assert cu.extract_billing_codes({"extra": {"coding": "x"}}) == []


class TestCodesDisplay:
    def test_cpt_and_cvx(self):
        assert cu.codes_display(IMMUNIZE_CODING) == "CPT 90721, CVX 50"

    def test_cpt_only(self):
        assert cu.codes_display(PERFORM_CODING) == "CPT 41108"

    def test_empty(self):
        assert cu.codes_display({"text": "x"}) == ""


class TestStripCptSuffix:
    def test_strips_trailing_cpt(self):
        assert cu.strip_cpt_suffix("Biopsy floor mouth (CPT: 41108)") == "Biopsy floor mouth"

    def test_case_insensitive(self):
        assert cu.strip_cpt_suffix("X (cpt: 99)") == "X"

    def test_keeps_non_cpt_parens(self):
        assert cu.strip_cpt_suffix("Influenza (split virus)") == "Influenza (split virus)"

    def test_no_suffix_unchanged(self):
        assert cu.strip_cpt_suffix("Plain name") == "Plain name"

    def test_non_string(self):
        assert cu.strip_cpt_suffix(None) == ""
        assert cu.strip_cpt_suffix(123) == ""


class TestCodedTitle:
    def test_name_and_codes_no_double_cpt(self):
        assert cu.coded_title(IMMUNIZE_CODING["text"], IMMUNIZE_CODING) == (
            "DTaP-Haemophilus influenzae type b conjugate vaccine (CPT 90721, CVX 50)"
        )

    def test_perform_cpt_only(self):
        assert cu.coded_title(PERFORM_CODING["text"], PERFORM_CODING) == (
            "Biopsy floor mouth (CPT 41108)"
        )

    def test_name_only_when_no_codes(self):
        assert cu.coded_title("Plain procedure", {"text": "Plain procedure"}) == "Plain procedure"

    def test_codes_only_when_no_name(self):
        assert cu.coded_title("", PERFORM_CODING) == "(CPT 41108)"

    def test_empty_both(self):
        assert cu.coded_title("", {}) == ""
