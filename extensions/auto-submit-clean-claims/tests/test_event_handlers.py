from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import (
    ClaimCoverageFactory,
    ClaimDiagnosisCodeFactory,
    ClaimFactory,
    ClaimLabelFactory,
    ClaimLineItemDiagnosisCodeFactory,
    ClaimLineItemFactory,
    ClaimProviderFactory,
    ClaimQueueFactory,
    CoverageFactory,
    TaskLabelFactory,
)

from canvas_sdk.v1.data.coverage import CoverageStack

from canvas_sdk.v1.data.claim import ClaimPatient

from auto_submit_clean_claims.handlers.auto_submit import AutoSubmitCleanClaims
from auto_submit_clean_claims.handlers.sweep_coding_queue import SweepCodingQueue
from auto_submit_clean_claims.helpers.claim_processor import is_plugin_label, process_claim
from auto_submit_clean_claims.helpers.scrub_checks import (
    check_clia,
    check_coverage,
    check_diagnoses,
    check_hospital_dates,
    check_line_items,
    check_patient,
    check_provider,
)


SECRETS = {
    "CANVAS_FHIR_CLIENT_ID": "test-client-id",
    "CANVAS_FHIR_CLIENT_SECRET": "test-client-secret",
}
ENVIRONMENT = {"CUSTOMER_IDENTIFIER": "testinstance"}


@pytest.fixture
def coding_queue():
    return ClaimQueueFactory(name="NeedsCodingReview", queue_sort_ordering=3)


@pytest.fixture
def submission_queue():
    return ClaimQueueFactory(name="QueuedForSubmission", queue_sort_ordering=4)


@pytest.fixture
def clean_claim(coding_queue):
    """A claim in the Coding queue with all valid provider/patient data and a line item."""
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
        clia_number="12D3456789",
    )
    li = ClaimLineItemFactory(claim=claim, proc_code="99213", units=1, charge=100.00)
    dx = ClaimDiagnosisCodeFactory(claim=claim, code="J06.9", rank=1)
    ClaimLineItemDiagnosisCodeFactory(line_item=li, code="J06.9", linked=True)
    return claim


def _make_handler(claim_id, event_type=EventType.CLAIM_CREATED):
    mock_event = MagicMock()
    mock_event.type = event_type
    mock_event.target.id = str(claim_id)
    handler = AutoSubmitCleanClaims(
        event=mock_event,
        secrets=SECRETS,
        environment=ENVIRONMENT,
    )
    return handler


# -- compute() tests --


def test_handler_responds_to_correct_events():
    assert EventType.Name(EventType.CLAIM_CREATED) in AutoSubmitCleanClaims.RESPONDS_TO
    assert EventType.Name(EventType.CLAIM_UPDATED) in AutoSubmitCleanClaims.RESPONDS_TO


def test_skips_claim_not_in_coding_queue():
    other_queue = ClaimQueueFactory(name="QueuedForSubmission", queue_sort_ordering=4)
    claim = ClaimFactory(current_queue=other_queue)
    handler = _make_handler(claim.id)
    effects = handler.compute()
    assert effects == []


@patch("auto_submit_clean_claims.handlers.auto_submit.FhirClient")
@patch("auto_submit_clean_claims.handlers.auto_submit.process_claim")
def test_clean_claim_moves_to_submission(mock_process, mock_fhir_cls, clean_claim, submission_queue):
    from canvas_sdk.effects.claim import ClaimEffect
    from canvas_sdk.v1.data.claim import ClaimQueues
    mock_process.return_value = [
        ClaimEffect(claim_id=str(clean_claim.id)).move_to_queue(ClaimQueues.QUEUED_FOR_SUBMISSION.label)
    ]
    handler = _make_handler(clean_claim.id)
    effects = handler.compute()
    assert len(effects) == 1
    assert effects[0].type == EffectType.MOVE_CLAIM_TO_QUEUE


