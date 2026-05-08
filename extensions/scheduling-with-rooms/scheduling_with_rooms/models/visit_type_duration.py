"""Per-visit-type allowed scheduling durations.

One row per allowed (note_type_code, duration_minutes) pair. A visit type
with zero rows falls back to the global ``SCHEDULE_DURATIONS`` secret (or
the hardcoded default list).
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import IntegerField, CharField


class VisitTypeDuration(CustomModel):
    note_type_code = CharField(max_length=128)
    duration_minutes = IntegerField()


def get_durations_for(note_type_code: str) -> list[int]:
    """Return the configured durations for a visit type, sorted ascending.

    Returns ``[]`` when nothing is configured (caller should fall back to
    the global default list).
    """
    if not note_type_code:
        return []
    return sorted(
        VisitTypeDuration.objects
        .filter(note_type_code=note_type_code)
        .values_list("duration_minutes", flat=True)
    )


def replace_durations(by_note_type: dict[str, list[int]]) -> None:
    """Replace-all save for each note_type_code present in the dict."""
    if not by_note_type:
        return
    codes = list(by_note_type.keys())
    VisitTypeDuration.objects.filter(note_type_code__in=codes).delete()
    rows: list[VisitTypeDuration] = []
    for code, minutes_list in by_note_type.items():
        if not isinstance(code, str) or not code:
            continue
        for minutes in set(minutes_list):
            if isinstance(minutes, int) and minutes > 0:
                rows.append(VisitTypeDuration(
                    note_type_code=code,
                    duration_minutes=minutes,
                ))
    if rows:
        VisitTypeDuration.objects.bulk_create(rows)
