"""Tests for AccessOperationsApi — GET modals and POST submissions."""
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


def _make_mock_coverage(mbi="1EG4-TE5-MK72", issuer_name="IL Medicare Part B", dbid=99):
    coverage = MagicMock()
    coverage.id_number = mbi
    coverage.dbid = dbid
    coverage.issuer = MagicMock()
    coverage.issuer.name = issuer_name
    return coverage


class TestEligibilityModalGet:
    def test_returns_html_when_patient_id_present(self):
        from canvas_sdk.effects.simple_api import HTMLResponse
        handler, _ = _make_handler(query_params={"patient_id": "p-123"})
        effects = handler.eligibility_modal()

        assert len(effects) == 1
        assert isinstance(effects[0], HTMLResponse)

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


class TestSubmitEligibility:
    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(request_body={})
        effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_404_when_patient_not_found(self):
        handler, _ = _make_handler(request_body={"patient_id": "missing-patient"})

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
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
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

    def test_creates_alignment_on_success(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()
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

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.OK
        assert mock_alignment.save.called

    def test_check_eligibility_called_with_embedded_patient_resource(self):
        """The MBI from Coverage.id_number must be embedded in the patient_resource."""
        from datetime import date
        birth = date(1942, 6, 15)
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
        mock_patient = _make_mock_patient(first_name="Jane", last_name="Doe", birth_date=birth)
        mock_coverage = _make_mock_coverage(mbi="1EG4-TE5-MK72")
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
        resource = call_kwargs["patient_resource"]
        assert resource["resourceType"] == "Patient"
        identifiers = resource["identifier"]
        assert any(
            i["system"] == "http://hl7.org/fhir/sid/us-mbi" and i["value"] == "1EG4-TE5-MK72"
            for i in identifiers
        )
        assert resource["name"][0]["family"] == "Doe"
        assert resource["birthDate"] == "1942-06-15"

    def test_sets_submission_state_on_202(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()
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
        """Fail closed: 422 when patient has no active Medicare Part B coverage."""
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

    def test_creates_alignment_on_success(self):
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()
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

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/xyz"

    def test_align_called_with_embedded_patient_resource(self):
        """The MBI from Coverage.id_number must be forwarded as embedded patient_resource."""
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient(first_name="John", last_name="Smith")
        mock_coverage = _make_mock_coverage(mbi="2EG9-AB1-CD34")
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
        resource = call_kwargs["patient_resource"]
        assert resource["resourceType"] == "Patient"
        assert any(
            i["system"] == "http://hl7.org/fhir/sid/us-mbi" and i["value"] == "2EG9-AB1-CD34"
            for i in resource["identifier"]
        )
        assert resource["name"][0]["family"] == "Smith"


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
        """Fail closed: 422 when patient has no active Medicare Part B coverage."""
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

    def test_returns_404_when_no_active_alignment(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()

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
        mock_coverage = _make_mock_coverage()
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = ""  # No alignment_id set

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

    def test_submits_unalign_on_success(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"
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

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/unalign-xyz"

    def test_unalign_called_without_patient_fhir_id(self):
        """After refactor, unalign() no longer takes patient_fhir_id."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"
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

        call_kwargs = mock_unalign.call_args[1]
        assert "alignment_id" in call_kwargs
        assert "reason_code" in call_kwargs
        assert "patient_fhir_id" not in call_kwargs
        assert "patient_resource" not in call_kwargs

    def test_marks_unaligned_immediately_on_non_202(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "patient-request"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage()
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign") as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment
            mock_unalign.return_value = (200, None, {})  # Synchronous response

            handler.submit_unalign()

        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        assert mock_alignment.status == ACCESSAlignment.STATUS_UNALIGNED


class TestBuildPatientResource:
    def test_resource_uses_resource_key_not_value_reference(self):
        """Confirm the FHIR patient param uses 'resource' (inline) not 'valueReference'."""
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        from datetime import date
        patient = MagicMock()
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        patient.birth_date = date(1942, 6, 15)

        resource = _build_patient_resource(patient, mbi="1EG4-TE5-MK72")

        assert resource["resourceType"] == "Patient"
        assert any(
            i["system"] == "http://hl7.org/fhir/sid/us-mbi" and i["value"] == "1EG4-TE5-MK72"
            for i in resource["identifier"]
        )
        assert resource["name"][0]["family"] == "Doe"
        assert resource["name"][0]["given"] == ["Jane"]
        assert resource["birthDate"] == "1942-06-15"

    def test_none_birth_date_omitted(self):
        """None birth_date must not appear in the resource (FHIR rejects null fields)."""
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = MagicMock()
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        patient.birth_date = None

        resource = _build_patient_resource(patient, mbi="1EG4-TE5-MK72")

        assert "birthDate" not in resource

    def test_mbi_system_is_us_mbi(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = MagicMock()
        patient.first_name = "A"
        patient.last_name = "B"
        patient.birth_date = None

        resource = _build_patient_resource(patient, mbi="TESTMBI")
        systems = [i["system"] for i in resource["identifier"]]
        assert "http://hl7.org/fhir/sid/us-mbi" in systems


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