@patch("auto_submit_clean_claims.handlers.auto_submit.FhirClient")
@patch("auto_submit_clean_claims.handlers.auto_submit.process_claim")
def test_claim_with_errors_adds_labels(mock_process, mock_fhir_cls, clean_claim):
    from canvas_sdk.effects.claim import ClaimEffect
    mock_process.return_value = [
        ClaimEffect(claim_id=str(clean_claim.id)).add_labels(["Missing Billing Provider Tax ID"])
    ]
    handler = _make_handler(clean_claim.id)
    effects = handler.compute()
    assert len(effects) == 1
    assert effects[0].type == EffectType.ADD_CLAIM_LABEL


# -- Label cleanup tests (test process_claim directly) --


def test_stale_static_label_removed_on_rerun(clean_claim, submission_queue):
    """A previously added static label is removed when it's no longer an error."""
    label = TaskLabelFactory(name="Missing Billing Provider Tax ID")
    ClaimLabelFactory(claim=clean_claim, label=label)
    fhir_client = MagicMock()
    with patch("auto_submit_clean_claims.helpers.claim_processor.scrub", return_value=[]):
        effects = process_claim(clean_claim, fhir_client)
    effect_types = [e.type for e in effects]
    assert EffectType.REMOVE_CLAIM_LABEL in effect_types
    assert EffectType.MOVE_CLAIM_TO_QUEUE in effect_types


def test_stale_dynamic_label_removed_on_rerun(clean_claim, submission_queue):
    """A previously added dynamic label (e.g. 'Charge 99213 has units < 1') is removed."""
    label = TaskLabelFactory(name="Charge 99213 has units < 1")
    ClaimLabelFactory(claim=clean_claim, label=label)
    fhir_client = MagicMock()
    with patch("auto_submit_clean_claims.helpers.claim_processor.scrub", return_value=[]):
        effects = process_claim(clean_claim, fhir_client)
    effect_types = [e.type for e in effects]
    assert EffectType.REMOVE_CLAIM_LABEL in effect_types


def test_non_plugin_labels_not_removed(clean_claim, submission_queue):
    """Labels not owned by this plugin are left alone."""
    label = TaskLabelFactory(name="Some Other Label")
    ClaimLabelFactory(claim=clean_claim, label=label)
    fhir_client = MagicMock()
    with patch("auto_submit_clean_claims.helpers.claim_processor.scrub", return_value=[]):
        effects = process_claim(clean_claim, fhir_client)
    effect_types = [e.type for e in effects]
    assert EffectType.REMOVE_CLAIM_LABEL not in effect_types


def test_stale_labels_removed_while_new_errors_added(clean_claim):
    """Old error label removed and new error label added in the same run."""
    old_label = TaskLabelFactory(name="Patient DOB missing")
    ClaimLabelFactory(claim=clean_claim, label=old_label)
    fhir_client = MagicMock()
    with patch("auto_submit_clean_claims.helpers.claim_processor.scrub", return_value=["Missing Billing Provider Tax ID"]):
        effects = process_claim(clean_claim, fhir_client)
    effect_types = [e.type for e in effects]
    assert EffectType.REMOVE_CLAIM_LABEL in effect_types
    assert EffectType.ADD_CLAIM_LABEL in effect_types


def test_no_duplicate_label_added(clean_claim):
    """If an error label already exists, it is not added again."""
    label = TaskLabelFactory(name="Missing Billing Provider Tax ID")
    ClaimLabelFactory(claim=clean_claim, label=label)
    fhir_client = MagicMock()
    with patch("auto_submit_clean_claims.helpers.claim_processor.scrub", return_value=["Missing Billing Provider Tax ID"]):
        effects = process_claim(clean_claim, fhir_client)
    effect_types = [e.type for e in effects]
    assert EffectType.ADD_CLAIM_LABEL not in effect_types


# -- is_plugin_label tests --


def test_is_plugin_label_static():
    assert is_plugin_label("Missing Billing Provider Tax ID") is True
    assert is_plugin_label("No diagnosis codes") is True


def test_is_plugin_label_dynamic():
    assert is_plugin_label("Charge 99213 has units < 1") is True
    assert is_plugin_label("Primary diagnosis V97.0 is an external cause code") is True


def test_is_plugin_label_unrelated():
    assert is_plugin_label("Some Other Label") is False
    assert is_plugin_label("Manual review needed") is False


# -- Provider scrub checks --


def test_missing_billing_provider_tax_id(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
    )
    assert "Missing Billing Provider Tax ID" in check_provider(provider)


