"""Proxies onto core Canvas models.

Plugin-owned tables cannot foreign-key straight at an SDK model; they key at a
proxy that subclasses it alongside ``ModelExtension``. Every waitlist foreign
key points at one of these.
"""

from canvas_sdk.v1.data import Appointment, NoteType, Patient, PracticeLocation, Staff
from canvas_sdk.v1.data.base import ModelExtension


class PatientProxy(Patient, ModelExtension):
    """The patient waiting to be scheduled."""


class StaffProxy(Staff, ModelExtension):
    """A staff member: the requested provider, or whoever created or changed an entry."""


class NoteTypeProxy(NoteType, ModelExtension):
    """The requested appointment type. Canvas calls this a note type."""


class PracticeLocationProxy(PracticeLocation, ModelExtension):
    """The requested location."""


class AppointmentProxy(Appointment, ModelExtension):
    """The appointment that satisfied an entry, or the slot that freed up."""
