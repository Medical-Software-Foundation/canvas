"""Render After Visit Summary as HTML."""

from __future__ import annotations
import re

from canvas_sdk.templates import render_to_string

from portal_content.services.avs_data_extractor import AVSDataExtractor
from logger import log


class AVSRenderer:
    """Render After Visit Summary HTML from note data."""

    def __init__(self, note_id: str):
        self.note_id = note_id
        self.extractor = AVSDataExtractor(note_id)

    def render(self) -> str:
        """Render AVS as HTML string."""
        log.info(f"Rendering AVS for note {self.note_id}")

        avs_data = self.extractor.extract()

        html = render_to_string("templates/avs_template.html", context=avs_data)

        # Minify HTML to prevent newline display issues in portal iframe
        html = re.sub(r"\s+", " ", html)
        html = re.sub(r">\s+<", "><", html)
        html = html.strip()

        log.info(f"Successfully rendered AVS HTML ({len(html)} characters)")
        return html

    def get_filename(self) -> str:
        """Generate filename for AVS download."""
        patient = self.extractor.patient
        note_date = self.extractor.note.created.strftime("%Y-%m-%d")

        last_name = patient.last_name.replace(" ", "_")
        first_name = patient.first_name.replace(" ", "_")

        return f"AVS_{last_name}_{first_name}_{note_date}.html"
