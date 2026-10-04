"""The patient-portal menu entry."""

import sys
from unittest.mock import MagicMock

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.v1.data import Patient

from patient_resources.applications.portal_app import MyResourcesPortalApp
from patient_resources.models import PatientResourceShare

log = sys.modules["logger"].log


def _app(context):
    app = MyResourcesPortalApp.__new__(MyResourcesPortalApp)
    app.event = MagicMock()
    app.event.context = context
    app.secrets = {}
    return app


def test_opens_the_portal_page_for_a_signed_in_patient():
    effect = _app({"user": {"id": "abc"}}).on_open()
    assert effect.url.startswith("/plugin-io/api/patient_resources/portal/")
    assert effect.target == LaunchModalEffect.TargetType.PAGE
    assert effect.content is None


def test_patient_id_is_never_placed_in_the_url():
    """The page resolves the patient from the session on every request instead.

    The query string carries the cache-bust token and nothing else, so there is
    no parameter in the document for anyone to swap for another patient's key.
    """
    from urllib.parse import parse_qs, urlparse

    effect = _app({"user": {"id": "abc123"}}).on_open()
    assert "abc123" not in effect.url
    assert set(parse_qs(urlparse(effect.url).query)) == {"v"}


def test_falls_back_to_the_patient_context_key():
    assert _app({"patient": {"id": "abc"}}).on_open() is not None


def test_returns_no_effect_when_there_is_no_patient():
    assert _app({}).on_open() == []
    assert log.warning.called


def test_the_warning_does_not_dump_the_event_context():
    """portal-content logs the whole context here, which puts patient data in logs."""
    _app({"user": {}, "secret_field": "sensitive"}).on_open()
    logged = " ".join(str(call) for call in log.warning.call_args_list)
    assert "sensitive" not in logged


# --- the badge ------------------------------------------------------------


def test_badge_counts_unviewed_shares(mock_patient):
    Patient.objects.filter.return_value.only.return_value.first.return_value = mock_patient
    PatientResourceShare.objects.filter.return_value.count.return_value = 2
    assert _app({"user": {"id": mock_patient.id}}).compute_notification_badge() == 2


def test_badge_is_zero_once_the_list_has_been_opened(mock_patient):
    """Zero clears an existing badge; None would leave it showing."""
    Patient.objects.filter.return_value.only.return_value.first.return_value = mock_patient
    PatientResourceShare.objects.filter.return_value.count.return_value = 0
    assert _app({"user": {"id": mock_patient.id}}).compute_notification_badge() == 0


def test_badge_is_none_without_a_patient():
    assert _app({}).compute_notification_badge() is None


def test_badge_is_none_when_the_patient_cannot_be_resolved():
    Patient.objects.filter.return_value.only.return_value.first.return_value = None
    assert _app({"user": {"id": "nobody"}}).compute_notification_badge() is None
