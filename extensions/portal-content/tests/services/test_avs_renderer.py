"""Tests for AVS HTML renderer."""
from unittest.mock import MagicMock, patch, call
from datetime import datetime

from portal_content.services.avs_renderer import AVSRenderer


class TestAVSRendererInit:
    def test_stores_note_id(self):
        with patch("portal_content.services.avs_renderer.AVSDataExtractor"):
            renderer = AVSRenderer("note-uuid-123")
            assert renderer.note_id == "note-uuid-123"


class TestAVSRendering:
    def test_render_calls_extractor_and_template(self):
        mock_extractor = MagicMock()
        mock_data = {
            "patient_name": "John Doe",
            "patient_dob": "01/15/1980",
            "medications": {"start": [], "adjust": [], "stop": [], "keep": []},
            "vitals": {},
            "diagnoses": [],
            "immunizations": [],
            "procedures": [],
            "upcoming_appointments": [],
        }
        mock_extractor.extract.return_value = mock_data

        with patch("portal_content.services.avs_renderer.AVSDataExtractor") as mock_cls, \
             patch("portal_content.services.avs_renderer.render_to_string") as mock_render:

            mock_cls.return_value = mock_extractor
            mock_render.return_value = "<html>Rendered AVS</html>"

            renderer = AVSRenderer("note-uuid-123")
            html = renderer.render()

            assert call("note-uuid-123") in mock_cls.mock_calls
            assert call.extract() in mock_extractor.mock_calls
            assert call("templates/avs_template.html", context=mock_data) in mock_render.mock_calls
            assert html == "<html>Rendered AVS</html>"

    def test_minifies_whitespace(self):
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = {}

        with patch("portal_content.services.avs_renderer.AVSDataExtractor") as mock_cls, \
             patch("portal_content.services.avs_renderer.render_to_string") as mock_render:

            mock_cls.return_value = mock_extractor
            mock_render.return_value = "<div>  \n  <span>text</span>  \n  </div>"

            html = AVSRenderer("id").render()
            assert "\n" not in html
            assert ">  <" not in html


class TestFilenameGeneration:
    def test_get_filename(self):
        mock_extractor = MagicMock()
        mock_extractor.patient = MagicMock(first_name="John", last_name="Doe")
        mock_extractor.note = MagicMock(created=datetime(2025, 1, 15, 10, 30))

        with patch("portal_content.services.avs_renderer.AVSDataExtractor") as mock_cls:
            mock_cls.return_value = mock_extractor
            assert AVSRenderer("id").get_filename() == "AVS_Doe_John_2025-01-15.html"

    def test_get_filename_with_spaces(self):
        mock_extractor = MagicMock()
        mock_extractor.patient = MagicMock(first_name="Mary Jane", last_name="Smith Williams")
        mock_extractor.note = MagicMock(created=datetime(2025, 2, 20, 14, 0))

        with patch("portal_content.services.avs_renderer.AVSDataExtractor") as mock_cls:
            mock_cls.return_value = mock_extractor
            filename = AVSRenderer("id").get_filename()
            assert filename == "AVS_Smith_Williams_Mary_Jane_2025-02-20.html"
            assert " " not in filename
