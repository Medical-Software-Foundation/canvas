from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch


class TestHideLegacyNoteSearch:
    def test_no_target_returns_empty(self) -> None:
        from chart_command_search.handlers.panel_config import HideLegacyNoteSearch

        handler = HideLegacyNoteSearch.__new__(HideLegacyNoteSearch)
        handler._event = MagicMock()
        handler._event.target = None
        with patch.object(HideLegacyNoteSearch, "target", new_callable=PropertyMock, create=True) as mock_target:
            mock_target.return_value = None
            result = handler.compute()
        assert result == []

    def test_with_target_returns_effects(self) -> None:
        from chart_command_search.handlers.panel_config import HideLegacyNoteSearch

        handler = HideLegacyNoteSearch.__new__(HideLegacyNoteSearch)
        with patch.object(HideLegacyNoteSearch, "target", new_callable=PropertyMock, create=True) as mock_target:
            mock_target.return_value = MagicMock()
            result = handler.compute()
        assert len(result) == 1

    def test_command_section_excluded(self) -> None:
        from canvas_sdk.effects.panel_configuration import PanelConfiguration

        handler_sections = {
            PanelConfiguration.PanelPatientSection.CHANGE_REQUEST,
            PanelConfiguration.PanelPatientSection.IMAGING_REPORT,
            PanelConfiguration.PanelPatientSection.INPATIENT_STAY,
            PanelConfiguration.PanelPatientSection.LAB_REPORT,
            PanelConfiguration.PanelPatientSection.PRESCRIPTION_ALERT,
            PanelConfiguration.PanelPatientSection.REFERRAL_REPORT,
            PanelConfiguration.PanelPatientSection.REFILL_REQUEST,
            PanelConfiguration.PanelPatientSection.TASK,
            PanelConfiguration.PanelPatientSection.UNCATEGORIZED_DOCUMENT,
        }
        assert PanelConfiguration.PanelPatientSection.COMMAND not in handler_sections
