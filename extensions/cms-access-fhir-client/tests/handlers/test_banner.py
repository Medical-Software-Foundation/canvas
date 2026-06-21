"""Tests for AccessBannerHandler."""
import pytest
from unittest.mock import MagicMock, call, patch


def _make_handler(secrets=None, patient_id="patient-uuid-123"):
    from cms_access_fhir_client.handlers.banner import AccessBannerHandler
    mock_event = MagicMock()
    mock_event.target.id = patient_id
    handler = AccessBannerHandler(event=mock_event, secrets=secrets or {})
    return handler, mock_event


class TestAccessBannerHandlerGating:
    def test_returns_empty_when_banner_disabled(self):
        handler, mock_event = _make_handler(secrets={"ACCESS_SHOW_BANNER": "false"})
        effects = handler.compute()

        assert effects == []
        # Returns early before accessing event — no calls needed
        assert mock_event.mock_calls == []

    def test_returns_empty_when_banner_secret_absent(self):
        handler, mock_event = _make_handler(secrets={})
        effects = handler.compute()

        assert effects == []
        # Returns early before accessing event — no calls needed
        assert mock_event.mock_calls == []

    def test_returns_empty_when_no_alignment_found(self):
        handler, mock_event = _make_handler(secrets={"ACCESS_SHOW_BANNER": "true"})

        mock_qs = MagicMock()
        mock_qs.filter.return_value.order_by.return_value.first.return_value = None

        with patch(
            "cms_access_fhir_client.handlers.banner.ACCESSAlignment.objects",
            mock_qs,
        ):
            effects = handler.compute()

        assert effects == []
        assert mock_qs.mock_calls == [
            call.filter(patient__id="patient-uuid-123"),
            call.filter().order_by("-updated_at"),
            call.filter().order_by().first(),
        ]


class TestAccessBannerHandlerIntents:
    def _run_with_status(self, status, track="eCKM"):
        handler, mock_event = _make_handler(secrets={"ACCESS_SHOW_BANNER": "true"})
        mock_alignment = MagicMock()
        mock_alignment.status = status
        mock_alignment.track = track

        mock_qs = MagicMock()
        mock_qs.filter.return_value.order_by.return_value.first.return_value = mock_alignment

        with patch(
            "cms_access_fhir_client.handlers.banner.ACCESSAlignment.objects",
            mock_qs,
        ):
            effects = handler.compute()

        return effects, mock_event, mock_alignment, mock_qs

    def test_aligned_status_produces_info_banner(self):
        effects, *_ = self._run_with_status("aligned")

        assert len(effects) == 1
        from canvas_sdk.effects.base import EffectType
        assert effects[0].type == EffectType.ADD_BANNER_ALERT

    def test_pending_status_produces_warning_banner(self):
        effects, *_ = self._run_with_status("pending")
        assert len(effects) == 1

    def test_unaligned_status_produces_banner(self):
        effects, *_ = self._run_with_status("unaligned")
        assert len(effects) == 1

    def test_error_status_produces_banner(self):
        effects, *_ = self._run_with_status("error")
        assert len(effects) == 1

    def test_eligible_status_produces_info_banner(self):
        effects, *_ = self._run_with_status("eligible")
        assert len(effects) == 1
