"""Tests for AccessOperationsApi — GET modals and POST submissions.

Key changes tested here:
- Flat payload: check_eligibility / align / unalign now receive mbi, payer_id, track directly
- Eligibility modal and submit now require track in the request body
- payer_id lookup order: coverage.issuer.payer_id → ACCESS_DEFAULT_PAYER_ID secret → 422 fail-closed
- unalign pulls track from the stored ACCESSAlignment record, not the request
"""
import json
import pytest
from http import HTTPStatus
from unittest.mock import MagicMock, patch


def _make_handler(secrets=None, request_body=None, query_params=None):
    from cms_access_fhir_client.api.operations_api import AccessOperationsApi
    handler = AccessOperationsApi.__new__(AccessOperationsApi)
    handler.secrets = secrets or {}
    mock_request = MagicMock()
    mock_request.json.return_value = request_body or {}
    mock_request.query_params.get = lambda key, default=None: (query_params or {}).get(key, default)
    handler.request = mock_request
    return handler, mock_request


def _make_mock_patient(patient_id="p-123", first_name="Jane", last_name="Doe", birth_date=None):
    patient = MagicMock()
    patient.id = patient_id
    patient.first_name = first_name
    patient.last_name = last_name
    patient.birth_date = birth_date
    return patient


def _make_mock_coverage(mbi="1EG4-TE5-MK72", issuer_name="IL Medicare Part B", dbid=99, payer_id=None):
    coverage = MagicMock()
    coverage.id_number = mbi
    coverage.dbid = dbid
    coverage.issuer = MagicMock()
    coverage.issuer.name = issuer_name
    coverage.issuer.payer_id = payer_id  # None by default — simulates unpopulated Transactor
    return coverage


class TestEligibilityModalGet:
    def test_returns_html_when_patient_id_present(self):
        from canvas_sdk.effects.simple_api import HTMLResponse
        handler, _ = _make_handler(query_params={"patient_id": "p-123"})
        effects = handler.eligibility_modal()

        assert len(effects) == 1
        assert isinstance(effects[0], HTMLResponse)

    def test_eligibility_html_contains_track_selector(self):
        """The eligibility modal HTML must include a track <select> (required by CMS)."""
        from canvas_sdk.effects.simple_api import HTMLResponse
        handler, _ = _make_handler(query_params={"patient_id": "p-123"})
        effects = handler.eligibility_modal()

        assert isinstance(effects[0], HTMLResponse)
        content = effects[0].content.decode() if isinstance(effects[0].content, bytes) else effects[0].content
        assert 'id="track"' in content
        assert 'required' in content
        assert 'eCKM' in content

    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(query_params={})
        effects = handler.eligibility_modal()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST


class TestAlignModalGet:
    def test_returns_html_when_patient_id_present(self):
        from canvas_sdk.effects.simple_api import HTMLResponse
        handler, _ = _make_handler(query_params={"patient_id": "p-123"})
        effects = handler.align_modal()

        assert len(effects) == 1
        assert isinstance(effects[0], HTMLResponse)

    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(query_params={})
        effects = handler.align_modal()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST


class TestUnalignModalGet:
    def test_returns_html_when_patient_id_present(self):
        from canvas_sdk.effects.simple_api import HTMLResponse
        handler, _ = _make_handler(query_params={"patient_id": "p-123"})
        effects = handler.unalign_modal()

        assert len(effects) == 1
        assert isinstance(effects[0], HTMLResponse)

    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(query_params={})
        effects = handler.unalign_modal()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST


class TestGetPayerId:
    """Tests for the _get_payer_id helper: coverage → secret → None."""

    def test_returns_coverage_payer_id_when_populated(self):
        from cms_access_fhir_client.api.operations_api import _get_payer_id
        coverage = _make_mock_coverage(payer_id="payer-from-transactor")
        result = _get_payer_id(coverage, secrets={})
        assert result == "payer-from-transactor"

    def test_falls_back_to_secret_when_transactor_empty(self):
        from cms_access_fhir_client.api.operations_api import _get_payer_id
        coverage = _make_mock_coverage(payer_id=None)
        coverage.issuer.payer_id = ""  # explicitly empty
        result = _get_payer_id(coverage, secrets={"ACCESS_DEFAULT_PAYER_ID": "secret-payer"})
        assert result == "secret-payer"

    def test_transactor_wins_over_secret(self):
        """Coverage.issuer.payer_id takes precedence over the secret."""
        from cms_access_fhir_client.api.operations_api import _get_payer_id
        coverage = _make_mock_coverage(payer_id="transactor-payer")
        result = _get_payer_id(coverage, secrets={"ACCESS_DEFAULT_PAYER_ID": "secret-payer"})
        assert result == "transactor-payer"

    def test_returns_none_when_both_absent(self):
        from cms_access_fhir_client.api.operations_api import _get_payer_id
        coverage = _make_mock_coverage(payer_id=None)
        coverage.issuer.payer_id = ""
        result = _get_payer_id(coverage, secrets={})
        assert result is None


