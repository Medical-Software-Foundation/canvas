"""Tests for patient_panel.services.columns.

Pure config parsing (no DB). Cache-backed prefs use the real plugin cache via
the patient_panel-prefixed cache from tests._helpers.
"""

__is_plugin__ = True

import json

import pytest

from patient_panel.services.columns import (
    DEFAULT_COLUMNS,
    enrich_columns_for_render,
    get_all_org_columns,
    get_effective_columns,
    get_flag_color_labels,
    get_panel_config,
    get_user_column_prefs,
    normalize_metadata_column,
    resolve_inline_edit,
)
from tests._helpers import cache_delete, cache_set, plugin_cache


# ── PANEL_CONFIG parsing ──────────────────────────────────────────────────

class TestGetPanelConfig:
    def test_default_config_when_no_secret(self) -> None:
        config = get_panel_config({})
        assert isinstance(config, list) and len(config) > 0
        assert "patient" in [c["key"] for c in config]

    def test_default_config_when_empty_string(self) -> None:
        config = get_panel_config({"PANEL_CONFIG": ""})
        assert "patient" in [c["key"] for c in config]

    def test_default_config_when_invalid_json(self) -> None:
        config = get_panel_config({"PANEL_CONFIG": "{invalid json"})
        assert "patient" in [c["key"] for c in config]

    def test_custom_config_only_visible_columns(self) -> None:
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "built-in", "key": "care_team", "visible": True},
            {"type": "built-in", "key": "services", "visible": False},
        ]})
        keys = [c["key"] for c in get_panel_config({"PANEL_CONFIG": custom})]
        assert "patient" in keys
        assert "care_team" in keys
        assert "services" not in keys

    def test_observation_column_parsed(self) -> None:
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "observation", "key": "a1c", "label": "A1C", "loinc": "4548-4", "visible": True, "format": "value_units"},
        ]})
        config = get_panel_config({"PANEL_CONFIG": custom})
        obs_col = next(c for c in config if c["key"] == "a1c")
        assert obs_col["type"] == "observation"
        assert obs_col["loinc"] == "4548-4"
        assert obs_col["format"] == "value_units"

    def test_metadata_column_parsed(self) -> None:
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "metadata", "key": "preferred_language", "label": "Language", "visible": True},
        ]})
        config = get_panel_config({"PANEL_CONFIG": custom})
        meta_col = next(c for c in config if c["key"] == "preferred_language")
        assert meta_col["type"] == "metadata"
        assert meta_col["label"] == "Language"

    def test_config_missing_columns_key_falls_back(self) -> None:
        config = get_panel_config({"PANEL_CONFIG": json.dumps({"other": "data"})})
        assert "patient" in [c["key"] for c in config]

    def test_unknown_builtin_key_dropped(self) -> None:
        # A misconfigured instance may declare metadata-backed fields like
        # `services`/`risk` as type "built-in". The renderer has no resolver or
        # label for them, so they would surface as dead columns (empty header,
        # `—` cells). They must be dropped rather than rendered.
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "built-in", "key": "services", "visible": True},
            {"type": "built-in", "key": "risk", "visible": True},
        ]})
        keys = [c["key"] for c in get_panel_config({"PANEL_CONFIG": custom})]
        assert "patient" in keys
        assert "services" not in keys
        assert "risk" not in keys

    def test_unknown_builtin_key_dropped_in_picker(self) -> None:
        # The column picker (visible_only=False) must also drop unrenderable
        # built-in keys so they don't appear as toggleable dead columns.
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "built-in", "key": "risk", "visible": False},
        ]})
        keys = [c["key"] for c in get_all_org_columns({"PANEL_CONFIG": custom})]
        assert "risk" not in keys


# ── FLAG_COLOR_LABELS ─────────────────────────────────────────────────────

