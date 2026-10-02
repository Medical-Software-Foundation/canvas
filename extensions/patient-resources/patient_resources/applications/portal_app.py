"""The patient-portal menu entry: "My Resources"."""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log

from patient_resources.constants import PORTAL_URL
from patient_resources.services.shares import unviewed_count


class MyResourcesPortalApp(Application):
    """The page where a patient reads what their care team shared with them."""

    def on_open(self) -> Effect | list[Effect]:
        """Open the patient's resource list.

        The patient id decides only whether to launch. It is deliberately not put
        in the URL: the page resolves the patient from the session header on every
        request, so there is nothing in the document for anyone to tamper with.
        """
        patient_id = self._patient_id()
        if not patient_id:
            # Logged without the event context. portal-content logs the whole
            # context here, which puts patient data in the logs; the app
            # identifier is enough to find this in practice.
            log.warning(
                "Cannot open My Resources: no patient in the portal event context"
            )
            return []

        return LaunchModalEffect(
            url=PORTAL_URL,
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()

    def compute_notification_badge(self) -> int | None:
        """How many shared resources this patient has not seen yet.

        This is the whole of "the patient is told". The locked scope is portal
        only with no send tracking, and it does not ask for a message -- so
        rather than inventing a channel and wording on the practice's behalf, the
        menu entry carries a count. ``None`` means emit no badge; ``0`` clears one.
        """
        patient_id = self._patient_id()
        if not patient_id:
            return None

        from canvas_sdk.v1.data import Patient

        patient = Patient.objects.filter(id=patient_id).only("id", "dbid").first()
        if patient is None:
            return None
        return unviewed_count(patient.dbid)

    def _patient_id(self) -> str:
        """The signed-in patient, from the portal event context.

        A portal event carries the patient under ``user``; the ``patient`` key is
        the fallback other portal plugins in this repo also check.
        """
        context: dict[str, Any] = getattr(self.event, "context", None) or {}
        user = context.get("user") or {}
        patient = context.get("patient") or {}
        return str(user.get("id") or patient.get("id") or "")
