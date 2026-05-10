"""Tests for tag_button: BUTTON_BACKGROUND_COLOR happy paths plus the
_safe_json XSS guard on the modal context.

Note: the bare `try/except Exception` fallbacks on BUTTON_TITLE /
BUTTON_BACKGROUND_COLOR were removed so ORM failures propagate to the
SDK error pipeline (per REVIEW.md "Always check"). Tests that asserted
the swallowed-error fallback have been removed alongside.
"""
import json
from unittest.mock import MagicMock, patch

from patient_tags.handlers.tag_button import PatientTagButton, _safe_json


class TestButtonBackgroundColor:
    @patch(
        "patient_tags.handlers.tag_button.get_patient_assignment_ids",
        return_value=[1, 2],
    )
    def test_yellow_when_assignments_present(self, mock_get: MagicMock) -> None:
        button = PatientTagButton.__new__(PatientTagButton)
        button.event = MagicMock()
        button.event.target.id = "p1"
        assert button.BUTTON_BACKGROUND_COLOR == "#feff86"

    @patch(
        "patient_tags.handlers.tag_button.get_patient_assignment_ids",
        return_value=[],
    )
    def test_gray_when_no_assignments(self, mock_get: MagicMock) -> None:
        button = PatientTagButton.__new__(PatientTagButton)
        button.event = MagicMock()
        button.event.target.id = "p1"
        assert button.BUTTON_BACKGROUND_COLOR == "#e5e7eb"


class TestSafeJson:
    """`_safe_json` must escape `<`, `>`, `&` so JSON embedded inside a
    `<script>` block can't break out of the script tag.
    """

    def test_escapes_script_close(self) -> None:
        payload = _safe_json([{"name": "</script><script>alert(1)</script>"}])
        assert "</script>" not in payload
        assert "\\u003c/script\\u003e" in payload

    def test_escapes_ampersand(self) -> None:
        payload = _safe_json({"x": "a & b"})
        assert "&" not in payload
        assert "\\u0026" in payload

    def test_round_trip_preserves_value(self) -> None:
        original = {"name": "</script>", "color": "<blue>"}
        # Decoding the unicode-escaped JSON yields the original string.
        decoded = json.loads(_safe_json(original))
        assert decoded == original

    def test_safe_input_unchanged(self) -> None:
        payload = _safe_json({"a": "plain text"})
        assert payload == '{"a": "plain text"}'


class TestHandleEscapesUserInput:
    """End-to-end: a malicious label name goes through handle() escaped."""

    @patch("patient_tags.handlers.tag_button.get_patient_assignment_ids", return_value=[])
    @patch("patient_tags.handlers.tag_button.list_banner_groups", return_value=[])
    @patch("patient_tags.handlers.tag_button.list_labels")
    @patch(
        "patient_tags.handlers.tag_button.render_to_string",
        return_value="<html></html>",
    )
    def test_malicious_label_name_is_escaped_in_context(
        self,
        mock_render: MagicMock,
        mock_list_labels: MagicMock,
        mock_list_groups: MagicMock,
        mock_get_assignments: MagicMock,
    ) -> None:
        mock_list_labels.return_value = [
            {"id": 1, "name": "</script><script>alert(1)</script>",
             "color": "blue", "description": "",
             "assignable_in_chart": True, "assignable_in_profile": True,
             "banner_group_id": None, "banner_group_name": None},
        ]

        button = PatientTagButton.__new__(PatientTagButton)
        event = MagicMock()
        event.target.id = "p1"
        button.event = event

        button.handle()

        ctx = mock_render.call_args.args[1]
        # The labels_json string passed to the template must NOT contain a
        # literal </script> for the HTML tokenizer to act on.
        assert "</script>" not in ctx["labels_json"]
        assert "\\u003c/script\\u003e" in ctx["labels_json"]
