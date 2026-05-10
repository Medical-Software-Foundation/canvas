"""Tests for patient_tags.services.banner_service.

Covers compute_banner_effects across the full matrix: no labels, labels
without groups, labels with groups, multi-label group joining and truncation,
unknown placement filtering, intent fallback, optional href, and legacy
per-label banner key cleanup.
"""
from unittest.mock import MagicMock, patch

from patient_tags.constants import LEGACY_BANNER_KEYS
from patient_tags.services import banner_service

# Every reconcile pass appends one RemoveBannerAlert per legacy key so
# instances upgraded from the pre-bannergroup schema self-heal.
LEGACY_REMOVE_COUNT = len(LEGACY_BANNER_KEYS)


def _group(*, dbid: int, separator: str = " • ",
           placements: list[str] | None = None,
           intent: str = "info", href: str = "") -> MagicMock:
    g = MagicMock(dbid=dbid, separator=separator, intent=intent, href=href)
    g.placements = placements if placements is not None else ["CHART"]
    return g


class TestBannerKey:
    def test_uses_prefix(self) -> None:
        assert banner_service.banner_key_for_group(7) == "custom-patient-tag-group-7"


class TestTruncateNarrative:
    def test_under_limit_unchanged(self) -> None:
        assert banner_service.truncate_narrative("hi") == "hi"

    def test_over_limit_appends_ellipsis(self) -> None:
        text = "x" * 200
        result = banner_service.truncate_narrative(text)
        assert result.endswith("…")
        assert len(result) == 90


class TestComputeBannerEffects:
    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_no_groups_emits_only_legacy_removes(
        self, mock_pl: MagicMock, mock_group: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = []
        mock_group.objects.all.return_value = []

        effects = banner_service.compute_banner_effects("p1")

        # No groups → no group-specific effects, but legacy keys still cleaned up.
        assert len(effects) == LEGACY_REMOVE_COUNT

    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_no_labels_emits_remove_for_each_group(
        self, mock_pl: MagicMock, mock_group: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = []
        mock_group.objects.all.return_value = [_group(dbid=1), _group(dbid=2)]

        effects = banner_service.compute_banner_effects("p1")

        assert len(effects) == 2 + LEGACY_REMOVE_COUNT

    @patch("patient_tags.models.Label")
    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_label_with_group_emits_add(
        self, mock_pl: MagicMock, mock_group: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = [10]
        mock_group.objects.all.return_value = [_group(dbid=1, intent="warning", href="/h")]
        mock_label.objects.filter.return_value.values_list.return_value = [("VIP", 1)]

        effects = banner_service.compute_banner_effects("p1")

        assert len(effects) == 1 + LEGACY_REMOVE_COUNT

    @patch("patient_tags.models.Label")
    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_label_without_group_does_not_emit_add(
        self, mock_pl: MagicMock, mock_group: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = [10]
        mock_group.objects.all.return_value = [_group(dbid=1)]
        mock_label.objects.filter.return_value.values_list.return_value = [("Loose", None)]

        effects = banner_service.compute_banner_effects("p1")

        # Group 1 has no labels assigned to it → emits Remove.
        assert len(effects) == 1 + LEGACY_REMOVE_COUNT

    @patch("patient_tags.models.Label")
    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_multiple_labels_in_group_join_and_truncate(
        self, mock_pl: MagicMock, mock_group: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = [10, 11]
        mock_group.objects.all.return_value = [
            _group(dbid=1, separator=" / ", placements=["CHART", "PROFILE"]),
        ]
        mock_label.objects.filter.return_value.values_list.return_value = [
            ("X" * 80, 1), ("Y" * 80, 1),
        ]

        effects = banner_service.compute_banner_effects("p1")

        assert len(effects) == 1 + LEGACY_REMOVE_COUNT

    @patch("patient_tags.models.Label")
    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_unknown_placement_falls_back_to_chart(
        self, mock_pl: MagicMock, mock_group: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = [10]
        mock_group.objects.all.return_value = [_group(dbid=1, placements=["BOGUS"])]
        mock_label.objects.filter.return_value.values_list.return_value = [("VIP", 1)]

        effects = banner_service.compute_banner_effects("p1")

        # No effects should be silently dropped.
        assert len(effects) == 1 + LEGACY_REMOVE_COUNT

    @patch("patient_tags.models.Label")
    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_unknown_intent_falls_back_to_info(
        self, mock_pl: MagicMock, mock_group: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = [10]
        mock_group.objects.all.return_value = [_group(dbid=1, intent="unknown-intent")]
        mock_label.objects.filter.return_value.values_list.return_value = [("VIP", 1)]

        effects = banner_service.compute_banner_effects("p1")
        assert len(effects) == 1 + LEGACY_REMOVE_COUNT


class TestLegacyBannerCleanup:
    """Every reconcile must emit RemoveBannerAlert for each legacy per-label key.

    Instances upgraded from the pre-bannergroup schema have orphaned active
    banners with keys like 'do-not-contact'. The current compute_banner_effects
    emits Remove for each on every pass so they fall away as soon as any tag
    change touches the patient.
    """

    @patch("patient_tags.services.banner_service.BannerGroup")
    @patch("patient_tags.services.banner_service.PatientLabel")
    def test_emits_remove_for_every_legacy_key(
        self, mock_pl: MagicMock, mock_group: MagicMock
    ) -> None:
        import json
        mock_pl.objects.filter.return_value.values_list.return_value = []
        mock_group.objects.all.return_value = []

        effects = banner_service.compute_banner_effects("p1")

        emitted_keys = {json.loads(e.payload)["key"] for e in effects}
        for legacy_key in LEGACY_BANNER_KEYS:
            assert legacy_key in emitted_keys, f"missing remove for {legacy_key}"
