"""Tests for admin application handler."""
import json

from patient_notify.handlers.admin_app import NotifyAdminApp


def test_on_open_returns_launch_modal_effect() -> None:
    """Test on_open returns a LaunchModalEffect targeting the admin page."""
    handler = NotifyAdminApp.__new__(NotifyAdminApp)

    result = handler.on_open()

    assert not isinstance(result, list)
    assert result.type == 3000  # LAUNCH_MODAL
    payload = json.loads(result.payload)
    assert payload["data"]["url"] == "/plugin-io/api/patient_notify/admin"
    assert payload["data"]["target"] == "page"


def test_manifest_admin_app_scope() -> None:
    """Test manifest declares admin app with provider_menu_item scope."""
    manifest_path = (
        "patient_notify/CANVAS_MANIFEST.json"
    )
    with open(manifest_path) as f:
        manifest = json.load(f)

    admin_app = manifest["components"]["applications"][0]
    assert admin_app["scope"] == "provider_menu_item"
    assert admin_app["menu_position"] == "top"
    assert admin_app["menu_order"] == 100


def test_manifest_data_access_includes_organization() -> None:
    """Test manifest protocols include v1.Organization in data_access.read."""
    manifest_path = (
        "patient_notify/CANVAS_MANIFEST.json"
    )
    with open(manifest_path) as f:
        manifest = json.load(f)

    for protocol in manifest["components"]["protocols"]:
        assert "v1.Organization" in protocol["data_access"]["read"], (
            f"{protocol['class']} missing v1.Organization"
        )
