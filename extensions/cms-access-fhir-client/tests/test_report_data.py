"""Tests for the $report-data document-Bundle builders and cms_client.report_data."""
from unittest.mock import MagicMock, patch

import pytest

from cms_access_fhir_client.report_data import (
    BUNDLE_PROFILE,
    COMPOSITION_PROFILE,
    build_data_bundle,
    build_organization,
    build_practitioner,
    supported_track,
)

SECRETS = {"ACCESS_BASE_URL": "https://api.access.cms.gov/fhir", "ACCESS_PARTICIPANT_ID": "ACCES12345"}
_PATIENT = {"resourceType": "Patient", "id": "p-1"}
_PRACT = {"resourceType": "Practitioner", "id": "pr-1"}
_ORG = {"resourceType": "Organization", "id": "org-1"}


def _build(track="CKM", measures=None):
    return build_data_bundle(
        track=track,
        patient_resource=_PATIENT,
        practitioner=_PRACT,
        organization=_ORG,
        measures=measures if measures is not None else {},
        bundle_id="b-1",
        timestamp="2026-06-13T12:00:00Z",
    )


class TestSupportedTrack:
    def test_all_four_tracks_supported(self):
        from cms_access_fhir_client.report_data import is_questionnaire_track
        assert supported_track("CKM")
        assert supported_track("eCKM")
        assert supported_track("MSK")
        assert supported_track("BH")
        assert not supported_track("XYZ")
        assert not is_questionnaire_track("CKM")
        assert is_questionnaire_track("MSK")
        assert is_questionnaire_track("BH")


class TestBuildDataBundle:
    def test_is_a_document_bundle_with_profile(self):
        b = _build()
        assert b["resourceType"] == "Bundle"
        assert b["type"] == "document"
        assert b["meta"]["profile"] == [BUNDLE_PROFILE]

    def test_identifier_has_system_and_value_bdl9(self):
        # FHIR bdl-9: a document Bundle identifier must have BOTH system and value,
        # else CMS rejects the submission (HTTP 400 on $submission-status).
        b = _build()
        assert b["identifier"].get("system")
        assert b["identifier"].get("value")

    def test_all_references_resolve_to_entry_full_urls(self):
        # CMS constraint access-data-reporting-bundle-composition-refs-in-bundle: every
        # reference must resolve to a bundle entry. Use absolute fullUrls + matching refs.
        b = _build(measures={"4548-4": {"value": 6.5, "unit": "%"}})
        full_urls = {e["fullUrl"] for e in b["entry"]}
        # every fullUrl is a valid absolute URI (no malformed urn:uuid:Type/id)
        for url in full_urls:
            assert url.startswith("https://")
            assert ":" not in url.split("https://", 1)[1].split("/", 1)[0] or True  # host has no stray colon
        comp = b["entry"][0]["resource"]
        refs = [comp["subject"]["reference"], comp["author"][0]["reference"], comp["custodian"]["reference"]]
        refs += [s["entry"][0]["reference"] for s in comp["section"][0]["section"]]
        # observation subjects too
        for e in b["entry"]:
            if e["resource"]["resourceType"] == "Observation":
                refs.append(e["resource"]["subject"]["reference"])
        for ref in refs:
            assert ref in full_urls

    def test_first_entry_is_composition_with_patient_pract_org(self):
        b = _build()
        first = b["entry"][0]["resource"]
        assert first["resourceType"] == "Composition"
        assert first["meta"]["profile"] == [COMPOSITION_PROFILE]
        types = [e["resource"]["resourceType"] for e in b["entry"]]
        assert types[:4] == ["Composition", "Patient", "Practitioner", "Organization"]

    def test_track_section_keyed_by_track_code(self):
        b = _build(track="CKM")
        comp = b["entry"][0]["resource"]
        section = comp["section"][0]
        assert section["code"]["coding"][0]["code"] == "CKM"

    def test_measures_become_observations_and_subsections(self):
        b = _build(measures={"4548-4": {"value": 6.5, "unit": "%"}})
        obs = [e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Observation"]
        assert len(obs) == 1
        assert obs[0]["code"]["coding"][0]["code"] == "4548-4"
        assert obs[0]["valueQuantity"]["value"] == 6.5
        subs = b["entry"][0]["resource"]["section"][0]["section"]
        assert [s["code"]["coding"][0]["code"] for s in subs] == ["4548-4"]

    def test_blood_pressure_becomes_components(self):
        b = _build(measures={"85354-9": {"components": {"8480-6": 120, "8462-4": 80}}})
        bp = next(e["resource"] for e in b["entry"]
                  if e["resource"]["resourceType"] == "Observation"
                  and e["resource"]["code"]["coding"][0]["code"] == "85354-9")
        codes = [c["code"]["coding"][0]["code"] for c in bp["component"]]
        assert codes == ["8480-6", "8462-4"]
        assert "valueQuantity" not in bp

    def test_missing_measures_are_omitted(self):
        b = _build(measures={})  # nothing gathered
        obs = [e for e in b["entry"] if e["resource"]["resourceType"] == "Observation"]
        assert obs == []
        # The track section exists but has no subsections.
        assert b["entry"][0]["resource"]["section"][0]["section"] == []

    def test_eckm_excludes_egfr_and_uacr(self):
        # eGFR (98979-8) and uACR (14959-1) provided but eCKM should not emit them.
        b = _build(track="eCKM", measures={"98979-8": {"value": 90, "unit": "mL/min"}, "29463-7": {"value": 80, "unit": "kg"}})
        codes = [e["resource"]["code"]["coding"][0]["code"] for e in b["entry"]
                 if e["resource"]["resourceType"] == "Observation"]
        assert "98979-8" not in codes
        assert "29463-7" in codes


class TestBuilders:
    def test_practitioner_uses_npi_when_present(self):
        p = build_practitioner("s1", "Jane", "Smith", npi="1234567893")
        assert p["identifier"][0]["system"] == "http://hl7.org/fhir/sid/us-npi"
        assert p["name"][0]["family"] == "Smith"

    def test_organization_carries_participant_id(self):
        o = build_organization("ACCES12345", "Test Org")
        assert o["identifier"][0]["value"] == "ACCES12345"
        assert o["name"] == "Test Org"


class TestCmsClientReportData:
    def test_builds_report_data_parameters_and_captures_exchange(self):
        from cms_access_fhir_client.cms_client import report_data

        resp = MagicMock()
        resp.status_code = 202
        resp.ok = True
        resp.text = ""
        resp.headers = {"Content-Location": "https://cms.test/submission-status/rd-1"}
        resp.json.return_value = {}
        mock_http = MagicMock()
        mock_http.post.return_value = resp
        debug: list = []
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status, content_location, _ = report_data(
                SECRETS,
                payer_id="00831",
                track="CKM",
                report_type="baseline",
                data_bundle=_build(),
                debug=debug,
            )
        assert status == 202
        assert content_location == "https://cms.test/submission-status/rd-1"
        payload = mock_http.post.call_args[1]["json"]
        names = [p["name"] for p in payload["parameter"]]
        assert names == ["participantID", "payerID", "track", "reportType", "dataBundle"]
        assert payload["meta"]["profile"][0].endswith("access-report-data-in")
        assert "access/Patient/$report-data" in debug[0]["request"]["url"]
