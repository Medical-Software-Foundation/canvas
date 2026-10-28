"""Tests for payload_builder: splitting, service line pointers, and formatting."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from canvas_sdk.v1.data import Claim

from candid.api.payload_builder import (
    MAX_DIAGNOSES_PER_ENCOUNTER,
    MAX_DIAGNOSIS_POINTERS_PER_SERVICE_LINE,
    OVERFLOW_CHARGE_CENTS,
    OVERFLOW_CPT_CODE,
    _add_billing_provider,
    _add_rendering_provider,
    _add_service_lines,
    _add_supervising_provider,
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


def test_overflow_line_caps_pointers_at_max() -> None:
    """Overflow line points to at most 4 diagnoses (837 limit)."""
    line = _make_overflow_service_line(MAX_DIAGNOSES_PER_ENCOUNTER)
    assert line["diagnosis_pointers"] == [0, 1, 2, 3]
    assert len(line["diagnosis_pointers"]) == MAX_DIAGNOSIS_POINTERS_PER_SERVICE_LINE


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
    li.id = f"li-{proc_code}"
    li.diagnosis_codes.filter.return_value = [_fake_dx(code) for code in linked_dx_codes]
    li.modifiers.values_list.return_value = []
    return li


def _fake_claim(line_items: list[MagicMock]) -> MagicMock:
    """Build a mock Claim whose get_active_claim_line_items() returns the given list."""
    claim = MagicMock()
    claim.get_active_claim_line_items.return_value = line_items
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


def test_diagnosis_pointers_capped_at_four() -> None:
    """Service line links to at most 4 diagnoses (837 limit)."""
    payload: dict = {
        "diagnoses": [
            {"code": f"DX_{i}", "code_type": "ABK" if i == 0 else "ABF"}
            for i in range(6)
        ]
    }

    li = _fake_line_item("99213", 100, ["DX_0", "DX_1", "DX_2", "DX_3", "DX_4", "DX_5"])
    claim = _fake_claim([li])

    _add_service_lines(claim, payload)

    pointers = payload["service_lines"][0]["diagnosis_pointers"]
    assert pointers == [0, 1, 2, 3]


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
# _add_service_lines — note billing-line-item ordering
# ---------------------------------------------------------------------------


def _fake_line_item_with_billing(proc_code: str, billing_created: datetime) -> MagicMock:
    """A claim line item linked to a note billing line item created at ``billing_created``."""
    li = MagicMock()
    li.proc_code = proc_code
    li.charge = 100
    li.units = 1
    li.id = f"li-{proc_code}"
    li.billing_line_item.created = billing_created
    li.diagnosis_codes.filter.return_value = []
    li.modifiers.values_list.return_value = []
    return li


def test_service_lines_follow_note_billing_order() -> None:
    """Service lines follow the note's billing-line-item order, not the claim's default sort.

    get_active_claim_line_items() returns items in -proc_code order, which reverses add-on
    CPT pairs (e.g. G0022 ahead of G0019). The payload must match the order the clinician
    entered on the note, because payers process service lines top-down.
    """
    payload: dict = {"diagnoses": []}

    # Note order: G0019 entered first (10:00), G0022 second (10:05). The claim default sort
    # (-proc_code) hands them back reversed (G0022, then G0019).
    g0022 = _fake_line_item_with_billing("G0022", datetime(2026, 4, 1, 10, 5))
    g0019 = _fake_line_item_with_billing("G0019", datetime(2026, 4, 1, 10, 0))
    claim = _fake_claim([g0022, g0019])

    _add_service_lines(claim, payload)

    codes = [sl["procedure_code"] for sl in payload["service_lines"]]
    assert codes == ["G0019", "G0022"]


def test_service_lines_without_billing_sort_last() -> None:
    """Claim lines with no billing line item (added directly on the claim) sort after note lines."""
    payload: dict = {"diagnoses": []}

    note_line = _fake_line_item_with_billing("99213", datetime(2026, 4, 1, 10, 0))
    manual_line = _fake_line_item_with_billing("99214", datetime(2026, 4, 1, 9, 0))
    manual_line.billing_line_item = None
    manual_line.created = datetime(2026, 4, 1, 11, 0)
    claim = _fake_claim([manual_line, note_line])

    _add_service_lines(claim, payload)

    codes = [sl["procedure_code"] for sl in payload["service_lines"]]
    assert codes == ["99213", "99214"]


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
    li.id = "li-99213"
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
    claim.get_active_claim_line_items.return_value = [line]

    dx = MagicMock()
    dx.code = "Z00.00"
    claim.diagnosis_codes.order_by.return_value.values_list.return_value = ["Z00.00"]

    primary = MagicMock()
    primary.id = "cov-primary"
    primary.active = True
    primary.payer_order = "Primary"
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
    claim.coverages.active.return_value = [primary]
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


def test_rendering_provider_address_omitted_when_no_zip_plus_four() -> None:
    """Rendering provider address requires zip+4; omit the address when the
    provider zip is only 5 digits, but keep the rest of the provider."""
    claim = _full_claim_for_payload()
    claim.provider.provider_zip = "62701"

    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["rendering_provider"]["npi"] == "0987654321"
    assert "address" not in payload["rendering_provider"]


def test_rendering_provider_address_included_with_zip_plus_four() -> None:
    """Rendering provider address is sent when a full zip+4 is available."""
    claim = _full_claim_for_payload()
    claim.provider.provider_zip = "62701-1234"

    payload, errors = build_claim_payload(claim)

    assert errors == []
    address = payload["rendering_provider"]["address"]
    assert address["zip_code"] == "62701"
    assert address["zip_plus_four_code"] == "1234"


def test_billing_provider_uses_9998_when_no_zip_plus_four() -> None:
    """Billing provider zip+4 is required and the address can't be dropped;
    fall back to the CMS-accepted 9998 placeholder."""
    claim = _full_claim_for_payload()
    claim.provider.billing_provider_zip = "62701"

    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["billing_provider"]["address"]["zip_plus_four_code"] == "9998"


def test_service_facility_uses_9998_when_no_zip_plus_four() -> None:
    """Service facility zip+4 is required; fall back to CMS placeholder 9998."""
    claim = _full_claim_for_payload()
    claim.provider.facility_zip = "62701"

    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["service_facility"]["address"]["zip_plus_four_code"] == "9998"


def test_build_claim_payload_self_pay_when_no_coverage() -> None:
    """No coverages → responsible_party = SELF_PAY."""
    claim = _full_claim_for_payload()
    claim.coverages.all.return_value = []
    claim.coverages.active.return_value = []
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


# ---------------------------------------------------------------------------
# _add_supervising_provider
# ---------------------------------------------------------------------------


def _supervising(
    npi: str = "9998887776",
    first_name: str = "Maria",
    last_name: str = "House",
    taxonomy: str = "207Q00000X",
) -> MagicMock:
    s = MagicMock()
    s.npi = npi
    s.first_name = first_name
    s.last_name = last_name
    s.taxonomy = taxonomy
    return s


def test_supervising_included_when_not_incident_to() -> None:
    """A non-incident-to claim with a snapshot yields the Candid supervising block."""
    claim = MagicMock()
    claim.incident_to = False
    claim.supervising_provider = _supervising()
    payload: dict = {}
    errors: list[str] = []

    _add_supervising_provider(claim, payload, errors)

    assert errors == []
    assert payload["supervising_provider"] == {
        "npi": "9998887776",
        "first_name": "Maria",
        "last_name": "House",
        "taxonomy_code": "207Q00000X",
    }


def test_supervising_omitted_when_incident_to() -> None:
    """Incident-to claims omit supervising — it rides the rendering provider."""
    claim = MagicMock()
    claim.incident_to = True
    claim.supervising_provider = _supervising()
    payload: dict = {}
    errors: list[str] = []

    _add_supervising_provider(claim, payload, errors)

    assert "supervising_provider" not in payload
    assert errors == []


def test_supervising_omitted_without_snapshot() -> None:
    """No snapshot → no supervising block and no error."""

    class _NoSupervisingClaim:
        incident_to = False

        @property
        def supervising_provider(self) -> object:
            raise Claim.supervising_provider.RelatedObjectDoesNotExist

    payload: dict = {}
    errors: list[str] = []

    _add_supervising_provider(_NoSupervisingClaim(), payload, errors)

    assert "supervising_provider" not in payload
    assert errors == []


def test_supervising_errors_when_npi_missing() -> None:
    """A supervising snapshot without an NPI surfaces an error and is omitted."""
    claim = MagicMock()
    claim.incident_to = False
    claim.supervising_provider = _supervising(npi="0")
    payload: dict = {}
    errors: list[str] = []

    _add_supervising_provider(claim, payload, errors)

    assert "supervising_provider" not in payload
    assert errors == ["Supervising provider: NPI is required, but was missing"]


@pytest.mark.parametrize("bad_npi", ["123456789", "12345678901", "99988877X6"])
def test_supervising_errors_when_npi_not_ten_digits(bad_npi: str) -> None:
    """An NPI that isn't exactly 10 digits is rejected (Candid would reject it too)."""
    claim = MagicMock()
    claim.incident_to = False
    claim.supervising_provider = _supervising(npi=bad_npi)
    payload: dict = {}
    errors: list[str] = []

    _add_supervising_provider(claim, payload, errors)

    assert "supervising_provider" not in payload
    assert errors == ["Supervising provider: NPI must be exactly 10 digits"]


