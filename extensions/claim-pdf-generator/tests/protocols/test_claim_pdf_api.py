"""Tests for claim_pdf_generator.protocols.claim_pdf_api."""

from decimal import Decimal
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from claim_pdf_generator.protocols.claim_pdf_api import (
    ClaimPdfAPI,
    _build_claim_context,
    _load_template,
    _render_template,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_claim():
    """A minimal mock Claim with all expected relationships."""
    claim = MagicMock()
    claim.id = "claim-abc-123"
    claim.prior_auth = "PA-999"
    claim.accept_assign = True
    claim.auto_accident = False
    claim.auto_accident_state = ""
    claim.employment_related = False
    claim.other_accident = False
    claim.illness_date = None
    claim.narrative = ""
    claim.account_number = "ACCT-001"
    claim.total_charges = Decimal("150.00")
    claim.total_paid = Decimal("0.00")
    claim.balance = Decimal("150.00")

    # patient OneToOne
    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.middle_name = ""
    patient.dob = "1985-03-15"
    patient.sex = "F"
    patient.ssn = "123-45-6789"
    patient.addr1 = "123 Main St"
    patient.addr2 = ""
    patient.city = "Springfield"
    patient.state = "IL"
    patient.zip = "62701"
    patient.phone = "555-555-5555"
    claim.patient = patient

    # provider OneToOne
    provider = MagicMock()
    provider.billing_provider_name = "Acme Medical"
    provider.billing_provider_npi = "1234567890"
    provider.billing_provider_tax_id = "12-3456789"
    provider.billing_provider_tax_id_type = "E"
    provider.billing_provider_addr1 = "500 Provider Way"
    provider.billing_provider_addr2 = ""
    provider.billing_provider_city = "Springfield"
    provider.billing_provider_state = "IL"
    provider.billing_provider_zip = "62701"
    provider.billing_provider_phone = "555-111-2222"
    provider.provider_first_name = "Alice"
    provider.provider_last_name = "Smith"
    provider.provider_middle_name = ""
    provider.provider_npi = "9876543210"
    provider.referring_provider_first_name = ""
    provider.referring_provider_last_name = ""
    provider.referring_provider_middle_name = ""
    provider.referring_provider_npi = "0"
    provider.referring_provider_ptan_identifier = ""
    provider.facility_name = ""
    provider.facility_npi = "0"
    provider.facility_addr1 = ""
    provider.facility_addr2 = ""
    provider.facility_city = ""
    provider.facility_state = ""
    provider.facility_zip = ""
    provider.hosp_from_date = "0000-00-00"
    provider.hosp_to_date = "0000-00-00"
    claim.provider = provider

    # coverages queryset
    primary_cov = MagicMock()
    primary_cov.payer_name = "Blue Cross"
    primary_cov.subscriber_number = "BCBS-001"
    primary_cov.subscriber_first_name = "Jane"
    primary_cov.subscriber_last_name = "Doe"
    primary_cov.subscriber_middle_name = ""
    primary_cov.subscriber_group = "GRP-100"
    primary_cov.subscriber_plan = "PPO Gold"
    primary_cov.subscriber_dob = "1985-03-15"
    primary_cov.subscriber_sex = "F"
    primary_cov.subscriber_addr1 = "123 Main St"
    primary_cov.subscriber_addr2 = ""
    primary_cov.subscriber_city = "Springfield"
    primary_cov.subscriber_state = "IL"
    primary_cov.subscriber_zip = "62701"
    primary_cov.subscriber_phone = "555-555-5555"
    primary_cov.patient_relationship_to_subscriber = "18"
    primary_cov.payer_plan_type = "HM"
    primary_cov.resubmission_code = ""
    primary_cov.payer_addr1 = ""
    primary_cov.payer_addr2 = ""
    primary_cov.payer_city = ""
    primary_cov.payer_state = ""
    primary_cov.payer_zip = ""

    coverage_qs = MagicMock()
    coverage_qs.filter.return_value.first.side_effect = lambda: (
        primary_cov
        if coverage_qs.filter.call_args and "Primary" in str(coverage_qs.filter.call_args)
        else None
    )
    claim.coverages = coverage_qs

    # line items
    line_item = MagicMock()
    line_item.proc_code = "99213"
    line_item.display = "Office Visit"
    line_item.from_date = "2024-01-15"
    line_item.thru_date = "2024-01-15"
    line_item.place_of_service = "11"
    line_item.units = 1
    line_item.charge = Decimal("150.00")
    line_item.billing_line_item_id = "bli-001"
    line_item.billing_line_item.modifiers.values_list.return_value = ["25"]
    line_item.diagnosis_codes.filter.return_value.values_list.return_value = [1]
    line_item.ndc_code = ""
    line_item.ndc_dosage = ""
    line_item.ndc_measure = ""
    line_item.narrative = ""
    claim.get_active_claim_line_items.return_value = [line_item]

    # diagnosis codes
    dx = MagicMock()
    dx.rank = 1
    dx.code = "Z00.00"
    dx.display = "Encounter for general adult medical examination"
    claim.diagnosis_codes.order_by.return_value = [dx]

    # note
    note = MagicMock()
    note.datetime_of_service = "2024-01-15"
    claim.note = note

    return claim


@pytest.fixture
def mock_request():
    """A minimal mock request object."""
    request = MagicMock()
    request.path_params = {"claim_id": "claim-abc-123"}
    request.query_params = {}
    return request


@pytest.fixture
def api_handler(mock_request):
    """ClaimPdfAPI instance with mocked request and secrets."""
    handler = ClaimPdfAPI.__new__(ClaimPdfAPI)
    handler.request = mock_request
    handler.secrets = {"simpleapi-api-key": "test-api-key-secret"}
    return handler


# ---------------------------------------------------------------------------
# _load_template
# ---------------------------------------------------------------------------


def test_load_template_superbill():
    """_load_template returns non-empty string for superbill.html."""
    content = _load_template("superbill.html")
    assert "superbill" in content.lower() or "SUPERBILL" in content


def test_load_template_hcfa():
    """_load_template returns non-empty string for hcfa.html."""
    content = _load_template("hcfa.html")
    assert "CMS-1500" in content or "hcfa" in content.lower() or "HCFA" in content


def test_load_template_missing_raises():
    """_load_template raises FileNotFoundError for unknown template."""
    with pytest.raises(FileNotFoundError):
        _load_template("nonexistent.html")


# ---------------------------------------------------------------------------
# _render_template
# ---------------------------------------------------------------------------


def test_render_template_interpolates_context():
    """_render_template substitutes context values into the template."""
    template_str = "<p>Hello {{ name }}</p>"
    result = _render_template(template_str, {"name": "World"})
    assert result == "<p>Hello World</p>"


def test_render_template_empty_context():
    """_render_template handles empty context without error."""
    template_str = "<p>No vars</p>"
    result = _render_template(template_str, {})
    assert result == "<p>No vars</p>"


# ---------------------------------------------------------------------------
# _build_claim_context
# ---------------------------------------------------------------------------


def test_build_claim_context_keys(mock_claim):
    """_build_claim_context returns all expected top-level keys."""
    ctx = _build_claim_context(mock_claim)

    assert set(ctx.keys()) == {
        "claim",
        "patient",
        "provider",
        "primary_coverage",
        "secondary_coverage",
        "line_items",
        "diagnosis_codes",
        "note",
        "total_charges",
        "total_paid",
        "balance",
    }


def test_build_claim_context_line_items_enriched(mock_claim):
    """Enriched line items contain expected keys with correct values."""
    ctx = _build_claim_context(mock_claim)

    items = ctx["line_items"]
    assert len(items) == 1
    item = items[0]
    assert item["proc_code"] == "99213"
    assert item["units"] == 1
    assert item["modifiers"] == ["25"]
    assert item["diag_pointers"] == [1]


def test_build_claim_context_no_billing_line_item(mock_claim):
    """Line items without billing_line_item_id get empty modifiers list."""
    line_item = mock_claim.get_active_claim_line_items.return_value[0]
    line_item.billing_line_item_id = None

    ctx = _build_claim_context(mock_claim)
    assert ctx["line_items"][0]["modifiers"] == []


def test_build_claim_context_diagnosis_codes(mock_claim):
    """Diagnosis codes list is populated from claim.diagnosis_codes."""
    ctx = _build_claim_context(mock_claim)
    assert len(ctx["diagnosis_codes"]) == 1
    assert ctx["diagnosis_codes"][0].code == "Z00.00"


def test_build_claim_context_financials(mock_claim):
    """Financial totals are forwarded from claim properties."""
    ctx = _build_claim_context(mock_claim)
    assert ctx["total_charges"] == Decimal("150.00")
    assert ctx["total_paid"] == Decimal("0.00")
    assert ctx["balance"] == Decimal("150.00")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_authenticate_valid_key(api_handler):
    """authenticate returns True when the provided key matches the secret."""
    from canvas_sdk.handlers.simple_api import APIKeyCredentials

    credentials = APIKeyCredentials.__new__(APIKeyCredentials)
    credentials.key = "test-api-key-secret"

    result = api_handler.authenticate(credentials)

    assert result is True


def test_authenticate_invalid_key(api_handler):
    """authenticate raises InvalidCredentialsError when the key does not match."""
    from canvas_sdk.handlers.simple_api import APIKeyCredentials

    credentials = APIKeyCredentials.__new__(APIKeyCredentials)
    credentials.key = "wrong-key"

    with pytest.raises(InvalidCredentialsError):
        api_handler.authenticate(credentials)


# ---------------------------------------------------------------------------
# _generate_pdf: claim not found
# ---------------------------------------------------------------------------


def test_generate_pdf_claim_not_found(api_handler):
    """Returns 404 JSON when claim does not exist."""
    with patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = None

        result = api_handler._generate_pdf("missing-id", "superbill", "superbill.html")

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.NOT_FOUND

    assert mock_claim_cls.mock_calls == [
        call.objects.filter(id="missing-id"),
        call.objects.filter().first(),
    ]
    assert mock_log.mock_calls == [call.warning("[ClaimPdfAPI] Claim not found: missing-id")]


# ---------------------------------------------------------------------------
# _generate_pdf: PDF generation failure
# ---------------------------------------------------------------------------


def test_generate_pdf_pdf_service_failure(api_handler, mock_claim):
    """Returns 500 JSON when pdf_generator.from_html returns None."""
    with patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._build_claim_context"
    ) as mock_build_ctx, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._load_template"
    ) as mock_load, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._render_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_build_ctx.return_value = {}
        mock_load.return_value = "<html/>"
        mock_render.return_value = "<html/>"
        mock_pdf_gen.from_html.return_value = None

        result = api_handler._generate_pdf("claim-abc-123", "superbill", "superbill.html")

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # from_html returns None so no __bool__() is called on a mock object
    assert mock_pdf_gen.mock_calls == [call.from_html(content="<html/>")]
    assert mock_log.mock_calls == [
        call.error("[ClaimPdfAPI] PDF generation failed for claim claim-abc-123")
    ]


