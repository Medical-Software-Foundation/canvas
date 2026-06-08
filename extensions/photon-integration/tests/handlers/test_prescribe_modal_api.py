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
        patch(f"{MODULE}.staff_identity",
              return_value={"email": "kristen@example.com", "name": "Kristen ONeill"}), \
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
        assert config["canvasUserEmail"] == "kristen@example.com"  # operator gate

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

    def test_oauth_callback_without_patient_renders_shell(self, patched):
        # Auth0 redirects back with code/state and no patient_id; render the
        # shell (no patient sync) so photon-client can finish the login.
        api = _api(query_params={"code": "abc", "state": "xyz"})
        result = api.index()
        assert patched.rts.call_args.args[0] == "static/index.html"
        config = json.loads(patched.rts.call_args.args[1]["config_json"])
        assert config["patientId"] == ""
        patched.resolve.assert_not_called()
        assert len(result) == 1  # shell only, no external-id effect

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

    def test_send_js_content_type(self, patched):
        result = _api().send_js()
        assert result[0].headers["Content-Type"] == "text/javascript"


def _command(cmd_id="c1", data=None):
    return SimpleNamespace(
        id=cmd_id,
        patient=SimpleNamespace(id="ptn-1"),
        data=data
        if data is not None
        else {
            "prescribe": {"text": "Lisinopril 10 mg tablet"},
            "sig": "Take 1 daily",
            "quantity_to_dispense": 30,
            "type_to_dispense": {"description": "tablet"},
            "refills": 1,
        },
    )


@pytest.fixture
def send_patched():
    with patch(f"{MODULE}.render_to_string", return_value="<html></html>") as rts, \
        patch(f"{MODULE}.Command") as command_cls, \
        patch(f"{MODULE}.photon_send_selected_map", return_value={"c1": True}) as selected, \
        patch(f"{MODULE}.build_client") as build_client, \
        patch(f"{MODULE}.fdb_to_rxcui", return_value="198052") as rxcui, \
        patch(f"{MODULE}.ndc_to_rxcui", return_value=None) as ndc_rxcui, \
        patch(f"{MODULE}.resolve_photon_patient", return_value=("pat_999", "EXT_EFFECT")), \
        patch(f"{MODULE}.resolve_prescriber",
              return_value={"email": "kristen@example.com", "name": "Kristen ONeill"}), \
        patch(f"{MODULE}.staff_identity",
              return_value={"email": "kristen@example.com", "name": "Kristen ONeill"}), \
        patch(f"{MODULE}.build_address", return_value={"city": "Town"}):
        build_client.return_value.find_treatment_by_code.return_value = {
            "id": "med_1", "name": "Ondansetron 4 mg ODT", "brandName": "Zofran",
            "genericName": "Ondansetron",
        }
        command_cls.objects.filter.return_value.select_related.return_value = [_command()]
        yield SimpleNamespace(rts=rts, command_cls=command_cls, selected=selected,
                              build_client=build_client, rxcui=rxcui, ndc_rxcui=ndc_rxcui)


class TestSend:
    def test_builds_prescription_payloads(self, send_patched):
        api = _api(query_params={"note_id": "4567"})
        result = api.send()

        assert result[0] == "EXT_EFFECT"  # external-id effect first
        config = json.loads(send_patched.rts.call_args.args[1]["config_json"])
        assert config["patientId"] == "pat_999"
        assert config["address"] == {"city": "Town"}
        assert config["graphqlUrl"] == "https://api.neutron.health/graphql"
        assert config["canvasUserEmail"] == "kristen@example.com"  # operator identity
        assert len(config["prescriptions"]) == 1
        rx = config["prescriptions"][0]
        assert rx["treatmentId"] == "med_1"
        assert rx["patientId"] == "pat_999"
        assert rx["rxcui"] == "198052"
        assert rx["dispenseUnit"] == "Tablet"
        assert rx["refillsAllowed"] == 1
        # the resolved Photon medication is surfaced for provider review
        assert rx["photonMedication"] == "Zofran — Ondansetron 4 mg ODT"
        # prescriber identity for the browser-side match guard
        assert rx["prescriberEmail"] == "kristen@example.com"
        assert rx["prescriberName"] == "Kristen ONeill"
        assert rx["error"] is None

    def test_config_json_escapes_script_breakout(self, send_patched):
        # Patient address is untrusted free text injected into an inline <script>;
        # a '</script>' payload must not survive into the rendered config_json.
        with patch(f"{MODULE}.build_address", return_value={"street1": "</script><script>alert(1)</script>"}):
            api = _api(query_params={"note_id": "4567"})
            api.send()
        raw = send_patched.rts.call_args.args[1]["config_json"]
        assert "</script>" not in raw
        assert "<" not in raw and ">" not in raw
        # still valid JSON that round-trips the original value
        assert json.loads(raw)["address"]["street1"] == "</script><script>alert(1)</script>"

    def test_unmatched_rxcui_flags_error(self, send_patched):
        send_patched.build_client.return_value.find_treatment_by_code.return_value = None
        api = _api(query_params={"note_id": "4567"})
        api.send()
        rx = json.loads(send_patched.rts.call_args.args[1]["config_json"])["prescriptions"][0]
        assert rx["treatmentId"] is None
        assert "No Photon match for RxNorm 198052" in rx["error"]

    def test_unsupported_unit_flags_error(self, send_patched):
        # treatment matches, but the dispense unit can't be safely represented.
        cmd = _command(data={
            "prescribe": {"text": "Wegovy", "value": "1"},
            "sig": "inject weekly",
            "quantity_to_dispense": 4,
            "type_to_dispense": {"text": "0.75 mL syringe"},
            "refills": 3,
        })
        send_patched.command_cls.objects.filter.return_value.select_related.return_value = [cmd]
        api = _api(query_params={"note_id": "4567"})
        api.send()
        rx = json.loads(send_patched.rts.call_args.args[1]["config_json"])["prescriptions"][0]
        assert rx["dispenseUnit"] is None
        assert "Dispense unit not supported" in rx["error"]

    def test_no_rxcui_flags_error(self, send_patched):
        send_patched.rxcui.return_value = None
        send_patched.build_client.return_value.find_treatment_by_code.return_value = None
        api = _api(query_params={"note_id": "4567"})
        api.send()
        rx = json.loads(send_patched.rts.call_args.args[1]["config_json"])["prescriptions"][0]
        assert "No RxNorm code" in rx["error"]

    def test_skips_unflagged_commands(self, send_patched):
        send_patched.selected.return_value = {}  # no command flagged 'Send via Photon'
        api = _api(query_params={"note_id": "4567"})
        api.send()
        config = json.loads(send_patched.rts.call_args.args[1]["config_json"])
        assert config["prescriptions"] == []

    def test_no_note_is_error(self, send_patched):
        api = _api(query_params={})
        api.send()
        assert send_patched.rts.call_args.args[0] == "static/error.html"

    def test_oauth_callback_renders_shell(self, send_patched):
        api = _api(query_params={"code": "a", "state": "b"})
        api.send()
        assert send_patched.rts.call_args.args[0] == "static/send.html"

    def test_missing_config_is_error(self, send_patched):
        api = _api(query_params={"note_id": "4567"}, secrets={"PHOTON_ENV": "sandbox"})
        api.send()
        assert send_patched.rts.call_args.args[0] == "static/error.html"
