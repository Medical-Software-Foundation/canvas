"""Keeping the chart's waitlist button in step with the roster.

The button in ``handlers/chart_button.py`` decides its label when the chart
header renders, from whether the patient has a live entry. Nothing redraws it on
its own, so after a write from the roster the chart would keep offering "Add to
waitlist" for someone already on the list until the page was reloaded.

Paired with ``services/banner.py``: both exist so a write anywhere leaves the
patient's chart telling the truth. The banner carries the status, this refreshes
the action.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadPatientActionButtonsEffect


def reload_chart_buttons(entry: Any) -> list[Effect]:
    """Ask the chart to redraw its buttons for this entry's patient.

    Returns nothing for an entry with no resolvable patient, matching
    ``banner_effects``: an effect keyed on ``None`` addresses no chart.
    """
    patient = getattr(entry, "patient", None)
    patient_id = getattr(patient, "id", None)
    if not patient_id:
        return []

    return [ReloadPatientActionButtonsEffect(id=str(patient_id)).apply()]
