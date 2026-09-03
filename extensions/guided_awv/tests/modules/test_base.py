"""Tests for the BaseModule system."""

from typing import Any

import pytest

from guided_awv.modules.base import AWVType, BaseModule


class ConcreteModule(BaseModule):
    """Concrete test implementation of BaseModule."""

    ORDER = 5
    TITLE = "Test Module"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-test"

    def get_context(self) -> dict[str, Any]:
        return {"test_key": "test_value"}


class InitialOnlyModule(BaseModule):
    """Module only visible for initial AWV."""

    ORDER = 1
    TITLE = "Initial Only"
    AWV_TYPES = AWVType.INITIAL

    def get_context(self) -> dict[str, Any]:
        return {}


class SubsequentOnlyModule(BaseModule):
    """Module only visible for subsequent AWV."""

    ORDER = 2
    TITLE = "Subsequent Only"
    AWV_TYPES = AWVType.SUBSEQUENT

    def get_context(self) -> dict[str, Any]:
        return {}


class TestBaseModule:
    """Tests for the BaseModule abstract class."""

    def test_is_visible_both_types_initial(self) -> None:
        """BOTH type module is visible for initial AWV."""
        module = ConcreteModule("note-1", "patient-1", AWVType.INITIAL)
        assert module.is_visible() is True

    def test_is_visible_both_types_subsequent(self) -> None:
        """BOTH type module is visible for subsequent AWV."""
        module = ConcreteModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert module.is_visible() is True

    def test_is_visible_initial_only_matches(self) -> None:
        """Initial-only module is visible for initial AWV."""
        module = InitialOnlyModule("note-1", "patient-1", AWVType.INITIAL)
        assert module.is_visible() is True

    def test_is_visible_initial_only_hidden_for_subsequent(self) -> None:
        """Initial-only module is not visible for subsequent AWV."""
        module = InitialOnlyModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert module.is_visible() is False

    def test_is_visible_subsequent_only_matches(self) -> None:
        """Subsequent-only module is visible for subsequent AWV."""
        module = SubsequentOnlyModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert module.is_visible() is True

    def test_is_visible_subsequent_only_hidden_for_initial(self) -> None:
        """Subsequent-only module is not visible for initial AWV."""
        module = SubsequentOnlyModule("note-1", "patient-1", AWVType.INITIAL)
        assert module.is_visible() is False

    def test_render_returns_dict(self) -> None:
        """render() returns a dict with required keys."""
        module = ConcreteModule("note-abc", "patient-xyz", AWVType.INITIAL)
        result = module.render()

        assert isinstance(result, dict)
        assert "section_id" in result
        assert "title" in result
        assert "icon" in result
        assert "order" in result
        assert "awv_type" in result
        assert "context" in result

    def test_render_context_from_get_context(self) -> None:
        """render() includes context from get_context()."""
        module = ConcreteModule("note-abc", "patient-xyz", AWVType.INITIAL)
        result = module.render()

        assert result["context"] == {"test_key": "test_value"}
        assert result["order"] == 5
        assert result["title"] == "Test Module"
        assert result["awv_type"] == AWVType.INITIAL

    def test_module_stores_constructor_args(self) -> None:
        """Module stores note_id, patient_id, and awv_type."""
        module = ConcreteModule("my-note", "my-patient", AWVType.SUBSEQUENT)
        assert module.note_id == "my-note"
        assert module.patient_id == "my-patient"
        assert module.awv_type == AWVType.SUBSEQUENT


