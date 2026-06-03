from canvas_sdk.effects import Effect
from canvas_sdk.effects.group import Group
from canvas_sdk.effects.patient_chart_group import PatientChartGroup
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

# Coded (normal) meds render first under no visible heading; unstructured meds
# render below under their own heading. Higher priority sorts higher in the list.
# Both sets are grouped explicitly so Canvas does not add its own "Other" bucket.
CODED_GROUP_KEY = "coded"
# Non-breaking space: a non-empty name avoids Canvas's "Other" fallback while
# rendering as a visually empty heading. An empty string falls back to "Other".
CODED_GROUP_NAME = " "
CODED_GROUP_PRIORITY = 1000

UNSTRUCTURED_GROUP_KEY = "unstructured"
UNSTRUCTURED_GROUP_NAME = "⚠️ Unstructured Medications (free text)"
UNSTRUCTURED_GROUP_PRIORITY = 100

# A medication is "structured" if it carries a real drug code. Compare against
# the system URL strings (the event context delivers systems as URL strings).
FDB_SYSTEM = "http://www.fdbhealth.com/"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
STRUCTURED_SYSTEMS = (FDB_SYSTEM, RXNORM_SYSTEM)


def is_unstructured(medication: dict) -> bool:
    """True when a medication has no FDB or RxNorm coding (free text / uncoded)."""
    for coding in medication.get("codings", []):
        if coding.get("system") in STRUCTURED_SYSTEMS:
            return False
    return True


def partition_medications(context: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split the chart medications into (coded, unstructured) lists, order preserved."""
    coded: list[dict] = []
    unstructured: list[dict] = []
    for medication in context:
        (unstructured if is_unstructured(medication) else coded).append(medication)
    return coded, unstructured


class Medications(BaseHandler):
    """Groups unstructured medications under their own heading, below the coded meds."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)

    def compute(self) -> list[Effect]:
        # event.context can be None for this event (e.g. a patient with no
        # medications), so guard before iterating.
        coded, unstructured = partition_medications(self.event.context or [])

        # Nothing to flag: leave the medication list rendering untouched.
        if not unstructured:
            return []

        groups: dict[str, Group] = {
            UNSTRUCTURED_GROUP_KEY: Group(
                priority=UNSTRUCTURED_GROUP_PRIORITY,
                items=unstructured,
                name=UNSTRUCTURED_GROUP_NAME,
            )
        }
        if coded:
            groups[CODED_GROUP_KEY] = Group(
                priority=CODED_GROUP_PRIORITY,
                items=coded,
                name=CODED_GROUP_NAME,
            )

        return [PatientChartGroup(items=groups).apply()]
