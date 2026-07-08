"""Tests for the pure workflow logic: medication extraction, plan selection, context cache."""

from __future__ import annotations

from types import SimpleNamespace

from prescribe_formulary_benefits.workflow import (
    command_kind_for_event,
    correlation_key,
    extract_medication,
    fingerprint_key,
    load_context,
    select_plan_name,
    store_context,
)


def _plan(**kwargs):
    defaults = {
        "pbm_name": "",
        "drug_formulary_number": None,
        "description": None,
        "rejected": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# --- command_kind_for_event ------------------------------------------------


def test_command_kind_maps_each_prescribe_family_event() -> None:
    assert command_kind_for_event("PRESCRIBE_COMMAND__POST_UPDATE") == "prescribe"
    assert command_kind_for_event("REFILL_COMMAND__POST_UPDATE") == "refill"
    assert (
        command_kind_for_event("ADJUST_PRESCRIPTION_COMMAND__POST_UPDATE")
        == "adjust_prescription"
    )


def test_command_kind_returns_none_for_unrelated_event() -> None:
    assert command_kind_for_event("ASSESS_COMMAND__POST_UPDATE") is None


# --- extract_medication ----------------------------------------------------


def test_extract_medication_reads_description_and_representative_ndc() -> None:
    fields = {
        "prescribe": {
            "text": "Lisinopril 10 mg tablet",
            "value": 606783,
            "extra": {"coding": [{"system": "http://www.fdbhealth.com/", "code": 606783}]},
        },
        "type_to_dispense": {"value": 1, "extra": {"representative_ndc": "00006010654"}},
    }
    assert extract_medication(fields, "prescribe") == ("Lisinopril 10 mg tablet", "00006010654")


def test_extract_medication_returns_none_without_ndc() -> None:
    """Until a dispensable NDC is available the benefits request can't be built."""
    fields = {
        "prescribe": {
            "text": "Lisinopril 10 mg tablet",
            "value": 606783,
            "extra": {"coding": [{"system": "http://www.fdbhealth.com/", "code": 606783}]},
        }
    }
    assert extract_medication(fields, "prescribe") is None


def test_extract_medication_returns_none_when_no_medication_selected() -> None:
    assert extract_medication({"sig": "take one daily"}, "prescribe") is None
    assert extract_medication({"prescribe": {"text": "", "value": None}}, "prescribe") is None


def test_adjust_uses_change_medication_to_not_the_original() -> None:
    """Adjust reads the new drug (change_medication_to), never the original prescription."""
    fields = {
        "prescribe": {
            "text": "Old drug 10 mg",
            "value": 1,
            "extra": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "99999999999"}]},
        },
        "change_medication_to": {
            "text": "New drug 5 mg",
            "value": 2,
            "extra": {"representative_ndc": "11111222233"},
        },
    }
    assert extract_medication(fields, "adjust_prescription") == ("New drug 5 mg", "11111222233")


def test_adjust_ignores_original_prescription_when_no_change_selected() -> None:
    """Adjusting sig/quantity without changing the drug does not trigger on the original."""
    fields = {
        "prescribe": {
            "text": "Old drug 10 mg",
            "value": 1,
            "extra": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "99999999999"}]},
        },
        "type_to_dispense": {"extra": {"representative_ndc": "99999999999"}},
    }
    assert extract_medication(fields, "adjust_prescription") is None


def test_prescribe_ignores_change_medication_to_field() -> None:
    fields = {
        "change_medication_to": {"text": "Adjust-only drug", "value": 2,
                                 "extra": {"representative_ndc": "11111222233"}},
        "prescribe": {"text": "Prescribed drug", "value": 1},
        "type_to_dispense": {"extra": {"representative_ndc": "00006010654"}},
    }
    assert extract_medication(fields, "prescribe") == ("Prescribed drug", "00006010654")


def test_extract_medication_finds_ndc_systemed_coding() -> None:
    fields = {
        "prescribe": {
            "text": "Some drug",
            "value": 9,
            "extra": {
                "coding": [
                    {"system": "http://www.fdbhealth.com/", "code": 9},
                    {"system": "http://hl7.org/fhir/sid/ndc", "code": "00093-7146-01"},
                ]
            },
        }
    }
    assert extract_medication(fields, "prescribe") == ("Some drug", "00093-7146-01")


