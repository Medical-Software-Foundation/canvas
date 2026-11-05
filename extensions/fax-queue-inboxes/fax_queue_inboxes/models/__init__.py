"""The plugin's own custom data models, split across three files per Section 1 of SPEC.md.

practice_label.py, fax_record.py and proxies.py each hold one unit named in the
components table. This file re exports FaxLabel, FaxRecord and PracticeLabel so that
fax_queue_inboxes.models.FaxRecord and fax_queue_inboxes.models.PracticeLabel
keep resolving exactly as they did before the split, which is what
handlers/api.py and the test suite both import.
"""

from __future__ import annotations

from fax_queue_inboxes.models.fax_record import FaxRecord
from fax_queue_inboxes.models.fax_label import FaxLabel
from fax_queue_inboxes.models.practice_label import PracticeLabel
from fax_queue_inboxes.models.proxies import IntegrationTaskProxy, StaffProxy, TeamProxy

__all__ = [
    "FaxLabel",
    "FaxRecord",
    "IntegrationTaskProxy",
    "PracticeLabel",
    "StaffProxy",
    "TeamProxy",
]
