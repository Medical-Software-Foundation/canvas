"""Tests for the Salesforce record link chart banner.

These exercise the handler against the ORM for the link check and the source
object lookup, so they run where canvas_sdk is importable. The autouse
transaction(db) fixture from pytest-canvas covers the database. The event and
the token store are mocked, the rest is real.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from canvas_sdk.events import EventType

from salesforce_to_canvas_integration.handlers.chart_banner import (
    BANNER_KEY,
    SalesforceChartBanner,
)
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)

_INSTANCE = "https://example.my.salesforce.com"


def _handler(
    event_type: int,
    target_id: str = "",
    secrets: dict[str, str] | None = None,
) -> SalesforceChartBanner:
    """Build a handler with a mocked event of the given type and target."""
    handler = SalesforceChartBanner.__new__(SalesforceChartBanner)
    handler.event = MagicMock()
    handler.event.type = event_type
    handler.event.target.id = target_id
    handler.secrets = secrets or {}
    return handler


def _link_patient(external_id: str) -> Any:
    """Create a Canvas patient carrying the salesforce external identifier."""
    from canvas_sdk.test_utils.factories import PatientFactory
    from canvas_sdk.v1.data.patient import PatientExternalIdentifier

    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


def _capture(external_id: str, source_object: str, content_hash: str) -> None:
    """Land an inbound record so the handler can recover the source object."""
    IncomingPatientRecord.objects.create(
        external_id=external_id,
        source_object=source_object,
        action="create",
        content_hash=content_hash,
    )


def _patch_tokens(instance_url: str | None) -> Any:
    """Patch the token store so load() returns a token with the instance url."""
    tokens = None
    if instance_url is not None:
        tokens = MagicMock()
        tokens.instance_url = instance_url
    store = MagicMock()
    store.return_value.load.return_value = tokens
    return patch.multiple(
        "salesforce_to_canvas_integration.handlers.chart_banner",
        TokenStore=store,
        get_cache=MagicMock(),
    )


def test_banner_for_a_linked_patient_uses_the_lightning_url() -> None:
    """A patient event on a linked patient emits a chart banner to the record."""
    patient = _link_patient("003LINK")
    _capture("003LINK", "Contact", "hash-create-001")

    with _patch_tokens(_INSTANCE):
        effects = _handler(EventType.PATIENT_UPDATED, str(patient.id)).compute()

    assert len(effects) == 1
    payload = effects[0].payload
    assert f"{_INSTANCE}/lightning/r/Contact/003LINK/view" in payload
    assert "chart" in payload
    assert BANNER_KEY in payload


def test_banner_uses_bare_redirect_when_no_source_object() -> None:
    """With no captured source object the href is the id prefix redirect."""
    patient = _link_patient("003NOEVT")

    with _patch_tokens(_INSTANCE):
        effects = _handler(EventType.PATIENT_CREATED, str(patient.id)).compute()

    assert len(effects) == 1
    assert f"{_INSTANCE}/003NOEVT" in effects[0].payload


def test_no_banner_for_an_unlinked_patient() -> None:
    """A patient event on a chart with no salesforce identifier emits nothing."""
    from canvas_sdk.test_utils.factories import PatientFactory

    patient = PatientFactory.create()

    with _patch_tokens(_INSTANCE):
        effects = _handler(EventType.PATIENT_UPDATED, str(patient.id)).compute()

    assert effects == []


def test_no_banner_when_instance_url_missing() -> None:
    """No connected org and no fallback secret means no href, no banner."""
    patient = _link_patient("003LINK")

    with _patch_tokens(None):
        effects = _handler(EventType.PATIENT_UPDATED, str(patient.id)).compute()

    assert effects == []


def test_secret_fallback_when_token_absent() -> None:
    """With no token, the SF_INSTANCE_URL secret supplies the org base."""
    patient = _link_patient("003LINK")
    _capture("003LINK", "Contact", "hash-fallback-001")
    secrets = {"SF_INSTANCE_URL": _INSTANCE}

    with _patch_tokens(None):
        effects = _handler(
            EventType.PATIENT_UPDATED, str(patient.id), secrets=secrets
        ).compute()

    assert len(effects) == 1
    assert f"{_INSTANCE}/lightning/r/Contact/003LINK/view" in effects[0].payload


def test_plugin_event_backfills_every_linked_patient() -> None:
    """A plugin event emits one banner per linked patient and skips the unlinked."""
    from canvas_sdk.test_utils.factories import PatientFactory

    _link_patient("003ONE")
    _link_patient("003TWO")
    PatientFactory.create()

    with _patch_tokens(_INSTANCE):
        effects = _handler(EventType.PLUGIN_UPDATED).compute()

    assert len(effects) == 2


def test_no_banned_characters_in_source() -> None:
    """No em dash, en dash, or curly quotes in the handler module source."""
    from pathlib import Path

    import salesforce_to_canvas_integration.handlers.chart_banner as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    for ch in ("—", "–", "“", "”", "‘", "’"):
        assert ch not in text
