from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from documentation_only_prescription.protocols.documentation_only_form import (
    ACTIONS_TO_REMOVE_WHEN_DOC_ONLY,
    DOCUMENTATION_ONLY_KEY,
    DOCUMENTATION_ONLY_LABEL,
    DocumentationOnlyActionFilter,
    DocumentationOnlyFormHandler,
)


def _event(*, schema_key=None, target_id="cmd-1", actions=None):
    return SimpleNamespace(
        context={
            "schema_key": schema_key,
            "actions": actions if actions is not None else [],
        },
        target=SimpleNamespace(id=target_id),
    )


class TestDocumentationOnlyFormHandler:
    def test_emits_form_field_for_prescribe_schema(self):
        handler = DocumentationOnlyFormHandler()
        handler.event = _event(schema_key="prescribe", target_id="rx-1")

        effects = handler.compute()

        assert len(effects) == 1
        effect = effects[0]
        assert effect.command_uuid == "rx-1"
        assert len(effect.form_fields) == 1

        field = effect.form_fields[0]
        assert field.key == DOCUMENTATION_ONLY_KEY
        assert field.label == DOCUMENTATION_ONLY_LABEL
        assert field.options == ["Yes"]
        assert field.required is False

    @pytest.mark.parametrize(
        "schema_key",
        ["medicationStatement", "stopMedication", "plan", "assess", None, ""],
    )
    def test_skips_non_prescribe_schemas(self, schema_key):
        handler = DocumentationOnlyFormHandler()
        handler.event = _event(schema_key=schema_key)

        assert handler.compute() == []


class TestDocumentationOnlyActionFilter:
    DEFAULT_ACTIONS = [
        {"name": "sign_send_action"},
        {"name": "sign_action"},
        {"name": "print_action"},
        {"name": "make_changes"},
    ]
    COMMITTED_ACTIONS = [
        {"name": "send_action"},
        {"name": "print"},
        {"name": "audit"},
    ]

    def _patch_metadata(self, value):
        entry = SimpleNamespace(value=value) if value is not None else None
        first_mock = MagicMock(return_value=entry)
        filter_mock = MagicMock(return_value=MagicMock(first=first_mock))
        return patch(
            "documentation_only_prescription.protocols.documentation_only_form.CommandMetadata.objects.filter",
            filter_mock,
        )

    def test_removes_send_and_print_when_documentation_only_yes(self):
        handler = DocumentationOnlyActionFilter()
        handler.event = _event(
            target_id="rx-2",
            actions=list(self.DEFAULT_ACTIONS),
        )

        with self._patch_metadata("Yes"):
            effects = handler.compute()

        assert len(effects) == 1
        payload = json.loads(effects[0].payload)
        remaining = {a["name"] for a in payload}
        assert remaining == {"sign_action", "make_changes"}
        assert ACTIONS_TO_REMOVE_WHEN_DOC_ONLY.isdisjoint(remaining)

    def test_removes_send_and_print_in_committed_state(self):
        handler = DocumentationOnlyActionFilter()
        handler.event = _event(
            target_id="rx-2",
            actions=list(self.COMMITTED_ACTIONS),
        )

        with self._patch_metadata("Yes"):
            effects = handler.compute()

        assert len(effects) == 1
        payload = json.loads(effects[0].payload)
        remaining = {a["name"] for a in payload}
        assert remaining == {"audit"}

    def test_no_effect_when_documentation_only_no(self):
        handler = DocumentationOnlyActionFilter()
        handler.event = _event(actions=list(self.DEFAULT_ACTIONS))

        with self._patch_metadata("No"):
            assert handler.compute() == []

    def test_no_effect_when_metadata_missing(self):
        handler = DocumentationOnlyActionFilter()
        handler.event = _event(actions=list(self.DEFAULT_ACTIONS))

        with self._patch_metadata(None):
            assert handler.compute() == []

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_no_effect_when_metadata_blank(self, blank):
        handler = DocumentationOnlyActionFilter()
        handler.event = _event(actions=list(self.DEFAULT_ACTIONS))

        with self._patch_metadata(blank):
            assert handler.compute() == []

    def test_handles_missing_actions_in_context(self):
        handler = DocumentationOnlyActionFilter()
        handler.event = SimpleNamespace(
            context={},
            target=SimpleNamespace(id="rx-3"),
        )

        with self._patch_metadata("Yes"):
            effects = handler.compute()

        assert len(effects) == 1
        assert json.loads(effects[0].payload) == []
