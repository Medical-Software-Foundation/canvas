"""Tests for the Photon Elements prescribe-modal SimpleAPI."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from photon_integration.client.photon_client import PhotonError
from photon_integration.handlers.prescribe_modal_api import PhotonPrescribeModalAPI

MODULE = "photon_integration.handlers.prescribe_modal_api"

FULL_SECRETS = {
    "PHOTON_SPA_CLIENT_ID": "spa-client",
    "PHOTON_ORG_ID": "org_123",
    "PHOTON_ENV": "sandbox",
}


def _api(query_params=None, headers=None, secrets=None):
    api = PhotonPrescribeModalAPI.__new__(PhotonPrescribeModalAPI)
    api.request = SimpleNamespace(
        headers=headers or {"host": "plugin-testing.canvasmedical.com"},
        query_params=query_params or {},
    )
    api.secrets = FULL_SECRETS if secrets is None else secrets
    return api


@pytest.fixture
def patched():
    """Patch the modal API's collaborators; yield the mocks."""
    with patch(f"{MODULE}.render_to_string", return_value="<html></html>") as rts, \
        patch(f"{MODULE}.Patient") as patient_cls, \
        patch(f"{MODULE}.build_client") as build_client, \
        patch(f"{MODULE}.resolve_photon_patient") as resolve:
        patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        patient_cls.objects.get.return_value = SimpleNamespace(id="ptn-1")
        resolve.return_value = ("pat_999", "EXT_EFFECT")
        yield SimpleNamespace(
            rts=rts, patient_cls=patient_cls, build_client=build_client, resolve=resolve
        )


class TestIndex:
    def test_renders_shell_with_config_and_persists_external_id(self, patched):
        api = _api(query_params={"patient_id": "ptn-1"})

        result = api.index()

        # external-id effect first, then the HTML response
        assert result[0] == "EXT_EFFECT"
        assert len(result) == 2
        # config injected into the shell
        template, ctx = patched.rts.call_args.args[0], patched.rts.call_args.args[1]
        assert template == "static/index.html"
        config = json.loads(ctx["config_json"])
        assert config["clientId"] == "spa-client"
        assert config["org"] == "org_123"
        assert config["patientId"] == "pat_999"
        assert config["devMode"] is True
        assert config["redirectUri"] == (
            "https://plugin-testing.canvasmedical.com/plugin-io/api/photon_integration/photon/"
        )

    def test_no_external_id_effect_when_already_synced(self, patched):
        patched.resolve.return_value = ("pat_999", None)
        api = _api(query_params={"patient_id": "ptn-1"})

        result = api.index()

        assert len(result) == 1  # only the HTML response

    def test_production_sets_dev_mode_false(self, patched):
        api = _api(
            query_params={"patient_id": "ptn-1"},
            secrets=dict(FULL_SECRETS, PHOTON_ENV="production"),
        )
        api.index()
        config = json.loads(patched.rts.call_args.args[1]["config_json"])
        assert config["devMode"] is False

    def test_redirect_uri_override(self, patched):
        api = _api(
            query_params={"patient_id": "ptn-1"},
            secrets=dict(FULL_SECRETS, PHOTON_REDIRECT_URI="https://custom/cb"),
        )
        api.index()
        config = json.loads(patched.rts.call_args.args[1]["config_json"])
        assert config["redirectUri"] == "https://custom/cb"

    def test_missing_patient_id_is_error(self, patched):
        api = _api(query_params={})
        api.index()
        assert patched.rts.call_args.args[0] == "static/error.html"
        patched.resolve.assert_not_called()

    def test_missing_config_is_error(self, patched):
        api = _api(query_params={"patient_id": "ptn-1"}, secrets={"PHOTON_ENV": "sandbox"})
        api.index()
        assert patched.rts.call_args.args[0] == "static/error.html"
        patched.resolve.assert_not_called()

    def test_patient_not_found_is_error(self, patched):
        patched.patient_cls.objects.get.side_effect = patched.patient_cls.DoesNotExist
        api = _api(query_params={"patient_id": "ptn-1"})
        api.index()
        assert patched.rts.call_args.args[0] == "static/error.html"

    def test_sync_failure_is_error(self, patched):
        patched.resolve.side_effect = PhotonError("boom")
        api = _api(query_params={"patient_id": "ptn-1"})
        api.index()
        assert patched.rts.call_args.args[0] == "static/error.html"


class TestAssets:
    def test_elements_js_content_type(self, patched):
        result = _api().elements_js()
        assert result[0].headers["Content-Type"] == "text/javascript"

    def test_main_js_content_type(self, patched):
        result = _api().main_js()
        assert result[0].headers["Content-Type"] == "text/javascript"

    def test_styles_css_content_type(self, patched):
        result = _api().styles_css()
        assert result[0].headers["Content-Type"] == "text/css"
