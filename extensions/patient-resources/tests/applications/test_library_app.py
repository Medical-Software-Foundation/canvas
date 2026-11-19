"""The global admin app."""

import sys

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from patient_resources import CACHE_BUST
from patient_resources.applications.library_app import PatientResourcesAdminApp


def _app():
    app = PatientResourcesAdminApp.__new__(PatientResourcesAdminApp)
    app.event = None
    app.secrets = {}
    return app


def test_opens_the_library_by_url_not_inline_content():
    """Inline content has no document origin, so the session would not travel."""
    effect = _app().on_open()
    assert effect.url.startswith("/plugin-io/api/patient_resources/app/")
    assert effect.content is None


def test_opens_as_a_full_page():
    """It is reached from the provider menu, where there is no modal host.

    Every other menu-item application in this repo opens a page or a window;
    none of them launches the default modal from a menu entry.
    """
    assert _app().on_open().target == LaunchModalEffect.TargetType.PAGE


def test_url_carries_the_cache_bust_token():
    assert f"v={CACHE_BUST}" in _app().on_open().url


def test_no_patient_data_is_needed_to_open_it():
    """Global scope: the app must not depend on a chart being open."""
    app = PatientResourcesAdminApp.__new__(PatientResourcesAdminApp)
    app.event = None
    app.secrets = {}
    assert app.on_open() is not None
    assert not sys.modules["logger"].log.warning.called
