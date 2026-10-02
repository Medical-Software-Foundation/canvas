from datetime import datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.patient import Patient
from logger import log

# Cap the number of records rendered so the modal stays responsive for
# patients with very long medication lists.
HISTORY_LIMIT = 250

# Coding systems whose `display` carries a human-readable drug name. FDB is
# Canvas's primary drug descriptor; RxNorm is the standard fallback.
FDB_SYSTEM = "http://www.fdbhealth.com/"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def _format_date(value: datetime | None) -> str:
    """Render a datetime as e.g. "Jan 05, 2026", or "" when absent."""
    return value.strftime("%b %d, %Y") if value else ""


def _is_readable(display: str) -> bool:
    """A coding display is usable as a drug name when it's present and not a
    placeholder like "UNKNOWN system=... code=...".
    """
    return bool(display) and not display.startswith("UNKNOWN")


def _medication_name(med: Medication) -> str:
    """Pick the best human-readable name from a medication's codings.

    Prefers FDB, then RxNorm, then any readable display, falling back to a
    clear placeholder when no coding carries a usable name.
    """
    codings = list(med.codings.all())

    for system in (FDB_SYSTEM, RXNORM_SYSTEM):
        for coding in codings:
            if system in str(coding.system) and _is_readable(coding.display):
                return str(coding.display)

    for coding in codings:
        if _is_readable(coding.display):
            return str(coding.display)

    return "Unknown medication"


def _build_medication(med: Medication) -> dict[str, object]:
    """Flatten a Medication into display-ready values (never None).

    `is_active` drives both the count tallies and the Active/Inactive filter:
    only the canonical "active" status counts as active, and every other value
    (e.g. "inactive", "stopped", or an empty/unknown status) buckets as
    inactive — so no record is ever orphaned from both filters. `status_label`
    preserves the real status text for the badge.
    """
    is_active = (med.status or "").strip().lower() == "active"
    return {
        "name": _medication_name(med),
        "is_active": is_active,
        "status_label": med.status.title() if med.status else "",
        "start_date": _format_date(med.start_date),
        "end_date": _format_date(med.end_date),
        "quantity": med.clinical_quantity_description or "",
        "national_drug_code": med.national_drug_code or "",
    }


class MedicationHistoryButton(ActionButton):
    """Adds a "Med Hx" button to the chart's Medications summary section.

    When clicked, it reads the patient's committed medications (active and
    historical) and renders them directly in a chart-pane modal.
    """

    BUTTON_TITLE = "Med Hx"
    BUTTON_KEY = "medication_history"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_MEDICATIONS_SECTION

    def visible(self) -> bool:
        return True

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            log.warning(
                "MedicationHistoryButton: no patient found for id %s", patient_id
            )
            return []

        # Show every medication on record (active and historical), excluding
        # only retracted (entered-in-error) and deleted records. Status
        # ordering surfaces active medications before inactive ones.
        meds = (
            Medication.objects.filter(
                patient=patient,
                deleted=False,
                entered_in_error__isnull=True,
            )
            .prefetch_related("codings")
            .order_by("status", "-start_date")[:HISTORY_LIMIT]
        )

        medications = [_build_medication(med) for med in meds]
        active_count = sum(1 for m in medications if m["is_active"])

        html = render_to_string(
            "templates/medication_history.html",
            {
                "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                "medications": medications,
                "active_count": active_count,
                "inactive_count": len(medications) - active_count,
            },
        )

        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Medication History",
            ).apply()
        ]
