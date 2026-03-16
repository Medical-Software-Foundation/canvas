"""Application handler for the Patient CSV Loader.

Opens a modal UI from the Canvas app drawer that lets staff
upload a CSV, preview validation results, and create patients.
"""

from __future__ import annotations

import json

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string

from patient_csv_loader.apps.csv_parser import generate_template_csv


class PatientCSVUpload(Application):
    """Global-scoped application for bulk patient creation via CSV."""

    def on_open(self) -> Effect | list[Effect]:
        api_base = "/plugin-io/api/patient_csv_loader"
        # JSON-encode so it becomes a valid JS string literal in the template
        template_csv_json = json.dumps(generate_template_csv())
        html = render_to_string(
            "templates/upload.html",
            {
                "api_base": api_base,
                "template_csv_json": template_csv_json,
            },
        )
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Patient CSV Loader",
        ).apply()