class TestRequiredParam:
    """Tests for the required parameter on helper methods."""

    def _module(self) -> ConcreteModule:
        return ConcreteModule("n", "p", AWVType.INITIAL)

    def test_text_input_required(self) -> None:
        html = self._module()._text_input("f", "Label", required=True)
        assert 'data-required="true"' in html
        assert 'awv-required' in html

    def test_text_input_not_required_by_default(self) -> None:
        html = self._module()._text_input("f", "Label")
        assert "data-required" not in html
        assert "awv-required" not in html

    def test_number_input_required(self) -> None:
        html = self._module()._number_input("f", "Label", required=True)
        assert 'data-required="true"' in html
        assert 'awv-required' in html

    def test_number_input_not_required_by_default(self) -> None:
        html = self._module()._number_input("f", "Label")
        assert "data-required" not in html

    def test_textarea_required(self) -> None:
        html = self._module()._textarea("f", "Label", required=True)
        assert 'data-required="true"' in html
        assert 'awv-required' in html

    def test_radio_group_required(self) -> None:
        html = self._module()._radio_group("f", "Label", ["A", "B"], required=True)
        assert 'data-required="true"' in html
        assert 'awv-required' in html

    def test_radio_group_not_required_by_default(self) -> None:
        html = self._module()._radio_group("f", "Label", ["A", "B"])
        assert "data-required" not in html

    def test_select_required(self) -> None:
        html = self._module()._select("f", "Label", ["A", "B"], required=True)
        assert 'data-required="true"' in html
        assert 'awv-required' in html

    def test_checkbox_group_required(self) -> None:
        html = self._module()._checkbox_group("f", "Label", ["A", "B"], required=True)
        assert 'data-required="true"' in html
        assert 'awv-required' in html


class TestBaseModuleHtmlEscape:
    """Regression tests for Claude review finding #12 (modules/base.py site).

    The HTML helpers previously interpolated caller-supplied label/value/name/
    option strings raw via f-strings. Real plugin callers feed chart-derived
    strings into these (medical_history.py, assessment_plan.py, vitals.py, ...)
    so a Condition / Medication display containing ``<`` or ``"`` could break
    the surrounding markup. Every interpolation point now goes through
    ``html.escape``.
    """

    def _m(self) -> ConcreteModule:
        return ConcreteModule(note_id="n", patient_id="p", awv_type=AWVType.INITIAL)

    def test_text_input_escapes_label_value_placeholder(self) -> None:
        out = self._m()._text_input(
            name="<script>",
            label="<b>Label</b>",
            placeholder='"quoted"',
            value="<img src=x>",
        )
        assert "<script>" not in out
        assert "<b>Label</b>" not in out
        assert "<img src=x>" not in out
        assert "&lt;script&gt;" in out
        assert "&lt;b&gt;Label&lt;/b&gt;" in out
        assert "&quot;quoted&quot;" in out

    def test_textarea_escapes_value(self) -> None:
        out = self._m()._textarea(name="n", label="L", value="</textarea><script>x</script>")
        # The closing textarea + script must not appear unescaped
        assert "</textarea><script>" not in out
        assert "&lt;/textarea&gt;&lt;script&gt;" in out

    def test_radio_group_escapes_option_values_and_labels(self) -> None:
        opts = [{"value": "<x>", "label": "<y>"}, "<z>"]
        out = self._m()._radio_group("n", "L", opts)
        assert "<x>" not in out
        assert "<y>" not in out
        assert "<z>" not in out
        assert "&lt;x&gt;" in out
        assert "&lt;y&gt;" in out
        assert "&lt;z&gt;" in out

    def test_select_escapes_option_values_and_labels(self) -> None:
        opts = [{"value": "<v>", "label": "<l>"}]
        out = self._m()._select("n", "L", opts)
        assert "<v>" not in out
        assert "<l>" not in out
        assert "&lt;v&gt;" in out
        assert "&lt;l&gt;" in out

    def test_info_row_escapes_label_and_value(self) -> None:
        out = self._m()._info_row("<b>label</b>", "<i>value</i>")
        assert "<b>label</b>" not in out
        assert "<i>value</i>" not in out
        assert "&lt;b&gt;label&lt;/b&gt;" in out

    def test_alert_escapes_text(self) -> None:
        out = self._m()._alert("<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out

    def test_subtitle_escapes_text(self) -> None:
        out = self._m()._subtitle("<h1>spoof</h1>")
        assert "<h1>spoof</h1>" not in out
        assert "&lt;h1&gt;spoof&lt;/h1&gt;" in out
