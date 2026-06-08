"""Tests for the 'Send via Photon' field and action filter handlers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from photon_integration.constants import (
    ACTIONS_TO_REMOVE_WHEN_PHOTON,
    PHOTON_FIELD_KEY,
    PHOTON_FIELD_LABEL,
    PHOTON_FIELD_OPTIONS,
    PHOTON_FIELD_TRUE_VALUE,
)
from photon_integration.handlers.command_field import (
    PhotonAdjustPrescriptionActionFilter,
    PhotonDispenseUnitValidation,
    PhotonFieldHandler,
    PhotonPrescribeActionFilter,
    PhotonRefillActionFilter,
)


def _event(*, schema_key=None, target_id="cmd-1", actions=None):
    return SimpleNamespace(
        context={
            "schema_key": schema_key,
            "actions": actions if actions is not None else [],
        },
        target=SimpleNamespace(id=target_id),
    )


def _patch_metadata(value):
    """Patch CommandMetadata.objects.filter(...).first() to return `value`."""
    entry = SimpleNamespace(value=value) if value is not None else None
    filter_mock = MagicMock(return_value=MagicMock(first=MagicMock(return_value=entry)))
    return patch(
        "photon_integration.handlers.command_field.CommandMetadata.objects.filter",
        filter_mock,
    )


class TestPhotonFieldHandler:
    @pytest.mark.parametrize("schema_key", ["prescribe", "refill", "adjustPrescription"])
    def test_emits_field_for_prescribe_family(self, schema_key):
        handler = PhotonFieldHandler(event=_event(schema_key=schema_key, target_id="rx-1"))

        with patch(
            "photon_integration.handlers.command_field.CommandMetadataCreateFormEffect"
        ) as eff_cls:
            eff_cls.return_value.apply.return_value = "FORM_EFFECT"
            effects = handler.compute()

        assert effects == ["FORM_EFFECT"]
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["command_uuid"] == "rx-1"
        assert len(kwargs["form_fields"]) == 1
        field = kwargs["form_fields"][0]
        assert field.key == PHOTON_FIELD_KEY
        assert field.label == PHOTON_FIELD_LABEL
        assert field.options == PHOTON_FIELD_OPTIONS
        assert field.required is False

    @pytest.mark.parametrize(
        "schema_key", ["medicationStatement", "plan", "assess", None, ""]
    )
    def test_skips_other_commands(self, schema_key):
        handler = PhotonFieldHandler(event=_event(schema_key=schema_key))

        assert handler.compute() == []


class TestPhotonActionFilters:
    DEFAULT_ACTIONS = [
        {"name": "sign_send_action"},
        {"name": "send_action"},
        {"name": "sign_action"},
        {"name": "print_action"},
        {"name": "make_changes"},
    ]

    @pytest.mark.parametrize(
        "handler_cls",
        [
            PhotonPrescribeActionFilter,
            PhotonRefillActionFilter,
            PhotonAdjustPrescriptionActionFilter,
        ],
    )
    def test_removes_send_actions_when_photon_selected(self, handler_cls):
        handler = handler_cls(
            event=_event(target_id="rx-2", actions=list(self.DEFAULT_ACTIONS))
        )

        with _patch_metadata(PHOTON_FIELD_TRUE_VALUE):
            effects = handler.compute()

        assert len(effects) == 1
        remaining = {a["name"] for a in json.loads(effects[0].payload)}
        # send + sign&send removed; sign and print retained.
        assert remaining == {"sign_action", "print_action", "make_changes"}
        assert ACTIONS_TO_REMOVE_WHEN_PHOTON.isdisjoint(remaining)

    def test_no_effect_when_not_selected(self):
        handler = PhotonPrescribeActionFilter(
            event=_event(actions=list(self.DEFAULT_ACTIONS))
        )

        with _patch_metadata("Something else"):
            assert handler.compute() == []

    def test_no_effect_when_metadata_missing(self):
        handler = PhotonPrescribeActionFilter(
            event=_event(actions=list(self.DEFAULT_ACTIONS))
        )

        with _patch_metadata(None):
            assert handler.compute() == []

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_no_effect_when_metadata_blank(self, blank):
        handler = PhotonRefillActionFilter(
            event=_event(actions=list(self.DEFAULT_ACTIONS))
        )

        with _patch_metadata(blank):
            assert handler.compute() == []

    def test_handles_missing_actions_context(self):
        handler = PhotonPrescribeActionFilter(
            event=SimpleNamespace(context={}, target=SimpleNamespace(id="rx-3"))
        )

        with _patch_metadata(PHOTON_FIELD_TRUE_VALUE):
            effects = handler.compute()

        assert len(effects) == 1
        assert json.loads(effects[0].payload) == []


def _validation_event(unit_text, target_id="rx-1"):
    fields = {"type_to_dispense": {"text": unit_text}} if unit_text is not None else {}
    return SimpleNamespace(context={"fields": fields}, target=SimpleNamespace(id=target_id))


class TestPhotonDispenseUnitValidation:
    def test_no_error_when_not_selected(self):
        handler = PhotonDispenseUnitValidation(event=_validation_event("vial"))
        with _patch_metadata("No"):
            assert handler.compute() == []

    def test_no_error_for_mappable_unit(self):
        handler = PhotonDispenseUnitValidation(event=_validation_event("tablet"))
        with _patch_metadata(PHOTON_FIELD_TRUE_VALUE), \
            patch("photon_integration.handlers.command_field.CommandValidationErrorEffect") as eff:
            assert handler.compute() == []
        eff.assert_not_called()

    def test_no_error_for_missing_unit(self):
        handler = PhotonDispenseUnitValidation(event=_validation_event(None))
        with _patch_metadata(PHOTON_FIELD_TRUE_VALUE):
            assert handler.compute() == []

    def test_error_for_unmappable_unit(self):
        handler = PhotonDispenseUnitValidation(event=_validation_event("ampule"))
        with _patch_metadata(PHOTON_FIELD_TRUE_VALUE), \
            patch("photon_integration.handlers.command_field.CommandValidationErrorEffect") as eff:
            eff.return_value.apply.return_value = "VALIDATION_ERROR"
            result = handler.compute()
        assert result == ["VALIDATION_ERROR"]
        assert "ampule" in eff.return_value.add_error.call_args.args[0]
