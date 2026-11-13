"""
Abstract base class shared by the diabetes quality measures in this plugin.

Subclasses set ``QUALIFYING_VISIT_CODES`` and implement ``in_numerator`` plus
``compute()``. The initial population is a patient 18-75 years of age at the end of the
measurement period with diabetes overlapping it and a qualifying visit during it; the
denominator removes the cross-cutting exclusions in ``ecqm_common``.
"""

from __future__ import annotations

import arrow

from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.value_set.v2027.condition import Diabetes

from .ecqm_common import EcqmPatient, age_in_years


class DiabetesQualityMeasure(ClinicalQualityMeasure):
    """Base class for the diabetes eCQMs (CMS122, CMS131, CMS951)."""

    class Meta:
        title = "Diabetes Quality Measure"
        version = "1.0"
        description = ""
        information = ""
        identifiers: list[str] = []
        types = ["CQM"]
        authors = ["Canvas Medical Team"]
        is_abstract = True

    AGE_RANGE_START = 18
    AGE_RANGE_END = 75
    QUALIFYING_VISIT_CODES: frozenset[str] = frozenset()

    @classmethod
    def enabled(cls) -> bool:
        """Always enabled; kept for parity with the legacy interface."""
        return True

    _patient: Patient | None = None
    _ecqm: EcqmPatient | None = None

    @property
    def patient(self) -> Patient:
        """The patient this protocol is computing for, fetched once per instance."""
        if self._patient is None:
            self._patient = Patient.objects.get(id=self.patient_id_from_target())
        return self._patient

    @property
    def ecqm(self) -> EcqmPatient:
        """eCQM data access for this patient and measurement period, built once per instance."""
        if self._ecqm is None:
            self._ecqm = EcqmPatient(
                self.patient.id, self.timeframe, age_in_years(self.patient, self.timeframe.end)
            )
        return self._ecqm

    def age(self) -> int:
        """Completed years of age at the end of the measurement period."""
        return age_in_years(self.patient, self.timeframe.end)

    def has_diabetes_in_period(self) -> bool:
        """A diabetes diagnosis whose prevalence period overlaps the measurement period."""
        return self.ecqm.has_condition(Diabetes, self.timeframe)

    def has_qualifying_visit(self) -> bool:
        """A visit billing one of the measure's qualifying encounter codes during the period."""
        return self.ecqm.count_visits(set(self.QUALIFYING_VISIT_CODES), self.timeframe) > 0

    def in_initial_population(self) -> bool:
        """Patients 18-75 with diabetes overlapping the period and a qualifying visit during it."""
        return (
            self.AGE_RANGE_START <= self.age() <= self.AGE_RANGE_END
            and self.has_diabetes_in_period()
            and self.has_qualifying_visit()
        )

    def is_excluded(self) -> bool:
        """The cross-cutting exclusions; subclasses add measure-specific ones."""
        return self.ecqm.excluded()

    def in_denominator(self) -> bool:
        """The initial population minus the denominator exclusions."""
        return self.in_initial_population() and not self.is_excluded()

    def in_numerator(self) -> bool:
        """Subclasses must override."""
        raise NotImplementedError("in_numerator must be overridden")

    def first_due_in(self) -> int | None:
        """Days until the patient becomes age-eligible (only if they already have diabetes)."""
        if self.age() < self.AGE_RANGE_START and self.has_diabetes_in_period():
            birthday = arrow.get(self.patient.birth_date)
            return (birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.end).days
        return None

    def display_date(self, when: arrow.Arrow) -> str:
        """Render an arrow timestamp as e.g. ``2 months ago on 8/2/18``."""
        return f"{when.humanize(other=self.now)} on {when.format('M/D/YY')}"