class TestSubmitEligibility:
    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(request_body={})
        effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_when_no_track(self):
        """Eligibility now requires track — CMS needs it as a flat parameter."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
        effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(effects[0].content)
        assert "track" in body["error"].lower()

    def test_returns_404_when_patient_not_found(self):
        handler, _ = _make_handler(request_body={"patient_id": "missing-patient", "track": "eCKM"})

        from cms_access_fhir_client.models.access_alignment import CustomPatient

        with patch(
            "cms_access_fhir_client.api.operations_api.CustomPatient.objects"
        ) as mock_patient_objects:
            mock_patient_objects.get.side_effect = CustomPatient.DoesNotExist

            effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_422_when_no_part_b_coverage(self):
        """Fail closed: 422 when patient has no active Medicare Part B coverage."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=None),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "Medicare Part B" in body["error"]

    def test_returns_422_when_payer_id_cannot_be_determined(self):
        """Fail closed: 422 when neither Transactor.payer_id nor ACCESS_DEFAULT_PAYER_ID is set."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"}, secrets={})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id=None)
        mock_coverage.issuer.payer_id = ""

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "payerID" in body["error"]

    def test_uses_coverage_payer_id_preferentially(self):
        """When Transactor.payer_id is populated it must be passed to check_eligibility."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(mbi="MBI-123", payer_id="transactor-payer-id")
        mock_alignment = MagicMock()
        mock_alignment.status = "eligible"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = {"parameter": [{"name": "status", "valueCode": "eligible"}]}
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_eligibility()

        _, call_kwargs = mock_check.call_args
        assert call_kwargs["payer_id"] == "transactor-payer-id"

    def test_falls_back_to_secret_payer_id(self):
        """When Transactor.payer_id is absent, use ACCESS_DEFAULT_PAYER_ID secret."""
        handler, _ = _make_handler(
            request_body={"patient_id": "p-123", "track": "eCKM"},
            secrets={"ACCESS_DEFAULT_PAYER_ID": "secret-fallback-payer"},
        )
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id=None)
        mock_coverage.issuer.payer_id = ""
        mock_alignment = MagicMock()
        mock_alignment.status = "eligible"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = {"parameter": [{"name": "status", "valueCode": "eligible"}]}
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_eligibility()

        _, call_kwargs = mock_check.call_args
        assert call_kwargs["payer_id"] == "secret-fallback-payer"

    def test_check_eligibility_called_with_flat_mbi_payer_id_track(self):
        """check_eligibility must be called with flat mbi/payer_id/track — no patient_resource."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "MSK"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(mbi="MBI-FLAT", payer_id="payer-flat")
        mock_alignment = MagicMock()
        mock_alignment.status = "eligible"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = {"parameter": [{"name": "status", "valueCode": "eligible"}]}
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_eligibility()

        _, call_kwargs = mock_check.call_args
        assert call_kwargs["mbi"] == "MBI-FLAT"
        assert call_kwargs["payer_id"] == "payer-flat"
        assert call_kwargs["track"] == "MSK"
        assert "patient_resource" not in call_kwargs

    def test_creates_alignment_on_success(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.status = "eligible"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = {
                "parameter": [{"name": "status", "valueCode": "eligible"}]
            }
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_eligibility()

        assert len(effects) == 2  # broadcast + JSONResponse
        assert effects[-1].status_code == HTTPStatus.OK
        assert mock_alignment.save.called

    def test_sets_submission_state_on_202(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = {
                "status_code": 202,
                "content_location": "https://api.cms.gov/status/abc",
                "parameter": [],
            }
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_eligibility()

        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/abc"
        assert mock_alignment.save.called

    def test_returns_502_on_runtime_error(self):
        """RuntimeError from CMS must result in 502 and saved error alignment."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility", side_effect=RuntimeError("CMS down")),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_eligibility()

        assert len(effects) == 2
        assert effects[-1].status_code == HTTPStatus.BAD_GATEWAY
        body = json.loads(effects[-1].content)
        assert "CMS down" in body["error"]


