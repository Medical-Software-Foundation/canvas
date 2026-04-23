"""Tests for vitals_visualizer.protocols.visualizer."""
import json
from datetime import datetime
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from vitals_visualizer.protocols import visualizer
from vitals_visualizer.protocols.visualizer import (
    VisualApp,
    VitalsVisualizerButton,
)

PATIENT_UUID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# VitalsVisualizerButton
# ---------------------------------------------------------------------------


class TestVitalsVisualizerButton:
    def test_button_metadata(self) -> None:
        assert VitalsVisualizerButton.BUTTON_TITLE == "Open Visualizer"
        assert VitalsVisualizerButton.BUTTON_KEY == "vitals_visualizer"

    def _make_button(self, target_id: str) -> VitalsVisualizerButton:
        # `self.target` is a read-only property that returns `self.event.target.id`.
        button = VitalsVisualizerButton.__new__(VitalsVisualizerButton)
        button.event = SimpleNamespace(target=SimpleNamespace(id=target_id))
        return button

    def test_visible_true_when_panel_exists(self) -> None:
        button = self._make_button(PATIENT_UUID)
        with patch.object(visualizer, "Observation") as mock_obs:
            qs = MagicMock()
            qs.filter.return_value.exclude.return_value.exists.return_value = True
            mock_obs.objects.for_patient.return_value = qs
            assert button.visible() is True

    def test_visible_false_when_no_panel(self) -> None:
        button = self._make_button(PATIENT_UUID)
        with patch.object(visualizer, "Observation") as mock_obs:
            qs = MagicMock()
            qs.filter.return_value.exclude.return_value.exists.return_value = False
            mock_obs.objects.for_patient.return_value = qs
            assert button.visible() is False

    def test_handle_emits_launch_modal_effect_with_patient_in_url(self) -> None:
        button = self._make_button(PATIENT_UUID)
        effects = button.handle()
        assert len(effects) == 1
        effect = effects[0]
        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == f"/plugin-io/api/vitals_visualizer/?patient={PATIENT_UUID}"


# ---------------------------------------------------------------------------
# VisualApp
# ---------------------------------------------------------------------------


def _make_api(patient: str | None = None) -> VisualApp:
    api = VisualApp.__new__(VisualApp)
    api.request = SimpleNamespace(
        query_params={"patient": patient} if patient is not None else {},
    )
    return api


def _setup_observations(panels: list, observations: list):
    """Return a mock `Observation` whose `.for_patient` yields a panel
    queryset on the first call and an observation queryset on the second,
    each with the right chain methods."""
    panels_qs = MagicMock()
    panels_qs.filter.return_value.exclude.return_value = panels

    obs_qs = MagicMock()
    obs_qs.filter.return_value = obs_qs
    obs_qs.exclude.return_value = obs_qs
    obs_qs.select_related.return_value = observations

    mock_obs = MagicMock()
    mock_obs.objects.for_patient.side_effect = [panels_qs, obs_qs]
    return mock_obs


