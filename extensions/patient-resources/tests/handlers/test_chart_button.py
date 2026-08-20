"""The chart-header button."""

from unittest.mock import MagicMock

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from patient_resources import CACHE_BUST
from patient_resources.handlers.chart_button import ShareResourcesButton


def _button(target_id):
    button = ShareResourcesButton.__new__(ShareResourcesButton)
    button.event = MagicMock()
    button.event.target = MagicMock()
    button.event.target.id = target_id
    button.secrets = {}
    return button


def test_button_is_declared_on_the_chart_patient_header():
    assert ShareResourcesButton.BUTTON_LOCATION == ActionButton.ButtonLocation.CHART_PATIENT_HEADER


def test_button_key_is_namespaced_to_this_plugin():
    """An unprefixed key can collide with another plugin's button."""
    assert ShareResourcesButton.BUTTON_KEY.startswith("patient_resources__")


def test_button_is_always_visible_without_a_query():
    assert _button("abc").visible() is True


def test_click_opens_the_picker_for_that_patient():
    effects = _button("abc123").handle()
    assert len(effects) == 1
    assert effects[0].url.startswith("/plugin-io/api/patient_resources/app/picker?patient=abc123")
    assert effects[0].target == LaunchModalEffect.TargetType.DEFAULT_MODAL
    assert effects[0].content is None


def test_picker_url_percent_encodes_the_patient_key():
    """An unencoded key with a reserved character would silently truncate."""
    url = _button("a b/c&d").handle()[0].url
    assert "patient=a%20b%2Fc%26d" in url


def test_picker_url_carries_the_cache_bust_token():
    assert f"v={CACHE_BUST}" in _button("abc").handle()[0].url


def test_a_missing_patient_yields_no_effect():
    """Partial event payloads are the norm; this must not raise."""
    for target_id in (None, ""):
        assert _button(target_id).handle() == []