class TestGetFlagColorLabels:
    def test_no_secret_returns_defaults(self) -> None:
        assert get_flag_color_labels({}) == {"green": "Green", "yellow": "Yellow", "red": "Red"}

    def test_empty_secret_returns_defaults(self) -> None:
        assert get_flag_color_labels({"FLAG_COLOR_LABELS": "   "})["green"] == "Green"

    def test_invalid_json_returns_defaults(self) -> None:
        assert get_flag_color_labels({"FLAG_COLOR_LABELS": "{not json"})["green"] == "Green"

    def test_full_override(self) -> None:
        labels = get_flag_color_labels({"FLAG_COLOR_LABELS": '{"red": "Urgent", "yellow": "Follow-up", "green": "On track"}'})
        assert labels == {"red": "Urgent", "yellow": "Follow-up", "green": "On track"}

    def test_partial_override_keeps_defaults(self) -> None:
        labels = get_flag_color_labels({"FLAG_COLOR_LABELS": '{"red": "Urgent"}'})
        assert labels["red"] == "Urgent"
        assert labels["green"] == "Green"
        assert labels["yellow"] == "Yellow"

    def test_extra_keys_ignored(self) -> None:
        labels = get_flag_color_labels({"FLAG_COLOR_LABELS": '{"red": "Urgent", "blue": "Ignored", "green": "Ok"}'})
        assert "blue" not in labels
        assert labels["red"] == "Urgent"
        assert labels["green"] == "Ok"

    def test_non_string_values_ignored(self) -> None:
        assert get_flag_color_labels({"FLAG_COLOR_LABELS": '{"red": 123}'})["red"] == "Red"


# ── normalize_metadata_column ─────────────────────────────────────────────

class TestNormalizeMetadataColumn:
    def test_clean_split_passes_through(self) -> None:
        result = normalize_metadata_column({"type": "metadata", "key": "consent_signatures", "path": "consents.ide-gas.status"})
        assert result["key"] == "consent_signatures"
        assert result["path"] == "consents.ide-gas.status"

    def test_shorthand_combined_key_is_split(self) -> None:
        result = normalize_metadata_column({"type": "metadata", "key": "consent_signatures.consents.ide-gas.status"})
        assert result["key"] == "consent_signatures"
        assert result["path"] == "consents.ide-gas.status"

    def test_strips_whitespace_after_dot(self) -> None:
        result = normalize_metadata_column({"type": "metadata", "key": "consent_signatures. consents.ide-gas.status"})
        assert result["key"] == "consent_signatures"
        assert result["path"] == "consents.ide-gas.status"

    def test_strips_whitespace_around_key_and_path(self) -> None:
        result = normalize_metadata_column({"type": "metadata", "key": "  consent_signatures  ", "path": "  consents.ide-gas.status  "})
        assert result["key"] == "consent_signatures"
        assert result["path"] == "consents.ide-gas.status"

    def test_no_dot_no_path_unchanged(self) -> None:
        result = normalize_metadata_column({"type": "metadata", "key": "preferred_language"})
        assert result["key"] == "preferred_language"
        assert result.get("path", "") == ""

    def test_explicit_path_wins_over_dot_in_key(self) -> None:
        result = normalize_metadata_column({"type": "metadata", "key": "weird.key", "path": "real.path"})
        assert result["key"] == "weird.key"
        assert result["path"] == "real.path"

    def test_preserves_other_fields(self) -> None:
        result = normalize_metadata_column({
            "type": "metadata",
            "key": "consent_signatures. consents.ide-gas.status",
            "label": "Consent Status",
            "visible": True,
        })
        assert result["label"] == "Consent Status"
        assert result["visible"] is True
        assert result["type"] == "metadata"


# ── get_all_org_columns ───────────────────────────────────────────────────

