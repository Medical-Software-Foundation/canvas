"""Plugin-owned tables.

Re-exported here so the schema generator finds every model from one import.
"""

from scheduling_waitlist.models.proxies import (
    AppointmentProxy,
    NoteTypeProxy,
    PatientProxy,
    PracticeLocationProxy,
    StaffProxy,
)
from scheduling_waitlist.models.slot_notification import SlotNotification
from scheduling_waitlist.models.waitlist_entry import WaitlistEntry

__all__ = [
    "AppointmentProxy",
    "NoteTypeProxy",
    "PatientProxy",
    "PracticeLocationProxy",
    "SlotNotification",
    "StaffProxy",
    "WaitlistEntry",
]
