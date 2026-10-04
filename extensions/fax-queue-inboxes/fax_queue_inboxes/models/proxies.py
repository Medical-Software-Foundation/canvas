"""Private proxy handles onto shared SDK models, per Section 3 of SPEC.md.

A ModelExtension proxy carries no shared namespace, so a ForeignKey or a
OneToOneField in this plugin's own store may target it directly, which is
the pattern fax_record.py uses for every relation it declares.
"""

from __future__ import annotations

from canvas_sdk.v1.data import IntegrationTask, ModelExtension, Staff, Team


class IntegrationTaskProxy(IntegrationTask, ModelExtension):
    pass


class StaffProxy(Staff, ModelExtension):
    pass


class TeamProxy(Team, ModelExtension):
    pass
