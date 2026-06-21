"""Tests for CMS ACCESS FHIR API client functions.

Covers:
- URL path structure: /access/Patient/$<op>
- entityId query param on every operation POST
- Prefer: respond-async header on all operations
- Identifier-shaped participantID and payerID (not valueString)
- Embedded Patient resource with cmsMBI system, MC type code, required birthDate
- valueCodeableConcept track structure with ACCESSTrackCS system
- valueCodeableConcept reason structure for $unalign
- poll_submission_status returns (status_code, body) tuple
- OperationOutcome parsing on 400 pre-validation failures
"""
import pytest
from unittest.mock import MagicMock, patch


SECRETS = {
    "ACCESS_BASE_URL": "https://api.access.cms.gov/fhir",
    "ACCESS_PARTICIPANT_ID": "ACCES12345",
    "ACCESS_OAUTH_CLIENT_ID": "client-id",
    "ACCESS_OAUTH_CLIENT_SECRET": "client-secret",
    "ACCESS_OAUTH_TOKEN_URL": "https://auth.cms.gov/token",
}

_PATIENT_RESOURCE = {
    "resourceType": "Patient",
    "id": "patient-uuid-123",
    "identifier": [
        {
            "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MC"}]},
            "system": "http://terminology.hl7.org/NamingSystem/cmsMBI",
            "value": "1EG4-TE5-MK72",
        }
    ],
    "name": [{"family": "Doe", "given": ["John"]}],
    "gender": "male",
    "birthDate": "1950-01-01",
}

_PAYER_ID = "00831"
_TRACK = "eCKM"

# A track-qualifying Condition resource as built by conditions.build_track_conditions.
_CONDITIONS = [
    {
        "resourceType": "Condition",
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": "E11.9",
                    "display": "Type 2 diabetes mellitus without complications",
                }
            ]
        },
        "subject": {"reference": "Patient/patient-uuid-123"},
    }
]


def _mock_http_and_token():
    mock_http = MagicMock()
    mock_http.headers = {}
    return mock_http


# ---------------------------------------------------------------------------
# _build_http
# ---------------------------------------------------------------------------

class TestBuildHttp:
    def test_raises_when_base_url_missing(self):
        from cms_access_fhir_client.cms_client import _build_http
        with pytest.raises(ValueError, match="ACCESS_BASE_URL"):
            _build_http({})

    def test_fails_closed_if_token_fails(self):
        from cms_access_fhir_client.cms_client import _build_http
        with patch(
            "cms_access_fhir_client.cms_client.get_access_token",
            side_effect=ValueError("Missing secret"),
        ):
            with pytest.raises(ValueError):
                _build_http(SECRETS)

    def test_returns_headers_with_bearer_token(self):
        from cms_access_fhir_client.cms_client import _build_http

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok-123"),
            patch("cms_access_fhir_client.cms_client.Http") as mock_http_cls,
        ):
            http, headers = _build_http(SECRETS)

        assert headers.get("Authorization") == "Bearer tok-123"
        mock_http_cls.assert_called_once_with(base_url="https://api.access.cms.gov/fhir/")

    def test_sets_prefer_respond_async_header(self):
        from cms_access_fhir_client.cms_client import _build_http

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http"),
        ):
            _, headers = _build_http(SECRETS)

        assert headers.get("Prefer") == "respond-async"


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

class TestParticipantIdParam:
    def test_uses_value_identifier_shape(self):
        from cms_access_fhir_client.cms_client import _participant_id_param
        result = _participant_id_param("ACCES12345")
        assert result["name"] == "participantID"
        assert "valueIdentifier" in result
        assert result["valueIdentifier"]["value"] == "ACCES12345"
        assert "dsacms" in result["valueIdentifier"]["system"]

    def test_no_value_string_key(self):
        from cms_access_fhir_client.cms_client import _participant_id_param
        result = _participant_id_param("ACCES12345")
        assert "valueString" not in result