class TestGetAllOrgColumns:
    def test_returns_all_default_columns_when_no_secret(self) -> None:
        keys = [c["key"] for c in get_all_org_columns({})]
        assert "patient" in keys
        assert "next_visit" in keys
        assert "mrn" in keys

    def test_returns_all_default_columns_when_empty_string(self) -> None:
        assert len(get_all_org_columns({"PANEL_CONFIG": ""})) == len(DEFAULT_COLUMNS)

    def test_returns_all_default_columns_when_invalid_json(self) -> None:
        assert "patient" in [c["key"] for c in get_all_org_columns({"PANEL_CONFIG": "{bad json"})]

    def test_returns_both_visible_and_hidden_columns(self) -> None:
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "built-in", "key": "care_team", "visible": False},
            {"type": "built-in", "key": "tasks", "visible": True},
        ]})
        cols = get_all_org_columns({"PANEL_CONFIG": custom})
        keys = [c["key"] for c in cols]
        assert "patient" in keys and "care_team" in keys and "tasks" in keys
        assert next(c for c in cols if c["key"] == "care_team")["visible"] is False

    def test_enriches_observation_columns(self) -> None:
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "observation", "key": "a1c", "loinc": "4548-4", "visible": True},
        ]})
        cols = get_all_org_columns({"PANEL_CONFIG": custom})
        assert next(c for c in cols if c["key"] == "a1c")["label"] == "A1C"

    def test_does_not_mutate_default_columns(self) -> None:
        for col, default in zip(get_all_org_columns({}), DEFAULT_COLUMNS):
            assert col is not default

    def test_falls_back_when_columns_key_missing(self) -> None:
        cols = get_all_org_columns({"PANEL_CONFIG": json.dumps({"other": "data"})})
        assert "patient" in [c["key"] for c in cols]


# ── cache-backed prefs (ORM-free but uses the plugin cache) ───────────────

pytestmark = pytest.mark.django_db


def _clear(*keys: str) -> None:
    for key in keys:
        cache_delete(key)


class TestGetUserColumnPrefs:
    def test_returns_none_when_no_cache_entry(self) -> None:
        _clear("column_prefs_staff-empty")
        assert get_user_column_prefs(plugin_cache(), "staff-empty") is None

    def test_returns_parsed_prefs(self) -> None:
        prefs = {"patient": True, "care_team": False, "tasks": True}
        cache_set("column_prefs_staff-parsed", json.dumps(prefs))
        try:
            assert get_user_column_prefs(plugin_cache(), "staff-parsed") == prefs
        finally:
            _clear("column_prefs_staff-parsed")

    def test_returns_none_on_invalid_json(self) -> None:
        cache_set("column_prefs_staff-bad", "{bad json")
        try:
            assert get_user_column_prefs(plugin_cache(), "staff-bad") is None
        finally:
            _clear("column_prefs_staff-bad")

    def test_returns_none_when_cached_value_is_not_dict(self) -> None:
        cache_set("column_prefs_staff-list", json.dumps(["not", "a", "dict"]))
        try:
            assert get_user_column_prefs(plugin_cache(), "staff-list") is None
        finally:
            _clear("column_prefs_staff-list")


class TestGetEffectiveColumns:
    def test_returns_org_visible_when_no_user_prefs(self) -> None:
        _clear("column_prefs_eff-1")
        keys = [c["key"] for c in get_effective_columns({}, plugin_cache(), "eff-1")]
        assert "patient" in keys
        assert "next_visit" not in keys  # hidden by default

    def test_user_prefs_override_visibility(self) -> None:
        cache_set("column_prefs_eff-2", json.dumps({"next_visit": True, "tasks": False}))
        try:
            keys = [c["key"] for c in get_effective_columns({}, plugin_cache(), "eff-2")]
            assert "next_visit" in keys
            assert "tasks" not in keys
        finally:
            _clear("column_prefs_eff-2")

    def test_columns_not_in_prefs_keep_org_visibility(self) -> None:
        cache_set("column_prefs_eff-3", json.dumps({"tasks": False}))
        try:
            keys = [c["key"] for c in get_effective_columns({}, plugin_cache(), "eff-3")]
            assert "patient" in keys
            assert "tasks" not in keys
        finally:
            _clear("column_prefs_eff-3")

    def test_effective_columns_with_custom_panel_config(self) -> None:
        custom = json.dumps({"columns": [
            {"type": "built-in", "key": "patient", "visible": True},
            {"type": "built-in", "key": "care_team", "visible": False},
            {"type": "built-in", "key": "tasks", "visible": True},
        ]})
        cache_set("column_prefs_eff-4", json.dumps({"care_team": True}))
        try:
            keys = [c["key"] for c in get_effective_columns({"PANEL_CONFIG": custom}, plugin_cache(), "eff-4")]
            assert "care_team" in keys
        finally:
            _clear("column_prefs_eff-4")


# ── inline-edit resolution (constraint: upsert replaces the WHOLE value) ────


def _secrets(fields: list[dict]) -> dict:
    return {"METADATA_FIELDS": json.dumps(fields)}


