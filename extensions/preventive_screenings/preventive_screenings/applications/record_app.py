"""Chart-side entry point for one patient's screening record.

**Why this exists rather than a chart-summary section.** The client asked to
see the last completed date, not only when something is due. Canvas renders no
protocol card at all for a satisfied screening, so that date is visible exactly
while a screening is overdue and invisible the moment it is up to date - which
is when somebody asks "when did she last have one?".

A chart-summary section would have shown it inline, and three routes to one
were ruled out on the instance on 2026-09-22:

* **No data model holds the practice's section list** - every SDK table checked.
* **The section-configuration event carries only the staff user** - proved with
  a probe: ``context keys=['user']``.
* **Canvas never asks.** A registered ``SECTION_KEY`` handler was deployed and
  ``GET_CUSTOM_SECTION`` did not fire once across three chart loads.

That leaves emitting ``PatientChartSummaryConfiguration``, which decides which
sections appear rather than adding one - so it would mean enumerating all
eleven built-ins, overriding a layout the practice configured, and colliding
with any other plugin doing the same. **Rejected deliberately** (Luke,
2026-09-22): this plugin is meant to be installed by many practices, and
replacing their chart layout to add one panel is not a defensible default.

So: one click instead of inline, and nothing of the practice's is touched.
"""

import time

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Generated once at module load, so it changes on every deploy and the modal is
# never served from a stale browser cache after an update.
_CACHE_BUST = str(int(time.time()))


class ScreeningRecordApplication(Application):
    """Open this patient's screening record."""

    def on_open(self) -> Effect:
        """Launch the record for whichever patient's chart we were opened from.

        The patient arrives on the event's context, not on ``target`` - the
        base ``Application`` matches ``target.id`` against the application's own
        identifier, so target is the app. An app opened outside a chart has no
        patient, and the route says so rather than guessing at one.
        """
        patient = self.event.context.get("patient") or {}
        patient_id = str(patient.get("id") or "")

        return LaunchModalEffect(
            url=(
                f"/plugin-io/api/preventive_screenings/record/ui"
                f"?patient={patient_id}&v={_CACHE_BUST}"
            ),
            # Beside the chart rather than over it. A screening record is
            # something a provider reads *while* looking at the patient, and a
            # modal that covers the chart to show chart data is the wrong shape.
            # It is also the closest thing available to the inline section this
            # replaces.
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()