# ---------------------------------------------------------------------------
# _add_billing_provider / _add_rendering_provider — NPI 10-digit validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_npi", ["123456789", "12345678901", "12345678X0"])
def test_billing_provider_errors_when_npi_not_ten_digits(bad_npi: str) -> None:
    """A billing NPI that isn't exactly 10 digits is rejected (Candid would reject it)."""
    claim = MagicMock()
    claim.provider = _full_provider()
    claim.provider.billing_provider_npi = bad_npi
    payload: dict = {}
    errors: list[str] = []

    _add_billing_provider(claim, payload, errors)

    assert "billing_provider" not in payload
    assert errors == ["Billing provider: NPI must be exactly 10 digits"]


@pytest.mark.parametrize("bad_npi", ["123456789", "12345678901", "12345678X0"])
def test_rendering_provider_errors_when_npi_not_ten_digits(bad_npi: str) -> None:
    """A rendering NPI that's present but not 10 digits is rejected."""
    claim = MagicMock()
    claim.provider = _full_provider()
    claim.provider.provider_npi = bad_npi
    payload: dict = {}
    errors: list[str] = []

    _add_rendering_provider(claim, payload, errors)

    assert "rendering_provider" not in payload
    assert errors == ["Rendering provider: NPI must be exactly 10 digits"]