class TestSubmitAlign:
    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(request_body={})
        effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_when_no_track(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
        effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_when_no_clinical_justification(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_404_when_patient_not_found(self):
        handler, _ = _make_handler(request_body={
            "patient_id": "missing",
            "track": "eCKM",
            "clinical_justification": "Justified",
        })

        from cms_access_fhir_client.models.access_alignment import CustomPatient

        with patch(
            "cms_access_fhir_client.api.operations_api.CustomPatient.objects"
        ) as mock_patient_objects:
            mock_patient_objects.get.side_effect = CustomPatient.DoesNotExist

            effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_422_when_no_part_b_coverage(self):
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient()

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=None),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "Medicare Part B" in body["error"]

    def test_returns_422_when_payer_id_cannot_be_determined(self):
        handler, _ = _make_handler(
            request_body={"patient_id": "p-123", "track": "eCKM", "clinical_justification": "CKD"},
            secrets={},
        )
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id=None)
        mock_coverage.issuer.payer_id = ""

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "payerID" in body["error"]

    def test_align_called_with_flat_mbi_payer_id_track(self):
        """align() must receive mbi, payer_id, track directly — no patient_resource."""
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(mbi="MBI-ALIGN", payer_id="payer-align")
        mock_alignment = MagicMock()
        mock_alignment.status = "pending"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.align") as mock_align,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_align.return_value = (202, "https://api.cms.gov/status/xyz", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_align()

        _, call_kwargs = mock_align.call_args
        assert call_kwargs["mbi"] == "MBI-ALIGN"
        assert call_kwargs["payer_id"] == "payer-align"
        assert call_kwargs["track"] == "eCKM"
        assert "patient_resource" not in call_kwargs

    def test_creates_alignment_on_success(self):
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.status = "pending"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.align") as mock_align,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_align.return_value = (202, "https://api.cms.gov/status/xyz", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_align()

        assert len(effects) == 2  # broadcast + JSONResponse
        assert effects[-1].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/xyz"


class TestSubmitUnalign:
    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(request_body={})
        effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_when_no_reason_code(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
        effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_404_when_patient_not_found(self):
        handler, _ = _make_handler(request_body={"patient_id": "missing", "reason_code": "patient-request"})

        from cms_access_fhir_client.models.access_alignment import CustomPatient

        with patch(
            "cms_access_fhir_client.api.operations_api.CustomPatient.objects"
        ) as mock_patient_objects:
            mock_patient_objects.get.side_effect = CustomPatient.DoesNotExist

            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_422_when_no_part_b_coverage(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=None),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "Medicare Part B" in body["error"]

    def test_returns_422_when_payer_id_cannot_be_determined(self):
        handler, _ = _make_handler(
            request_body={"patient_id": "p-123", "reason_code": "patient-request"},
            secrets={},
        )
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id=None)
        mock_coverage.issuer.payer_id = ""

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "payerID" in body["error"]

    def test_returns_404_when_no_active_alignment(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = None

            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_422_when_alignment_missing_id(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = ""

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment

            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_unalign_called_with_flat_params_including_track_from_alignment(self):
        """unalign() must receive mbi, payer_id, track, alignment_id, reason_code.
        track comes from the stored alignment record, not the HTTP request body."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(mbi="MBI-UNALIGN", payer_id="payer-unalign")
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"
        mock_alignment.track = "BH"
        mock_alignment.status = "aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign") as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment
            mock_unalign.return_value = (202, "https://api.cms.gov/status/unalign-xyz", {})

            handler.submit_unalign()

        _, call_kwargs = mock_unalign.call_args
        assert call_kwargs["mbi"] == "MBI-UNALIGN"
        assert call_kwargs["payer_id"] == "payer-unalign"
        assert call_kwargs["track"] == "BH"  # pulled from alignment record
        assert call_kwargs["alignment_id"] == "align-abc"
        assert call_kwargs["reason_code"] == "patient-request"
        assert "patient_resource" not in call_kwargs
        assert "patient_fhir_id" not in call_kwargs

    def test_submits_unalign_on_success(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"
        mock_alignment.track = "eCKM"
        mock_alignment.status = "aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign") as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment
            mock_unalign.return_value = (202, "https://api.cms.gov/status/unalign-xyz", {})

            effects = handler.submit_unalign()

        assert len(effects) == 2  # broadcast + JSONResponse
        assert effects[-1].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/unalign-xyz"

    def test_marks_unaligned_immediately_on_non_202(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"
        mock_alignment.track = "CKM"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign") as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment
            mock_unalign.return_value = (200, None, {})

            handler.submit_unalign()

        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        assert mock_alignment.status == ACCESSAlignment.STATUS_UNALIGNED


class TestExtractEligibilityStatus:
    def test_eligible_code_maps_to_eligible_status(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        result = {"parameter": [{"name": "status", "valueCode": "eligible"}]}
        assert _extract_eligibility_status(result) == ACCESSAlignment.STATUS_ELIGIBLE

    def test_ineligible_code_maps_correctly(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        result = {"parameter": [{"name": "status", "valueCode": "ineligible"}]}
        assert _extract_eligibility_status(result) == ACCESSAlignment.STATUS_INELIGIBLE

    def test_already_aligned_code_maps_correctly(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        result = {"parameter": [{"name": "status", "valueCode": "already-aligned"}]}
        assert _extract_eligibility_status(result) == ACCESSAlignment.STATUS_ALREADY_ALIGNED

    def test_unknown_code_returns_error(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        assert _extract_eligibility_status({}) == ACCESSAlignment.STATUS_ERROR
        assert _extract_eligibility_status({"parameter": []}) == ACCESSAlignment.STATUS_ERROR