def test_extract_medication_falls_back_to_coding_display_for_description() -> None:
    fields = {
        "prescribe": {
            "text": "",
            "value": 9,
            "extra": {
                "coding": [{"system": "http://www.fdbhealth.com/", "code": 9, "display": "Drug X"}]
            },
        },
        "type_to_dispense": {"extra": {"representative_ndc": "00006010654"}},
    }
    assert extract_medication(fields, "prescribe") == ("Drug X", "00006010654")


# --- select_plan_name ------------------------------------------------------
# The benefits request's `plan` is matched server-side against each eligibility
# plan's pbm_name, so selection must return pbm_name (not description/formulary).


def test_select_plan_name_returns_pbm_name_of_first_active_plan() -> None:
    plans = [
        _plan(rejected=True, pbm_name="Rejected PBM"),
        _plan(pbm_name="CAREBRIDGE HEALTH PBM", description="Acme Commercial", drug_formulary_number="F123"),
    ]
    assert select_plan_name(plans) == "CAREBRIDGE HEALTH PBM"


def test_select_plan_name_ignores_description_and_formulary() -> None:
    # A plan with a description/formulary but no pbm_name can't be matched.
    assert select_plan_name([_plan(description="Acme Commercial", drug_formulary_number="F999")]) is None


def test_select_plan_name_none_when_all_rejected() -> None:
    """Rejected plans are never used to scope a benefits request."""
    plans = [_plan(rejected=True, pbm_name="CareMark")]
    assert select_plan_name(plans) is None


def test_select_plan_name_none_when_empty() -> None:
    assert select_plan_name([]) is None


# --- context cache roundtrip ----------------------------------------------


def test_store_and_load_context_roundtrip(fake_cache) -> None:
    payload = {"stage": "eligibility", "command_uuid": "abc", "ndc": "123"}
    store_context(fake_cache, "corr-1", payload)

    assert load_context(fake_cache, "corr-1") == payload


def test_load_context_consumes_the_entry(fake_cache) -> None:
    store_context(fake_cache, "corr-1", {"stage": "benefits"})
    load_context(fake_cache, "corr-1")
    # Second read returns None — a response is only handled once.
    assert load_context(fake_cache, "corr-1") is None


def test_load_context_unknown_correlation_returns_none(fake_cache) -> None:
    assert load_context(fake_cache, "never-seen") is None


def test_load_context_with_corrupt_value_returns_none(fake_cache) -> None:
    """A non-JSON cached value is handled gracefully (not raised)."""
    fake_cache.set(correlation_key("corr-x"), "{not valid json")
    assert load_context(fake_cache, "corr-x") is None


def test_cache_key_helpers_are_namespaced() -> None:
    assert correlation_key("abc") == "corr:abc"
    assert fingerprint_key("cmd-1") == "cmd_fp:cmd-1"


def test_extract_medication_ignores_non_ndc_representative_value() -> None:
    """A representative value that isn't NDC-shaped is not treated as an NDC."""
    fields = {
        "prescribe": {"text": "Some drug", "value": 9},
        "type_to_dispense": {"extra": {"representative_ndc": "N/A"}},
    }
    assert extract_medication(fields, "prescribe") is None


def test_extract_medication_ignores_non_string_ndc_value() -> None:
    """A non-string representative NDC (e.g. an int) is not accepted as an NDC."""
    fields = {
        "prescribe": {"text": "Some drug", "value": 9},
        "type_to_dispense": {"extra": {"representative_ndc": 123456789}},
    }
    assert extract_medication(fields, "prescribe") is None


def test_extract_medication_none_when_description_unresolvable() -> None:
    """Medication selected (has value + ndc) but no text/display -> no description -> None."""
    fields = {
        "prescribe": {
            "text": "",
            "value": 9,
            "extra": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "00093104801"}]},
        },
    }
    assert extract_medication(fields, "prescribe") is None
