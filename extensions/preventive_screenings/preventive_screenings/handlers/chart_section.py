"""Show every screening that applies to a patient, on chart open.

The protocol cards are the triage list: what needs doing. This is the record:
what was done, when, and when it is next due - including screenings that are up
to date, which Canvas renders no card for at all. That gap is the client's own
requirement going unmet: *"We also need to see the last completed date, not
only when it's due."*

**This is the one place the plugin may compute on chart open.** The whole
event-driven architecture exists because a chart-read event may not return
``ADD_OR_UPDATE_PROTOCOL_CARD`` - the effect is built, returned and silently
discarded (proved on the instance 2026-09-19). That restriction is about
protocol cards. ``PatientChartSummaryCustomSection`` is this event's own return
type, so this renders live and stores nothing: no keys, no fingerprints, no
retraction, and no way to be stale.

**It deliberately does NOT emit ``PatientChartSummaryConfiguration``.** That
effect does not add a section - its docstring says it decides which sections
appear, and its ``sections`` field carries ``min_length=1`` - so using it would
mean enumerating all eleven built-ins and taking ownership of a layout the
practice configured, while colliding with any other plugin doing the same. For
a plugin meant to be installed by many practices that is not acceptable.

Appending to the practice's own list was the wanted behaviour and is not
available: there is no data model holding the configuration (every SDK table
checked, 2026-09-22), and the section-configuration event's context carries
only ``user`` - proved with a probe on the instance the same day.

So this handler registers a ``SECTION_KEY`` and waits to be asked. If Canvas
discovers section handlers by itself, the section appears and nothing is
overridden. If it does not, this handler is simply never called and nothing
happens - which costs nothing and settles the question.

The cost when it does run is real and worth stating: it reads the chart on
every chart open. The reads are the same batched handful
``services.completion`` does everywhere else - one per source, never one per
screening - so the budget is fixed rather than growing with the practice's
rules. If it ever needs to come off the hot path, serve a ``url`` instead of
``content`` so the section loads on expand rather than on open.
"""

from datetime import UTC, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_chart_summary_custom_section import (
    PatientChartSummaryCustomSection,
)
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from logger import log

# Imported by name, never as `from ...services import chart_section` then
# `chart_section.build_section()`. The sandbox refuses attribute access on an
# imported module object, and does so at RUN time - see handlers/sweep.py.
from preventive_screenings.services.chart_section import build_section
from preventive_screenings.services.config_store import (
    DEFAULTS_CURRENT_AS_OF,
    active_screenings,
    load_config,
)
from preventive_screenings.services.review import review_patient


class PreventiveScreeningChartSection(PatientChartSummaryCustomSectionHandler):
    """Render the patient's screening record into the chart summary."""

    # Canvas matches this against `event.context["section"]`. It is part of the
    # plugin's external surface once anything references it, so treat it as
    # permanent in the same way the seed screening ids are.
    SECTION_KEY = "preventive_screenings"

    def handle(self) -> list[Effect]:
        """Build the section for this patient, or nothing if it cannot be built."""
        patient_id = str(self.event.target.id or "")
        if not patient_id:
            return []

        screenings = active_screenings(load_config())
        if not screenings:
            return []

        today = datetime.now(UTC).date()
        review = review_patient(patient_id, screenings, today)

        # No rows means the patient could not be assessed - no birth date, or
        # deceased. Saying nothing is right: a section asserting "no screenings
        # apply" would be claiming knowledge we do not have.
        if not review.rows:
            return []

        log.info(
            f"preventive_screenings: chart section rendered, "
            f"{sum(1 for row in review.rows if row.status is not None)} applicable"
        )
        return [
            PatientChartSummaryCustomSection(
                content=build_section(review.rows, DEFAULTS_CURRENT_AS_OF),
                icon="clipboard",
            ).apply()
        ]
