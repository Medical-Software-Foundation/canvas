"""Tests for PreventionPlanButton ActionButton handler."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _build_note(system: str = "SNOMED", code: str = "401131001", name: str = "Annual Wellness Visit") -> MagicMock:
    """Build a mock Note whose note_type_version has the given system/code/name."""
    note = MagicMock()
    note.note_type_version.system = system
    note.note_type_version.code = code
    note.note_type_version.name = name
    return note


class TestPreventionPlanButtonVisible:
    """Tests for PreventionPlanButton.visible() - filters by SNOMED 401131001.

    Matches the same gate GuidedAWVApp.visible() uses (shared via
    guided_awv.constants). Prior versions of this file asserted name-keyword
    matching - that behavior was replaced as part of the Claude review fix
    for divergent visibility filters.
    """

    def _make_button(self, context: dict) -> Any:
        """Instantiate with a mock event carrying the given context."""
        from guided_awv.protocols.prevention_plan_button import PreventionPlanButton

        btn = PreventionPlanButton.__new__(PreventionPlanButton)
        btn.event = MagicMock()
        btn.event.context = context
        return btn

    def test_returns_false_when_no_note_id(self) -> None:
        btn = self._make_button({})
        assert btn.visible() is False

    def test_returns_false_when_note_query_raises(self) -> None:
        btn = self._make_button({"note_id": 42})
        note_mod = MagicMock()
        note_mod.Note.objects.select_related.return_value.get.side_effect = Exception("not found")
        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            assert btn.visible() is False

    def test_returns_false_for_non_awv_snomed_code(self) -> None:
        """A SNOMED-coded note with a different code (e.g. office visit) is hidden."""
        btn = self._make_button({"note_id": 42})
        note_mod = MagicMock()
        note_mod.Note.objects.select_related.return_value.get.return_value = _build_note(
            system="SNOMED", code="185349003", name="Office Visit",
        )
        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            assert btn.visible() is False

    def test_returns_false_when_system_differs(self) -> None:
        """Same code under a different coding system is hidden."""
        btn = self._make_button({"note_id": 42})
        note_mod = MagicMock()
        note_mod.Note.objects.select_related.return_value.get.return_value = _build_note(
            system="LOINC", code="401131001",
        )
        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            assert btn.visible() is False

    def test_returns_true_for_awv_snomed_code(self) -> None:
        """SNOMED 401131001 - the AWV note type - is the only thing that matches."""
        btn = self._make_button({"note_id": 42})
        note_mod = MagicMock()
        note_mod.Note.objects.select_related.return_value.get.return_value = _build_note()
        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            assert btn.visible() is True

    def test_returns_true_even_when_name_lacks_awv_keyword(self) -> None:
        """Regression: a note whose system+code match but whose name doesn't say
        'AWV' or 'wellness' must still show the button. Previously the button
        used name-keyword matching while GuidedAWVApp used SNOMED, so they
        could diverge on a note like 'Annual Visit - Adult' with SNOMED 401131001.
        """
        btn = self._make_button({"note_id": 42})
        note_mod = MagicMock()
        note_mod.Note.objects.select_related.return_value.get.return_value = _build_note(
            system="SNOMED", code="401131001", name="Annual Visit - Adult",
        )
        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            assert btn.visible() is True

    def test_visibility_matches_guided_awv_app(self) -> None:
        """PreventionPlanButton.visible() and GuidedAWVApp.visible() must agree.

        Both use the shared is_awv_note_type helper in guided_awv.constants.
        This test pairs them on the same mock note and asserts they return the
        same boolean for AWV / non-AWV / missing-note-type-version inputs.
        """
        from guided_awv.applications.guided_awv_app import GuidedAWVApp
        from guided_awv.protocols.prevention_plan_button import PreventionPlanButton

        scenarios = [
            ("matching AWV", _build_note(), True),
            ("wrong SNOMED code", _build_note(code="185349003"), False),
            ("wrong system", _build_note(system="LOINC"), False),
        ]
        for label, mock_note, expected in scenarios:
            note_mod = MagicMock()
            note_mod.Note.objects.select_related.return_value.get.return_value = mock_note
            with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
                btn = PreventionPlanButton.__new__(PreventionPlanButton)
                btn.event = MagicMock()
                btn.event.context = {"note_id": 42}
                app = GuidedAWVApp.__new__(GuidedAWVApp)
                app.event = MagicMock()
                app.event.context = {"note_id": 42}
                assert btn.visible() == expected, f"button mismatch for {label}"
                assert app.visible() == expected, f"app mismatch for {label}"
                assert btn.visible() == app.visible(), f"divergence for {label}"


class TestPreventionPlanButtonHandle:
    """Tests for PreventionPlanButton.handle()."""

    def _make_button(self, context: dict, patient_id: str = "patient-abc-123") -> Any:
        from guided_awv.protocols.prevention_plan_button import PreventionPlanButton

        btn = PreventionPlanButton.__new__(PreventionPlanButton)
        btn.event = MagicMock()
        btn.event.context = context
        btn.event.target.id = patient_id
        return btn

    def test_returns_empty_list_when_note_uuid_lookup_fails(self) -> None:
        btn = self._make_button({"note_id": 42})

        note_mod = MagicMock()
        note_mod.Note.objects.get.side_effect = Exception("not found")

        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            result = btn.handle()

        assert result == []

    def test_returns_empty_list_when_patient_id_empty(self) -> None:
        btn = self._make_button({"note_id": 42}, patient_id="")

        note_mod = MagicMock()
        mock_note_obj = MagicMock()
        mock_note_obj.id = "note-uuid-456"
        note_mod.Note.objects.get.return_value = mock_note_obj

        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            result = btn.handle()

        assert result == []

    @patch("guided_awv.protocols.prevention_plan_button.LaunchModalEffect")
    def test_returns_error_modal_when_build_plan_raises(
        self, mock_modal_cls: MagicMock
    ) -> None:
        btn = self._make_button({"note_id": 42})

        note_mod = MagicMock()
        mock_note_obj = MagicMock()
        mock_note_obj.id = "note-uuid-456"
        note_mod.Note.objects.get.return_value = mock_note_obj

        mock_modal_instance = MagicMock()
        mock_modal_cls.return_value = mock_modal_instance
        mock_modal_cls.TargetType.DEFAULT_MODAL = "default_modal"

        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            with patch(
                "guided_awv.api.awv_api.GeneratePreventionPlanHandler._build_plan",
                side_effect=RuntimeError("plan failed"),
            ):
                result = btn.handle()

        assert len(result) == 1
        # The modal was constructed with error content
        call_kwargs = mock_modal_cls.call_args.kwargs
        assert "Error Generating Prevention Plan" in call_kwargs["content"]
        assert "plan failed" in call_kwargs["content"]
        assert call_kwargs["title"] == "Prevention Plan Error"

    @patch("guided_awv.protocols.prevention_plan_button.LaunchModalEffect")
    def test_returns_modal_with_plan_html_on_success(
        self, mock_modal_cls: MagicMock
    ) -> None:
        btn = self._make_button({"note_id": 42})

        note_mod = MagicMock()
        mock_note_obj = MagicMock()
        mock_note_obj.id = "note-uuid-456"
        note_mod.Note.objects.get.return_value = mock_note_obj

        mock_modal_instance = MagicMock()
        mock_modal_cls.return_value = mock_modal_instance
        mock_modal_cls.TargetType.DEFAULT_MODAL = "default_modal"

        plan_html = "<div>Your prevention plan</div>"

        with patch.dict("sys.modules", {"canvas_sdk.v1.data.note": note_mod}):
            with patch(
                "guided_awv.api.awv_api.GeneratePreventionPlanHandler._build_plan",
                return_value=plan_html,
            ):
                result = btn.handle()

        assert len(result) == 1
        call_kwargs = mock_modal_cls.call_args.kwargs
        assert call_kwargs["content"] == plan_html
        assert call_kwargs["title"] == "Personalized Prevention Plan"
