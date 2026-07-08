"""Red 'Collect Consent' action button in the patient chart header.

Visible only for patients who do not already have an accepted consent of the
configured coding. Clicking it opens a modal with the scripted consent statement.

Visibility is only evaluated on page load, so the button can linger after a
consent is collected until the next reload. To handle that stale state, ``handle``
re-checks for an accepted consent and shows an informational notice (rather than
collecting again) when one is already on file.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient, PatientConsent

from logger import log

from consent_capture.constants import (
    ACCEPTED_STATES,
    BUTTON_COLOR,
    BUTTON_KEY,
    BUTTON_TITLE,
    NO_STATEMENT_NOTE,
    parse_statement,
)


def should_prompt(patient_id, code, accepted_exists):
    """Decide whether the Collect Consent button should be shown.

    - No patient in context -> hide.
    - No consent code configured yet -> show (so it can be collected once set up).
    - Otherwise show only when there is no accepted consent already on file.
    """
    if not patient_id:
        return False
    if not code:
        return True
    return not accepted_exists


class ConsentButton(ActionButton):
    BUTTON_TITLE = BUTTON_TITLE
    BUTTON_KEY = BUTTON_KEY
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    BUTTON_BACKGROUND_COLOR = BUTTON_COLOR

    def _patient_id(self):
        target = getattr(self.event, "target", None)
        return getattr(target, "id", None)

    def _has_accepted_consent(self, patient_id) -> bool:
        """Whether the patient already has an accepted consent of the configured
        coding. Returns False when no consent code is configured yet (there is
        nothing to check against)."""
        code = self.secrets.get("CONSENT_CODE", "")
        if not code:
            return False

        system = self.secrets.get("CONSENT_SYSTEM", "")
        filters = {
            "patient__id": patient_id,
            "category__code": code,
            "state__in": ACCEPTED_STATES,
        }
        if system:
            filters["category__system"] = system

        return PatientConsent.objects.filter(**filters).exists()

    def visible(self) -> bool:
        """Show the button only when there is no accepted consent on file."""
        patient_id = self._patient_id()
        if not patient_id:
            return False

        code = self.secrets.get("CONSENT_CODE", "")
        if not code:
            return should_prompt(patient_id, code, False)

        accepted_exists = self._has_accepted_consent(patient_id)
        return should_prompt(patient_id, code, accepted_exists)

    def handle(self) -> list[Effect]:
        patient_id = self._patient_id()

        # visible() is only evaluated on page load, so the button can linger in the
        # chart header after a consent was just recorded this session. If the
        # consent is now on file, show an informational notice instead of
        # collecting it again.
        if patient_id and self._has_accepted_consent(patient_id):
            log.info(
                "ConsentButton: consent already on file for patient %s; showing notice"
                % patient_id
            )
            html = render_to_string(
                "templates/consent_none.html",
                {"button_title": BUTTON_TITLE},
            )
            modal = LaunchModalEffect(
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                content=html,
            )
            return [modal.apply()]

        staff_id = self.event.context.get("user", {}).get("id", "")

        log.info(
            "ConsentButton: opened for patient %s by staff %s"
            % (patient_id, staff_id)
        )

        patient_name = ""
        patient_dob = ""
        row = (
            Patient.objects.filter(id=patient_id)
            .values_list("first_name", "last_name", "birth_date")
            .first()
        )
        if row:
            patient_name = ("%s %s" % (row[0] or "", row[1] or "")).strip()
            patient_dob = row[2].isoformat() if row[2] else ""

        paragraphs = parse_statement(self.secrets.get("CONSENT_STATEMENT", ""))

        html = render_to_string(
            "templates/consent.html",
            {
                "patient_id": patient_id,
                "patient_name": patient_name,
                "patient_dob": patient_dob,
                "consent_display": self.secrets.get("CONSENT_DISPLAY", ""),
                "paragraphs": paragraphs,
                "no_statement_note": NO_STATEMENT_NOTE,
            },
        )

        modal = LaunchModalEffect(
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            content=html,
        )
        return [modal.apply()]
