"""
Shared utility functions for the BP CPT2 extension.
"""

from typing import Optional

from canvas_sdk.v1.data import Note, Patient, Observation
from logger import log


def get_blood_pressure_readings(
    *,
    patient: Optional[Patient] = None,
    note: Optional[Note] = None
) -> tuple[Optional[float], Optional[float]]:
    """
    Retrieve the most recent systolic and diastolic BP readings.

    Must provide either patient or note (or both). If both are provided, note takes precedence.

    Args:
        patient: Patient object to filter by (gets most recent BP for patient)
        note: Note object to filter by (gets BP readings from this specific note)

    Returns:
        Tuple of (systolic, diastolic) as floats, or (None, None) if not found

    Raises:
        ValueError: If neither patient nor note is provided

    Examples:
        >>> get_blood_pressure_readings(patient=my_patient)
        (120.0, 80.0)
        >>> get_blood_pressure_readings(note=my_note)
        (140.0, 90.0)
    """
    if note is None and patient is None:
        raise ValueError("Either patient or note must be provided")

    # Build filters based on what was provided
    filters = {
        "deleted": False,
        "entered_in_error_id__isnull": True,
        "committer_id__isnull": False
    }

    if note is not None:
        filters["note_id"] = note.dbid
    elif patient is not None:
        filters["patient"] = patient

    # Get the blood_pressure observation
    bp_observation = Observation.objects.filter(
        **filters,
        category='vital-signs',
        name='blood_pressure'
    ).exclude(value='').order_by('created').last()

    systolic_value = None
    diastolic_value = None

    if bp_observation and bp_observation.value:
        # Try parsing the value format "120/60"
        try:
            parts = bp_observation.value.split('/')
            if len(parts) == 2:
                systolic_value = float(parts[0].strip())
                diastolic_value = float(parts[1].strip())
                log.info(f"Parsed BP from value '{bp_observation.value}': {systolic_value}/{diastolic_value}")
        except (ValueError, AttributeError) as e:
            log.error(f"Failed to parse BP value '{bp_observation.value}': {e}")

    # If parsing failed, try checking components
    if systolic_value is None or diastolic_value is None:
        if bp_observation and hasattr(bp_observation, 'components'):
            try:
                # components might be a RelatedManager, so call .all() to get queryset
                components_list = bp_observation.components.all() if hasattr(bp_observation.components, 'all') else []
                log.info(f"Checking components: {components_list}")
                for component in components_list:  # pragma: no cover
                    # Fallback parsing for alternative component-based BP format
                    if 'systolic' in component.get('code', {}).get('text', '').lower():
                        systolic_value = float(component.get('value', {}).get('quantity', {}).get('value', 0))
                    elif 'diastolic' in component.get('code', {}).get('text', '').lower():
                        diastolic_value = float(component.get('value', {}).get('quantity', {}).get('value', 0))
            except (AttributeError, TypeError) as e:  # pragma: no cover
                log.info(f"Unable to parse components: {e}")

    # Log the result
    if patient:
        log.info(f"Patient {patient.id} BP readings - Systolic: {systolic_value}, Diastolic: {diastolic_value}")
    elif note:
        log.info(f"Note {note.id} BP readings - Systolic: {systolic_value}, Diastolic: {diastolic_value}")

    return systolic_value, diastolic_value
