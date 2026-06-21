"""Tests for the MSK/BH questionnaire-based $report-data bundle builders."""
from cms_access_fhir_client.report_data import (
    _SECTION_CS,
    _TRACK_CS,
    TRACK_INSTRUMENTS,
    _questionnaire_response_resource,
    build_data_bundle,
)

_LOINC = "http://loinc.org"
_PATIENT = {"resourceType": "Patient", "id": "p-1"}
_PRACT = {"resourceType": "Practitioner", "id": "pr-1"}
_ORG = {"resourceType": "Organization", "id": "org-1"}


class TestInstrumentRegistry:
    def test_bh_section_codes_match_om(self):
        bh = {code: (system, title) for code, system, title, _ in TRACK_INSTRUMENTS["BH"]}
        # OM v0.9.11 BH Composition example codes
        assert bh["44249-1"][0] == _LOINC          # PHQ-9
        assert bh["69737-5"][0] == _LOINC          # GAD-7
        assert bh["WHODAS"][0] == _SECTION_CS       # ACCESS CodeSystem
        assert bh["PGIC"][0] == _SECTION_CS

    def test_msk_section_codes_match_om(self):
        msk = {code: system for code, system, _t, _l in TRACK_INSTRUMENTS["MSK"]}
        assert msk["76804-4"] == _LOINC   # PROMIS-PF SF6b
        assert msk["97908-8"] == _LOINC   # Oswestry
        assert msk["82324-5"] == _LOINC   # KOOS JR
        assert msk["82316-1"] == _LOINC   # HOOS JR
        assert msk["QuickDASH"] == _SECTION_CS
        assert msk["PGIC"] == _SECTION_CS


class TestQuestionnaireResponseResource:
    def test_builds_us_core_qr_with_item_and_ordinal(self):
        instrument = ("44249-1", _LOINC, "Depression (PHQ-9)", "44249-1")
        response = {
            "narrative": "Depression (PHQ-9). Score: 12.",
            "authored": "2026-06-01T10:00:00Z",
            "items": [
                {"linkId": "q1", "text": "Little interest",
                 "answer_code": "LA6568-5", "answer_system": _LOINC,
                 "answer_display": "Several days", "ordinal": 1.0},
            ],
        }
        qr = _questionnaire_response_resource("qr-x", instrument, response, "Patient/p-1", "2026-06-13T00:00:00Z")
        assert qr["resourceType"] == "QuestionnaireResponse"
        assert qr["status"] == "completed"
        assert qr["authored"] == "2026-06-01T10:00:00Z"  # uses response authored, not fallback
        assert "us-core-questionnaireresponse" in qr["meta"]["profile"][0]
        # US Core requires the `questionnaire` canonical — always present.
        assert qr["questionnaire"].endswith("/44249-1")
        item = qr["item"][0]
        assert item["linkId"] == "q1"
        coding = item["answer"][0]["valueCoding"]
        assert coding["code"] == "LA6568-5"
        assert coding["extension"][0]["valueDecimal"] == 1.0

    def test_free_text_answer(self):
        instrument = ("PGIC", _SECTION_CS, "PGIC", None)
        response = {"items": [{"linkId": "q1", "text": "How are you?", "answer_text": "Much better"}]}
        qr = _questionnaire_response_resource("qr-p", instrument, response, "Patient/p-1", "2026-06-13T00:00:00Z")
        assert qr["item"][0]["answer"][0]["valueString"] == "Much better"
        assert qr["authored"] == "2026-06-13T00:00:00Z"  # fallback when none on response


class TestBuildQuestionnaireBundle:
    def _bundle(self, responses):
        return build_data_bundle(
            track="BH", patient_resource=_PATIENT, practitioner=_PRACT, organization=_ORG,
            responses=responses, bundle_id="b-1", timestamp="2026-06-13T12:00:00Z",
        )

    def test_track_section_and_subsections(self):
        bundle = self._bundle({
            "44249-1": {"narrative": "PHQ-9", "items": []},
            "69737-5": {"narrative": "GAD-7", "items": []},
            "PGIC": {"narrative": "PGIC", "items": []},
        })
        comp = bundle["entry"][0]["resource"]
        track_section = comp["section"][0]
        assert track_section["code"]["coding"][0] == {"system": _TRACK_CS, "code": "BH"}
        subs = {s["code"]["coding"][0]["code"]: s["code"]["coding"][0]["system"] for s in track_section["section"]}
        assert subs["44249-1"] == _LOINC
        assert subs["69737-5"] == _LOINC
        assert subs["PGIC"] == _SECTION_CS
        # Each subsection reference must EXACTLY equal a bundle entry's fullUrl (absolute,
        # so the doc-Bundle reference-resolution constraint is satisfied).
        full_urls = {e["fullUrl"] for e in bundle["entry"]}
        for s in track_section["section"]:
            ref = s["entry"][0]["reference"]
            assert ref in full_urls
            assert ref.startswith("https://")

    def test_embeds_questionnaire_so_canonical_resolves(self):
        # CMS rejects an unresolvable QR.questionnaire canonical. The bundle must embed a
        # Questionnaire whose url == the QR's questionnaire canonical.
        bundle = self._bundle({"44249-1": {"narrative": "PHQ-9", "items": [
            {"linkId": "q1", "text": "Little interest", "answer_code": "LA6568-5",
             "answer_system": _LOINC, "answer_display": "Several days", "ordinal": 1.0},
        ]}})
        qr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "QuestionnaireResponse")
        questionnaires = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Questionnaire"]
        assert len(questionnaires) == 1
        q = questionnaires[0]
        assert q["url"] == qr["questionnaire"]          # canonical resolves within the bundle
        assert q["status"] == "active"
        # Questionnaire item linkIds cover the QR's items
        q_links = {it["linkId"] for it in q["item"]}
        assert "q1" in q_links

    def test_missing_instruments_omitted_but_track_section_present(self):
        bundle = self._bundle({})  # no responses gathered
        comp = bundle["entry"][0]["resource"]
        track_section = comp["section"][0]
        assert track_section["code"]["coding"][0]["code"] == "BH"   # track section always present
        assert track_section.get("section", []) == []               # no subsections
        # No QuestionnaireResponse resources when nothing gathered.
        assert not [e for e in bundle["entry"] if e["resource"]["resourceType"] == "QuestionnaireResponse"]
