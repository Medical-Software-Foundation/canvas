"""Tests for the Salesforce Canvas id writeback handler.

These run the handler against the ORM for the link lookup, so they run where
canvas_sdk is importable. The autouse transaction(db) fixture from pytest-canvas
covers the database. The event is mocked and the Salesforce client is a fake
swapped through the handler's _build_client seam, the patient and its external
identifier are real.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

from canvas_sdk.events import EventType

from salesforce_to_canvas_integration.handlers.canvas_id_writeback import (
    SalesforceCanvasIdWriteback,
)
from salesforce_to_canvas_integration.services.sf_client import (
    SalesforceError,
    SalesforceNotConnectedError,
)

_SECRETS = {
    "SF_CLIENT_ID": "cid",
    "SF_CLIENT_SECRET": "csecret",
    "SF_LOGIN_URL": "https://login.salesforce.com",
    "SF_WEBHOOK_SECRET": "whsecret",
    "SF_ADMIN_STAFF_IDS": "abc",
}


class FakeClient:
    """Records the write_canvas_id call, or raises a scripted error."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, str]] = []

    def write_canvas_id(
        self,
        *,
        sobject: str,
        sf_record_id: str,
        canvas_patient_id: str,
        field_name: str = "Canvas_Patient_ID__c",
    ) -> None:
        self.calls.append(
            {
                "sobject": sobject,
                "sf_record_id": sf_record_id,
                "canvas_patient_id": canvas_patient_id,
            }
        )
        if self.error is not None:
            raise self.error


def _handler(
    target_id: str = "",
    secrets: dict[str, str] | None = None,
    client: FakeClient | None = None,
) -> SalesforceCanvasIdWriteback:
    """Build a handler with a mocked PATIENT_CREATED event and a fake client."""
    handler = SalesforceCanvasIdWriteback.__new__(SalesforceCanvasIdWriteback)
    handler.event = MagicMock()
    handler.event.type = EventType.PATIENT_CREATED
    handler.event.target.id = target_id
    handler.secrets = secrets if secrets is not None else dict(_SECRETS)
    if client is not None:
        handler._build_client = lambda config: client  # type: ignore[method-assign]
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


def test_writes_the_canvas_id_for_a_linked_patient() -> None:
    """A create on a linked patient PATCHes the Salesforce record with its id."""
    patient = _link_patient("003WB")
    client = FakeClient()

    effects = _handler(str(patient.id), client=client).compute()

    assert effects == []
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["sobject"] == "Contact"
    assert call["sf_record_id"] == "003WB"
    assert call["canvas_patient_id"] == str(patient.id)


def test_skips_a_patient_with_no_salesforce_identifier() -> None:
    """A create on a non sync patient writes nothing back."""
    from canvas_sdk.test_utils.factories import PatientFactory

    patient = PatientFactory.create()
    client = FakeClient()

    effects = _handler(str(patient.id), client=client).compute()

    assert effects == []
    assert client.calls == []


def test_degrades_quietly_when_not_connected() -> None:
    """No OAuth connection means the attempt is made and the error swallowed."""
    patient = _link_patient("003WB")
    client = FakeClient(error=SalesforceNotConnectedError("no tokens"))

    effects = _handler(str(patient.id), client=client).compute()

    assert effects == []
    assert len(client.calls) == 1


def test_degrades_quietly_on_a_writeback_failure() -> None:
    """A failed PATCH degrades to a logged skip, never propagates."""
    patient = _link_patient("003WB")
    client = FakeClient(error=SalesforceError("500 boom"))

    effects = _handler(str(patient.id), client=client).compute()

    assert effects == []
    assert len(client.calls) == 1


def test_uses_the_configured_source_sobject() -> None:
    """The PATCH targets the configured source sObject, not always Contact."""
    patient = _link_patient("00QLEAD")
    client = FakeClient()
    secrets = dict(_SECRETS, SF_SOURCE_SOBJECT="Lead")

    _handler(str(patient.id), secrets=secrets, client=client).compute()

    assert client.calls[0]["sobject"] == "Lead"


def test_no_banner_target_id_is_a_clean_noop() -> None:
    """An event with no target id writes nothing and does not query."""
    client = FakeClient()

    effects = _handler("", client=client).compute()

    assert effects == []
    assert client.calls == []


def test_degrades_quietly_on_config_error() -> None:
    """A missing config key logs and returns [], never raises."""
    patient = _link_patient("003WB")
    handler = _handler(str(patient.id), secrets={})

    effects = handler.compute()

    assert effects == []


def test_build_client_returns_a_salesforce_client_instance() -> None:
    """_build_client constructs the real client when the seam is not overridden."""
    from unittest.mock import MagicMock, patch

    from salesforce_to_canvas_integration.services.config import load_config
    from salesforce_to_canvas_integration.services.sf_client import SalesforceClient

    handler = _handler()
    config = load_config(dict(_SECRETS))

    class _FakeCache:
        def get(self, key: str, default: object = None) -> object:
            return default

        def set(self, key: str, value: object, **kw: object) -> None:
            pass

        def delete(self, key: str) -> None:
            pass

    with patch(
        "salesforce_to_canvas_integration.handlers.canvas_id_writeback.get_cache",
        return_value=_FakeCache(),
    ):
        client = handler._build_client(config)

    assert isinstance(client, SalesforceClient)


def test_no_banned_characters_in_source() -> None:
    """No em dash, en dash, or curly quotes in the handler module source."""
    from pathlib import Path

    import salesforce_to_canvas_integration.handlers.canvas_id_writeback as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    for ch in ("—", "–", "“", "”", "‘", "’"):
        assert ch not in text
