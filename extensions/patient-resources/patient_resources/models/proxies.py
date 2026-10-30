"""Proxies onto core Canvas models.

Plugin-owned tables cannot foreign-key straight at an SDK model; they key at a
proxy that subclasses it alongside ``ModelExtension``. Every foreign key in this
plugin points at one of these.
"""

from canvas_sdk.v1.data import Patient, Staff
from canvas_sdk.v1.data.base import ModelExtension


class PatientProxy(Patient, ModelExtension):
    """The patient a resource was shared with."""


class StaffProxy(Staff, ModelExtension):
    """A staff member: whoever curated a resource, or shared one with a patient."""
