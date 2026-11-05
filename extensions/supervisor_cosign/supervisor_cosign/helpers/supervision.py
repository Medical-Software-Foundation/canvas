"""Supervisor and supervisee resolution, off the native Canvas pairing.

``Staff.default_supervising_provider`` is a self-FK; this plugin keeps no
roster of its own, so everything here is one or two queries against that one
field. ``Staff.id`` is a 32-char hex ``key`` CharField with no dashes, which is
what the ``canvas-logged-in-user-id`` header carries and what the co-sign
records store.
"""

from canvas_sdk.v1.data.staff import Staff

from supervisor_cosign.models.cosign_record import CoSignRecord


def supervises_someone(staff_id: str) -> bool:
    """True when an active staff member reports to ``staff_id`` or ``staff_id`` supervises a co-sign record.

    Written forward through ``default_supervising_provider`` rather than
    through the ``supervising_team`` reverse accessor so the related_name is
    not load-bearing. One ``EXISTS`` with a single self-join; call it once per
    request and pass the answer around, never per row.
    """
    if not staff_id:
        return False
    if Staff.objects.filter(active=True, default_supervising_provider__id=staff_id).exists():
        return True
    # Also true for a supervisor named only on a note's supervising_provider,
    # who holds co-sign records without being anyone's default.
    return CoSignRecord.objects.filter(supervisor_id=staff_id).exists()


def supervised_staff(supervisor_ids: list[str] | None = None) -> list[dict]:
    """Active supervisees, with their supervisor, as plain dicts.

    ``supervisor_ids=None`` means every supervised staff member on the
    instance, which is the oversight view. One query either way, and it carries
    the supervisor's name too so the caller never needs a second ``Staff``
    lookup to label a row.
    """
    qs = Staff.objects.filter(active=True, default_supervising_provider__isnull=False)
    if supervisor_ids is not None:
        qs = qs.filter(default_supervising_provider__id__in=supervisor_ids)
    rows = qs.values(
        "id",
        "first_name",
        "last_name",
        "default_supervising_provider__id",
        "default_supervising_provider__first_name",
        "default_supervising_provider__last_name",
    ).order_by("last_name", "first_name")
    supervisees = []
    for row in rows:
        supervisees.append(
            {
                "id": str(row["id"]),
                "name": _name(row["first_name"], row["last_name"]),
                "supervisor_id": str(row["default_supervising_provider__id"] or ""),
                "supervisor_name": _name(
                    row["default_supervising_provider__first_name"],
                    row["default_supervising_provider__last_name"],
                ),
            }
        )
    return supervisees


def _name(first: str, last: str) -> str:
    return (str(first or "") + " " + str(last or "")).strip()