class TestVisualAppAuth:
    def test_staff_session_passes(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": "staff", "type": "Staff"})
        assert api.authenticate(creds) is True

    def test_patient_session_rejected(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": "p", "type": "Patient"})
        with pytest.raises(InvalidCredentialsError):
            api.authenticate(creds)


class TestVisualAppIndex:
    def _render_ctx(self, mock_render) -> dict:
        """Unwrap the `context` kwarg from the last render_to_string call."""
        return mock_render.mock_calls[0].kwargs["context"]

    def test_no_panels_returns_empty_data_for_all_metrics(self) -> None:
        api = _make_api(patient=PATIENT_UUID)
        mock_obs = _setup_observations([], [])
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="<html/>") as mock_render,
        ):
            response = api.index()[0]

        assert response.status_code == HTTPStatus.OK
        ctx = self._render_ctx(mock_render)
        data = json.loads(ctx["data"])
        assert set(data.keys()) == {
            "Weight (lbs)", "Body Temp (\u00b0F)", "Systolic BP (mmHg)",
            "Diastolic BP (mmHg)", "Oxygen Sat (%)", "Height (inches)",
            "Waist Circ (cm)", "Pulse (bpm)", "Respiration Rate (bpm)",
        }
        for series in data.values():
            assert series == []
        assert json.loads(ctx["dates"]) == []
        # graph_ranges is always the static config dict
        assert "Weight (lbs)" in json.loads(ctx["graph_ranges"])

    def test_weight_is_converted_from_oz_to_lbs(self) -> None:
        panel = SimpleNamespace(id="p1", effective_datetime=datetime(2026, 1, 1, 12, 0))
        weight = SimpleNamespace(
            name="weight", value="160",
            is_member_of=SimpleNamespace(id="p1"),
        )
        api = _make_api(patient=PATIENT_UUID)
        mock_obs = _setup_observations([panel], [weight])
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="x") as mock_render,
        ):
            api.index()

        data = json.loads(self._render_ctx(mock_render)["data"])
        assert data["Weight (lbs)"] == [10.0]  # 160 oz / 16

    def test_blood_pressure_splits_into_systolic_diastolic(self) -> None:
        panel = SimpleNamespace(id="p1", effective_datetime=datetime(2026, 1, 1))
        bp = SimpleNamespace(
            name="blood_pressure", value="120/80",
            is_member_of=SimpleNamespace(id="p1"),
        )
        api = _make_api(patient=PATIENT_UUID)
        mock_obs = _setup_observations([panel], [bp])
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="x") as mock_render,
        ):
            api.index()

        data = json.loads(self._render_ctx(mock_render)["data"])
        assert data["Systolic BP (mmHg)"] == [120.0]
        assert data["Diastolic BP (mmHg)"] == [80.0]

    def test_skips_note_and_pulse_rhythm_observations(self) -> None:
        panel = SimpleNamespace(id="p1", effective_datetime=datetime(2026, 1, 1))
        note = SimpleNamespace(
            name="note", value="anything",
            is_member_of=SimpleNamespace(id="p1"),
        )
        pulse_rhythm = SimpleNamespace(
            name="pulse_rhythm", value="Regular",
            is_member_of=SimpleNamespace(id="p1"),
        )
        api = _make_api(patient=PATIENT_UUID)
        mock_obs = _setup_observations([panel], [note, pulse_rhythm])
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="x") as mock_render,
        ):
            api.index()

        data = json.loads(self._render_ctx(mock_render)["data"])
        # No values assigned; all entries remain None for this panel.
        assert data["Pulse (bpm)"] == [None]

    def test_skips_observations_with_empty_value(self) -> None:
        panel = SimpleNamespace(id="p1", effective_datetime=datetime(2026, 1, 1))
        empty = SimpleNamespace(
            name="pulse", value=None,
            is_member_of=SimpleNamespace(id="p1"),
        )
        api = _make_api(patient=PATIENT_UUID)
        mock_obs = _setup_observations([panel], [empty])
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="x") as mock_render,
        ):
            api.index()

        data = json.loads(self._render_ctx(mock_render)["data"])
        assert data["Pulse (bpm)"] == [None]

    def test_non_numeric_numeric_string_kept_as_string(self) -> None:
        # Simulates a path where try_parse hits the ValueError branch and
        # preserves the raw string.
        panel = SimpleNamespace(id="p1", effective_datetime=datetime(2026, 1, 1))
        non_num = SimpleNamespace(
            name="pulse", value="Regular",
            is_member_of=SimpleNamespace(id="p1"),
        )
        api = _make_api(patient=PATIENT_UUID)
        mock_obs = _setup_observations([panel], [non_num])
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="x") as mock_render,
        ):
            api.index()

        data = json.loads(self._render_ctx(mock_render)["data"])
        assert data["Pulse (bpm)"] == ["Regular"]

    def test_dates_sorted_chronologically_and_values_follow(self) -> None:
        panel_late = SimpleNamespace(id="p2", effective_datetime=datetime(2026, 2, 1))
        panel_early = SimpleNamespace(id="p1", effective_datetime=datetime(2025, 12, 1))
        obs_late = SimpleNamespace(
            name="pulse", value="90",
            is_member_of=SimpleNamespace(id="p2"),
        )
        obs_early = SimpleNamespace(
            name="pulse", value="70",
            is_member_of=SimpleNamespace(id="p1"),
        )
        api = _make_api(patient=PATIENT_UUID)
        # Deliberately out of order on the wire.
        mock_obs = _setup_observations(
            [panel_late, panel_early], [obs_late, obs_early]
        )
        with (
            patch.object(visualizer, "Observation", mock_obs),
            patch.object(visualizer, "render_to_string", return_value="x") as mock_render,
        ):
            api.index()

        ctx = self._render_ctx(mock_render)
        dates = json.loads(ctx["dates"])
        data = json.loads(ctx["data"])
        assert dates == ["12/1/2025", "2/1/2026"]
        assert data["Pulse (bpm)"] == [70.0, 90.0]


class TestVisualAppGetCss:
    def test_returns_css_response(self) -> None:
        api = _make_api()
        with patch.object(visualizer, "render_to_string", return_value="body{}") as mock_render:
            response = api.get_css()[0]
        assert mock_render.mock_calls == [call("templates/style.css")]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
