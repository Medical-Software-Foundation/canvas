"""
Shared utility functions for the BP CPT2 extension.
"""

from typing import Optional

from canvas_sdk.v1.data import Note, Observation
from logger import log


def get_blood_pressure_readings(note: Note) -> tuple[Optional[float], Optional[float]]:
    """
    Retrieve the minimum systolic and diastolic BP readings from up to 3 most recent observations for a specific note.

    This function retrieves up to 3 most recent blood pressure observations for the given note,
    parses each observation, and returns the minimum systolic and minimum diastolic values found
    across all observations.

    Args:
        note: Note object to get BP readings from (required)

    Returns:
        Tuple of (min_systolic, min_diastolic) as floats, or (None, None) if not found

    Examples:
        >>> get_blood_pressure_readings(my_note)
        (135.0, 85.0)  # Minimum values from up to 3 observations
    """
    # Build filters for the specific note
    filters = {
        "deleted": False,
        "entered_in_error_id__isnull": True,
        "committer_id__isnull": False,
        "note_id": note.dbid
    }

    # Get up to 3 most recent blood_pressure observations
    bp_observations = list(Observation.objects.filter(
        **filters,
        category='vital-signs',
        name='blood_pressure'
    ).exclude(value='').order_by('-created')[:3])

    log.info(f"Note {note.id} - Retrieved {len(bp_observations)} BP observation(s)")

    # Collect all valid systolic and diastolic values
    systolic_values = []
    diastolic_values = []

    for i, bp_observation in enumerate(bp_observations, 1):
        systolic = None
        diastolic = None

        if bp_observation and bp_observation.value:
            # Try parsing the value format "120/60"
            try:
                parts = bp_observation.value.split('/')
                if len(parts) == 2:
                    systolic = float(parts[0].strip())
                    diastolic = float(parts[1].strip())
                    log.info(f"Note {note.id} - Observation {i}: Parsed BP '{bp_observation.value}' -> {systolic}/{diastolic}")
            except (ValueError, AttributeError) as e:
                log.error(f"Note {note.id} - Observation {i}: Failed to parse BP value '{bp_observation.value}': {e}")

        # If parsing failed, try checking components
        if systolic is None or diastolic is None:
            if bp_observation and hasattr(bp_observation, 'components'):
                try:
                    # components might be a RelatedManager, so call .all() to get queryset
                    components_list = bp_observation.components.all() if hasattr(bp_observation.components, 'all') else []
                    log.info(f"Note {note.id} - Observation {i}: Checking components: {components_list}")
                    for component in components_list:  # pragma: no cover
                        # Fallback parsing for alternative component-based BP format
                        if 'systolic' in component.get('code', {}).get('text', '').lower():
                            systolic = float(component.get('value', {}).get('quantity', {}).get('value', 0))
                        elif 'diastolic' in component.get('code', {}).get('text', '').lower():
                            diastolic = float(component.get('value', {}).get('quantity', {}).get('value', 0))
                except (AttributeError, TypeError) as e:  # pragma: no cover
                    log.info(f"Note {note.id} - Observation {i}: Unable to parse components: {e}")

        # Add valid values to our lists
        if systolic is not None:
            systolic_values.append(systolic)
        if diastolic is not None:
            diastolic_values.append(diastolic)

    # Calculate minimum values
    systolic_value = min(systolic_values) if systolic_values else None
    diastolic_value = min(diastolic_values) if diastolic_values else None

    # Log the final result
    log.info(f"Note {note.id} - Final BP readings (minimum of {len(bp_observations)} observation(s)) - Systolic: {systolic_value}, Diastolic: {diastolic_value}")

    return systolic_value, diastolic_value
