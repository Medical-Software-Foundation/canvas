"""Query-shape tests: assert on generated SQL, which resolves real field names.

A mocked queryset never resolves a field, so a wrong column or a reintroduced
join passes against mocks and only fails against a live database. These build
the querysets the endpoints build and inspect the SQL without executing it.
"""

from __future__ import annotations

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.note import Note

_PID = "abc123"


def _select_clause(qs) -> str:
    return str(qs.query).split(" FROM ")[0]


def _patient_appointments_notes_qs(linked_note_dbids=None):
    """Mirrors get_patient_appointments' notes query."""
    qs = (
        Note.objects.filter(patient__id=_PID)
        .select_related("provider", "note_type_version")
        .defer("body", "related_data")
        .order_by("-datetime_of_service")
    )
    if linked_note_dbids:
        qs = qs.exclude(dbid__in=linked_note_dbids)
    return qs


def _patient_appointments_appt_qs():
    """Mirrors get_patient_appointments' appointments query."""
    return (
        Appointment.objects.filter(patient__id=_PID)
        .select_related("provider", "note_type")
        .order_by("-start_time")
    )


def test_notes_query_does_not_load_the_note_body() -> None:
    """`body` is the note's clinical content and the largest field on the row.

    This endpoint reads only id/title/datetime_of_service plus two scalars off
    related rows, and runs on every chart open.
    """
    select = _select_clause(_patient_appointments_notes_qs())
    assert '"body"' not in select
    assert "related_data" not in select


def test_notes_query_does_not_join_location() -> None:
    """Nothing in the serializer reads location, so the join is pure overhead."""
    sql = str(_patient_appointments_notes_qs().query)
    assert "practicelocation" not in sql.lower()


def test_appointments_query_does_not_join_location() -> None:
    sql = str(_patient_appointments_appt_qs().query)
    assert "practicelocation" not in sql.lower()


def test_notes_query_still_selects_every_field_the_serializer_reads() -> None:
    """Guard the other direction: a deferred field the serializer touches would
    be lazily loaded per row, turning this into an N+1."""
    select = _select_clause(_patient_appointments_notes_qs())
    for column in ("title", "datetime_of_service"):
        assert column in select, column
    # Related fields come from the joins, so the join must still be there.
    sql = str(_patient_appointments_notes_qs().query)
    assert "JOIN" in sql


def test_appointment_note_fk_holds_a_dbid_not_a_uuid() -> None:
    """The premise the dedup below rests on, asserted rather than assumed.

    `Appointment.note` declares no `to_field`, so it targets Note's primary key.
    On an SDK model that is `dbid`; `id` is a separate UUID column that is merely
    unique. So `appt.note_id` is an integer.
    """
    target = Appointment._meta.get_field("note").target_field
    assert target.name == "dbid"
    assert Note._meta.pk.name == "dbid"
    assert Note._meta.get_field("id").get_internal_type() == "UUIDField"


def test_linked_note_dedup_excludes_on_dbid() -> None:
    """The exclude must name `dbid`, the column `appt.note_id` actually holds.

    Excluding by `id` does not raise: UUIDField coerces an int through
    `uuid.UUID(int=...)`, so a dbid becomes a zero-padded UUID that matches no
    real note. The dedup then silently no-ops and every note already shown as an
    appointment is listed a second time. Assert on the rendered SQL, because
    that is the only place the wrong column is visible.
    """
    sql = str(_patient_appointments_notes_qs(linked_note_dbids={12345, 6789}).query)
    where = sql.split(" WHERE ")[1]
    assert "dbid" in where
    # The zero-padded UUID an int silently coerces into. Its presence means the
    # exclude went through the UUID column and matches nothing.
    assert "00000000000000000000000000003039" not in where
    assert "12345" in where


def test_notes_query_has_no_exclude_when_nothing_is_linked() -> None:
    """No appointments carrying a note means no exclude clause at all."""
    sql = str(_patient_appointments_notes_qs().query)
    assert "NOT" not in sql.split(" WHERE ")[1]


def test_deferring_blobs_measurably_shrinks_the_row() -> None:
    """Records the win so a regression is visible, not just theoretical."""
    lean = _select_clause(_patient_appointments_notes_qs()).count(",") + 1
    fat = _select_clause(
        Note.objects.filter(patient__id=_PID)
        .select_related("provider", "note_type_version", "location")
        .order_by("-datetime_of_service")
    ).count(",") + 1
    assert lean < fat
    assert fat - lean >= 20, f"expected a meaningful reduction, got {fat} -> {lean}"