def test_incorrect_billing_provider_tax_id(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="12345",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
    )
    assert "Incorrect Billing Provider Tax ID (must be 9 chars)" in check_provider(provider)


def test_missing_rendering_provider_tax_id(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
    )
    assert "Missing Rendering Provider Tax ID" in check_provider(provider)


def test_incorrect_rendering_provider_tax_id(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="123",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
    )
    assert "Incorrect Rendering Provider Tax ID (must be 9 chars)" in check_provider(provider)


def test_missing_billing_provider_npi(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="",
        provider_npi="0987654321",
    )
    assert "Missing Billing Provider Group NPI" in check_provider(provider)


def test_incorrect_billing_provider_npi(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="12345",
        provider_npi="0987654321",
    )
    assert "Incorrect Billing Provider Group NPI (must be 10 chars)" in check_provider(provider)


def test_missing_rendering_provider_npi(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="",
    )
    assert "Missing Rendering Provider NPI" in check_provider(provider)


def test_incorrect_rendering_provider_npi(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="123",
    )
    assert "Incorrect Rendering Provider NPI (must be 10 chars)" in check_provider(provider)


# -- Hospital dates --


def test_hospital_charges_missing_dates(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    provider = ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
        hosp_from_date="0000-00-00",
    )
    ClaimLineItemFactory(claim=claim, proc_code="99213", units=1, place_of_service="21")
    errors = check_hospital_dates(provider, claim.line_items.active())
    assert "Hospital inpatient charges require admit/discharge dates" in errors


# -- Patient checks --