class TestPayerIdParam:
    def test_uses_value_identifier_shape(self):
        from cms_access_fhir_client.cms_client import _payer_id_param
        result = _payer_id_param("00831")
        assert result["name"] == "payerID"
        assert "valueIdentifier" in result
        assert result["valueIdentifier"]["value"] == "00831"

    def test_has_carin_bb_type_coding(self):
        from cms_access_fhir_client.cms_client import _payer_id_param
        result = _payer_id_param("00831")
        type_codings = result["valueIdentifier"]["type"]["coding"]
        assert len(type_codings) == 1
        assert type_codings[0]["code"] == "payerid"
        assert "carin-bb" in type_codings[0]["system"]

    def test_has_oid_system(self):
        from cms_access_fhir_client.cms_client import _payer_id_param
        result = _payer_id_param("00831")
        assert result["valueIdentifier"]["system"] == "urn:oid:2.16.840.1.113883.3.221.5"

    def test_no_value_string_key(self):
        from cms_access_fhir_client.cms_client import _payer_id_param
        result = _payer_id_param("00831")
        assert "valueString" not in result


class TestTrackParam:
    def test_uses_value_codeable_concept_shape(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("CKM")
        assert result["name"] == "track"
        assert "valueCodeableConcept" in result
        assert "valueCode" not in result

    def test_has_access_track_cs_system(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("CKM")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert "ACCESSTrackCS" in coding["system"]

    def test_ckm_display_value(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("CKM")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert coding["display"] == "Cardio-Kidney-Metabolic track"

    def test_eckm_display_value(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("eCKM")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert coding["display"] == "Early Cardio-Kidney-Metabolic track"

    def test_msk_display_value(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("MSK")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert coding["display"] == "Musculoskeletal track"

    def test_bh_display_value(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("BH")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert coding["display"] == "Behavioral Health track"

    def test_unknown_track_code_uses_code_as_display(self):
        from cms_access_fhir_client.cms_client import _track_param
        result = _track_param("UNKNOWN")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert coding["display"] == "UNKNOWN"


class TestUnalignReasonParam:
    def test_uses_value_codeable_concept_shape(self):
        from cms_access_fhir_client.cms_client import _unalign_reason_param
        result = _unalign_reason_param("loss-of-contact")
        assert result["name"] == "reason"
        assert "valueCodeableConcept" in result
        assert "valueCode" not in result

    def test_has_unalignment_reason_cs_system(self):
        from cms_access_fhir_client.cms_client import _unalign_reason_param
        result = _unalign_reason_param("patient-initiated")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert "ACCESSUnalignmentReasonCS" in coding["system"]

    def test_code_forwarded(self):
        from cms_access_fhir_client.cms_client import _unalign_reason_param
        result = _unalign_reason_param("no-longer-clinically-eligible")
        coding = result["valueCodeableConcept"]["coding"][0]
        assert coding["code"] == "no-longer-clinically-eligible"


# ---------------------------------------------------------------------------
# check_eligibility
# ---------------------------------------------------------------------------

class TestCheckEligibility:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import check_eligibility
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            check_eligibility({}, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

    def test_posts_to_access_prefix_path(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

        path = mock_http.post.call_args[0][0]
        assert path == "access/Patient/$check-eligibility?entityId=ACCES12345"

    def test_includes_conditions_when_provided(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        resp = MagicMock(); resp.status_code = 200; resp.json.return_value = {"parameter": []}; resp.text = ""
        mock_http.post.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID,
                              track=_TRACK, conditions=_CONDITIONS)
        names = [p["name"] for p in mock_http.post.call_args[1]["json"]["parameter"]]
        assert names.count("condition") == len(_CONDITIONS)

    def test_omits_condition_when_none(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        resp = MagicMock(); resp.status_code = 200; resp.json.return_value = {"parameter": []}; resp.text = ""
        mock_http.post.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)
        names = [p["name"] for p in mock_http.post.call_args[1]["json"]["parameter"]]
        assert "condition" not in names

    def test_participantID_uses_value_identifier(self):
        """participantID must use valueIdentifier, not valueString."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        pid_param = next(p for p in payload["parameter"] if p["name"] == "participantID")
        assert "valueIdentifier" in pid_param
        assert "valueString" not in pid_param
        assert pid_param["valueIdentifier"]["value"] == "ACCES12345"

    def test_payerID_uses_value_identifier_with_carin_bb_type(self):
        """payerID must use valueIdentifier with CARIN BB type coding."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id="00831", track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        payer_param = next(p for p in payload["parameter"] if p["name"] == "payerID")
        assert "valueIdentifier" in payer_param
        assert "valueString" not in payer_param
        assert payer_param["valueIdentifier"]["value"] == "00831"
        type_coding = payer_param["valueIdentifier"]["type"]["coding"][0]
        assert type_coding["code"] == "payerid"

    def test_patient_parameter_uses_resource_key(self):
        """patient parameter must use `resource` key with embedded Patient resource."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "resource" in patient_param
        assert patient_param["resource"]["resourceType"] == "Patient"

    def test_patient_resource_has_mbi_identifier(self):
        """Patient resource must contain cmsMBI identifier with MC type code."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        identifiers = patient_param["resource"]["identifier"]
        mbi_id = next(
            (i for i in identifiers if i.get("system") == "http://terminology.hl7.org/NamingSystem/cmsMBI"),
            None,
        )
        assert mbi_id is not None
        mc_code = mbi_id["type"]["coding"][0]["code"]
        assert mc_code == "MC"

    def test_patient_resource_has_birth_date(self):
        """Patient resource must include birthDate (required by CMS)."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "birthDate" in patient_param["resource"]
        assert patient_param["resource"]["birthDate"] == "1950-01-01"

    def test_track_uses_value_codeable_concept(self):
        """track must use valueCodeableConcept with ACCESSTrackCS system."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track="CKM")

        payload = mock_http.post.call_args[1]["json"]
        track_param = next(p for p in payload["parameter"] if p["name"] == "track")
        assert "valueCodeableConcept" in track_param
        assert "valueCode" not in track_param
        coding = track_param["valueCodeableConcept"]["coding"][0]
        assert coding["code"] == "CKM"
        assert "ACCESSTrackCS" in coding["system"]

    def test_no_flat_mbi_parameter(self):
        """There must be no top-level `mbi` parameter — MBI is inside the Patient resource."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "mbi" not in param_names

    def test_raises_runtime_error_on_400_with_operation_outcome(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "details": {"text": "participantID not found in registry"},
                }
            ],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="participantID not found in registry"):
                check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

    def test_raises_runtime_error_on_400_with_no_issues(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"resourceType": "OperationOutcome", "issue": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Unknown error"):
                check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)

    def test_regression_cms_real_error_propagates(self):
        """The exact CMS error from the live test cycle must propagate."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "details": {
                        "text": "Payload validation failed with the following error: "
                                "missing required field(s): participantID, payerID, track, Patient, mbi, birthDate"
                    },
                }
            ],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="missing required field"):
                check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK)


# ---------------------------------------------------------------------------
# align
# ---------------------------------------------------------------------------

class TestAlign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import align
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            align({}, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)

    def test_posts_to_access_prefix_path(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/abc"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)

        path = mock_http.post.call_args[0][0]
        assert path == "access/Patient/$align?entityId=ACCES12345"

    def test_includes_switch_consent_when_true(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        resp = MagicMock(); resp.status_code = 202; resp.headers.get.return_value = None; resp.text = ""
        mock_http.post.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK,
                  conditions=_CONDITIONS, switch_consent=True)
        params = mock_http.post.call_args[1]["json"]["parameter"]
        sca = [p for p in params if p["name"] == "switchConsentAttestation"]
        assert len(sca) == 1 and sca[0]["valueBoolean"] is True

    def test_omits_switch_consent_by_default(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        resp = MagicMock(); resp.status_code = 202; resp.headers.get.return_value = None; resp.text = ""
        mock_http.post.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)
        names = [p["name"] for p in mock_http.post.call_args[1]["json"]["parameter"]]
        assert "switchConsentAttestation" not in names

    def test_participantID_uses_value_identifier(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)

        payload = mock_http.post.call_args[1]["json"]
        pid_param = next(p for p in payload["parameter"] if p["name"] == "participantID")
        assert "valueIdentifier" in pid_param
        assert "valueString" not in pid_param

    def test_payerID_uses_value_identifier(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id="00831", track=_TRACK, conditions=_CONDITIONS)

        payload = mock_http.post.call_args[1]["json"]
        payer_param = next(p for p in payload["parameter"] if p["name"] == "payerID")
        assert "valueIdentifier" in payer_param
        assert payer_param["valueIdentifier"]["value"] == "00831"

    def test_patient_parameter_uses_resource_key(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "resource" in patient_param
        assert patient_param["resource"]["resourceType"] == "Patient"

    def test_track_uses_value_codeable_concept(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track="MSK", conditions=_CONDITIONS)

        payload = mock_http.post.call_args[1]["json"]
        track_param = next(p for p in payload["parameter"] if p["name"] == "track")
        assert "valueCodeableConcept" in track_param
        assert track_param["valueCodeableConcept"]["coding"][0]["code"] == "MSK"

    def test_no_flat_mbi_parameter(self):
        """No top-level `mbi` param — MBI lives inside the Patient resource."""
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "mbi" not in param_names

    def test_returns_202_with_content_location(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/abc"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status_code, content_location, body = align(
                SECRETS,
                patient_resource=_PATIENT_RESOURCE,
                payer_id=_PAYER_ID,
                track=_TRACK,
                conditions=_CONDITIONS,
            )

        assert status_code == 202
        assert content_location == "https://api.cms.gov/status/abc"
        assert body == {}

    def test_raises_on_400_operation_outcome(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Invalid track"}}],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Invalid track"):
                align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track="INVALID", conditions=_CONDITIONS)

    def test_includes_condition_params_and_no_clinical_justification(self):
        """v0.9.11: $align carries one condition param per condition; no clinicalJustification."""
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=_CONDITIONS)

        payload = mock_http.post.call_args[1]["json"]
        assert payload["meta"]["profile"] == [
            "https://dsacms.github.io/cmmi-access-model/StructureDefinition/access-align-in"
        ]
        param_names = [p["name"] for p in payload["parameter"]]
        condition_params = [p for p in payload["parameter"] if p["name"] == "condition"]
        assert len(condition_params) == 1
        assert condition_params[0]["resource"]["resourceType"] == "Condition"
        assert condition_params[0]["resource"]["code"]["coding"][0]["code"] == "E11.9"
        assert "isProviderReferral" in param_names
        assert "clinicalJustification" not in param_names

    def test_raises_when_conditions_empty(self):
        """$align must fail closed when no track-qualifying condition is supplied."""
        from cms_access_fhir_client.cms_client import align
        with pytest.raises(ValueError, match="at least one track-qualifying condition"):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, conditions=[])


# ---------------------------------------------------------------------------
# unalign
# ---------------------------------------------------------------------------

class TestUnalign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import unalign
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            unalign({}, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

    def test_posts_to_access_prefix_path(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/xyz"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

        path = mock_http.post.call_args[0][0]
        assert path == "access/Patient/$unalign?entityId=ACCES12345"

    def test_participantID_uses_value_identifier(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

        payload = mock_http.post.call_args[1]["json"]
        pid_param = next(p for p in payload["parameter"] if p["name"] == "participantID")
        assert "valueIdentifier" in pid_param
        assert "valueString" not in pid_param

    def test_reason_uses_value_codeable_concept(self):
        """reason must use valueCodeableConcept with ACCESSUnalignmentReasonCS, not valueCode."""
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="patient-initiated")

        payload = mock_http.post.call_args[1]["json"]
        reason_param = next(p for p in payload["parameter"] if p["name"] == "reason")
        assert "valueCodeableConcept" in reason_param
        assert "valueCode" not in reason_param
        coding = reason_param["valueCodeableConcept"]["coding"][0]
        assert coding["code"] == "patient-initiated"
        assert "ACCESSUnalignmentReasonCS" in coding["system"]

    def test_track_uses_value_codeable_concept(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track="BH", reason_code="loss-of-contact")

        payload = mock_http.post.call_args[1]["json"]
        track_param = next(p for p in payload["parameter"] if p["name"] == "track")
        assert "valueCodeableConcept" in track_param
        assert track_param["valueCodeableConcept"]["coding"][0]["code"] == "BH"

    def test_patient_parameter_uses_resource_key(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "resource" in patient_param
        assert patient_param["resource"]["resourceType"] == "Patient"

    def test_no_flat_mbi_parameter(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "mbi" not in param_names

    def test_no_alignment_id_parameter(self):
        """alignmentId is NOT in the OM $unalign schema and must not be sent."""
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "alignmentId" not in param_names

    def test_returns_status_and_location(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/unalign-xyz"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status_code, content_location, body = unalign(
                SECRETS,
                patient_resource=_PATIENT_RESOURCE,
                payer_id=_PAYER_ID,
                track=_TRACK,
                reason_code="patient-initiated",
            )

        assert status_code == 202
        assert content_location == "https://api.cms.gov/status/unalign-xyz"
        assert body == {}

    def test_raises_on_400_operation_outcome(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Alignment not found"}}],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Alignment not found"):
                unalign(SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK, reason_code="loss-of-contact")

    def test_no_longer_clinically_eligible_requires_condition(self):
        """reason=no-longer-clinically-eligible without a condition fails closed."""
        from cms_access_fhir_client.cms_client import unalign
        with pytest.raises(ValueError, match="requires at least one disqualifying condition"):
            unalign(
                SECRETS,
                patient_resource=_PATIENT_RESOURCE,
                payer_id=_PAYER_ID,
                track=_TRACK,
                reason_code="no-longer-clinically-eligible",
                conditions=[],
            )

    def test_includes_condition_params_when_provided(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(
                SECRETS,
                patient_resource=_PATIENT_RESOURCE,
                payer_id=_PAYER_ID,
                track=_TRACK,
                reason_code="no-longer-clinically-eligible",
                conditions=_CONDITIONS,
            )

        payload = mock_http.post.call_args[1]["json"]
        condition_params = [p for p in payload["parameter"] if p["name"] == "condition"]
        assert len(condition_params) == 1
        reason_param = next(p for p in payload["parameter"] if p["name"] == "reason")
        assert reason_param["valueCodeableConcept"]["coding"][0]["code"] == "no-longer-clinically-eligible"


# ---------------------------------------------------------------------------
# report_data
# ---------------------------------------------------------------------------

# report_data is now implemented; see tests/test_report_data.py for its coverage.


# ---------------------------------------------------------------------------
# poll_submission_status
# ---------------------------------------------------------------------------

class TestPollSubmissionStatus:
    def test_returns_status_code_and_body_tuple(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"resourceType": "Parameters"}'
        mock_response.json.return_value = {"resourceType": "Parameters", "parameter": []}
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            result = poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert isinstance(result, tuple)
        status_code, body = result
        assert status_code == 200
        assert body["resourceType"] == "Parameters"

    def test_returns_202_with_empty_body_for_in_progress(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.text = ""
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status_code, body = poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert status_code == 202
        assert body == {}
        mock_response.raise_for_status.assert_not_called()

    def test_returns_4xx_terminal_without_raising(self):
        """Per OM, a 4xx on $submission-status is terminal — returned to the caller, not raised."""
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock(); mock_http.headers = {}
        resp = MagicMock()
        resp.status_code = 404
        resp.text = '{"resourceType":"OperationOutcome"}'
        resp.json.return_value = {"resourceType": "OperationOutcome"}
        mock_http.get.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            code, body = poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")
        assert code == 404
        assert body["resourceType"] == "OperationOutcome"
        resp.raise_for_status.assert_not_called()

    def test_raises_runtime_error_on_5xx_transient(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock(); mock_http.headers = {}
        resp = MagicMock(); resp.status_code = 503; resp.text = "upstream down"
        mock_http.get.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="transient"):
                poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

    def test_does_not_raise_on_202(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.text = ""
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        mock_response.raise_for_status.assert_not_called()

    def test_gets_status_url_with_bearer_token(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"resourceType": "Parameters"}'
        mock_response.json.return_value = {"resourceType": "Parameters"}
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert mock_http.get.call_args[0][0] == "https://api.cms.gov/status/abc"
        headers = mock_http.get.call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer tok"


# ---------------------------------------------------------------------------
# _parse_operation_outcome
# ---------------------------------------------------------------------------

class TestParseOperationOutcome:
    def test_extracts_detail_text(self):
        from cms_access_fhir_client.cms_client import _parse_operation_outcome
        body = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Bad ID"}}],
        }
        assert _parse_operation_outcome(body) == "Bad ID"

    def test_returns_unknown_error_for_empty_issues(self):
        from cms_access_fhir_client.cms_client import _parse_operation_outcome
        assert _parse_operation_outcome({"issue": []}) == "Unknown error"
        assert _parse_operation_outcome({}) == "Unknown error"
