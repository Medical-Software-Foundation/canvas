"""HCC005v1 - Annual Wellness Visit.

Surfaces a protocol card for Medicare-eligible patients (65+) who are due for
an Annual Wellness Visit (AWV). A patient is considered satisfied when a
qualifying AWV CPT code has been billed within the protocol timeframe (one
year by default).
"""

from typing import Any

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.billing import BillingLineItem
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.custom import Hcc005v1AnnualWellnessVisit


class Hcc005v1(ClinicalQualityMeasure):
    """Annual Wellness Visit protocol."""

    class Meta:
        title = "Annual Wellness Visit"
        version = "2019-11-04v1"
        description = "Patient 65 or older due  for Annual Wellness Visit."
        information = "https://canvas-medical.help.usepylon.com/articles/3810882246-protocol-annual-wellness-visit-hcc005v1"
        identifiers = ["HCC005v1"]
        types = ["HCC"]
        authors = ["Canvas Medical Team"]
        references = [
            "Canvas Medical HCC, https://canvas-medical.help.usepylon.com/articles/3810882246-protocol-annual-wellness-visit-hcc005v1"
        ]
        default_permission_flags = {"protocols:actions:HCC005v1:instruct": True}

    RESPONDS_TO = [
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_CREATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_DELETED),
    ]

    MINIMUM_AGE = 65

    _patient: Patient | None = None
    _qualifying_visits: list[BillingLineItem] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Seed _patient_id from the event context so patient_id_from_target() never runs its
        # target lookup, which raises on every non-patient event until
        # https://github.com/canvas-medical/canvas-plugins/pull/1962 ships. Remove this override
        # once the plugin's SDK version includes that fix. Patient events carry no context
        # patient and resolve from the target, which works today.
        if patient := self.event.context.get("patient"):
            self._patient_id = patient["id"]

    @property
    def patient(self) -> Patient:
        """The Patient model for the event target, fetched once per instance."""
        if self._patient is None:
            self._patient = Patient.objects.get(id=self.patient_id_from_target())
        return self._patient

    @property
    def qualifying_visits(self) -> list[BillingLineItem]:
        """All qualifying AWV billing line items for the patient, oldest first, fetched once
        per instance.
        """
        if self._qualifying_visits is None:
            self._qualifying_visits = list(
                BillingLineItem.objects.filter(patient__id=self.patient_id_from_target())
                .find(Hcc005v1AnnualWellnessVisit)
                .order_by("created")
            )
        return self._qualifying_visits

    @property
    def last_qualifying_visit_in_timeframe(self) -> BillingLineItem | None:
        """The most recent qualifying AWV billing line item inside the protocol timeframe."""
        start = self.timeframe.start.datetime
        end = self.timeframe.end.datetime
        within = [item for item in self.qualifying_visits if start <= item.created <= end]
        return within[-1] if within else None

    def in_initial_population(self) -> bool:
        """Initial population: Patients 65+ years of age."""
        return bool(self.patient.age_at(self.timeframe.end) >= self.MINIMUM_AGE)

    def in_denominator(self) -> bool:
        """Patients in the initial population."""
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        """Patients without a qualifying AWV visit within the timeframe."""
        return self.last_qualifying_visit_in_timeframe is None

    def display_date(self, day: arrow.Arrow) -> str:
        """Humanized "{relative} on {M/D/YY}" format used in narratives."""
        return f"{day.humanize(other=self.now)} on {day.format('M/D/YY')}"

    def recent_visit_context(self) -> str:
        """Narrative describing the most recent qualifying visit, if any."""
        if not self.qualifying_visits:
            return "There are no Annual Wellness Visits on record."
        last_date = arrow.get(self.qualifying_visits[-1].created)
        return f"Last Annual Wellness Visit was {self.display_date(last_date)}."

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard effect describing the patient's AWV status."""
        patient_id = self.patient_id_from_target()
        card = ProtocolCard(
            patient_id=patient_id,
            key="HCC005v1",
            title="Annual Wellness Visit",
        )

        if not self.in_denominator():
            card.status = ProtocolCard.Status.NOT_APPLICABLE
            birth_date = arrow.get(self.patient.birth_date)
            card.due_in = (birth_date.shift(years=self.MINIMUM_AGE) - self.timeframe.end).days
            return [card.apply()]

        if self.in_numerator():
            card.status = ProtocolCard.Status.DUE
            card.due_in = -1
            card.narrative = (
                f"{self.patient.first_name} is due for a Annual Wellness Visit.\n"
                f"{self.recent_visit_context()}"
            )
            card.add_recommendation(
                title="Schedule for Annual Wellness Visit",
                button="Schedule",
                command="instruct",
            )
        else:
            visit = self.last_qualifying_visit_in_timeframe
            assert visit is not None  # guarded by in_numerator() == False
            visit_date = arrow.get(visit.created)
            card.status = ProtocolCard.Status.SATISFIED
            card.due_in = (visit_date.shift(days=self.timeframe.duration) - self.now).days
            card.narrative = (
                f"{self.patient.first_name} had a visit {self.display_date(visit_date)}."
            )

        return [card.apply()]
