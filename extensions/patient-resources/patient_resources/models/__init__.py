"""Plugin-owned tables and the proxies their foreign keys point at.

Re-exported here so the schema generator finds every model from one import.
"""

from patient_resources.models.proxies import PatientProxy, StaffProxy
from patient_resources.models.resource import PatientResource
from patient_resources.models.share import PatientResourceShare

__all__ = [
    "PatientProxy",
    "PatientResource",
    "PatientResourceShare",
    "StaffProxy",
]
