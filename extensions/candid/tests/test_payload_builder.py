"""Tests for payload_builder: splitting, service line pointers, and formatting."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from candid.api.payload_builder import (
    MAX_DIAGNOSES_PER_ENCOUNTER,
    OVERFLOW_CHARGE_CENTS,
    OVERFLOW_CPT_CODE,
    _add_service_lines,
    _clamp_service_line_pointers,
    _format_diagnosis_chunk,
    _make_overflow_service_line,
    _split_diagnoses,
    _split_zip,
    build_claim_payload,
    build_split_payloads,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_diagnoses(n: int) -> list[dict]:
    """Build a list of n formatted diagnosis dicts (ABK + ABF)."""
    if n == 0:
        return []
    return [
        {"code": f"DX{i:03d}", "code_type": "ABK" if i == 0 else "ABF"} for i in range(n)
    ]


def _make_service_line(
    proc_code: str, pointers: list[int], charge_cents: int = 10000
) -> dict:
    """Build a minimal service line dict."""
    return {
        "procedure_code": proc_code,
        "units": "UN",
        "quantity": "1",
        "charge_amount_cents": charge_cents,
        "diagnosis_pointers": pointers,
    }


# ---------------------------------------------------------------------------
# _split_diagnoses
# ---------------------------------------------------------------------------


def test_split_single_chunk() -> None:
    """12 or fewer diagnoses produce one chunk."""
    diagnoses = _make_diagnoses(12)
    chunks = _split_diagnoses(diagnoses)
    assert len(chunks) == 1
    assert len(chunks[0]) == 12


def test_split_two_chunks() -> None:
    """14 diagnoses produce two chunks: 12 + 2."""
    diagnoses = _make_diagnoses(14)
    chunks = _split_diagnoses(diagnoses)
    assert len(chunks) == 2
    assert len(chunks[0]) == 12
    assert len(chunks[1]) == 2


def test_split_three_chunks() -> None:
    """25 diagnoses produce three chunks: 12 + 12 + 1."""
    diagnoses = _make_diagnoses(25)
    chunks = _split_diagnoses(diagnoses)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [12, 12, 1]


def test_split_preserves_rank_order() -> None:
    """Diagnoses stay in their original rank order after splitting."""
    diagnoses = _make_diagnoses(14)
    chunks = _split_diagnoses(diagnoses)
    assert [d["code"] for d in chunks[0]] == [f"DX{i:03d}" for i in range(12)]
    assert [d["code"] for d in chunks[1]] == ["DX012", "DX013"]


# ---------------------------------------------------------------------------
# _format_diagnosis_chunk
# ---------------------------------------------------------------------------


def test_format_chunk_first_is_abk() -> None:
    """First diagnosis in each chunk is ABK (primary), rest are ABF."""
    chunk = [{"code": "A00"}, {"code": "B00"}, {"code": "C00"}]
    formatted = _format_diagnosis_chunk(chunk)
    assert formatted[0] == {"code": "A00", "code_type": "ABK"}
    assert formatted[1] == {"code": "B00", "code_type": "ABF"}
    assert formatted[2] == {"code": "C00", "code_type": "ABF"}


def test_format_empty_chunk() -> None:
    """Empty chunk produces empty list."""
    assert _format_diagnosis_chunk([]) == []


# ---------------------------------------------------------------------------
# _clamp_service_line_pointers
# ---------------------------------------------------------------------------


def test_clamp_keeps_in_range_pointers() -> None:
    """Pointers within max_index are kept unchanged."""
    lines = [_make_service_line("99213", [0, 3, 11])]
    clamped = _clamp_service_line_pointers(lines, max_index=11)
    assert clamped[0]["diagnosis_pointers"] == [0, 3, 11]


def test_clamp_drops_out_of_range() -> None:
    """Pointers beyond max_index are dropped."""
    lines = [_make_service_line("99213", [0, 5, 12, 13])]
    clamped = _clamp_service_line_pointers(lines, max_index=11)
    assert clamped[0]["diagnosis_pointers"] == [0, 5]


def test_clamp_removes_pointers_key_when_all_out_of_range() -> None:
    """When all pointers are out of range, the key is removed entirely."""
    lines = [_make_service_line("99213", [12, 13])]
    clamped = _clamp_service_line_pointers(lines, max_index=11)
    assert "diagnosis_pointers" not in clamped[0]


def test_clamp_preserves_pointer_order() -> None:
    """Pointers keep their original order (no sorting)."""
    lines = [_make_service_line("99213", [5, 2, 8])]
    clamped = _clamp_service_line_pointers(lines, max_index=11)
    assert clamped[0]["diagnosis_pointers"] == [5, 2, 8]


def test_clamp_handles_multiple_service_lines() -> None:
    """Each service line is clamped independently."""
    lines = [
        _make_service_line("99213", [0, 12]),
        _make_service_line("99214", [11, 13]),
    ]
    clamped = _clamp_service_line_pointers(lines, max_index=11)
    assert clamped[0]["diagnosis_pointers"] == [0]
    assert clamped[1]["diagnosis_pointers"] == [11]


# ---------------------------------------------------------------------------
# _make_overflow_service_line
# ---------------------------------------------------------------------------


def test_overflow_line_structure() -> None:
    """99499 overflow line has correct code, charge, and pointers."""
    line = _make_overflow_service_line(3)
    assert line["procedure_code"] == OVERFLOW_CPT_CODE
    assert line["charge_amount_cents"] == OVERFLOW_CHARGE_CENTS
    assert line["diagnosis_pointers"] == [0, 1, 2]
    assert line["units"] == "UN"
    assert line["quantity"] == "1"


# ---------------------------------------------------------------------------
# _add_service_lines — diagnosis pointer sorting
# ---------------------------------------------------------------------------


def _fake_dx(code: str) -> MagicMock:
    """Build a mock LineItemDiagnosisCode with a linked claim_diagnosis_code."""
    linked_dx = MagicMock()
    linked_dx.claim_diagnosis_code.code = code
    linked_dx.linked = True
    return linked_dx


def _fake_line_item(proc_code: str, charge: int, linked_dx_codes: list[str]) -> MagicMock:
    """Build a mock ClaimLineItem with linked diagnosis codes."""
    li = MagicMock()
    li.proc_code = proc_code
    li.charge = charge
    li.units = 1
    li.diagnosis_codes.filter.return_value = [_fake_dx(code) for code in linked_dx_codes]
    li.modifiers.values_list.return_value = []
    return li


def _fake_claim(line_items: list[MagicMock]) -> MagicMock:
    """Build a mock Claim whose line_items.all() returns the given list."""
    claim = MagicMock()
    claim.line_items.all.return_value = line_items
    return claim


def test_diagnosis_pointers_are_sorted_ascending() -> None:
    """Diagnosis pointers must be sorted so the primary diagnosis (index 0) comes first.

    Regression test: the order of LineItemDiagnosisCode records is not guaranteed
    to match the claim-level diagnosis rank. Without sorting, the primary diagnosis
    can appear as a secondary pointer, causing payer denials.
    """
    # Diagnoses in claim-level order: DX_A=0, DX_B=1, DX_C=2
    payload: dict = {
        "diagnoses": [
            {"code": "DX_A", "code_type": "ABK"},
            {"code": "DX_B", "code_type": "ABF"},
            {"code": "DX_C", "code_type": "ABF"},
        ]
    }

    # Line item links DX_B first, then DX_A, then DX_C (wrong order from ORM)
    li = _fake_line_item("99205", 100, ["DX_B", "DX_A", "DX_C"])
    claim = _fake_claim([li])

    _add_service_lines(claim, payload)

    pointers = payload["service_lines"][0]["diagnosis_pointers"]
    # Should be sorted: [0, 1, 2] not [1, 0, 2]
    assert pointers == [0, 1, 2]


def test_diagnosis_pointers_sorted_with_subset() -> None:
    """When a service line only links to some diagnoses, pointers are still sorted."""
    payload: dict = {
        "diagnoses": [
            {"code": "DX_A", "code_type": "ABK"},
            {"code": "DX_B", "code_type": "ABF"},
            {"code": "DX_C", "code_type": "ABF"},
        ]
    }

    # Line item links DX_C then DX_A (skipping DX_B)
    li = _fake_line_item("99213", 100, ["DX_C", "DX_A"])
    claim = _fake_claim([li])

    _add_service_lines(claim, payload)

    pointers = payload["service_lines"][0]["diagnosis_pointers"]
    assert pointers == [0, 2]  # sorted, not [2, 0]


# ---------------------------------------------------------------------------
# _split_zip
# ---------------------------------------------------------------------------


def test_split_zip_handles_9_digit_with_dash() -> None:
    assert _split_zip("12345-6789") == ("12345", "6789")


def test_split_zip_handles_9_digit_no_dash() -> None:
    assert _split_zip("123456789") == ("12345", "6789")


def test_split_zip_handles_5_digit() -> None:
    assert _split_zip("12345") == ("12345", "")


def test_split_zip_handles_empty() -> None:
    assert _split_zip("") == ("", "")
    assert _split_zip(None) == ("", "")


# ---------------------------------------------------------------------------
# build_claim_payload — happy path smoke test
# ---------------------------------------------------------------------------


def _full_provider() -> MagicMock:
    p = MagicMock()
    p.billing_provider_npi = "1234567890"
    p.billing_provider_tax_id = "12-3456789"
    p.billing_provider_name = "Test Clinic"
    p.billing_provider_addr1 = "100 Main St"
    p.billing_provider_addr2 = ""
    p.billing_provider_city = "Springfield"
    p.billing_provider_state = "IL"
    p.billing_provider_zip = "62701"
    p.billing_provider_taxonomy = "207Q00000X"
    p.provider_npi = "0987654321"
    p.provider_first_name = "Alice"
    p.provider_last_name = "Smith"
    p.provider_taxonomy = "207Q00000X"
    p.provider_addr1 = "100 Main St"
    p.provider_addr2 = ""
    p.provider_city = "Springfield"
    p.provider_state = "IL"
    p.provider_zip = "62701"
    p.facility_name = "Test Clinic"
    p.facility_addr1 = "100 Main St"
    p.facility_addr2 = ""
    p.facility_city = "Springfield"
    p.facility_state = "IL"
    p.facility_zip = "62701"
    return p


def _full_patient() -> MagicMock:
    p = MagicMock()
    p.id = "pat-1"
    p.first_name = "Bob"
    p.last_name = "Jones"
    p.dob = date(1990, 1, 1)
    p.sex = "M"
    p.addr1 = "200 Oak Ave"
    p.addr2 = ""
    p.city = "Springfield"
    p.state = "IL"
    p.zip = "62701"
    return p


def _full_line_item() -> MagicMock:
    li = MagicMock()
    li.proc_code = "99213"
    li.charge = Decimal("100.00")
    li.units = 1
    li.from_date = date(2026, 1, 15)
    li.place_of_service = "11"
    linked = MagicMock()
    linked.claim_diagnosis_code.code = "Z00.00"
    linked.linked = True
    li.diagnosis_codes.filter.return_value = [linked]
    li.modifiers.values_list.return_value = []
    return li


def _full_claim_for_payload() -> MagicMock:
    claim = MagicMock()
    claim.id = "claim-uuid-1"
    claim.accept_assign = True
    claim.prior_auth = None
    claim.note = None
    claim.patient = _full_patient()
    claim.provider = _full_provider()

    line = _full_line_item()
    claim.line_items.all.return_value = [line]
    claim.line_items.first.return_value = line

    dx = MagicMock()
    dx.code = "Z00.00"
    claim.diagnosis_codes.order_by.return_value.values_list.return_value = ["Z00.00"]

    primary = MagicMock()
    primary.id = "cov-primary"
    primary.active = True
    primary.payer_order = 0
    primary.subscriber_first_name = "Bob"
    primary.subscriber_last_name = "Jones"
    primary.subscriber_sex = "M"
    primary.patient_relationship_to_subscriber = "18"
    primary.subscriber_number = "MEM123"
    primary.payer_id = "PAYER1"
    primary.payer_name = "Blue Cross"
    primary.subscriber_dob = date(1990, 1, 1)
    primary.subscriber_group = ""
    primary.subscriber_addr1 = "200 Oak Ave"
    primary.subscriber_addr2 = ""
    primary.subscriber_city = "Springfield"
    primary.subscriber_state = "IL"
    primary.subscriber_zip = "62701"
    primary.coverage = MagicMock(plan="Gold PPO")
    claim.coverages.all.return_value = [primary]
    return claim


def test_build_claim_payload_happy_path() -> None:
    """Fully populated claim produces a complete payload with no errors."""
    claim = _full_claim_for_payload()
    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["external_id"] == "canvas:claim-uuid-1"
    assert payload["responsible_party"] == "INSURANCE_PAY"
    assert payload["billable_status"] == "BILLABLE"
    assert payload["benefits_assigned_to_provider"] is True
    assert payload["provider_accepts_assignment"] is True
    assert payload["place_of_service_code"] == "11"
    assert payload["date_of_service"] == "2026-01-15"
    assert payload["diagnoses"] == [{"code": "Z00.00", "code_type": "ABK"}]
    assert len(payload["service_lines"]) == 1
    assert payload["service_lines"][0]["procedure_code"] == "99213"
    assert payload["patient"]["first_name"] == "Bob"
    assert payload["patient"]["external_id"] == "canvas:pat-1"
    assert payload["billing_provider"]["npi"] == "1234567890"
    assert payload["rendering_provider"]["npi"] == "0987654321"
    assert payload["service_facility"]["organization_name"] == "Test Clinic"
    assert payload["subscriber_primary"]["insurance_card"]["payer_id"] == "PAYER1"


def test_build_claim_payload_self_pay_when_no_coverage() -> None:
    """No coverages → responsible_party = SELF_PAY."""
    claim = _full_claim_for_payload()
    claim.coverages.all.return_value = []
    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["responsible_party"] == "SELF_PAY"
    assert "subscriber_primary" not in payload


def test_build_claim_payload_collects_errors_for_missing_patient_fields() -> None:
    claim = _full_claim_for_payload()
    claim.patient.zip = ""
    claim.patient.city = ""

    _, errors = build_claim_payload(claim)
    assert any("zip" in e for e in errors)
    assert any("city" in e for e in errors)


def test_build_split_payloads_returns_single_payload_for_few_diagnoses() -> None:
    """≤12 diagnoses → exactly one payload, no overflow encounter."""
    claim = _full_claim_for_payload()
    claim.diagnosis_codes.order_by.return_value.values_list.return_value = [
        f"DX{i:03d}" for i in range(5)
    ]
    splits = build_split_payloads(claim)
    assert len(splits) == 1
    payload, errors = splits[0]
    assert errors == []
    assert len(payload["diagnoses"]) == 5
