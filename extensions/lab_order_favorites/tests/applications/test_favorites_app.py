"""Tests for the patient-scoped favorites application handler."""

from unittest.mock import MagicMock, patch

from lab_order_favorites.applications import favorites_app
from lab_order_favorites.applications.favorites_app import LabFavoritesApp


def test_on_open_renders_patient_modal():
    event = MagicMock()
    event.context = {"patient": {"id": "pat-1"}}
    handler = LabFavoritesApp(event)

    patient = MagicMock()
    patient.id = "pat-1"

    with patch.object(favorites_app.Patient.objects, "get", return_value=patient) as get, \
         patch.object(favorites_app, "render_to_string", return_value="<html>") as render:
        effect = handler.on_open()

    assert effect is not None
    assert get.call_args.kwargs == {"id": "pat-1"}
    template, context = render.call_args[0]
    assert template == "templates/favorites.html"
    assert context["patient_id"] == "pat-1"
    assert context["api_base"] == "/plugin-io/api/lab_order_favorites"
