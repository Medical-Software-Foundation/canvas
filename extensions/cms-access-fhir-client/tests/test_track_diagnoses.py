"""Tests for ACCESS track diagnosis value-set matching."""
from cms_access_fhir_client.track_diagnoses import (
    TRACK_DIAGNOSIS_CODES,
    canonical_code_for_track,
)


class TestCanonicalCodeForTrack:
    def test_matches_undotted_canvas_code_to_dotted_canonical(self):
        # Canvas stores "E119"; CKM value set publishes "E11.9"
        assert canonical_code_for_track("CKM", "E119") == "E11.9"

    def test_matches_already_dotted_code(self):
        assert canonical_code_for_track("CKM", "E11.9") == "E11.9"

    def test_matches_longer_code(self):
        assert canonical_code_for_track("CKM", "E11649") == "E11.649"

    def test_is_case_insensitive(self):
        assert canonical_code_for_track("CKM", "e119") == "E11.9"

    def test_returns_none_for_non_qualifying_code(self):
        # Orca bite is not a CKM diagnosis
        assert canonical_code_for_track("CKM", "W5621XA") is None

    def test_returns_none_for_unknown_track(self):
        assert canonical_code_for_track("NOPE", "E119") is None

    def test_track_sets_are_populated(self):
        # Guard against an empty/regeneration failure — counts are IG v0.9.12.
        assert len(TRACK_DIAGNOSIS_CODES["eCKM"]) == 45
        assert len(TRACK_DIAGNOSIS_CODES["CKM"]) == 688
        assert len(TRACK_DIAGNOSIS_CODES["MSK"]) == 2495
        assert len(TRACK_DIAGNOSIS_CODES["BH"]) == 69
        # eCKM dropped the I67.x cerebral-atherosclerosis codes in v0.9.12.
        assert not any(c.startswith("I67") for c in TRACK_DIAGNOSIS_CODES["eCKM"])
