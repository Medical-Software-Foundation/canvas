"""Medication Reconciliation module (CMS Element 4)."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.medication_statement import MedicationStatement
from logger import log

from guided_awv.modules.base import AWVType, BaseModule


class MedicationReconciliationModule(BaseModule):
    """
    Medication Reconciliation section.

    Displays current medications from the chart and captures structured
    reconciliation data: method, OTC/supplements, adherence, high-risk
    medication review, and provider attestation.
    """

    ORDER = 2
    TITLE = "Medication Reconciliation"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-pills"

    RECONCILIATION_METHODS = [
        "Patient-reported",
        "Pill bottle review",
        "EHR review",
        "Pharmacy records",
        "Caregiver-reported",
    ]

    ADHERENCE_OPTIONS = [
        "Taking all medications as prescribed",
        "Sometimes misses doses",
        "Frequently misses doses",
        "Not taking medications",
        "Unable to assess",
    ]

    ATTESTATION_OPTIONS = [
        "All medications reviewed with patient",
        "Discrepancies identified and resolved",
        "Patient verbalized understanding of medications",
        "Medication list updated in chart",
    ]

    def render_content_html(self) -> str:
        """Render medication reconciliation form with ORM medication list."""
        ctx = self.get_context()
        html = ""

        # Current medications from chart (read-only)
        html += self._subtitle(f"Current Medications ({ctx['medication_count']})")
        if ctx["current_medications"]:
            for m in ctx["current_medications"]:
                display = m.get("medication__codings__display") or "Unknown"
                sig = m.get("sig_original_input") or ""
                html += self._info_row(display, sig)
        else:
            html += '<p style="color:#999;font-size:12px;">No current medications on record</p>'

        html += self._divider()

        # Reconciliation method
        html += self._subtitle("Reconciliation Details")
        html += self._select(
            "reconciliation_method",
            "How was the medication list reviewed?",
            self.RECONCILIATION_METHODS,
            required=True,
        )

        # OTC medications
        html += self._textarea(
            "otc_medications",
            "Over-the-counter (OTC) medications",
            placeholder="List any OTC medications the patient is taking (e.g., aspirin, ibuprofen, antacids).",
        )

        # Supplements
        html += self._textarea(
            "supplements",
            "Vitamins, herbs, and supplements",
            placeholder="List any supplements (e.g., vitamin D, fish oil, calcium, herbal remedies).",
        )

        # Adherence assessment
        html += self._radio_group(
            "adherence_assessment",
            "Medication adherence assessment",
            self.ADHERENCE_OPTIONS,
        )

        html += self._divider()

        # High-risk medications
        html += self._subtitle("High-Risk Medication Review")
        html += self._alert(
            "Review for potentially inappropriate medications in older adults "
            "(e.g., anticholinergics, benzodiazepines, NSAIDs, opioids). "
            "Consider Beers Criteria for deprescribing opportunities.",
            "info",
        )
        html += self._radio_group(
            "high_risk_meds_identified",
            "Were high-risk medications identified?",
            ["Yes", "No", "N/A"],
        )

        # Conditional: high-risk medication notes
        html += (
            '<div class="awv-conditional" '
            'data-conditional-on="high_risk_meds_identified" '
            'data-conditional-value="Yes" '
            'style="display:none;">'
        )
        html += self._textarea(
            "high_risk_meds_notes",
            "High-risk medication details and plan",
            placeholder="Describe identified high-risk medications and planned interventions (e.g., taper, switch, discontinue).",
        )
        html += "</div>"

        html += self._divider()

        # Attestation
        html += self._subtitle("Reconciliation Attestation")
        html += self._checkbox_group(
            "reconciliation_attestation",
            "Attestation (check all that apply)",
            self.ATTESTATION_OPTIONS,
        )

        # Reconciliation confirmation
        html += self._radio_group(
            "medications_reconciled",
            "Medications reconciled?",
            ["Yes", "No"],
            required=True,
        )

        # Notes
        html += self._textarea(
            "reconciliation_notes",
            "Additional reconciliation notes",
            placeholder="Document any medication changes, concerns, or follow-up actions.",
        )

        return f'<div class="awv-module-content">{html}{self._save_button("saveMedicationReconciliation", "Save Reconciliation")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return medication reconciliation context with current medications."""
        try:
            # REVIEW.md "Always check": exclude entered-in-error meds so the
            # reconciliation list doesn't ask the provider to attest to records
            # already flagged as mistaken.
            current_medications = self._dedup_by_id(
                list(
                    MedicationStatement.objects.filter(
                        patient__id=self.patient_id,
                        deleted=False,
                        entered_in_error_id__isnull=True,
                    )
                    .select_related("medication")
                    .values("id", "medication__codings__display", "sig_original_input")
                    .order_by("medication__codings__display")
                )
            )
        except Exception as exc:
            log.warning(f"MedicationReconciliationModule: failed to load medications: {exc}")
            current_medications = []

        return {
            "current_medications": current_medications,
            "medication_count": len(current_medications),
            "note_id": self.note_id,
        }
