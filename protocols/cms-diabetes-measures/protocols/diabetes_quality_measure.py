"""
Abstract base class shared by the four CMS diabetes quality measures in this plugin.

This mirrors the legacy ``DiabetesQualityMeasure`` from
``workflow_sdk_loader.builtin_cqms`` but is rebuilt on top of the Canvas SDK
(``canvas_sdk.protocols.ClinicalQualityMeasure``). Subclasses implement
``in_denominator``/``in_numerator`` plus ``compute()``.
"""

from __future__ import annotations

from functools import cached_property

import arrow

from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.v2022.condition import Diabetes


class DiabetesQualityMeasure(ClinicalQualityMeasure):
    """Base class for the CMS diabetes CQM family (CMS122v6/123v6/131v6/134v6)."""

    class Meta:
        title = "Diabetes Quality Measure"
        version = "1.0"
        description = ""
        information = ""
        identifiers: list[str] = []
        types = ["CCP"]
        authors = ["Canvas Medical Team"]
        is_abstract = True

    AGE_RANGE_START = 18
    AGE_RANGE_END = 75

    @classmethod
    def enabled(cls) -> bool:
        """Always enabled; kept for parity with the legacy interface."""
        return True

    @cached_property
    def patient(self) -> Patient:
        """The patient this protocol is computing for."""
        return Patient.objects.get(id=self.patient_id_from_target())

    def has_diabetes_in_period(self) -> bool:
        """True if the patient has an active Diabetes condition during the timeframe."""
        return (
            Condition.objects.for_patient(self.patient.id)
            .find(Diabetes)
            .active()
            .filter(onset_date__lte=self.timeframe.end.date())
            .exists()
        )

    def in_initial_population(self) -> bool:
        """Patients 18-75 with diabetes (legacy "had a visit" gate is omitted: there's no
        equivalent ``has_visit_within`` on the SDK Patient).
        """
        age = self.patient.age_at(self.timeframe.end)
        return self.AGE_RANGE_START <= age < self.AGE_RANGE_END and self.has_diabetes_in_period()

    def in_denominator(self) -> bool:
        """Subclasses must override."""
        raise NotImplementedError("in_denominator must be overridden")

    def in_numerator(self) -> bool:
        """Subclasses must override."""
        raise NotImplementedError("in_numerator must be overridden")

    def first_due_in(self) -> int | None:
        """Days until the patient becomes age-eligible (only if they already have diabetes)."""
        if (
            self.patient.age_at(self.timeframe.end) < self.AGE_RANGE_START
            and self.has_diabetes_in_period()
        ):
            birthday = arrow.get(self.patient.birth_date)
            return (birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.end).days
        return None

    def display_date(self, when: arrow.Arrow) -> str:
        """Render an arrow timestamp as e.g. ``2 months ago on 8/2/18``."""
        return f"{when.humanize(other=self.now)} on {when.format('M/D/YY')}"
