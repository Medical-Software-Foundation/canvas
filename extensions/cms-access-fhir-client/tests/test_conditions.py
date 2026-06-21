"""Tests for building track-qualifying Condition resources from the problem list."""
from unittest.mock import MagicMock, patch


def _coding(system, code, display=""):
    c = MagicMock()
    c.system = system
    c.code = code
    c.display = display
    return c


def _condition(*codings):
    cond = MagicMock()
    cond.codings.all.return_value = list(codings)
    return cond


def _patch_conditions(conditions):
    """Patch Condition.objects.for_patient(...).active().prefetch_related(...) -> conditions."""
    qs = MagicMock()
    qs.active.return_value = qs
    qs.prefetch_related.return_value = conditions
    objects = MagicMock()
    objects.for_patient.return_value = qs
    return patch("cms_access_fhir_client.conditions.Condition.objects", objects)


class TestBuildTrackConditions:
    def test_emits_dotted_code_for_qualifying_diagnosis(self):
        from cms_access_fhir_client.conditions import build_track_conditions

        patient = MagicMock()
        patient.id = "pat-1"
        conditions = [_condition(_coding("ICD-10", "E119", "Type 2 diabetes mellitus"))]

        with _patch_conditions(conditions):
            resources = build_track_conditions(patient, "CKM", patient_fhir_id="pat-1")

        assert len(resources) == 1
        r = resources[0]
        coding = r["code"]["coding"][0]
        assert coding["system"] == "http://hl7.org/fhir/sid/icd-10-cm"
        assert coding["code"] == "E11.9"  # dotted canonical, not the stored "E119"
        assert coding["display"] == "Type 2 diabetes mellitus"
        assert r["subject"]["reference"] == "Patient/pat-1"
        # IMPL requires meta.profile (track-specific) + status/category fields
        assert r["meta"]["profile"] == ["https://dsacms.github.io/cmmi-access-model/StructureDefinition/access-ckm-condition"]
        assert r["clinicalStatus"]["coding"][0]["code"] == "active"
        assert r["category"][0]["coding"][0]["code"] == "problem-list-item"

    def test_falls_back_to_all_active_icd10_when_none_qualify(self):
        # Hybrid gate-softening: no CKM-qualifying code → send ALL active ICD-10 so a stale
        # value set can't block a valid alignment; non-ICD-10 systems are still skipped.
        from cms_access_fhir_client.conditions import build_track_conditions

        patient = MagicMock()
        patient.id = "pat-2"
        conditions = [
            _condition(_coding("ICD-10", "W5621XA", "Bitten by orca")),  # not CKM but active ICD-10
            _condition(_coding("SNOMED", "44054006", "Diabetes")),  # wrong system → skipped
        ]

        with _patch_conditions(conditions):
            resources = build_track_conditions(patient, "CKM", patient_fhir_id="pat-2")

        codes = [r["code"]["coding"][0]["code"] for r in resources]
        assert codes == ["W56.21XA"]  # dotted fallback; SNOMED excluded

    def test_sends_only_qualifying_when_a_match_exists(self):
        # When a track-qualifying code is present, send ONLY it (no fallback to all active).
        from cms_access_fhir_client.conditions import build_track_conditions

        patient = MagicMock()
        patient.id = "pat-3"
        conditions = [
            _condition(_coding("ICD-10", "E119", "Type 2 diabetes")),    # CKM-qualifying
            _condition(_coding("ICD-10", "W5621XA", "Bitten by orca")),  # not CKM
        ]

        with _patch_conditions(conditions):
            resources = build_track_conditions(patient, "CKM", patient_fhir_id="pat-3")

        codes = [r["code"]["coding"][0]["code"] for r in resources]
        assert codes == ["E11.9"]  # only the qualifying code, not W56.21XA

    def test_deduplicates_repeated_qualifying_code(self):
        from cms_access_fhir_client.conditions import build_track_conditions

        patient = MagicMock()
        patient.id = "pat-3"
        conditions = [
            _condition(_coding("ICD-10", "E119")),
            _condition(_coding("ICD-10", "E11.9")),  # same code, dotted
        ]

        with _patch_conditions(conditions):
            resources = build_track_conditions(patient, "CKM", patient_fhir_id="pat-3")

        assert len(resources) == 1

    def test_returns_empty_when_patient_has_no_conditions(self):
        from cms_access_fhir_client.conditions import build_track_conditions

        patient = MagicMock()
        patient.id = "pat-4"

        with _patch_conditions([]):
            resources = build_track_conditions(patient, "CKM", patient_fhir_id="pat-4")

        assert resources == []


class TestBuildActiveConditions:
    def test_emits_all_active_icd10_conditions_dotted(self):
        from cms_access_fhir_client.conditions import build_active_conditions

        patient = MagicMock()
        patient.id = "pat-5"
        # N186 (ESRD) is not in any track value set, but is a valid disqualifying dx
        conditions = [_condition(_coding("ICD-10", "N186", "End stage renal disease"))]

        with _patch_conditions(conditions):
            resources = build_active_conditions(patient, patient_fhir_id="pat-5")

        assert len(resources) == 1
        r = resources[0]
        coding = r["code"]["coding"][0]
        assert coding["system"] == "http://hl7.org/fhir/sid/icd-10-cm"
        assert coding["code"] == "N18.6"  # dotted
        assert r["subject"]["reference"] == "Patient/pat-5"
        # disqualifying dx uses the clinical-exclusion profile
        assert r["meta"]["profile"] == ["https://dsacms.github.io/cmmi-access-model/StructureDefinition/access-clinical-exclusion-condition"]

    def test_skips_non_icd10_and_returns_empty_when_none(self):
        from cms_access_fhir_client.conditions import build_active_conditions

        patient = MagicMock()
        patient.id = "pat-6"

        with _patch_conditions([_condition(_coding("SNOMED", "123"))]):
            resources = build_active_conditions(patient, patient_fhir_id="pat-6")

        assert resources == []
