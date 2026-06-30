"""Tests for group_therapy.protocols.billing_assessment_linker."""

from unittest.mock import MagicMock, call, patch

from group_therapy.protocols.billing_assessment_linker import BillingAssessmentLinker


class TestBillingAssessmentLinker:
    def test_links_assessment_to_billing_line_item(self, mock_command):
        mock_assessment = MagicMock()
        mock_assessment.id = "assessment-uuid-456"
        mock_bli = MagicMock()
        mock_bli.id = "bli-uuid-789"

        with (
            patch(
                "group_therapy.protocols.billing_assessment_linker.Command.objects"
            ) as mock_cmd_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.Assessment.objects"
            ) as mock_assess_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.BillingLineItem.objects"
            ) as mock_bli_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.load_config"
            ) as mock_load_config,
            patch(
                "group_therapy.protocols.billing_assessment_linker.billing_cpt_codes",
                return_value=["90853", "90832"],
            ),
            patch(
                "group_therapy.protocols.billing_assessment_linker.UpdateBillingLineItem"
            ) as mock_update_bli,
        ):
            mock_cmd_objects.get.return_value = mock_command
            mock_assess_objects.filter.return_value.first.return_value = mock_assessment
            mock_bli_objects.filter.return_value.first.return_value = mock_bli
            mock_load_config.return_value = {}

            handler = BillingAssessmentLinker()
            handler.event = MagicMock()
            handler.event.target = "command-uuid-123"

            effects = handler.compute()

            assert mock_cmd_objects.mock_calls == [call.get(id="command-uuid-123")]
            assert mock_assess_objects.mock_calls == [
                call.filter(note_id="note-db-id-123"),
                call.filter().first(),
                call.filter().first().__bool__(),
            ]
            assert mock_bli_objects.mock_calls == [
                call.filter(note=mock_command.note, cpt__in=["90853", "90832"]),
                call.filter().first(),
                call.filter().first().__bool__(),
            ]
            assert mock_update_bli.mock_calls == [
                call(
                    billing_line_item_id="bli-uuid-789",
                    assessment_ids=["assessment-uuid-456"],
                ),
                call().apply(),
            ]
            assert len(effects) == 1

    def test_no_assessment_found_returns_empty(self, mock_command):
        with (
            patch(
                "group_therapy.protocols.billing_assessment_linker.Command.objects"
            ) as mock_cmd_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.Assessment.objects"
            ) as mock_assess_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.BillingLineItem.objects"
            ) as mock_bli_objects,
        ):
            mock_cmd_objects.get.return_value = mock_command
            mock_assess_objects.filter.return_value.first.return_value = None

            handler = BillingAssessmentLinker()
            handler.event = MagicMock()
            handler.event.target = "command-uuid-123"

            effects = handler.compute()

            assert mock_cmd_objects.mock_calls == [call.get(id="command-uuid-123")]
            assert mock_assess_objects.mock_calls == [
                call.filter(note_id="note-db-id-123"),
                call.filter().first(),
            ]
            assert mock_bli_objects.mock_calls == []
            assert effects == []

    def test_no_billing_line_item_returns_empty(self, mock_command):
        mock_assessment = MagicMock()
        mock_assessment.id = "assessment-uuid-456"

        with (
            patch(
                "group_therapy.protocols.billing_assessment_linker.Command.objects"
            ) as mock_cmd_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.Assessment.objects"
            ) as mock_assess_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.BillingLineItem.objects"
            ) as mock_bli_objects,
            patch(
                "group_therapy.protocols.billing_assessment_linker.load_config"
            ) as mock_load_config,
            patch(
                "group_therapy.protocols.billing_assessment_linker.billing_cpt_codes",
                return_value=["90853", "90832"],
            ),
        ):
            mock_cmd_objects.get.return_value = mock_command
            mock_assess_objects.filter.return_value.first.return_value = mock_assessment
            mock_bli_objects.filter.return_value.first.return_value = None
            mock_load_config.return_value = {}

            handler = BillingAssessmentLinker()
            handler.event = MagicMock()
            handler.event.target = "command-uuid-123"

            effects = handler.compute()

            assert mock_cmd_objects.mock_calls == [call.get(id="command-uuid-123")]
            assert mock_assess_objects.mock_calls == [
                call.filter(note_id="note-db-id-123"),
                call.filter().first(),
                call.filter().first().__bool__(),
            ]
            assert mock_bli_objects.mock_calls == [
                call.filter(note=mock_command.note, cpt__in=["90853", "90832"]),
                call.filter().first(),
            ]
            assert effects == []
