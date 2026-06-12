"""Medical History module."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.medication_statement import MedicationStatement
from canvas_sdk.v1.data.condition import Condition, ClinicalStatus
from logger import log

from guided_awv.modules.base import AWVType, BaseModule


class MedicalHistoryModule(BaseModule):
    """
    Medical History section.

    Initial AWV: Complete capture of past medical history, surgical history,
    current medications, and allergies.

    Subsequent AWV: Review and update mode - shows existing data with ability
    to add/edit.
    """

    ORDER = 3
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-file-medical"

    @property
    def TITLE(self) -> str:  # type: ignore[override]
        """Return title based on AWV type."""
        if self.awv_type == AWVType.INITIAL:
            return "Medical History (Complete Capture)"
        return "Medical History (Review & Update)"

    def render_content_html(self) -> str:
        """Render medical history from ORM data."""
        ctx = self.get_context()
        html = ""
        html += self._subtitle(f"Active Conditions ({ctx['medical_count']})")
        if ctx["medical_conditions"]:
            for c in ctx["medical_conditions"]:
                display = c.get("codings__display") or "Unknown"
                onset = c.get("onset_date") or ""
                html += self._info_row(display, f"Onset: {onset}" if onset else "")
        else:
            html += '<p style="color:#999;font-size:12px;">No active conditions on record</p>'
        html += self._divider()
        html += self._subtitle(f"Surgical History ({ctx['surgical_count']})")
        if ctx["surgical_conditions"]:
            for c in ctx["surgical_conditions"]:
                display = c.get("codings__display") or "Unknown"
                date = c.get("resolution_date") or c.get("onset_date") or ""
                status = c.get("clinical_status") or ""
                detail = f"Date: {date}" if date else ""
                if status and status != "resolved":
                    detail += f" ({status})" if detail else f"({status})"
                html += self._info_row(display, detail)
        else:
            html += '<p style="color:#999;font-size:12px;">No surgical history on record</p>'
        # New diagnosis search
        html += self._divider()
        html += self._subtitle("Add New Diagnosis")
        html += (
            '<div style="position:relative;margin-bottom:8px;">'
            '<input type="text" id="new-dx-search" placeholder="Search conditions (e.g. diabetes, hypertension)..." '
            'autocomplete="off" '
            'style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;font-size:13px;box-sizing:border-box;">'
            '<div id="new-dx-results" style="display:none;position:absolute;z-index:100;width:100%;'
            'max-height:200px;overflow-y:auto;background:#fff;border:1px solid #ddd;border-top:none;'
            'border-radius:0 0 4px 4px;box-shadow:0 2px 4px rgba(0,0,0,0.1);"></div>'
            '</div>'
            '<div id="added-diagnoses"></div>'
        )
        html += self._divider()
        html += self._subtitle(f"Current Medications ({ctx['medication_count']})")
        if ctx["current_medications"]:
            for m in ctx["current_medications"]:
                display = m.get("medication__codings__display") or "Unknown"
                sig = m.get("sig_original_input") or ""
                html += self._info_row(display, sig)
        else:
            html += '<p style="color:#999;font-size:12px;">No current medications on record</p>'
        html += self._divider()
        html += self._subtitle(f"Allergies ({ctx['allergy_count']})")
        if ctx["allergies"]:
            for a in ctx["allergies"]:
                display = a.get("codings__display") or "Unknown"
                narrative = a.get("narrative") or ""
                html += self._info_row(display, narrative)
        else:
            html += '<p style="color:#999;font-size:12px;">No allergies on record</p>'
        html += self._divider()
        html += self._subtitle("Review Attestation")
        html += self._checkbox_group(
            "medical_history_attestation",
            "Attestation (check all that apply)",
            [
                "Medical history reviewed and updated for this visit",
                "Surgical history reviewed and updated",
                "Medication list reviewed (see Medication Reconciliation)",
                "Allergy list reviewed and updated",
            ],
            required=True,
        )
        return f'<div class="awv-module-content">{html}{self._save_button("saveMedicalHistory", "Save Medical History")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return medical history context data."""
        # REVIEW.md "Always check": filter entered_in_error_id__isnull=True
        # on every clinical read so records a clinician later flagged as
        # mistaken don't surface in the AWV review UI, narratives, or counts.
        medical_conditions = [
            c for c in self._dedup_by_id(list(
                Condition.objects.filter(
                    patient__id=self.patient_id,
                    clinical_status=ClinicalStatus.ACTIVE,
                    surgical=False,
                    deleted=False,
                    entered_in_error_id__isnull=True,
                )
                .select_related()
                .values("id", "codings__display", "onset_date")
                .order_by("codings__display")
            ))
            if c.get("codings__display")
        ]

        surgical_conditions = [
            c for c in self._dedup_by_id(list(
                Condition.objects.filter(
                    patient__id=self.patient_id,
                    surgical=True,
                    deleted=False,
                    entered_in_error_id__isnull=True,
                )
                .select_related()
                .values("id", "codings__display", "onset_date", "resolution_date", "clinical_status")
                .order_by("codings__display")
            ))
            if c.get("codings__display")
        ]

        try:
            current_medications = self._dedup_by_id(list(
                MedicationStatement.objects.filter(
                    patient__id=self.patient_id,
                    deleted=False,
                    entered_in_error_id__isnull=True,
                )
                .select_related("medication")
                .values("id", "medication__codings__display", "sig_original_input")
                .order_by("medication__codings__display")
            ))
        except Exception as exc:
            log.warning(f"MedicalHistoryModule: failed to load medications: {exc}")
            current_medications = []

        allergies = self._dedup_by_id(list(
            AllergyIntolerance.objects.filter(
                patient__id=self.patient_id,
                deleted=False,
                entered_in_error_id__isnull=True,
            )
            .values("id", "codings__display", "narrative")
            .order_by("codings__display")
        ))

        return {
            "is_initial": self.awv_type == AWVType.INITIAL,
            "medical_conditions": medical_conditions,
            "surgical_conditions": surgical_conditions,
            "current_medications": current_medications,
            "allergies": allergies,
            "medical_count": len(medical_conditions),
            "surgical_count": len(surgical_conditions),
            "medication_count": len(current_medications),
            "allergy_count": len(allergies),
        }
