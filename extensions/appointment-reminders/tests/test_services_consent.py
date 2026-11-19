"""Tests for the SMS consent write-back built after a Twilio STOP/START.

The effect payload is asserted through ``Patient.values``, which is what
actually reaches Canvas, rather than through the dataclasses on the way in.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from appointment_reminders.services.consent import sms_consent_effect

_PHONE = "+14155551234"


@pytest.fixture(autouse=True)
def _patient_exists():
    """``Patient.update()`` validates the patient against the DB; there isn't one."""
    with patch("canvas_sdk.effects.patient.base.PatientModel") as mock_model:
        mock_model.objects.filter.return_value.exists.return_value = True
        yield


def _contact(
    system: str = "phone",
    value: str = _PHONE,
    *,
    use: str = "mobile",
    rank: int = 0,
    has_consent: bool = True,
    state: str = "active",
) -> MagicMock:
    contact = MagicMock()
    contact.system = system
    contact.value = value
    contact.use = use
    contact.rank = rank
    contact.has_consent = has_consent
    contact.state = state
    return contact


def _patient(contacts: list, pid: str = "pat-1") -> MagicMock:
    patient = MagicMock()
    patient.id = pid
    patient.telecom.all.return_value = contacts
    return patient


def _payload(effect) -> list[dict]:
    """The contact_points list as serialized onto the effect."""
    import json

    return json.loads(effect.payload)["data"]["contact_points"]


def test_opt_out_clears_consent_on_the_matching_phone() -> None:
    patient = _patient([_contact()])
    effect = sms_consent_effect(patient, _PHONE, has_consent=False)

    assert effect is not None
    rows = _payload(effect)
    assert len(rows) == 1
    assert rows[0]["value"] == _PHONE
    assert rows[0]["has_consent"] is False


def test_opt_in_restores_consent() -> None:
    patient = _patient([_contact(has_consent=False)])
    effect = sms_consent_effect(patient, _PHONE, has_consent=True)

    assert _payload(effect)[0]["has_consent"] is True


def test_matches_phone_stored_in_a_different_format() -> None:
    patient = _patient([_contact(value="(415) 555-1234")])
    effect = sms_consent_effect(patient, _PHONE, has_consent=False)

    assert effect is not None
    assert _payload(effect)[0]["has_consent"] is False


def test_other_contact_points_are_resent_unchanged() -> None:
    """Regression guard for replace-based update semantics.

    Canvas does not document whether a ``contact_points`` update merges or
    replaces. If it replaces, sending only the phone would delete the patient's
    email and their second number — so every live row has to go along, with its
    own consent value untouched.
    """
    patient = _patient(
        [
            _contact(),
            _contact(system="email", value="x@y.com", use="home", rank=1, has_consent=True),
            _contact(value="+19998887777", use="home", rank=2, has_consent=True),
        ]
    )
    effect = sms_consent_effect(patient, _PHONE, has_consent=False)
    rows = _payload(effect)

    assert len(rows) == 3
    by_value = {row["value"]: row for row in rows}
    assert by_value[_PHONE]["has_consent"] is False          # the one that texted STOP
    assert by_value["x@y.com"]["has_consent"] is True        # untouched
    assert by_value["+19998887777"]["has_consent"] is True   # untouched
    assert by_value["x@y.com"]["system"] == "email"
    assert by_value["x@y.com"]["use"] == "home"
    assert by_value["x@y.com"]["rank"] == 1


def test_deleted_contact_points_are_dropped() -> None:
    patient = _patient([_contact(), _contact(value="+19998887777", state="deleted")])
    rows = _payload(sms_consent_effect(patient, _PHONE, has_consent=False))

    assert [row["value"] for row in rows] == [_PHONE]


def test_returns_none_when_no_phone_matches() -> None:
    patient = _patient([_contact(value="+19998887777")])
    assert sms_consent_effect(patient, _PHONE, has_consent=False) is None


def test_returns_none_when_email_matches_nothing() -> None:
    """An email row is never a consent target, even with the same value."""
    patient = _patient([_contact(system="email", value=_PHONE)])
    assert sms_consent_effect(patient, _PHONE, has_consent=False) is None


def test_returns_none_when_already_in_the_requested_state() -> None:
    """A repeated STOP should not generate a redundant patient write."""
    patient = _patient([_contact(has_consent=False)])
    assert sms_consent_effect(patient, _PHONE, has_consent=False) is None


def test_writes_when_any_duplicate_row_still_disagrees() -> None:
    """Same number twice, one row still consenting: the write must happen."""
    patient = _patient(
        [_contact(has_consent=False), _contact(use="home", rank=1, has_consent=True)]
    )
    rows = _payload(sms_consent_effect(patient, _PHONE, has_consent=False))

    assert [row["has_consent"] for row in rows] == [False, False]


def test_unrecognized_use_falls_back_rather_than_dropping_the_row() -> None:
    """A blank ``use`` must not cost the patient a contact point."""
    patient = _patient([_contact(), _contact(system="email", value="x@y.com", use="")])
    rows = _payload(sms_consent_effect(patient, _PHONE, has_consent=False))

    assert len(rows) == 2
    assert {row["value"] for row in rows} == {_PHONE, "x@y.com"}
    assert next(r for r in rows if r["value"] == "x@y.com")["use"] == "other"


def test_effect_targets_the_right_patient() -> None:
    import json

    patient = _patient([_contact()], pid="pat-42")
    effect = sms_consent_effect(patient, _PHONE, has_consent=False)

    assert json.loads(effect.payload)["data"]["patient_id"] == "pat-42"
