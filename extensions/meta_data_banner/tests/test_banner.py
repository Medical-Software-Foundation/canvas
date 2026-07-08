"""Tests for the shared banner-building helpers."""
from meta_data_banner.banner import build_banner_for_patient, banner_effect_for_patient
from tests.conftest import make_metadata_entry


class TestBuildBannerForPatient:
    def test_single_variable(self, mock_patient):
        assert build_banner_for_patient(mock_patient, "Status: {ccm_diagnosis}") is not None

    def test_multiple_variables(self, mock_patient):
        banner = build_banner_for_patient(
            mock_patient, "{ccm_diagnosis} | Risk: {risk_score}"
        )
        assert banner is not None

    def test_missing_key_returns_none(self, mock_patient):
        assert build_banner_for_patient(mock_patient, "Program: {nonexistent_key}") is None

    def test_partial_keys_returns_none(self, mock_patient):
        """If template references two keys but patient only has one, no banner."""
        assert build_banner_for_patient(mock_patient, "{ccm_diagnosis} | {missing_key}") is None

    def test_blank_value_returns_none(self, mock_patient):
        mock_patient.metadata.all.return_value = [make_metadata_entry("ccm_diagnosis", "")]
        assert build_banner_for_patient(mock_patient, "Status: {ccm_diagnosis}") is None

    def test_whitespace_value_returns_none(self, mock_patient):
        mock_patient.metadata.all.return_value = [make_metadata_entry("ccm_diagnosis", "   ")]
        assert build_banner_for_patient(mock_patient, "Status: {ccm_diagnosis}") is None

    def test_none_value_returns_none(self, mock_patient):
        mock_patient.metadata.all.return_value = [make_metadata_entry("ccm_diagnosis", None)]
        assert build_banner_for_patient(mock_patient, "Status: {ccm_diagnosis}") is None

    def test_no_variables_in_template_returns_none(self, mock_patient):
        assert build_banner_for_patient(mock_patient, "Static text with no variables") is None

    def test_no_metadata_returns_none(self, mock_patient):
        mock_patient.metadata.all.return_value = []
        assert build_banner_for_patient(mock_patient, "Status: {ccm_diagnosis}") is None

    def test_long_narrative_is_truncated(self, mock_patient):
        """Narratives over 90 chars are truncated to 87 chars plus an ellipsis."""
        import meta_data_banner.banner as banner_mod

        banner_mod.AddBannerAlert.reset_mock()
        mock_patient.metadata.all.return_value = [
            make_metadata_entry("ccm_diagnosis", "A" * 200)
        ]

        build_banner_for_patient(mock_patient, "{ccm_diagnosis}")

        _, add_kwargs = banner_mod.AddBannerAlert.call_args
        assert len(add_kwargs["narrative"]) == 90
        assert add_kwargs["narrative"].endswith("...")


class TestBannerEffectForPatient:
    def test_match_produces_add_effect(self, mock_patient):
        """A patient whose metadata fills the template gets an AddBannerAlert."""
        import meta_data_banner.banner as banner_mod

        banner_mod.AddBannerAlert.reset_mock()
        banner_mod.RemoveBannerAlert.reset_mock()

        banner_effect_for_patient(mock_patient, "Status: {ccm_diagnosis}")

        assert banner_mod.AddBannerAlert.called
        assert not banner_mod.RemoveBannerAlert.called

    def test_no_match_produces_remove_effect(self, mock_patient):
        """A patient missing metadata gets a RemoveBannerAlert to clear stale banners."""
        import meta_data_banner.banner as banner_mod

        banner_mod.AddBannerAlert.reset_mock()
        banner_mod.RemoveBannerAlert.reset_mock()
        mock_patient.metadata.all.return_value = []

        banner_effect_for_patient(mock_patient, "Status: {ccm_diagnosis}")

        assert banner_mod.RemoveBannerAlert.called
        assert not banner_mod.AddBannerAlert.called
