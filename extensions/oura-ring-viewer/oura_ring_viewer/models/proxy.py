"""Plugin-side proxy for the Canvas patient table, used as a foreign key target."""

from canvas_sdk.v1.data import ModelExtension, Patient


class PatientProxy(Patient, ModelExtension):
    """Lets custom data rows reference a real patient record."""
