"""The chart lookups compile against the real SDK models.

Other tests stand in for the database, so a renamed field would still pass there. Building the SQL
resolves every field name without a database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from canvas_sdk.v1.data import Appointment, BusinessLine, Coverage, PatientFacilityAddress, PatientMetadata
from canvas_sdk.v1.data.reason_for_visit import ReasonForVisit
from django.db.models import Q


def test_chart_lookups_compile() -> None:
    on, now = date(2026, 10, 20), datetime(2026, 10, 20, tzinfo=UTC)
    moved = Appointment.objects.filter(patient=1, appointment_rescheduled_from__isnull=False).values("appointment_rescheduled_from_id")
    queries = [
        PatientFacilityAddress.objects.filter(patient=1, state="active").select_related("facility").order_by("dbid"),
        Appointment.objects.filter(patient=1, entered_in_error__isnull=True)
        .exclude(status__in=["cancelled", "noshowed"])
        .exclude(dbid__in=moved)
        .exclude(note_id=1)
        .filter(start_time__lt=now)
        .order_by("-start_time")
        .values_list("start_time", flat=True),
        Coverage.objects.filter(patient=1, coverage_rank=1, stack="IN_USE", coverage_start_date__lte=on)
        .filter(Q(coverage_end_date__isnull=True) | Q(coverage_end_date__gte=on))
        .select_related("issuer")
        .order_by("dbid"),
        BusinessLine.objects.filter(dbid=1).values_list("name", flat=True),
        PatientMetadata.objects.filter(patient=1, key__in={"program_name"}).values_list("key", "value"),
        PatientMetadata.objects.order_by("key").values_list("key", flat=True).distinct(),
        ReasonForVisit.objects.committed().filter(note_id=1).prefetch_related("codings").order_by("dbid"),
    ]
    for query in queries:
        assert str(query.query).startswith("SELECT")