def test_generate_pdf_pdf_url_empty(api_handler, mock_claim):
    """Returns 500 JSON when pdf response has an empty URL."""
    with patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._build_claim_context"
    ) as mock_build_ctx, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._load_template"
    ) as mock_load, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._render_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_build_ctx.return_value = {}
        mock_load.return_value = "<html/>"
        mock_render.return_value = "<html/>"

        pdf_resp = MagicMock()
        pdf_resp.url = ""  # empty url → falsy
        mock_pdf_gen.from_html.return_value = pdf_resp

        result = api_handler._generate_pdf("claim-abc-123", "superbill", "superbill.html")

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # from_html is called; pdf_resp is a truthy MagicMock so __bool__() appears,
    # then url="" is falsy so execution enters the failure branch
    assert mock_pdf_gen.mock_calls == [
        call.from_html(content="<html/>"),
        call.from_html().__bool__(),
    ]
    assert mock_log.mock_calls == [
        call.error("[ClaimPdfAPI] PDF generation failed for claim claim-abc-123")
    ]


# ---------------------------------------------------------------------------
# _generate_pdf: format=url (default)
# ---------------------------------------------------------------------------


def test_generate_pdf_format_url_default(api_handler, mock_claim):
    """Returns JSON with pdf_url when format query param is absent (defaults to url)."""
    api_handler.request.query_params = {}

    with patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._build_claim_context"
    ) as mock_build_ctx, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._load_template"
    ) as mock_load, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._render_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_build_ctx.return_value = {}
        mock_load.return_value = "<html/>"
        mock_render.return_value = "<html/>"

        pdf_resp = MagicMock()
        pdf_resp.url = "https://s3.example.com/claim-abc-123.pdf"
        mock_pdf_gen.from_html.return_value = pdf_resp

        result = api_handler._generate_pdf("claim-abc-123", "superbill", "superbill.html")

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    # JSONResponse body should contain pdf_url, claim_id, form_type
    body = response.body if hasattr(response, "body") else response.content
    body_str = body.decode() if isinstance(body, bytes) else str(body)
    assert "pdf_url" in body_str
    assert "claim-abc-123" in body_str
    assert "superbill" in body_str

    # from_html called; MagicMock return value is truthy so __bool__() is also called
    assert mock_pdf_gen.mock_calls == [
        call.from_html(content="<html/>"),
        call.from_html().__bool__(),
    ]
    assert mock_log.mock_calls == []


