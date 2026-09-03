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


def _declared_variables() -> dict[str, bool]:
    """Declared variable names mapped to their ``sensitive`` flag.

    Reads the current ``variables`` array and the deprecated ``secrets`` list,
    so the invariants below hold through the migration either way.
    """
    manifest = json.loads((PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text())
    declared = {name: True for name in manifest.get("secrets", [])}
    for entry in manifest.get("variables", []):
        declared[entry["name"]] = entry.get("sensitive", False)
    return declared


def test_namespace_read_write_access_key_declared() -> None:
    """When custom_data.access is read_write, the manifest MUST declare
    the namespace_read_write_access_key variable or installs fail."""
    manifest = json.loads((PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text())
    if manifest.get("custom_data", {}).get("access") == "read_write":
        assert "namespace_read_write_access_key" in _declared_variables(), (
            "read_write namespace requires namespace_read_write_access_key declared"
        )


def test_credential_variables_are_marked_sensitive() -> None:
    """Anything that authenticates, or that holds patient data, must be masked.

    A credential declared non-sensitive is readable in the Admin UI and by
    anyone with managing-user permissions, so this is a real exposure rather
    than a style preference.
    """
    declared = _declared_variables()
    must_be_masked = {
        "namespace_read_write_access_key",
        "twilio-account-sid",
        "twilio-auth-token",
        "twilio-api-key-sid",
        "twilio-api-key-secret",
        "sendgrid-api-key",
    }
    for name in must_be_masked:
        assert declared.get(name) is True, f"{name} must be declared sensitive"


def test_operational_variables_stay_readable() -> None:
    """Values an operator has to eyeball are deliberately not masked.

    A sensitive variable can only be confirmed as ``[set]``, which makes
    diagnosing a signature mismatch or a wrong sender number needlessly hard.
    """
    declared = _declared_variables()
    for name in (
        "twilio-phone-number",
        "twilio-inbound-webhook-url",
        "sendgrid-from-email",
        "ADMIN_ROLE_NAMES",
    ):
        assert declared.get(name) is False, f"{name} should be readable, not masked"


def test_every_variable_used_in_code_is_declared() -> None:
    """A variable read at runtime but missing from the manifest can never be set."""
    declared = _declared_variables()
    for name in (
        "twilio-account-sid",
        "twilio-auth-token",
        "twilio-phone-number",
        "twilio-inbound-webhook-url",
        "sendgrid-api-key",
        "sendgrid-from-email",
        "LOCK_MESSAGE_TEMPLATES",
        "ADMIN_ROLE_NAMES",
    ):
        assert name in declared, f"{name} is read in code but not declared"


def test_no_legacy_bigleap_references_in_manifest() -> None:
    raw = (PLUGIN_DIR / "CANVAS_MANIFEST.json").read_text().lower()
    for term in ("big_leap", "bigleap", "spravato", "rebate", "forms_with_signature"):
        assert term not in raw, f"manifest still contains legacy term {term!r}"


def test_plugin_config_holds_only_credentials_and_permissions() -> None:
    """Operational settings belong in the admin app, not plugin config.

    Plugin config requires instance-level access to change, which is the right
    bar for credentials and for who may administer the plugin — and the wrong
    bar for day-to-day operation. Testing mode used to live here and now lives
    in CampaignConfig, where an administrator can reach it.
    """
    declared = set(_declared_variables())
    operational = {"TESTING_MODE", "TESTING_MODE_PATIENTS", "TESTING_MODE_RECIPIENTS"}
    assert not (declared & operational), (
        "operational settings must not be declared as plugin variables"
    )