def test_rendering_provider_allows_name_only_without_npi() -> None:
    """No NPI is fine for rendering when first+last name are present — no 10-digit check."""
    claim = MagicMock()
    claim.provider = _full_provider()
    claim.provider.provider_npi = ""
    payload: dict = {}
    errors: list[str] = []

    _add_rendering_provider(claim, payload, errors)

    assert errors == []
    assert "npi" not in payload["rendering_provider"]
    assert payload["rendering_provider"]["first_name"] == "Alice"


def test_build_claim_payload_includes_supervising_leaves_billing_and_rendering() -> None:
    """End-to-end: supervising is included while billing and rendering are unchanged."""
    claim = _full_claim_for_payload()
    claim.incident_to = False
    claim.supervising_provider = _supervising()

    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["supervising_provider"]["npi"] == "9998887776"
    assert payload["billing_provider"]["npi"] == "1234567890"
    assert payload["rendering_provider"]["npi"] == "0987654321"


# ---------------------------------------------------------------------------
# build_split_payloads with >12 diagnoses
# ---------------------------------------------------------------------------


def test_build_split_payloads_splits_over_twelve_diagnoses() -> None:
    claim = _full_claim_for_payload()
    codes = [f"DX{i:03d}" for i in range(14)]
    claim.diagnosis_codes.order_by.return_value.values_list.return_value = codes
    line = claim.get_active_claim_line_items.return_value[0]
    linked = []
    for code in ("DX000", "DX005", "DX013"):
        dx = MagicMock()
        dx.claim_diagnosis_code.code = code
        linked.append(dx)
    line.diagnosis_codes.filter.return_value = linked

    splits = build_split_payloads(claim)

    assert len(splits) == 2
    (primary, primary_errors), (supplemental, supp_errors) = splits
    assert primary_errors == [] and supp_errors == []

    assert primary["external_id"] == "canvas:claim-uuid-1-1"
    assert [d["code"] for d in primary["diagnoses"]] == codes[:12]
    assert primary["diagnoses"][0]["code_type"] == "ABK"
    # Pointer 13 lives on the supplemental split, so it's dropped here
    assert primary["service_lines"][0]["procedure_code"] == "99213"
    assert primary["service_lines"][0]["diagnosis_pointers"] == [0, 5]

    assert supplemental["external_id"] == "canvas:claim-uuid-1-2"
    assert supplemental["diagnoses"] == [
        {"code": "DX012", "code_type": "ABK"},
        {"code": "DX013", "code_type": "ABF"},
    ]
    assert supplemental["service_lines"] == [
        {
            "procedure_code": OVERFLOW_CPT_CODE,
            "description": (
                "Supplemental claim for additional diagnosis codes exceeding CMS-1500 limit"
            ),
            "modifiers": [],
            "units": "UN",
            "quantity": "1",
            "charge_amount_cents": OVERFLOW_CHARGE_CENTS,
            "diagnosis_pointers": [0, 1],
            "external_id": "canvas:claim-uuid-1-2-sl0",
        }
    ]
    # Splits are independent copies: patient data isn't shared by reference
    assert supplemental["patient"] == primary["patient"]
    assert supplemental["patient"] is not primary["patient"]