def test_patient_address_incomplete(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimPatient.objects.create(
        claim=claim, addr1="", city="Boston", state="MA", zip="02101", dob="1990-01-01",
    )
    assert "Patient address incomplete" in check_patient(claim)


def test_patient_dob_missing(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimPatient.objects.create(
        claim=claim, addr1="123 Main", city="Boston", state="MA", zip="02101", dob="0000-00-00",
    )
    assert "Patient DOB missing" in check_patient(claim)


def test_workers_comp_missing_ssn(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue, auto_accident=True)
    ClaimPatient.objects.create(
        claim=claim, addr1="123 Main", city="Boston", state="MA", zip="02101",
        dob="1990-01-01", ssn="",
    )
    assert "Workers Comp/Auto claim missing patient SSN" in check_patient(claim)


# -- Coverage checks --


def test_missing_coverage_policy_id(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    coverage = CoverageFactory(
        coverage_start_date=date(2020, 1, 1),
        coverage_end_date=None,
        stack=CoverageStack.IN_USE,
    )
    claim_coverage = ClaimCoverageFactory(claim=claim, coverage=coverage, subscriber_number="", active=True)
    assert "Missing coverage policy ID" in check_coverage(claim, claim_coverage)


def test_missing_subscriber_address_for_non_self(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    coverage = CoverageFactory(
        coverage_start_date=date(2020, 1, 1),
        coverage_end_date=None,
        stack=CoverageStack.IN_USE,
    )
    claim_coverage = ClaimCoverageFactory(
        claim=claim,
        coverage=coverage,
        subscriber_number="ABC123",
        patient_relationship_to_subscriber="child",
        subscriber_addr1="",
        subscriber_city="",
        subscriber_state="",
        subscriber_zip="",
        active=True,
    )
    assert "Missing subscriber address for non-self subscriber" in check_coverage(claim, claim_coverage)


# -- Line item checks --


def test_no_service_charges(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    assert "No service charges on claim" in check_line_items(claim, claim.line_items.active())


def test_zero_total_charges(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimLineItemFactory(claim=claim, proc_code="99213", units=1, charge=0.00)
    assert "Total billed amount is $0" in check_line_items(claim, claim.line_items.active())


def test_line_item_units_less_than_one(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimLineItemFactory(claim=claim, proc_code="99213", units=0, charge=100.00)
    assert "Charge 99213 has units < 1" in check_line_items(claim, claim.line_items.active())


def test_ndc_code_missing_dosage(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimLineItemFactory(
        claim=claim,
        proc_code="J1234",
        units=1,
        charge=100.00,
        ndc_code="12345678901",
        ndc_dosage="",
        ndc_measure="",
    )
    assert "Charge J1234 has NDC code but missing dosage/measure" in check_line_items(claim, claim.line_items.active())


# -- Diagnosis checks --


def test_no_diagnosis_codes(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimLineItemFactory(claim=claim, proc_code="99213", units=1, charge=100.00)
    assert "No diagnosis codes" in check_diagnoses(claim, claim.line_items.active())


def test_charge_missing_diagnosis_pointer(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimLineItemFactory(claim=claim, proc_code="99213", units=1, charge=100.00)
    ClaimDiagnosisCodeFactory(claim=claim, code="J06.9", rank=1)
    # No ClaimLineItemDiagnosisCode linking li to the dx
    assert "Charge 99213 missing diagnosis pointer" in check_diagnoses(claim, claim.line_items.active())


def test_duplicate_diagnosis_codes(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimDiagnosisCodeFactory(claim=claim, code="J06.9", rank=1)
    ClaimDiagnosisCodeFactory(claim=claim, code="J06.9", rank=2)
    assert "Duplicate diagnosis codes" in check_diagnoses(claim, claim.line_items.active())


def test_primary_diagnosis_external_cause_code(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimDiagnosisCodeFactory(claim=claim, code="V97.0", rank=1)
    assert "Primary diagnosis V97.0 is an external cause code" in check_diagnoses(claim, claim.line_items.active())


# -- FHIR-based checks --


def test_clia_check_skipped_when_clia_present(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
        clia_number="12D3456789",
    )
    ClaimLineItemFactory(claim=claim, proc_code="80053", units=1, charge=50.00)
    fhir_client = MagicMock()
    errors = check_clia(fhir_client, claim, claim.provider, claim.line_items.active())
    assert errors == []
    fhir_client.read.assert_not_called()


def test_clia_check_skipped_when_no_lab_charges(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
        clia_number="",
    )
    ClaimLineItemFactory(claim=claim, proc_code="99213", units=1, charge=100.00)
    fhir_client = MagicMock()
    errors = check_clia(fhir_client, claim, claim.provider, claim.line_items.active())
    assert errors == []
    fhir_client.read.assert_not_called()


def test_clia_check_catches_qw_modifier(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
        clia_number="",
    )
    ClaimLineItemFactory(claim=claim, proc_code="80053", units=1, charge=50.00)
    fhir_client = MagicMock()
    fhir_client.read.return_value = {
        "item": [
            {
                "productOrService": {"coding": [{"code": "80053"}]},
                "modifier": [{"coding": [{"code": "QW"}]}],
            }
        ]
    }
    errors = check_clia(fhir_client, claim, claim.provider, claim.line_items.active())
    assert errors == ["Lab charges with QW modifier but missing CLIA#"]


def test_clia_check_passes_without_qw_modifier(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    ClaimProviderFactory(
        claim=claim,
        billing_provider_tax_id="123456789",
        provider_tax_id="987654321",
        billing_provider_npi="1234567890",
        provider_npi="0987654321",
        clia_number="",
    )
    ClaimLineItemFactory(claim=claim, proc_code="80053", units=1, charge=50.00)
    fhir_client = MagicMock()
    fhir_client.read.return_value = {
        "item": [
            {
                "productOrService": {"coding": [{"code": "80053"}]},
                "modifier": [],
            }
        ]
    }
    errors = check_clia(fhir_client, claim, claim.provider, claim.line_items.active())
    assert errors == []


# -- Coverage active checks --


def test_coverage_not_active_out_of_date_range(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    coverage = CoverageFactory(
        coverage_start_date=date(2020, 1, 1),
        coverage_end_date=date(2020, 12, 31),
    )
    claim_coverage = ClaimCoverageFactory(
        claim=claim, coverage=coverage, subscriber_number="ABC123", active=True
    )
    errors = check_coverage(claim, claim_coverage)
    assert errors == ["Coverage is not active for this date of service"]


def test_coverage_not_active_wrong_stack(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    coverage = CoverageFactory(
        coverage_start_date=date(2020, 1, 1),
        coverage_end_date=None,
        stack=CoverageStack.REMOVED,
    )
    claim_coverage = ClaimCoverageFactory(
        claim=claim, coverage=coverage, subscriber_number="ABC123", active=True
    )
    errors = check_coverage(claim, claim_coverage)
    assert errors == ["Coverage is not active for this date of service"]


def test_coverage_active_in_range_and_in_use(coding_queue):
    claim = ClaimFactory(current_queue=coding_queue)
    coverage = CoverageFactory(
        coverage_start_date=date(2020, 1, 1),
        coverage_end_date=None,
        stack=CoverageStack.IN_USE,
    )
    claim_coverage = ClaimCoverageFactory(
        claim=claim, coverage=coverage, subscriber_number="ABC123", active=True
    )
    errors = check_coverage(claim, claim_coverage)
    assert errors == []


# -- Cron handler tests --


def _make_cron_handler():
    mock_event = MagicMock()
    mock_event.type = EventType.CRON
    mock_event.target.id = "2026-03-06T12:05:00+00:00"
    handler = SweepCodingQueue(
        event=mock_event,
        secrets=SECRETS,
        environment=ENVIRONMENT,
    )
    return handler


@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.FhirClient")
def test_cron_skips_when_no_claims_in_coding_queue(mock_fhir_cls):
    handler = _make_cron_handler()
    effects = handler.execute()
    assert effects == []
    mock_fhir_cls.assert_not_called()


@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.FhirClient")
@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.process_claim")
def test_cron_moves_clean_claim(mock_process, mock_fhir_cls, clean_claim, submission_queue):
    from canvas_sdk.effects.claim import ClaimEffect
    from canvas_sdk.v1.data.claim import ClaimQueues
    mock_process.return_value = [
        ClaimEffect(claim_id=str(clean_claim.id)).move_to_queue(ClaimQueues.QUEUED_FOR_SUBMISSION.label)
    ]
    handler = _make_cron_handler()
    effects = handler.execute()
    assert any(e.type == EffectType.MOVE_CLAIM_TO_QUEUE for e in effects)


@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.FhirClient")
@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.process_claim")
def test_cron_labels_claim_with_errors(mock_process, mock_fhir_cls, clean_claim):
    from canvas_sdk.effects.claim import ClaimEffect
    mock_process.return_value = [
        ClaimEffect(claim_id=str(clean_claim.id)).add_labels(["Patient DOB missing"])
    ]
    handler = _make_cron_handler()
    effects = handler.execute()
    assert any(e.type == EffectType.ADD_CLAIM_LABEL for e in effects)
    assert not any(e.type == EffectType.MOVE_CLAIM_TO_QUEUE for e in effects)


@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.FhirClient")
@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.process_claim")
def test_cron_processes_multiple_claims(mock_process, mock_fhir_cls, coding_queue, submission_queue):
    from canvas_sdk.effects.claim import ClaimEffect
    from canvas_sdk.v1.data.claim import ClaimQueues
    claim1 = ClaimFactory(current_queue=coding_queue)
    claim2 = ClaimFactory(current_queue=coding_queue)
    mock_process.side_effect = lambda claim, fhir: [
        ClaimEffect(claim_id=str(claim.id)).move_to_queue(ClaimQueues.QUEUED_FOR_SUBMISSION.label)
    ]
    handler = _make_cron_handler()
    effects = handler.execute()
    move_effects = [e for e in effects if e.type == EffectType.MOVE_CLAIM_TO_QUEUE]
    assert len(move_effects) == 2


@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.FhirClient")
@patch("auto_submit_clean_claims.handlers.sweep_coding_queue.process_claim")
def test_cron_removes_stale_labels(mock_process, mock_fhir_cls, clean_claim, submission_queue):
    from canvas_sdk.effects.claim import ClaimEffect
    mock_process.return_value = [
        ClaimEffect(claim_id=str(clean_claim.id)).remove_labels(["Patient DOB missing"]),
        ClaimEffect(claim_id=str(clean_claim.id)).move_to_queue("QueuedForSubmission"),
    ]
    handler = _make_cron_handler()
    effects = handler.execute()
    assert any(e.type == EffectType.REMOVE_CLAIM_LABEL for e in effects)


def test_cron_schedule():
    assert SweepCodingQueue.SCHEDULE == "0 */5 * * *"
