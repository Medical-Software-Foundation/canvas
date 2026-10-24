"""Proxies so a custom model can hold a foreign key to a platform model.

A CustomModel cannot point at a platform model directly. The pattern is a proxy
subclass mixing in ModelExtension, and a foreign key to the proxy declared with
to_field="dbid".
"""

from canvas_sdk.v1.data import Patient, Staff
from canvas_sdk.v1.data.base import ModelExtension


class PatientProxy(Patient, ModelExtension):
    """Patient, reachable as the target of a custom model foreign key."""

    @property
    def display_name(self) -> str:
        """The patient's name as a person reads it."""
        return f"{self.first_name} {self.last_name}"


class StaffProxy(Staff, ModelExtension):
    """Staff, reachable as the target of a custom model foreign key."""

    @property
    def display_name(self) -> str:
        """The staff member's name as a person reads it."""
        return f"{self.first_name} {self.last_name}"
