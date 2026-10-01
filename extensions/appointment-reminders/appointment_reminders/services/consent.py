"""Mirror a Twilio opt-out/opt-in keyword onto the patient's phone contact point.

Twilio blocks (or unblocks) the number on its own side and then forwards the
keyword to our webhook, but that decision never reaches Canvas by itself. While
Canvas's native incoming-SMS handler owned the number it did this write; the
moment the number's webhook is repointed at this plugin (which two-way confirm
requires) nothing does, so ``_get_patient_contacts`` keeps seeing consent and
every later send fails with Twilio 21610.

Only ``has_consent`` is writable. The ``Patient`` effect's contact-point
dataclass carries ``system``/``value``/``use``/``rank``/``has_consent`` and no
``opted_out``, so a plugin cannot set the field the chart UI labels "opted
out". ``has_consent`` is the better lever regardless: it gates SMS alone, and
STOP is an SMS carrier keyword, where ``opted_out`` would also silence email.
"""
from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient as PatientEffect
from canvas_sdk.effects.patient import PatientContactPoint as ContactPointPayload
from canvas_sdk.v1.data.common import (
    ContactPointState,
    ContactPointSystem,
    ContactPointUse,
)
from logger import log

from appointment_reminders.services.delivery import _normalize_phone


def _coerce(enum_cls: Any, raw: Any, fallback: Any) -> Any:
    """Coerce a stored contact-point string to its enum, falling back if unknown.

    The read model stores ``system``/``use`` as CharFields over the same choices
    the effect's enums define, so this is normally an exact round-trip. A blank
    or unrecognized value still has to produce *something*, because the effect
    serializes via ``.value`` and dropping the row is the more destructive
    option (see the replace-semantics note in ``sms_consent_effect``).
    """
    try:
        return enum_cls(raw)
    except ValueError:
        log.warning(
            f"[consent] Unrecognized {enum_cls.__name__} '{raw}'; "
            f"sending as {fallback.value}"
        )
        return fallback


def sms_consent_effect(
    patient: Any, phone_e164: str, *, has_consent: bool
) -> Effect | None:
    """Return a ``Patient`` effect setting SMS consent on ``phone_e164``, or None.

    None means there is nothing to write: the patient has no phone row matching
    the number that texted in, or every match already holds the requested value.
    That keeps a redundant keyword ("STOP" twice) from generating a pointless
    patient write.

    The effect carries **every** live contact point, not just the phone being
    changed. Canvas documents ``addresses`` updates as replace-based and says
    nothing either way about ``contact_points``, and the payload has no row ids
    to match on, so the full set is the only shape that behaves correctly under
    either reading — a partial list under replace semantics would delete the
    patient's other numbers and their email address.
    """
    live = [
        contact
        for contact in patient.telecom.all()
        # Exclude only what is explicitly deleted rather than keeping only what
        # is explicitly active, so a row with an unset state survives the
        # round-trip instead of being dropped.
        if contact.state != ContactPointState.DELETED
    ]

    def is_target(contact: Any) -> bool:
        return (
            contact.system == ContactPointSystem.PHONE
            and _normalize_phone(contact.value) == phone_e164
        )

    targets = [contact for contact in live if is_target(contact)]
    if not targets:
        log.info("[consent] Inbound number matches no phone on the chart; no write")
        return None
    if all(bool(contact.has_consent) is has_consent for contact in targets):
        return None

    payload = [
        ContactPointPayload(
            system=_coerce(ContactPointSystem, contact.system, ContactPointSystem.OTHER),
            value=contact.value,
            use=_coerce(ContactPointUse, contact.use, ContactPointUse.OTHER),
            rank=contact.rank or 0,
            has_consent=has_consent if is_target(contact) else bool(contact.has_consent),
        )
        for contact in live
    ]

    return PatientEffect(
        patient_id=str(patient.id), contact_points=payload
    ).update()
