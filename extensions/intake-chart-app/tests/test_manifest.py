"""Regression tests for CANVAS_MANIFEST.json invariants.

The plugin runner enforces declarations that aren't visible from the
Python source — pruning a manifest entry "because nothing imports it"
silently breaks the deploy. These assertions are cheap and guard against
that.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_manifest() -> dict:
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "intake_chart_app"
        / "CANVAS_MANIFEST.json"
    )
    return json.loads(manifest_path.read_text())


def test_manifest_declares_namespace_read_write_access_key() -> None:
    """The runtime auto-generates a value for this secret when the
    namespace is first initialised, but only when the secret is declared
    here. Without the declaration, any plugin that sets
    ``custom_data.access = read_write`` fails to load with
    ``PluginInstallationError: ... 'namespace_read_write_access_key'
    secret is not configured``."""
    manifest = _load_manifest()
    secrets = manifest.get("secrets", [])
    custom_data = manifest.get("custom_data", {})
    if custom_data.get("access") == "read_write":
        assert "namespace_read_write_access_key" in secrets, (
            "Manifest sets custom_data.access = read_write but does not "
            "declare 'namespace_read_write_access_key' in secrets. The "
            "runtime won't auto-generate the key and the plugin will fail "
            "to load."
        )
    if custom_data.get("access") in ("read", "read_only"):
        assert "namespace_read_only_access_key" in secrets, (
            "Manifest sets custom_data.access = read_only but does not "
            "declare 'namespace_read_only_access_key' in secrets."
        )


def test_manifest_secrets_match_self_secrets_lookups() -> None:
    """Every ``self.secrets.get("X")`` lookup in production code must be
    declared in the manifest's ``secrets`` array. Catches both
    accidental code-side typos and accidental manifest pruning."""
    manifest = _load_manifest()
    declared = set(manifest.get("secrets", []))
    # Secrets known to be read from Python code in this plugin. Keep this
    # explicit (rather than grepping at test time) so the list stays
    # easy to audit. The runtime-injected ``namespace_*_access_key``
    # entries are NOT read by plugin code, so they don't appear here.
    expected_used_by_code = {
        "intake-note-types",
        "canvas-instance-origin",
    }
    missing = expected_used_by_code - declared
    assert not missing, (
        f"Secrets used by plugin code but not declared in manifest: {missing}"
    )


def test_manifest_plugin_version_set() -> None:
    """Sanity: deploys need a real semver-shaped string here."""
    manifest = _load_manifest()
    version = manifest.get("plugin_version", "")
    parts = version.split(".")
    assert len(parts) >= 3, f"plugin_version {version!r} doesn't look semver-shaped"
    for part in parts[:3]:
        assert part.isdigit(), f"plugin_version {version!r} has non-numeric segment {part!r}"