def test_build_split_payloads_returns_errors_without_splitting() -> None:
    claim = _full_claim_for_payload()
    claim.diagnosis_codes.order_by.return_value.values_list.return_value = [
        f"DX{i:03d}" for i in range(20)
    ]
    claim.patient = None

    splits = build_split_payloads(claim)

    assert len(splits) == 1
    assert "Claim patient info is missing" in splits[0][1]


def test_build_claim_payload_reports_unexpected_step_error() -> None:
    claim = _full_claim_for_payload()
    claim.diagnosis_codes.order_by.side_effect = RuntimeError("db gone")

    payload, errors = build_claim_payload(claim)

    assert "Unexpected error building diagnoses: db gone" in errors
    # Other steps still ran
    assert payload["patient"]["first_name"] == "Bob"


# ---------------------------------------------------------------------------
# Core fields, diagnoses, service lines
# ---------------------------------------------------------------------------


def test_core_fields_errors_when_identifiers_missing() -> None:
    claim = _full_claim_for_payload()
    claim.id = None
    line = claim.line_items.first.return_value
    line.from_date = None
    line.place_of_service = None

    _, errors = build_claim_payload(claim)

    assert "External encounter id is missing" in errors
    assert "Date of service is missing" in errors
    assert "Place of service is missing" in errors


def test_core_fields_prior_auth_and_accept_assign_default() -> None:
    claim = _full_claim_for_payload()
    claim.prior_auth = 12345
    claim.accept_assign = None

    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert payload["prior_authorization_number"] == "12345"
    assert payload["provider_accepts_assignment"] is True


def test_core_fields_respect_accept_assign_false() -> None:
    claim = _full_claim_for_payload()
    claim.accept_assign = False
    payload, _ = build_claim_payload(claim)
    assert payload["provider_accepts_assignment"] is False


def test_date_of_service_uses_note_datetime_in_instance_tz() -> None:
    from zoneinfo import ZoneInfo

    claim = _full_claim_for_payload()
    claim.note = MagicMock()
    claim.note.datetime_of_service = datetime(2026, 2, 1, 3, 0, tzinfo=ZoneInfo("UTC"))

    central, _ = build_claim_payload(claim)
    utc, _ = build_claim_payload(claim, tz=ZoneInfo("UTC"))

    assert central["date_of_service"] == "2026-01-31"
    assert utc["date_of_service"] == "2026-02-01"


def test_place_of_service_falls_back_to_note_then_note_type() -> None:
    claim = _full_claim_for_payload()
    claim.line_items.first.return_value.place_of_service = ""
    claim.note = MagicMock()
    claim.note.place_of_service = "02"
    payload, _ = build_claim_payload(claim)
    assert payload["place_of_service_code"] == "02"

    claim.note.place_of_service = None
    claim.note.note_type_version.default_place_of_service = "22"
    payload, _ = build_claim_payload(claim)
    assert payload["place_of_service_code"] == "22"

    claim.note.note_type_version = None
    _, errors = build_claim_payload(claim)
    assert "Place of service is missing" in errors


def test_missing_diagnoses_is_an_error() -> None:
    claim = _full_claim_for_payload()
    claim.diagnosis_codes.order_by.return_value.values_list.return_value = []
    payload, errors = build_claim_payload(claim)
    assert "Diagnosis code is missing" in errors
    assert "diagnoses" not in payload


