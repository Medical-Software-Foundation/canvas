from unittest.mock import MagicMock, PropertyMock, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from patient_tags.handlers.banner_sync import BannerSyncHandler
from patient_tags.handlers.tag_button import PatientTagButton
from patient_tags.services.banner_service import (
    banner_key_for_group,
    truncate_narrative,
)


class TestPatientTagButton:
    def test_button_metadata(self) -> None:
        from canvas_sdk.handlers.action_button import ActionButton

        assert PatientTagButton.BUTTON_LOCATION == ActionButton.ButtonLocation.CHART_PATIENT_HEADER
        assert PatientTagButton.BUTTON_KEY == "patient_tags_button"

    @patch("patient_tags.handlers.tag_button.get_patient_assignment_ids")
    def test_button_title_includes_count_when_assigned(self, mock_get: MagicMock) -> None:
        mock_get.return_value = [1, 2, 3]
        button = PatientTagButton.__new__(PatientTagButton)
        button.event = MagicMock()
        button.event.target.id = "p1"
        assert button.BUTTON_TITLE == "Tags (3)"

    @patch("patient_tags.handlers.tag_button.get_patient_assignment_ids")
    def test_button_title_plain_when_none_assigned(self, mock_get: MagicMock) -> None:
        mock_get.return_value = []
        button = PatientTagButton.__new__(PatientTagButton)
        button.event = MagicMock()
        button.event.target.id = "p1"
        assert button.BUTTON_TITLE == "Tags"

    @patch("patient_tags.handlers.tag_button.get_patient_assignment_ids")
    @patch("patient_tags.handlers.tag_button.list_banner_groups")
    @patch("patient_tags.handlers.tag_button.list_labels")
    @patch(
        "patient_tags.handlers.tag_button.render_to_string",
        return_value="<html></html>",
    )
    def test_handle_renders_modal_with_patient_context(
        self,
        mock_render: MagicMock,
        mock_list_labels: MagicMock,
        mock_list_groups: MagicMock,
        mock_get_assignments: MagicMock,
    ) -> None:
        mock_list_labels.return_value = [
            {"id": 1, "name": "X", "assignable_in_chart": True, "assignable_in_profile": False,
             "color": "blue", "description": "", "banner_group_id": None, "banner_group_name": None},
            {"id": 2, "name": "Y", "assignable_in_chart": False, "assignable_in_profile": True,
             "color": "red", "description": "", "banner_group_id": None, "banner_group_name": None},
        ]
        mock_list_groups.return_value = []
        mock_get_assignments.return_value = [1]

        button = PatientTagButton.__new__(PatientTagButton)
        event = MagicMock()
        event.target.id = "patient-abc"
        button.event = event

        effects = button.handle()

        assert len(effects) == 1
        assert effects[0].type == EffectType.LAUNCH_MODAL
        mock_get_assignments.assert_called_once_with("patient-abc")
        # All labels pass through; the frontend filters by assignable_in_*
        # for the Available pill section (Manage Labels tab needs the full list).
        ctx = mock_render.call_args.args[1]
        import json
        assert [l["id"] for l in json.loads(ctx["labels_json"])] == [1, 2]


class TestBannerSyncHandler:
    def test_responds_to_patient_updated(self) -> None:
        assert EventType.Name(EventType.PATIENT_UPDATED) in BannerSyncHandler.RESPONDS_TO

    @patch("patient_tags.handlers.banner_sync.compute_banner_effects")
    @patch.object(
        BannerSyncHandler, "target", new_callable=PropertyMock, return_value="patient-9"
    )
    def test_compute_delegates_to_service(
        self, mock_target: PropertyMock, mock_compute: MagicMock
    ) -> None:
        mock_compute.return_value = [MagicMock()]
        handler = BannerSyncHandler.__new__(BannerSyncHandler)

        effects = handler.compute()

        mock_compute.assert_called_once_with("patient-9")
        assert len(effects) == 1


class TestBannerServiceHelpers:
    def test_banner_key_format(self) -> None:
        assert banner_key_for_group(42) == "custom-patient-tag-group-42"

    def test_truncate_narrative_under_limit(self) -> None:
        text = "Do Not Contact"
        assert truncate_narrative(text) == text

    def test_truncate_narrative_over_limit_appends_ellipsis(self) -> None:
        text = "x" * 120
        result = truncate_narrative(text)
        assert len(result) <= 90
        assert result.endswith("…")


class TestRuleConflictValidation:
    """create_rule must block opposing rules for the same trigger+target."""

    @patch("patient_tags.services.label_service.LabelRule")
    @patch("patient_tags.services.label_service.Label")
    def test_blocks_opposing_action_on_same_trigger_target(
        self, mock_label: MagicMock, mock_rule: MagicMock
    ) -> None:
        from patient_tags.services.label_service import create_rule

        mock_label.objects.filter.return_value.exists.return_value = True
        # First .exists() call (duplicate check) → False; second (conflict check) → True.
        mock_rule.objects.filter.return_value.exists.side_effect = [False, True]

        try:
            create_rule(trigger_label_id=1, action="auto_assign", target_label_id=2)
        except ValueError as exc:
            assert "Conflict" in str(exc)
        else:
            raise AssertionError("expected ValueError")


class TestRuleApplication:
    """Direct unit tests for the _apply_rules_for_triggers conflict-resolution logic."""

    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.LabelRule")
    def test_no_rules_is_noop(self, mock_rule: MagicMock, mock_pl: MagicMock) -> None:
        from patient_tags.services.label_service import _apply_rules_for_triggers

        mock_rule.objects.filter.return_value = []
        _apply_rules_for_triggers(MagicMock(), [1])

        mock_pl.objects.create.assert_not_called()
        mock_pl.objects.filter.assert_not_called()

    @patch("patient_tags.services.label_service.PatientLabelAudit")
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.LabelRule")
    def test_auto_remove_wins_over_auto_assign_for_same_target(
        self,
        mock_rule: MagicMock,
        mock_pl: MagicMock,
        mock_label: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        from patient_tags.services.label_service import _apply_rules_for_triggers

        # Trigger 1 → auto_assign target 99
        # Trigger 2 → auto_remove target 99
        rule_assign = MagicMock(action="auto_assign", target_label_id=99)
        rule_remove = MagicMock(action="auto_remove", target_label_id=99)
        mock_rule.objects.filter.return_value = [rule_assign, rule_remove]
        # Patient currently has 99 assigned (so it's in current set, removable).
        mock_pl.objects.filter.return_value.values_list.return_value = [99]
        mock_label.objects.filter.return_value.values.return_value = []

        patient = MagicMock()
        _apply_rules_for_triggers(patient, [1, 2])

        # Remove was called for {99}; create should NOT have been called.
        mock_pl.objects.create.assert_not_called()
        delete_calls = [c for c in mock_pl.objects.filter.call_args_list]
        assert any("label_id__in" in str(c) for c in delete_calls)
