"""Tests for clinical_pathways.terminal_commands."""

from __future__ import annotations

from clinical_pathways.terminal_commands import (
    TERMINAL_COMMANDS,
    terminal_command_catalog,
)


class TestTerminalCommandsRegistry:
    def test_pathway_classification_is_registered(self) -> None:
        assert "pathway_classification" in TERMINAL_COMMANDS

    def test_schema_key_matches_manifest_convention(self) -> None:
        spec = TERMINAL_COMMANDS["pathway_classification"]
        assert spec["schema_key"] == "pathwayClassification"
        assert spec["section"] == "plan"

    def test_required_fields_include_title_and_body(self) -> None:
        spec = TERMINAL_COMMANDS["pathway_classification"]
        required_keys = {f["key"] for f in spec["fields"] if f.get("required")}
        assert required_keys == {"title", "body"}

    def test_severity_options_cover_clinical_levels(self) -> None:
        spec = TERMINAL_COMMANDS["pathway_classification"]
        severity_field = next(f for f in spec["fields"] if f["key"] == "severity")
        values = {opt["value"] for opt in severity_field["options"]}
        assert {"minor", "moderate", "severe", "critical", ""} == values


class TestTerminalCommandCatalog:
    def test_catalog_serializes_each_registered_command(self) -> None:
        catalog = terminal_command_catalog()
        assert len(catalog) == len(TERMINAL_COMMANDS)
        keys_in_catalog = {entry["key"] for entry in catalog}
        assert keys_in_catalog == set(TERMINAL_COMMANDS.keys())

    def test_catalog_entries_strip_internal_fields(self) -> None:
        catalog = terminal_command_catalog()
        entry = next(e for e in catalog if e["key"] == "pathway_classification")
        # The catalog projection should NOT expose the internal "section" key.
        assert "section" not in entry
        # And should expose name/description/fields/schema_key.
        assert set(entry.keys()) == {
            "key",
            "schema_key",
            "name",
            "description",
            "fields",
        }