def test_service_line_quantity_charge_and_modifiers() -> None:
    claim = _full_claim_for_payload()
    line = claim.get_active_claim_line_items.return_value[0]
    line.units = 2
    line.charge = Decimal("125.50")
    line.modifiers.values_list.return_value = ["25", "59"]

    payload, _ = build_claim_payload(claim)

    sl = payload["service_lines"][0]
    assert sl["quantity"] == "2"
    assert sl["charge_amount_cents"] == "12550"
    assert sl["modifiers"] == ["25", "59"]
    assert sl["external_id"] == "li-99213"


def test_service_line_omits_optional_fields_when_absent() -> None:
    claim = _full_claim_for_payload()
    line = claim.get_active_claim_line_items.return_value[0]
    line.units = None
    line.charge = None
    unlinked = MagicMock()
    unlinked.claim_diagnosis_code = None
    line.diagnosis_codes.filter.return_value = [unlinked]

    payload, _ = build_claim_payload(claim)

    sl = payload["service_lines"][0]
    assert "quantity" not in sl
    assert "charge_amount_cents" not in sl
    assert "diagnosis_pointers" not in sl
    assert "modifiers" not in sl


def test_no_active_line_items_omits_service_lines() -> None:
    claim = _full_claim_for_payload()
    claim.get_active_claim_line_items.return_value = []
    payload, _ = build_claim_payload(claim)
    assert "service_lines" not in payload


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------


def test_patient_payload_uses_note_patient_and_addr2() -> None:
    claim = _full_claim_for_payload()
    claim.patient.addr2 = "Apt 4"
    claim.patient.zip = "62701-1234"
    claim.patient.sex = "F"
    claim.note = MagicMock()
    claim.note.datetime_of_service = None
    claim.note.patient.id = "note-pat-9"

    payload, errors = build_claim_payload(claim)

    assert errors == []
    patient = payload["patient"]
    assert patient["external_id"] == "canvas:note-pat-9"
    assert patient["gender"] == "female"
    assert patient["date_of_birth"] == "1990-01-01"
    assert patient["address"] == {
        "address1": "200 Oak Ave",
        "address2": "Apt 4",
        "city": "Springfield",
        "state": "IL",
        "zip_code": "62701",
    }


def test_missing_patient_is_an_error() -> None:
    claim = _full_claim_for_payload()
    claim.patient = None
    payload, errors = build_claim_payload(claim)
    assert "Claim patient info is missing" in errors
    assert "patient" not in payload


@pytest.mark.parametrize(
    "sex,gender", [("M", "male"), ("O", "other"), ("UNK", "unknown"), ("X", "unknown")]
)
def test_patient_gender_mapping(sex: str, gender: str) -> None:
    claim = _full_claim_for_payload()
    claim.patient.sex = sex
    payload, _ = build_claim_payload(claim)
    assert payload["patient"]["gender"] == gender


# ---------------------------------------------------------------------------
# Providers and facility
# ---------------------------------------------------------------------------


def test_missing_provider_errors_once_and_skips_provider_sections() -> None:
    claim = _full_claim_for_payload()
    claim.provider = None

    payload, errors = build_claim_payload(claim)

    assert errors == ["Claim provider info is missing"]
    for key in ("billing_provider", "rendering_provider", "service_facility"):
        assert key not in payload


def test_billing_provider_missing_fields_listed() -> None:
    claim = _full_claim_for_payload()
    claim.provider.billing_provider_tax_id = ""
    claim.provider.billing_provider_zip = ""

    payload, errors = build_claim_payload(claim)

    assert (
        "The following items were missing for the billing provider: "
        "billing_provider_tax_id, billing_provider_zip_code"
    ) in errors
    assert "billing_provider" not in payload


def test_billing_provider_optional_fields() -> None:
    claim = _full_claim_for_payload()
    claim.provider.billing_provider_addr2 = "Suite 1"
    claim.provider.billing_provider_name = ""
    claim.provider.billing_provider_taxonomy = ""

    payload, _ = build_claim_payload(claim)

    bp = payload["billing_provider"]
    assert bp["address"]["address2"] == "Suite 1"
    assert "organization_name" not in bp
    assert "taxonomy_code" not in bp


