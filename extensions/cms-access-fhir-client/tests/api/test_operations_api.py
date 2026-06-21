"""Tests for AccessOperationsApi — GET modals and POST submissions.

Key changes tested here (OM v0.9.8 payload rebuild):
- check_eligibility / align / unalign now receive patient_resource, payer_id, track
- _build_patient_resource builds a US Core Patient resource from Canvas patient data
- Eligibility modal and submit require track in the request body
- payer_id lookup order: coverage.issuer.payer_id → ACCESS_DEFAULT_PAYER_ID secret → 422 fail-closed
- unalign pulls track from the stored ACCESSAlignment record
- _extract_eligibility_status returns (status_constant, raw_code) and reads `result` param
"""
import json
import pytest
from http import HTTPStatus
from unittest.mock import MagicMock, patch
from datetime import date


def _make_handler(secrets=None, request_body=None, query_params=None):
    from cms_access_fhir_client.api.operations_api import AccessOperationsApi
    handler = AccessOperationsApi.__new__(AccessOperationsApi)
    handler.secrets = secrets or {}
    mock_request = MagicMock()
    mock_request.json.return_value = request_body or {}
    mock_request.query_params.get = lambda key, default=None: (query_params or {}).get(key, default)
    handler.request = mock_request
    return handler, mock_request


def _make_mock_patient(
    patient_id="p-123",
    first_name="Jane",
    last_name="Doe",
    birth_date=date(1950, 1, 1),
    sex_at_birth="female",
):
    patient = MagicMock()
    patient.id = patient_id
    patient.first_name = first_name
    patient.last_name = last_name
    patient.birth_date = birth_date
    patient.sex_at_birth = sex_at_birth
    return patient


def _make_mock_coverage(mbi="1EG4-TE5-MK72", issuer_name="IL Medicare Part B", dbid=99, payer_id=None):
    coverage = MagicMock()
    coverage.id_number = mbi
    coverage.dbid = dbid
    coverage.issuer = MagicMock()
    coverage.issuer.name = issuer_name
    coverage.issuer.payer_id = payer_id  # None by default — simulates unpopulated Transactor
    return coverage


# ---------------------------------------------------------------------------
# _build_patient_resource
# ---------------------------------------------------------------------------

