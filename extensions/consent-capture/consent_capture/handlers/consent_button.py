"""'Consents' action button in the patient chart header.

With multiple configured consents the button is a hub: it opens a picker listing
every active consent with its on-file status, and the provider fills them out one
at a time. The same picker is also reachable any time from the app-drawer
``ConsentApp``.

The button is **always shown** for a patient in context — it is a persistent,
discoverable entry point — and its *color* signals status rather than its
presence. It goes RED only for an eligible (active, non-deceased) patient with a
required consent still due (never recorded, or expired); otherwise it is a neutral
gray chip. The label is always "Consents". Deceased/inactive patients therefore
always see the gray button and never the red one, matching the banner, which stays
gated to eligible patients.

Color is recomputed each time the header is evaluated. After a consent is recorded,
``ConsentApi.collect`` emits ``ReloadPatientActionButtonsEffect`` so the color
updates live (red -> gray) without a page reload.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton

from consent_capture.constants import (
    BUTTON_DUE_BACKGROUND,
    BUTTON_DUE_TEXT,
    BUTTON_KEY,
    BUTTON_SATISFIED_BACKGROUND,
    BUTTON_SATISFIED_TEXT,
    BUTTON_TITLE,
)
from consent_capture.picker_modal import build_picker_modal
from consent_capture.service import is_eligible_patient, picker_items


def needs_any(items):
    """Whether at least one *required* active consent is still not on file
    (never recorded, or expired). Optional consents do not surface the button —
    it mirrors the hub's "Required" (due) section, so the red button means
    "a required consent is missing" rather than "some optional consent is unfilled"."""
    return any(item.get("required") and not item.get("on_file") for item in items)


class ConsentButton(ActionButton):
    BUTTON_TITLE = BUTTON_TITLE
    BUTTON_KEY = BUTTON_KEY
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def _patient_id(self):
        target = getattr(self.event, "target", None)
        return getattr(target, "id", None)

    def visible(self) -> bool:
        """Always show the button for a patient in context, coloring it to signal
        status (the label is always "Consents"). It is RED (white text) only for an
        eligible (active, non-deceased) patient that still has a *required* consent
        not on file (needed or expired); otherwise it is a neutral gray chip
        (light-gray background, dark slate text). Ineligible patients short-circuit
        before the consent lookup, so they never go red — matching the banner, which
        only surfaces when due.

        The ``ActionButton`` base reads ``BUTTON_BACKGROUND_COLOR`` /
        ``BUTTON_TEXT_COLOR`` off the instance right after this returns, so setting
        them here applies the chosen colors for this render."""
        patient_id = self._patient_id()
        if not patient_id:
            return False  # no patient in context -> no patient-header button
        due = is_eligible_patient(patient_id) and needs_any(picker_items(patient_id))
        if due:
            self.BUTTON_BACKGROUND_COLOR = BUTTON_DUE_BACKGROUND
            self.BUTTON_TEXT_COLOR = BUTTON_DUE_TEXT
        else:
            self.BUTTON_BACKGROUND_COLOR = BUTTON_SATISFIED_BACKGROUND
            self.BUTTON_TEXT_COLOR = BUTTON_SATISFIED_TEXT
        return True

    def handle(self) -> list[Effect]:
        patient_id = self._patient_id()
        staff_id = self.event.context.get("user", {}).get("id", "")
        secrets = getattr(self, "secrets", None) or {}
        return [build_picker_modal(patient_id, staff_id, secrets).apply()]