def test_rendering_provider_requires_npi_or_name() -> None:
    claim = _full_claim_for_payload()
    claim.provider.provider_npi = "0"
    claim.provider.provider_last_name = ""

    payload, errors = build_claim_payload(claim)

    assert "Rendering provider: NPI OR first+last name is required" in errors
    assert "rendering_provider" not in payload


def test_rendering_provider_address_includes_addr2() -> None:
    claim = _full_claim_for_payload()
    claim.provider.provider_zip = "627011234"
    claim.provider.provider_addr2 = "Floor 2"
    claim.provider.provider_taxonomy = ""

    payload, _ = build_claim_payload(claim)

    rp = payload["rendering_provider"]
    assert rp["address"]["address2"] == "Floor 2"
    assert "taxonomy_code" not in rp


def test_service_facility_addr2_included() -> None:
    claim = _full_claim_for_payload()
    claim.provider.facility_addr2 = "Bldg B"
    payload, _ = build_claim_payload(claim)
    assert payload["service_facility"]["address"]["address2"] == "Bldg B"


def test_service_facility_required_for_telehealth() -> None:
    claim = _full_claim_for_payload()
    claim.line_items.first.return_value.place_of_service = "02"
    claim.provider.facility_name = ""

    payload, errors = build_claim_payload(claim)

    assert (
        "Service facility information is required for telehealth claims, "
        "but was missing: service_facility_org_name"
    ) in errors
    assert "service_facility" not in payload


def test_service_facility_optional_for_in_person() -> None:
    claim = _full_claim_for_payload()
    claim.provider.facility_name = ""
    payload, errors = build_claim_payload(claim)
    assert errors == []
    assert "service_facility" not in payload


def test_supervising_provider_optional_names_omitted() -> None:
    claim = MagicMock(spec=Claim)
    claim.incident_to = False
    claim.supervising_provider = MagicMock(
        npi="9998887776", first_name="", last_name="", taxonomy=""
    )
    payload: dict = {}
    errors: list[str] = []

    _add_supervising_provider(claim, payload, errors)

    assert errors == []
    assert payload["supervising_provider"] == {"npi": "9998887776"}


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------


def _subscriber_coverage(coverage_id: str, payer_order: str) -> MagicMock:
    claim = _full_claim_for_payload()
    cov = claim.coverages.active.return_value[0]
    cov.id = coverage_id
    cov.payer_order = payer_order
    return cov


def test_subscribers_primary_and_secondary_with_optional_fields() -> None:
    claim = _full_claim_for_payload()
    primary = claim.coverages.active.return_value[0]
    primary.subscriber_group = "GRP1"
    primary.subscriber_addr2 = "Unit 3"
    secondary = _subscriber_coverage("cov-secondary", "Secondary")
    secondary.payer_id = "PAYER2"
    secondary.subscriber_dob = None
    secondary.coverage = None
    secondary.subscriber_addr1 = ""
    claim.coverages.active.return_value = [secondary, primary]

    payload, errors = build_claim_payload(claim)

    assert errors == []
    sp = payload["subscriber_primary"]
    assert sp["insurance_card"]["group_number"] == "GRP1"
    assert sp["insurance_card"]["plan_name"] == "Gold PPO"
    assert sp["insurance_card"]["emr_payer_crosswalk"] == "CANVAS"
    assert sp["address"]["address2"] == "Unit 3"
    assert sp["date_of_birth"] == "1990-01-01"
    ss = payload["subscriber_secondary"]
    assert ss["insurance_card"]["payer_id"] == "PAYER2"
    assert "date_of_birth" not in ss
    assert "plan_name" not in ss["insurance_card"]
    assert "address" not in ss


def test_incomplete_primary_subscriber_errors_for_insurance_pay() -> None:
    claim = _full_claim_for_payload()
    claim.coverages.active.return_value[0].subscriber_number = ""

    payload, errors = build_claim_payload(claim)

    assert (
        "Because the responsible_party is INSURANCE_PAY, the primary subscriber "
        "is required but has missing fields"
    ) in errors
    assert "subscriber_primary" not in payload


def test_incomplete_secondary_subscriber_is_dropped_silently() -> None:
    claim = _full_claim_for_payload()
    secondary = _subscriber_coverage("cov-secondary", "Secondary")
    secondary.payer_name = ""
    claim.coverages.active.return_value.append(secondary)

    payload, errors = build_claim_payload(claim)

    assert errors == []
    assert "subscriber_secondary" not in payload
    assert "subscriber_primary" in payload