class TestBuildPatientResource:
    def test_raises_when_birth_date_is_none(self):
        """Missing birthDate must raise, not silently strip the field."""
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient(birth_date=None)
        with pytest.raises(ValueError, match="birth_date"):
            _build_patient_resource(patient, mbi="1EG4-TE5-MK72")

    def test_includes_birth_date_as_iso_string(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient(birth_date=date(1950, 3, 15))
        result = _build_patient_resource(patient, mbi="1EG4-TE5-MK72")
        assert result["birthDate"] == "1950-03-15"

    def test_includes_mbi_identifier_with_mc_type(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient()
        result = _build_patient_resource(patient, mbi="TEST-MBI-99")
        identifiers = result["identifier"]
        assert len(identifiers) == 1
        ident = identifiers[0]
        assert ident["system"] == "http://terminology.hl7.org/NamingSystem/cmsMBI"
        assert ident["value"] == "TEST-MBI-99"
        assert ident["type"]["coding"][0]["code"] == "MC"

    def test_includes_name(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient(first_name="Alice", last_name="Smith")
        result = _build_patient_resource(patient, mbi="X")
        assert result["name"][0]["family"] == "Smith"
        assert result["name"][0]["given"] == ["Alice"]

    def test_declares_us_core_patient_profile(self):
        """IMPL requires meta.profile; CMS ACCESS uses US Core Patient 6.1.0."""
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        result = _build_patient_resource(_make_mock_patient(), mbi="X")
        assert result["meta"]["profile"] == [
            "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient|6.1.0"
        ]

    def test_uses_sex_at_birth_for_gender(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient(sex_at_birth="male")
        result = _build_patient_resource(patient, mbi="X")
        assert result["gender"] == "male"

    def test_maps_single_letter_sex_at_birth_codes(self):
        """Canvas stores sex_at_birth as F/M/O; map to the FHIR gender value set."""
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        for code, expected in [("F", "female"), ("M", "male"), ("O", "other"), ("UNK", "unknown")]:
            patient = _make_mock_patient(sex_at_birth=code)
            assert _build_patient_resource(patient, mbi="X")["gender"] == expected

    def test_falls_back_to_unknown_when_no_gender(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient(sex_at_birth=None)
        # Remove gender attribute entirely
        del patient.gender
        result = _build_patient_resource(patient, mbi="X")
        assert result["gender"] == "unknown"

    def test_resource_type_is_patient(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient()
        result = _build_patient_resource(patient, mbi="X")
        assert result["resourceType"] == "Patient"

    def test_id_is_patient_uuid(self):
        from cms_access_fhir_client.api.operations_api import _build_patient_resource
        patient = _make_mock_patient(patient_id="abc-uuid-123")
        result = _build_patient_resource(patient, mbi="X")
        assert result["id"] == "abc-uuid-123"


# ---------------------------------------------------------------------------
# _get_payer_id
# ---------------------------------------------------------------------------

class TestGetPayerId:
    def test_returns_coverage_payer_id_when_populated(self):
        from cms_access_fhir_client.api.operations_api import _get_payer_id
        coverage = _make_mock_coverage(payer_id="payer-from-transactor")
        result = _get_payer_id(coverage, secrets={})
        assert result == "payer-from-transactor"

    def test_falls_back_to_secret_when_transactor_empty(self):
        from cms_access_fhir_client.api.operations_api import _get_payer_id
        coverage = _make_mock_coverage(payer_id=None)
        coverage.issuer.payer_id = ""
        result = _get_payer_id(coverage, secrets={"ACCESS_DEFAULT_PAYER_ID": "secret-payer"})
        assert result == "secret-payer"

    def test_transactor_wins_over_secret(self):
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


# ---------------------------------------------------------------------------
# submit_eligibility
# ---------------------------------------------------------------------------

class TestSubmitEligibility:
    def test_returns_400_when_no_patient_id(self):
        handler, _ = _make_handler(request_body={})
        effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_400_when_no_track(self):
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

    def test_returns_422_when_patient_birth_date_is_none(self):
        """Patient with no birth_date must return 422 — CMS requires birthDate."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient(birth_date=None)
        mock_coverage = _make_mock_coverage(payer_id="00831")

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_eligibility()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(effects[0].content)
        assert "birth_date" in body["error"].lower() or "birthDate" in body["error"]

    def test_uses_coverage_payer_id_preferentially(self):
        """When Transactor.payer_id is populated it must be passed to check_eligibility."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(mbi="MBI-123", payer_id="transactor-payer-id")
        mock_alignment = MagicMock()
        mock_alignment.status = "eligible"
        mock_alignment.status_message = ""

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = (202, "https://cms.test/submission-status/abc", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_eligibility()

        _, call_kwargs = mock_check.call_args
        assert call_kwargs["payer_id"] == "transactor-payer-id"

    def test_check_eligibility_called_with_patient_resource_not_mbi(self):
        """check_eligibility must be called with patient_resource — no flat mbi kwarg."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "MSK"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(mbi="MBI-FLAT", payer_id="payer-flat")
        mock_alignment = MagicMock()
        mock_alignment.status = "eligible"
        mock_alignment.status_message = ""

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = (202, "https://cms.test/submission-status/abc", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_eligibility()

        _, call_kwargs = mock_check.call_args
        assert "patient_resource" in call_kwargs
        assert call_kwargs["patient_resource"]["resourceType"] == "Patient"
        assert "mbi" not in call_kwargs

    def test_creates_alignment_on_async_accepted(self):
        """A 202 from CMS must persist the submission URL and return ACCEPTED to the modal."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.status = "pending"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.check_eligibility") as mock_check,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_check.return_value = (202, "https://cms.test/submission-status/xyz", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_eligibility()

        assert len(effects) == 1  # JSONResponse only
        assert effects[-1].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.save.called
        assert mock_alignment.submission_status_url == "https://cms.test/submission-status/xyz"

    def test_non_202_2xx_is_an_error_not_stuck_pending(self):
        """$check-eligibility is always 202+Content-Location; a 2xx without one is a contract
        violation — error out instead of parking the row in a stuck PENDING reported as success."""
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
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
            mock_check.return_value = (200, None, {})  # 2xx but not the documented 202
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_eligibility()

        assert effects[-1].status_code == HTTPStatus.BAD_GATEWAY
        assert mock_alignment.status == ACCESSAlignment.STATUS_ERROR
        assert mock_alignment.submission_state != ACCESSAlignment.SUB_STATE_IN_PROGRESS

    def test_returns_502_on_runtime_error(self):
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

        assert len(effects) == 1  # JSONResponse only
        assert effects[-1].status_code == HTTPStatus.BAD_GATEWAY
        body = json.loads(effects[-1].content)
        assert "CMS down" in body["error"]


# ---------------------------------------------------------------------------
# submit_align
# ---------------------------------------------------------------------------

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

    def test_returns_422_when_patient_birth_date_is_none(self):
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient(birth_date=None)
        mock_coverage = _make_mock_coverage(payer_id="00831")

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_align_called_with_patient_resource_not_mbi(self):
        """align() must receive patient_resource — no flat mbi kwarg."""
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
            patch("cms_access_fhir_client.api.operations_api.build_track_conditions", return_value=[{"resourceType": "Condition"}]),
            patch("cms_access_fhir_client.api.operations_api.align") as mock_align,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_align.return_value = (202, "https://api.cms.gov/status/xyz", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            handler.submit_align()

        _, call_kwargs = mock_align.call_args
        assert "patient_resource" in call_kwargs
        assert call_kwargs["patient_resource"]["resourceType"] == "Patient"
        assert call_kwargs["payer_id"] == "payer-align"
        assert call_kwargs["track"] == "eCKM"
        assert call_kwargs["conditions"] == [{"resourceType": "Condition"}]
        assert "mbi" not in call_kwargs
        assert "clinical_justification" not in call_kwargs

    def test_returns_422_when_no_qualifying_condition(self):
        """$align fails closed when the patient has no track-qualifying diagnosis."""
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "track": "eCKM",
            "clinical_justification": "Stage 3 CKD",
        })
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.build_track_conditions", return_value=[]),
            patch("cms_access_fhir_client.api.operations_api.align") as mock_align,
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_align()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "qualifying" in json.loads(effects[0].content)["error"]
        mock_align.assert_not_called()

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
            patch("cms_access_fhir_client.api.operations_api.build_track_conditions", return_value=[{"resourceType": "Condition"}]),
            patch("cms_access_fhir_client.api.operations_api.align") as mock_align,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_align.return_value = (202, "https://api.cms.gov/status/xyz", {})
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_align()

        assert len(effects) == 1  # JSONResponse only
        assert effects[-1].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/xyz"

    def test_non_202_2xx_is_an_error_not_stuck_pending(self):
        """$align is always 202+Content-Location; a bare 2xx must error, not be coerced to PENDING."""
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "track": "eCKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.build_track_conditions", return_value=[{"resourceType": "Condition"}]),
            patch("cms_access_fhir_client.api.operations_api.align") as mock_align,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_align.return_value = (200, None, {})  # 2xx but not the documented 202
            mock_alignment_objects.get_or_create.return_value = (mock_alignment, True)

            effects = handler.submit_align()

        assert effects[-1].status_code == HTTPStatus.BAD_GATEWAY
        assert mock_alignment.status == ACCESSAlignment.STATUS_ERROR
        assert mock_alignment.submission_state != ACCESSAlignment.SUB_STATE_IN_PROGRESS


# ---------------------------------------------------------------------------
# submit_unalign
# ---------------------------------------------------------------------------

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
        handler, _ = _make_handler(request_body={"patient_id": "missing", "reason_code": "loss-of-contact"})

        from cms_access_fhir_client.models.access_alignment import CustomPatient

        with patch(
            "cms_access_fhir_client.api.operations_api.CustomPatient.objects"
        ) as mock_patient_objects:
            mock_patient_objects.get.side_effect = CustomPatient.DoesNotExist

            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_422_when_no_part_b_coverage(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
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
            request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"},
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

    def test_returns_422_when_patient_birth_date_is_none(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
        mock_patient = _make_mock_patient(birth_date=None)
        mock_coverage = _make_mock_coverage(payer_id="00831")

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
        ):
            mock_patient_objects.get.return_value = mock_patient
            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_returns_404_when_no_active_alignment(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
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

    def test_explains_when_unalignment_already_pending(self):
        """A track in unalignment-pending won't match the aligned/already-aligned filter;
        the error must say it's already pending, not 'no active alignment'."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        pending = MagicMock()
        pending.status = "pending"
        pending.submission_state = ""
        pending.status_message = "unalignment-pending"
        pending.track = "CKM"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
        ):
            mock_patient_objects.get.return_value = mock_patient
            # First query (aligned/already-aligned) → None; second query (any) → pending row.
            mock_alignment_objects.filter.return_value.order_by.return_value.first.side_effect = [None, pending]

            effects = handler.submit_unalign()

        assert effects[0].status_code == HTTPStatus.NOT_FOUND
        body = json.loads(effects[0].content)
        assert "already pending" in body["error"]
        assert "unalignment-pending" in body["error"]

    def test_proceeds_when_alignment_id_blank(self):
        """v0.9.11 $unalign carries no alignmentId — a blank stored alignment_id must
        NOT block the unalignment (the old 422 guard was removed)."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = ""
        mock_alignment.track = "CKM"
        mock_alignment.status = "aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign", return_value=(202, "https://cms.test/sub/1", {})) as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment

            effects = handler.submit_unalign()

        assert mock_unalign.called  # reached CMS instead of failing closed on alignment_id
        assert effects[-1].status_code == HTTPStatus.ACCEPTED

    def test_unalign_accepts_already_aligned_rows(self):
        """A repeat $align returns 'already-aligned' (overwriting 'aligned'), but the
        patient is still aligned at CMS — unalign must look up both statuses and proceed."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        alignment = MagicMock()
        alignment.alignment_id = ""
        alignment.track = "CKM"
        alignment.status = "already-aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign", return_value=(202, "https://cms.test/sub/1", {})) as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = alignment
            effects = handler.submit_unalign()

        # The lookup must include 'already-aligned', not just 'aligned'.
        status_in = mock_alignment_objects.filter.call_args.kwargs.get("status__in")
        assert status_in is not None and "already-aligned" in status_in
        assert mock_unalign.called
        assert effects[-1].status_code == HTTPStatus.ACCEPTED

    def test_unalign_targets_requested_track(self):
        """When the caller specifies a track, unalign looks up that track's alignment."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact", "track": "CKM"})
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        alignment = MagicMock()
        alignment.alignment_id = ""
        alignment.track = "CKM"
        alignment.status = "aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.unalign", return_value=(202, "https://cms.test/sub/1", {})) as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            base_qs = mock_alignment_objects.filter.return_value
            base_qs.filter.return_value.order_by.return_value.first.return_value = alignment
            effects = handler.submit_unalign()

        assert base_qs.filter.call_args.kwargs.get("track") == "CKM"  # track-specific lookup applied
        assert mock_unalign.called
        assert effects[-1].status_code == HTTPStatus.ACCEPTED

    def test_unalign_called_with_patient_resource_and_track_from_alignment(self):
        """unalign() must receive patient_resource, payer_id, track (from alignment), reason_code.
        No flat mbi, no alignmentId."""
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
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
        assert "patient_resource" in call_kwargs
        assert call_kwargs["patient_resource"]["resourceType"] == "Patient"
        assert call_kwargs["payer_id"] == "payer-unalign"
        assert call_kwargs["track"] == "BH"  # from alignment record
        assert call_kwargs["reason_code"] == "loss-of-contact"
        assert "mbi" not in call_kwargs
        assert "alignmentId" not in call_kwargs
        assert "alignment_id" not in call_kwargs

    def test_returns_422_when_no_longer_clinically_eligible_without_condition(self):
        """reason=no-longer-clinically-eligible needs a disqualifying dx; 422 when none."""
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "reason_code": "no-longer-clinically-eligible",
        })
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.alignment_id = "align-abc"
        mock_alignment.track = "CKM"
        mock_alignment.status = "aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.build_active_conditions", return_value=[]),
            patch("cms_access_fhir_client.api.operations_api.unalign") as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment
            effects = handler.submit_unalign()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "disqualifying" in json.loads(effects[0].content)["error"]
        mock_unalign.assert_not_called()

    def test_passes_conditions_for_no_longer_clinically_eligible(self):
        handler, _ = _make_handler(request_body={
            "patient_id": "p-123",
            "reason_code": "no-longer-clinically-eligible",
        })
        mock_patient = _make_mock_patient()
        mock_coverage = _make_mock_coverage(payer_id="payer-001")
        mock_alignment = MagicMock()
        mock_alignment.track = "CKM"
        mock_alignment.alignment_id = "align-abc"
        mock_alignment.status = "aligned"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as mock_patient_objects,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=mock_coverage),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment.objects") as mock_alignment_objects,
            patch("cms_access_fhir_client.api.operations_api.build_active_conditions", return_value=[{"resourceType": "Condition"}]),
            patch("cms_access_fhir_client.api.operations_api.unalign") as mock_unalign,
        ):
            mock_patient_objects.get.return_value = mock_patient
            mock_alignment_objects.filter.return_value.order_by.return_value.first.return_value = mock_alignment
            mock_unalign.return_value = (202, "https://api.cms.gov/status/u", {})
            handler.submit_unalign()

        _, call_kwargs = mock_unalign.call_args
        assert call_kwargs["conditions"] == [{"resourceType": "Condition"}]

    def test_submits_unalign_on_success(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
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

        assert len(effects) == 1  # JSONResponse only
        assert effects[-1].status_code == HTTPStatus.ACCEPTED
        assert mock_alignment.submission_status_url == "https://api.cms.gov/status/unalign-xyz"

    def test_marks_unaligned_immediately_on_non_202(self):
        handler, _ = _make_handler(request_body={"patient_id": "p-123", "reason_code": "loss-of-contact"})
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


# ---------------------------------------------------------------------------
# _extract_eligibility_status
# ---------------------------------------------------------------------------

class TestExtractEligibilityStatus:
    """OM v0.9.8: polling response uses `result` (valueCodeableConcept), not `status` (valueCode).

    Function now returns (status_constant, raw_cms_code) tuple.
    """

    def _make_result(self, code: str) -> dict:
        return {
            "parameter": [
                {
                    "name": "result",
                    "valueCodeableConcept": {
                        "coding": [{"code": code}]
                    },
                }
            ]
        }

    def test_eligible_maps_to_eligible_status(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("eligible"))
        assert status == ACCESSAlignment.STATUS_ELIGIBLE
        assert raw == "eligible"

    def test_eligible_pending_diagnosis_maps_to_eligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("eligible-pending-diagnosis"))
        assert status == ACCESSAlignment.STATUS_ELIGIBLE
        assert raw == "eligible-pending-diagnosis"

    def test_eligible_switch_participants_maps_to_eligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("eligible-switch-participants"))
        assert status == ACCESSAlignment.STATUS_ELIGIBLE
        assert raw == "eligible-switch-participants"

    def test_not_eligible_already_aligned_maps_to_already_aligned(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-already-aligned"))
        assert status == ACCESSAlignment.STATUS_ALREADY_ALIGNED
        assert raw == "not-eligible-already-aligned"

    def test_not_eligible_not_medicare_maps_to_ineligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-not-medicare"))
        assert status == ACCESSAlignment.STATUS_INELIGIBLE
        assert raw == "not-eligible-not-medicare"

    def test_not_eligible_services_maps_to_ineligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-services"))
        assert status == ACCESSAlignment.STATUS_INELIGIBLE

    def test_not_eligible_diagnoses_maps_to_ineligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-diagnoses"))
        assert status == ACCESSAlignment.STATUS_INELIGIBLE

    def test_not_eligible_control_group_maps_to_ineligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-control-group"))
        assert status == ACCESSAlignment.STATUS_INELIGIBLE

    def test_not_eligible_clinical_exclusion_maps_to_ineligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-clinical-exclusion"))
        assert status == ACCESSAlignment.STATUS_INELIGIBLE

    def test_not_eligible_mismatch_maps_to_ineligible(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status(self._make_result("not-eligible-mismatch"))
        assert status == ACCESSAlignment.STATUS_INELIGIBLE

    def test_empty_result_returns_error(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status({})
        assert status == ACCESSAlignment.STATUS_ERROR

    def test_empty_parameter_list_returns_error(self):
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        status, raw = _extract_eligibility_status({"parameter": []})
        assert status == ACCESSAlignment.STATUS_ERROR

    def test_legacy_valueCode_status_param_also_works(self):
        """Back-compat: if response uses `status` + `valueCode` it still maps correctly."""
        from cms_access_fhir_client.api.operations_api import _extract_eligibility_status
        from cms_access_fhir_client.models.access_alignment import ACCESSAlignment
        result = {"parameter": [{"name": "status", "valueCode": "eligible"}]}
        status, raw = _extract_eligibility_status(result)
        assert status == ACCESSAlignment.STATUS_ELIGIBLE
