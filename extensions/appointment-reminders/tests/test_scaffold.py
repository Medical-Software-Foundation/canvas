"""Smoke tests for the appointment_reminders plugin scaffold.

Verifies the plugin package imports, the manifest is present and valid JSON,
and the manifest fields the SDK enforces (name, version, namespace pattern)
match the values declared in code.
"""

from __future__ import annotations

import json
import pathlib
import re

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1] / "appointment_reminders"


def test_plugin_package_imports() -> None:
    import appointment_reminders  # noqa: F401


def test_manifest_is_present_and_valid_json() -> None:
    manifest_path = PLUGIN_DIR / "CANVAS_MANIFEST.json"
    assert manifest_path.exists(), "CANVAS_MANIFEST.json missing from plugin root"
    json.loads(manifest_path.read_text())


def test_manifest_name_and_version() -> None:
    manifest = json.loads((PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text())
    assert manifest["name"] == "appointment_reminders"
    # Version must be semver-ish
    assert re.match(r"^\d+\.\d+\.\d+$", manifest["plugin_version"])


def test_custom_data_namespace_matches_required_pattern() -> None:
    """plugin-runner enforces ^[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$ on namespaces."""
    manifest = json.loads((PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text())
    namespace = manifest["custom_data"]["namespace"]
    assert re.match(r"^[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$", namespace), (
        f"namespace {namespace!r} violates org__name pattern"
    )


def test_namespace_read_write_access_key_declared() -> None:
    """When custom_data.access is read_write, the manifest MUST declare
    the namespace_read_write_access_key secret or installs fail."""
    manifest = json.loads((PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text())
    if manifest.get("custom_data", {}).get("access") == "read_write":
        assert "namespace_read_write_access_key" in manifest.get("secrets", []), (
            "read_write namespace requires namespace_read_write_access_key in secrets"
        )


def test_no_legacy_bigleap_references_in_manifest() -> None:
    raw = (PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text().lower()
    for term in ("big_leap", "bigleap", "spravato", "rebate", "forms_with_signature"):
        assert term not in raw, f"manifest still contains legacy term {term!r}"
