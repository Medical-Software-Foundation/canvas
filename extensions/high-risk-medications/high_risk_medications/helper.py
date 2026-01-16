"""
Helper functions for high-risk medications.
"""

from canvas_sdk.v1.data.medication import Medication

HIGH_RISK_PATTERNS = ["warfarin", "insulin", "digoxin", "methotrexate"]

def get_high_risk_meds(patient_id: str) -> list[dict]:
    """Get high-risk medications for a patient."""
    medications = Medication.objects.filter(
        patient__id=patient_id,
        status="active"
    )

    high_risk_meds = []
    for med in medications:
        coding = med.codings.first()
        med_name = coding.display or ""
        if any(pattern in med_name.lower() for pattern in HIGH_RISK_PATTERNS):
            high_risk_meds.append({
                "name": med_name,
                "id": med.id
            })

    return high_risk_meds