RISK_SELECT_FIELD = {
    "key": "risk_score",
    "label": "Risk",
    "type": "SELECT",
    "options": ["Low", "Medium", "High"],
    "editable": True,
}


class TestResolveInlineEdit:
    def test_select_metadata_column_returns_type_and_options(self) -> None:
        col = {"type": "metadata", "key": "risk_score"}
        assert resolve_inline_edit(col, _secrets([RISK_SELECT_FIELD])) == {
            "type": "SELECT",
            "options": ["Low", "Medium", "High"],
        }

    def test_text_field_returns_empty_options(self) -> None:
        col = {"type": "metadata", "key": "note"}
        secrets = _secrets([{"key": "note", "type": "TEXT", "editable": True}])
        assert resolve_inline_edit(col, secrets) == {"type": "TEXT", "options": []}

    def test_date_field_returns_empty_options(self) -> None:
        col = {"type": "metadata", "key": "review_on"}
        secrets = _secrets([{"key": "review_on", "type": "DATE", "editable": True}])
        assert resolve_inline_edit(col, secrets) == {"type": "DATE", "options": []}

    def test_non_editable_field_returns_none(self) -> None:
        col = {"type": "metadata", "key": "risk_score"}
        field = {**RISK_SELECT_FIELD, "editable": False}
        assert resolve_inline_edit(col, _secrets([field])) is None

    def test_no_matching_metadata_field_returns_none(self) -> None:
        col = {"type": "metadata", "key": "risk_score"}
        assert resolve_inline_edit(col, _secrets([])) is None

    def test_dotted_path_column_returns_none(self) -> None:
        # Editing would upsert the WHOLE metadata value, clobbering the nested
        # JSON the dotted path points at. Must never be inline-editable.
        col = {"type": "metadata", "key": "risk_score", "path": "nested.value"}
        assert resolve_inline_edit(col, _secrets([RISK_SELECT_FIELD])) is None

    def test_tags_render_column_returns_none(self) -> None:
        # tags render is a pipe-joined multi-value; a single-value upsert would
        # clobber the list. Must never be inline-editable.
        col = {"type": "metadata", "key": "risk_score", "render": "tags"}
        assert resolve_inline_edit(col, _secrets([RISK_SELECT_FIELD])) is None

    def test_select_with_no_options_returns_none(self) -> None:
        col = {"type": "metadata", "key": "risk_score"}
        field = {"key": "risk_score", "type": "SELECT", "options": [], "editable": True}
        assert resolve_inline_edit(col, _secrets([field])) is None

    def test_non_metadata_column_returns_none(self) -> None:
        for col in (
            {"type": "built-in", "key": "patient"},
            {"type": "observation", "key": "a1c", "loinc": "4548-4"},
        ):
            assert resolve_inline_edit(col, _secrets([RISK_SELECT_FIELD])) is None

    def test_options_source_is_metadata_fields_not_column_sort_order(self) -> None:
        # The editable option set MUST come from METADATA_FIELDS (what the
        # backend validates against), not the column's sort_order.
        col = {"type": "metadata", "key": "risk_score", "sort_order": ["X", "Y"]}
        result = resolve_inline_edit(col, _secrets([RISK_SELECT_FIELD]))
        assert result == {"type": "SELECT", "options": ["Low", "Medium", "High"]}


class TestEnrichColumnsForRender:
    def test_adds_inline_edit_only_to_safe_columns(self) -> None:
        columns = [
            {"type": "built-in", "key": "patient"},
            {"type": "metadata", "key": "risk_score"},
            {"type": "metadata", "key": "risk_score", "path": "a.b"},
        ]
        out = enrich_columns_for_render(columns, _secrets([RISK_SELECT_FIELD]))
        assert "inline_edit" not in out[0]
        assert out[1]["inline_edit"] == {"type": "SELECT", "options": ["Low", "Medium", "High"]}
        assert "inline_edit" not in out[2]

    def test_does_not_mutate_input(self) -> None:
        columns = [{"type": "metadata", "key": "risk_score"}]
        enrich_columns_for_render(columns, _secrets([RISK_SELECT_FIELD]))
        assert columns == [{"type": "metadata", "key": "risk_score"}]