def test_generate_pdf_format_url_explicit(api_handler, mock_claim):
    """Returns JSON with pdf_url when format=url is explicitly provided."""
    api_handler.request.query_params = {"format": "url"}

    with patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._build_claim_context"
    ) as mock_build_ctx, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._load_template"
    ) as mock_load, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._render_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_build_ctx.return_value = {}
        mock_load.return_value = "<html/>"
        mock_render.return_value = "<html/>"

        pdf_resp = MagicMock()
        pdf_resp.url = "https://s3.example.com/claim-abc-123.pdf"
        mock_pdf_gen.from_html.return_value = pdf_resp

        result = api_handler._generate_pdf("claim-abc-123", "hcfa", "hcfa.html")

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK

    assert mock_pdf_gen.mock_calls == [
        call.from_html(content="<html/>"),
        call.from_html().__bool__(),
    ]
    assert mock_log.mock_calls == []


# ---------------------------------------------------------------------------
# _generate_pdf: format=pdf (raw bytes)
# ---------------------------------------------------------------------------


def test_generate_pdf_format_pdf_returns_bytes(api_handler, mock_claim):
    """Returns application/pdf Response with raw bytes when format=pdf."""
    api_handler.request.query_params = {"format": "pdf"}

    mock_raw_response = MagicMock()
    mock_raw_response.content = b"%PDF-1.4 fake-bytes"

    with patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._build_claim_context"
    ) as mock_build_ctx, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._load_template"
    ) as mock_load, patch(
        "claim_pdf_generator.protocols.claim_pdf_api._render_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.Http"
    ) as mock_http_cls, patch(
        "claim_pdf_generator.protocols.claim_pdf_api.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_build_ctx.return_value = {}
        mock_load.return_value = "<html/>"
        mock_render.return_value = "<html/>"

        pdf_resp = MagicMock()
        pdf_resp.url = "https://s3.example.com/claim-abc-123.pdf"
        mock_pdf_gen.from_html.return_value = pdf_resp

        mock_http_cls.return_value.get.return_value = mock_raw_response

        result = api_handler._generate_pdf("claim-abc-123", "superbill", "superbill.html")

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    # Verify content-type header
    assert response.headers.get("Content-Type") == "application/pdf"
    assert response.content == b"%PDF-1.4 fake-bytes"

    assert mock_pdf_gen.mock_calls == [
        call.from_html(content="<html/>"),
        call.from_html().__bool__(),
    ]
    assert mock_http_cls.mock_calls == [
        call(),
        call().get("https://s3.example.com/claim-abc-123.pdf"),
    ]
    assert mock_log.mock_calls == []


# ---------------------------------------------------------------------------
# superbill and hcfa endpoint routing
# ---------------------------------------------------------------------------


def test_superbill_endpoint_calls_generate_pdf(api_handler):
    """superbill() calls _generate_pdf with form_type=superbill and correct template."""
    api_handler.request.path_params = {"claim_id": "claim-abc-123"}

    with patch.object(api_handler, "_generate_pdf") as mock_gen:
        mock_gen.return_value = [MagicMock()]
        api_handler.superbill()

    assert mock_gen.mock_calls == [
        call("claim-abc-123", form_type="superbill", template="superbill.html")
    ]


def test_hcfa_endpoint_calls_generate_pdf(api_handler):
    """hcfa() calls _generate_pdf with form_type=hcfa and correct template."""
    api_handler.request.path_params = {"claim_id": "claim-abc-123"}

    with patch.object(api_handler, "_generate_pdf") as mock_gen:
        mock_gen.return_value = [MagicMock()]
        api_handler.hcfa()

    assert mock_gen.mock_calls == [
        call("claim-abc-123", form_type="hcfa", template="hcfa.html")
    ]


# ---------------------------------------------------------------------------
# End-to-end render: templates render without errors
# ---------------------------------------------------------------------------


def _make_template_context() -> dict:
    """Build a real-data context dict suitable for Django template rendering."""
    dx = SimpleNamespace(rank=1, code="Z00.00", display="General exam")
    line_item = {
        "proc_code": "99213",
        "display": "Office Visit",
        "from_date": "2024-01-15",
        "thru_date": "2024-01-15",
        "place_of_service": "11",
        "units": 1,
        "charge": Decimal("150.00"),
        "modifiers": ["25"],
        "diag_pointers": [1],
        "ndc_code": "",
        "ndc_dosage": "",
        "ndc_measure": "",
        "narrative": "",
    }
    patient = SimpleNamespace(
        first_name="Jane",
        last_name="Doe",
        middle_name="",
        dob="1985-03-15",
        sex="F",
        ssn="123-45-6789",
        addr1="123 Main St",
        addr2="",
        city="Springfield",
        state="IL",
        zip="62701",
        phone="555-5555",
    )
    provider = SimpleNamespace(
        billing_provider_name="Acme Medical",
        billing_provider_npi="1234567890",
        billing_provider_tax_id="12-3456789",
        billing_provider_tax_id_type="E",
        billing_provider_addr1="500 Provider Way",
        billing_provider_addr2="",
        billing_provider_city="Springfield",
        billing_provider_state="IL",
        billing_provider_zip="62701",
        billing_provider_phone="555-111-2222",
        billing_provider_id="",
        provider_first_name="Alice",
        provider_last_name="Smith",
        provider_middle_name="",
        provider_npi="9876543210",
        referring_provider_first_name="",
        referring_provider_last_name="",
        referring_provider_middle_name="",
        referring_provider_npi="0",
        referring_provider_ptan_identifier="",
        facility_name="",
        facility_npi="0",
        facility_addr1="",
        facility_addr2="",
        facility_city="",
        facility_state="",
        facility_zip="",
        hosp_from_date="0000-00-00",
        hosp_to_date="0000-00-00",
    )
    primary_coverage = SimpleNamespace(
        payer_name="Blue Cross",
        subscriber_number="BCBS-001",
        subscriber_first_name="Jane",
        subscriber_last_name="Doe",
        subscriber_middle_name="",
        subscriber_group="GRP-100",
        subscriber_plan="PPO Gold",
        subscriber_dob="1985-03-15",
        subscriber_sex="F",
        subscriber_addr1="123 Main St",
        subscriber_addr2="",
        subscriber_city="Springfield",
        subscriber_state="IL",
        subscriber_zip="62701",
        subscriber_phone="555-5555",
        patient_relationship_to_subscriber="18",
        payer_plan_type="HM",
        resubmission_code="",
    )
    claim = SimpleNamespace(
        id="claim-abc-123",
        prior_auth="PA-999",
        accept_assign=True,
        auto_accident=False,
        auto_accident_state="",
        employment_related=False,
        other_accident=False,
        illness_date=None,
        narrative="",
        account_number="ACCT-001",
        total_charges=Decimal("150.00"),
    )
    note = SimpleNamespace(datetime_of_service="2024-01-15")
    return {
        "claim": claim,
        "patient": patient,
        "provider": provider,
        "primary_coverage": primary_coverage,
        "secondary_coverage": None,
        "line_items": [line_item],
        "diagnosis_codes": [dx],
        "note": note,
        "total_charges": Decimal("150.00"),
        "total_paid": Decimal("0.00"),
        "balance": Decimal("150.00"),
    }


def test_superbill_renders_with_real_template():
    """superbill.html renders without exception given a full context."""
    ctx = _make_template_context()
    template_str = _load_template("superbill.html")
    html = _render_template(template_str, ctx)
    assert "SUPERBILL" in html
    assert "99213" in html
    assert "Z00.00" in html


def test_hcfa_renders_with_real_template():
    """hcfa.html renders without exception given a full context."""
    ctx = _make_template_context()
    template_str = _load_template("hcfa.html")
    html = _render_template(template_str, ctx)
    assert "CMS-1500" in html
    assert "HEALTH INSURANCE CLAIM FORM" in html
    assert "99213" in html


def test_superbill_renders_minimal_claim():
    """superbill.html renders without crashing when optional fields are absent."""
    bare_claim = MagicMock()
    bare_claim.id = "bare-claim"
    bare_claim.prior_auth = ""
    bare_claim.accept_assign = False
    bare_claim.auto_accident = False
    bare_claim.auto_accident_state = ""
    bare_claim.employment_related = False
    bare_claim.other_accident = False
    bare_claim.illness_date = None
    bare_claim.narrative = ""
    bare_claim.account_number = ""
    bare_claim.total_charges = Decimal("0.00")
    bare_claim.total_paid = Decimal("0.00")
    bare_claim.balance = Decimal("0.00")
    # No patient / provider / note
    del bare_claim.patient
    del bare_claim.provider
    bare_claim.note = None
    bare_claim.coverages.filter.return_value.first.return_value = None
    bare_claim.get_active_claim_line_items.return_value = []
    bare_claim.diagnosis_codes.order_by.return_value = []

    # getattr falls back to None for missing attributes
    ctx = _build_claim_context(bare_claim)
    assert ctx["patient"] is None
    assert ctx["provider"] is None
    assert ctx["line_items"] == []

    template_str = _load_template("superbill.html")
    # Should not raise
    html = _render_template(template_str, ctx)
    assert "<html" in html
