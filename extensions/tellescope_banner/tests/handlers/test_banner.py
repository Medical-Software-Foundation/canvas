"""Behavior tests for the Tellescope profile banner."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from tellescope_banner.handlers.banner import (
    BANNER_KEY,
    TellescopeProfileBanner,
    build_profile_url,
    template_placeholders,
)

SYSTEM = "https://tellescope.example/enduser"
EXTERNAL_TEMPLATE = "https://app.tellescope.example/endusers/{external_id}"
PATIENT_TEMPLATE = "https://app.tellescope.example/canvas/{patient_id}"


def patient_event(patient_id: str, event_type: int = EventType.PATIENT_UPDATED) -> Any:
    return SimpleNamespace(
        type=event_type,
        target=SimpleNamespace(id=patient_id),
        context={},
    )


def identifier_event(patient_id: str, event_type: int) -> Any:
    return SimpleNamespace(
        type=event_type,
        target=SimpleNamespace(id="identifier-1"),
        context={"patient": {"id": patient_id}},
    )


def run(event: Any, secrets: dict[str, str]) -> list[Any]:
    return TellescopeProfileBanner(event=event, secrets=secrets).compute()


def payload(effect: Any) -> dict[str, Any]:
    return json.loads(effect.payload)


def add_identifier(patient: Any, value: str, system: str = SYSTEM) -> None:
    PatientExternalIdentifier.objects.create(
        patient=patient,
        system=system,
        value=value,
        use="usual",
        identifier_type="",
        issued_date="2026-01-01",
        expiration_date="2099-01-01",
    )


# --- template parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "template,expected",
    [
        (EXTERNAL_TEMPLATE, {"external_id"}),
        (PATIENT_TEMPLATE, {"patient_id"}),
        (
            "https://x.example/{patient_id}?e={external_id}",
            {"patient_id", "external_id"},
        ),
    ],
)
def test_valid_templates_report_their_placeholders(
    template: str, expected: set[str]
) -> None:
    assert template_placeholders(template) == expected


@pytest.mark.parametrize(
    "template",
    [
        "http://app.tellescope.example/endusers/{external_id}",  # not https
        "javascript:alert(1)//{patient_id}",
        "https://app.tellescope.example/endusers/",  # no placeholder
        "https://app.tellescope.example/{mrn}",  # unknown placeholder
        "https://app.tellescope.example/{patient_id}}",  # stray brace
        "https://app.tellescope.example/{{patient_id}",
    ],
)
def test_unusable_templates_are_rejected(template: str) -> None:
    assert template_placeholders(template) is None


def test_values_are_url_encoded_including_slashes() -> None:
    url = build_profile_url(EXTERNAL_TEMPLATE, {"external_id": "a b/../c?d=1&e#f"})
    assert (
        url == "https://app.tellescope.example/endusers/a%20b%2F..%2Fc%3Fd%3D1%26e%23f"
    )


# --- handler ----------------------------------------------------------------


@pytest.mark.django_db
def test_patient_id_template_adds_linked_banner() -> None:
    patient = PatientFactory.create()

    effects = run(
        patient_event(patient.id), {"TELLESCOPE_PROFILE_URL_TEMPLATE": PATIENT_TEMPLATE}
    )

    assert len(effects) == 1
    assert effects[0].type == EffectType.ADD_BANNER_ALERT
    body = payload(effects[0])
    assert body["patient"] == patient.id
    assert body["key"] == BANNER_KEY
    assert body["data"]["href"] == f"https://app.tellescope.example/canvas/{patient.id}"
    assert body["data"]["intent"] == "info"
    assert body["data"]["placement"] == ["chart", "profile"]


@pytest.mark.django_db
def test_external_id_template_uses_matching_identifier_encoded() -> None:
    patient = PatientFactory.create()
    add_identifier(patient, "other-system-value", system="https://other.example")
    add_identifier(patient, "ts 123/x")

    effects = run(
        identifier_event(patient.id, EventType.PATIENT_EXTERNAL_IDENTIFIER_CREATED),
        {
            "TELLESCOPE_PROFILE_URL_TEMPLATE": EXTERNAL_TEMPLATE,
            "TELLESCOPE_IDENTIFIER_SYSTEM": SYSTEM,
        },
    )

    assert effects[0].type == EffectType.ADD_BANNER_ALERT
    assert payload(effects[0])["data"]["href"] == (
        "https://app.tellescope.example/endusers/ts%20123%2Fx"
    )


@pytest.mark.django_db
def test_missing_template_removes_banner() -> None:
    patient = PatientFactory.create()

    effects = run(patient_event(patient.id), {})

    assert len(effects) == 1
    assert effects[0].type == EffectType.REMOVE_BANNER_ALERT
    assert payload(effects[0]) == {
        "patient": patient.id,
        "patient_filter": None,
        "key": BANNER_KEY,
    }


@pytest.mark.django_db
def test_invalid_template_removes_banner() -> None:
    patient = PatientFactory.create()

    effects = run(
        patient_event(patient.id),
        {"TELLESCOPE_PROFILE_URL_TEMPLATE": "http://insecure.example/{patient_id}"},
    )

    assert [e.type for e in effects] == [EffectType.REMOVE_BANNER_ALERT]


@pytest.mark.django_db
def test_external_id_template_without_system_setting_removes_banner() -> None:
    patient = PatientFactory.create()
    add_identifier(patient, "ts-123")

    effects = run(
        patient_event(patient.id),
        {"TELLESCOPE_PROFILE_URL_TEMPLATE": EXTERNAL_TEMPLATE},
    )

    assert [e.type for e in effects] == [EffectType.REMOVE_BANNER_ALERT]


@pytest.mark.django_db
def test_patient_without_identifier_gets_no_banner() -> None:
    patient = PatientFactory.create()
    add_identifier(patient, "   ")

    effects = run(
        patient_event(patient.id, EventType.PATIENT_CREATED),
        {
            "TELLESCOPE_PROFILE_URL_TEMPLATE": EXTERNAL_TEMPLATE,
            "TELLESCOPE_IDENTIFIER_SYSTEM": SYSTEM,
        },
    )

    assert [e.type for e in effects] == [EffectType.REMOVE_BANNER_ALERT]


@pytest.mark.django_db
def test_newer_blank_identifier_does_not_hide_an_older_real_one() -> None:
    patient = PatientFactory.create()
    add_identifier(patient, "ts-123")
    add_identifier(patient, "   ")

    effects = run(
        patient_event(patient.id),
        {
            "TELLESCOPE_PROFILE_URL_TEMPLATE": EXTERNAL_TEMPLATE,
            "TELLESCOPE_IDENTIFIER_SYSTEM": SYSTEM,
        },
    )

    assert effects[0].type == EffectType.ADD_BANNER_ALERT
    assert payload(effects[0])["data"]["href"].endswith("/endusers/ts-123")


@pytest.mark.django_db
def test_deleted_identifier_removes_banner() -> None:
    patient = PatientFactory.create()

    effects = run(
        identifier_event(patient.id, EventType.PATIENT_EXTERNAL_IDENTIFIER_DELETED),
        {
            "TELLESCOPE_PROFILE_URL_TEMPLATE": EXTERNAL_TEMPLATE,
            "TELLESCOPE_IDENTIFIER_SYSTEM": SYSTEM,
        },
    )

    assert [e.type for e in effects] == [EffectType.REMOVE_BANNER_ALERT]
    assert payload(effects[0])["patient"] == patient.id


def test_event_without_patient_does_nothing() -> None:
    event = SimpleNamespace(
        type=EventType.PATIENT_EXTERNAL_IDENTIFIER_UPDATED,
        target=SimpleNamespace(id="identifier-1"),
        context={},
    )

    assert run(event, {"TELLESCOPE_PROFILE_URL_TEMPLATE": PATIENT_TEMPLATE}) == []
