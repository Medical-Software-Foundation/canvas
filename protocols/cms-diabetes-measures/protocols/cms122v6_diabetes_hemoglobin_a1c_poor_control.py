"""
CMS122v6 - Diabetes: Hemoglobin A1c (HbA1c) Poor Control (>9%).

Patients are numerator-compliant (in the *poor* sense - this is an inverse measure) if
their most recent HbA1c is >9.0%, there's a result without a value, or no HbA1c has been
performed during the measurement period. A SATISFIED protocol card here means the patient
is *not* in poor control.

https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS122v6.html
"""

from __future__ import annotations

from functools import cached_property

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.lab import LabReport, LabValue
from canvas_sdk.value_set.v2022.laboratory_test import Hba1CLaboratoryTest

from .diabetes_quality_measure import DiabetesQualityMeasure


class ClinicalQualityMeasure122v6(DiabetesQualityMeasure):
    """CMS122v6 - HbA1c poor control."""

    class Meta:
        title = "Diabetes: Hemoglobin HbA1c Poor Control (> 9%)"
        version = "2019-02-12v1"
        description = (
            "Patients 18-75 years of age with diabetes who have either a hemoglobin A1c > 9.0% "
            "or no hemoglobin A1c within the last year."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS122v6.html"
        identifiers = ["CMS122v6"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    MINIMUM_HBA1C = 9.0

    @cached_property
    def last_hba1c_lab_value(self) -> LabValue | None:
        """Most-recent committed HbA1c LabValue inside the measurement period, if any."""
        return (
            LabValue.objects.filter(
                report__patient__id=self.patient.id,
                report__original_date__gte=self.timeframe.start.datetime,
                report__original_date__lte=self.timeframe.end.datetime,
            )
            .find(Hba1CLaboratoryTest)
            .order_by("-report__original_date")
            .first()
        )

    @cached_property
    def last_hba1c_report(self) -> LabReport | None:
        """The LabReport corresponding to ``last_hba1c_lab_value``."""
        value = self.last_hba1c_lab_value
        return value.report if value else None

    @property
    def last_hba1c_value(self) -> float | None:
        """Numeric HbA1c reading. Returns ``0`` if the stored value won't parse."""
        value = self.last_hba1c_lab_value
        if value is None:
            return None
        raw = value.value
        if isinstance(raw, str):
            return self.relative_float(raw)
        return float(raw)

    @property
    def last_hba1c_arrow(self) -> arrow.Arrow | None:
        """The original date of the latest HbA1c report, if any."""
        report = self.last_hba1c_report
        return arrow.get(report.original_date) if report else None

    @property
    def last_hba1c_date(self) -> str | None:
        """Humanized "X months ago on M/D/YY" rendering of the latest HbA1c date."""
        when = self.last_hba1c_arrow
        return self.display_date(when) if when else None

    def in_denominator(self) -> bool:
        """In the initial population; hospice exclusion isn't checked because there's no SDK
        hospice flag on Patient. Subclassers can override if a customer needs that gate.
        """
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        """True if HbA1c is missing, has no parseable value, or is >9.0%."""
        if self.last_hba1c_lab_value is None:
            return True
        value = self.last_hba1c_value
        return value is None or value > self.MINIMUM_HBA1C

    def _due_card(self) -> ProtocolCard:
        """Build a DUE card recommending either an HbA1c order or a dietary instruction."""
        first_name = self.patient.first_name
        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS122v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        if self.last_hba1c_value is None:
            humanized = (
                self.now.shift(days=-1 * self.timeframe.duration, months=-1)
                .humanize(other=self.now, granularity="month", only_distance=True)
                .replace(" ago", "")
            )
            card.narrative = f"{first_name}'s last HbA1c test was over {humanized}."
            card.add_recommendation(
                title="Order HbA1c",
                button="Order",
            )
        else:
            card.narrative = (
                f"{first_name}'s last HbA1c done {self.last_hba1c_date} was "
                f"{self.last_hba1c_value:.1f}%."
            )
            card.add_recommendation(
                title=(
                    "Discuss lifestyle modification and medication adherence. "
                    "Consider diabetes education and medication intensification as appropriate."
                ),
                button="Instruct",
            )
        return card

    def _satisfied_card(self) -> ProtocolCard:
        """Build a SATISFIED card describing the most-recent in-period HbA1c value."""
        due_in = (self.last_hba1c_arrow.shift(days=self.timeframe.duration) - self.now).days
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS122v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            narrative=(
                f"{self.patient.first_name}'s last HbA1c done {self.last_hba1c_date} was "
                f"{self.last_hba1c_value:.1f}%."
            ),
            due_in=due_in,
        )

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard effect summarizing this patient's HbA1c control."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS122v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        if self.in_numerator():
            return [self._due_card().apply()]
        return [self._satisfied_card().apply()]
