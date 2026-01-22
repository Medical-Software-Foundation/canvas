"""
Helper functions for high-risk medications.
"""

import json
from canvas_sdk.v1.data.medication import Medication


def parse_patterns(patterns_input: str) -> list[str]:
    """Parse patterns from a JSON array or comma-separated string."""
    try:
        return json.loads(patterns_input)
    except (json.JSONDecodeError, TypeError):
        if patterns_input:
            return [pattern.strip().lower() for pattern in patterns_input.split(",") if pattern.strip()]

    raise ValueError(f"Invalid patterns input: {patterns_input}")


def get_high_risk_meds(patient_id: str, patterns_input: str) -> list[dict]:
    """Get high-risk medications for a patient.

    Args:
        patient_id: The patient's ID
        patterns_input: JSON array or comma-separated string of patterns.
    """
    patterns = parse_patterns(patterns_input)

    medications = Medication.objects.filter(
        patient__id=patient_id,
        status="active"
    )

    high_risk_meds = []
    for med in medications:
        coding = med.codings.first()
        med_name = coding.display or ""
        if any(pattern in med_name.lower() for pattern in patterns):
            high_risk_meds.append({
                "name": med_name,
                "id": med.id
            })

    return high_risk_meds