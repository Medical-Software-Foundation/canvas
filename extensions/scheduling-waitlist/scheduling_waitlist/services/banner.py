"""The chart banner saying a patient is already on the waitlist.

This answers one of the two questions a chart gets asked: "is this person
already waiting?" -- passively, with no click. The other question, "put them on
the list", is an action and belongs to the chart-header button in
``handlers/chart_button.py``; a banner cannot serve it. The two are deliberately
separate controls rather than one control doing both jobs badly.

The banner is keyed, not appended: re-emitting with the same key replaces the
previous one, so these effects can be returned from every write path without
stacking duplicates on a patient's chart.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert.add_banner_alert import AddBannerAlert
from canvas_sdk.effects.banner_alert.remove_banner_alert import RemoveBannerAlert

from scheduling_waitlist.constants import BANNER_KEY, BANNER_NARRATIVE_MAX, ROSTER_URL
from scheduling_waitlist.services.display import ANY_TYPE, note_type_name
from scheduling_waitlist.services.entries import live_entries_for_patient


def compose_narrative(entries: list[Any]) -> str:
    """One line describing what this patient is waiting for.

    Truncated rather than validated: the real effect rejects anything over
    ``BANNER_NARRATIVE_MAX``, and a patient with several long service names
    would otherwise turn a banner into a failed effect. Losing the tail of a
    list is a much smaller problem than losing the whole banner.
    """
    count = len(entries)
    if count == 1:
        note_type = getattr(entries[0], "note_type", None)
        # A null service means "any appointment type will do", which is a real
        # preference rather than missing data, so it is named as such.
        label = ANY_TYPE if note_type is None else note_type_name(note_type)
        text = f"On the scheduling waitlist for {label}"
    else:
        text = f"On the scheduling waitlist for {count} appointment types"

    if len(text) <= BANNER_NARRATIVE_MAX:
        return text
    return text[: BANNER_NARRATIVE_MAX - 1].rstrip() + "…"


def banner_effects(patient: Any) -> list[Effect]:
    """Bring the banner into line with what this patient is waiting for.

    Returns a single add-or-remove effect, so callers can append it to whatever
    they were already returning. An unresolvable patient yields nothing rather
    than a banner keyed on ``None``, which would be un-removable.
    """
    patient_id = getattr(patient, "id", None)
    if not patient_id:
        return []

    entries = live_entries_for_patient(getattr(patient, "dbid", None))
    if not entries:
        return [RemoveBannerAlert(patient_id=str(patient_id), key=BANNER_KEY).apply()]

    return [
        AddBannerAlert(
            patient_id=str(patient_id),
            key=BANNER_KEY,
            narrative=compose_narrative(entries),
            placement=[AddBannerAlert.Placement.CHART],
            intent=AddBannerAlert.Intent.INFO,
            href=ROSTER_URL,
        ).apply()
    ]


def banner_effects_for_entry(entry: Any) -> list[Effect]:
    """Refresh the banner for the patient an entry belongs to.

    Every write path holds an entry rather than a patient, and the entry's
    ``patient`` relation carries both the dbid the waitlist keys on and the UUID
    the banner needs.
    """
    return banner_effects(getattr(entry, "patient", None))
