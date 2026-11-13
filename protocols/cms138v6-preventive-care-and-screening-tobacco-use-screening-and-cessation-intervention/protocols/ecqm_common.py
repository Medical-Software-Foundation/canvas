"""Patient data access and denominator exclusions shared by the 2027 (v15) eCQMs.

Implements the eCQM shared libraries HospiceQDM 7.0, PalliativeCareQDM 6.0, and
AdvancedIllnessandFrailtyQDM 11.0 against Canvas data, plus the lookups the measures
themselves use. QDM data types map to Canvas records as follows:

- Diagnoses and symptoms are ``Condition`` rows, whose prevalence period runs from
  ``onset_date`` to ``resolution_date`` (open when unresolved).
- Encounters are billing line items, matched on their CPT and HCPCS codes.
- Interventions are instructions and procedures, matched on their codings.
- Performed procedures are procedures plus surgical history conditions.
- Active medications are ``Medication`` rows, whose relevant period runs from
  ``start_date`` to ``end_date``; a medication order is a medication starting in the window.
- Laboratory tests are lab values, dated by their report's ``original_date``.
- Diagnostic studies and physical exams by an outside provider are imaging and referral
  reports, matched on their codings.
- Assessments with a coded result are questionnaire answers (question code plus response
  option code) or observations (observation coding plus value coding).

Two spec criteria have no Canvas data to read: an inpatient discharge to hospice (the SDK
exposes no discharge disposition) and a frailty device *order* (DME orders carry HCPCS
codes while the Frailty Device value set is SNOMED CT). A frailty device recorded as a
"Medical equipment used" assessment still counts.

The measurement period is the protocol's timeframe: the year ending now.

Plugins cannot import from one another, so an identical copy of this module lives in
each plugin that needs it. Each plugin's tests compare its copy with the others.
"""

from __future__ import annotations

import arrow
from django.db.models import Q

from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.billing import BillingLineItem
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.instruction import Instruction
from canvas_sdk.v1.data.lab import LabValue
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.procedure import Procedure
from canvas_sdk.v1.data.questionnaire import InterviewQuestionResponse
from canvas_sdk.value_set.v2027.condition import (
    AdvancedIllness,
    FrailtyDiagnosis,
    HospiceDiagnosis,
    PalliativeCareDiagnosis,
)
from canvas_sdk.value_set.v2027.device import FrailtyDevice
from canvas_sdk.value_set.v2027.encounter import (
    FrailtyEncounter,
    HospiceEncounter,
    PalliativeCareEncounter,
)
from canvas_sdk.value_set.v2027.intervention import (
    HospiceCareAmbulatory,
    PalliativeCareIntervention,
)
from canvas_sdk.value_set.v2027.medication import DementiaMedications
from canvas_sdk.value_set.v2027.symptom import FrailtySymptom
from canvas_sdk.value_set.value_set import ValueSet

LOINC = "http://loinc.org"
SNOMEDCT = "http://snomed.info/sct"
ICD10_URL = "ICD-10"  # the SDK's system URL for ICD-10-CM and ICD-10-PCS codings

# Direct-reference codes from the shared libraries.
HOSPICE_CARE_ASSESSMENT = "45755-6"  # Hospice care [Minimum Data Set]
YES = "373066001"  # Yes (qualifier value)
PALLIATIVE_CARE_ASSESSMENT = "71007-9"  # FACIT-Pal questionnaire
HOUSING_STATUS = "71802-3"  # Housing status
LIVES_IN_NURSING_HOME = "160734000"  # Lives in nursing home (finding)
MEDICAL_EQUIPMENT_USED = "98181-1"  # Medical equipment used

EARLIEST = arrow.get("1900-01-01")


def age_in_years(patient: Patient, when: arrow.Arrow) -> int:
    """Completed years of age at ``when``, as the eCQM ``AgeInYearsAt`` counts them."""
    return int(patient.age_at(when))


def parse_number(text: object) -> float | None:
    """The numeric value of a result such as ``7.2``, ``>14``, or ``<= 3``; ``None`` if non-numeric."""
    cleaned = str(text or "").strip().lstrip("<>=≤≥ ").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def codes_in(value_set: type[ValueSet]) -> set[str]:
    """Every code in a value set, across code systems."""
    return {code for codes in value_set.values.values() for code in codes}


def billing_codes(value_set: type[ValueSet]) -> set[str]:
    """The CPT and HCPCS codes of a value set, the codes a billing line item can carry.

    ``BillingLineItem.objects.find()`` reads only a value set's ``HCPCS`` attribute, and eCQM
    value sets keep their codes in ``CPT`` and ``HCPCSLEVELII``, so it matches nothing for
    them. Filtering ``cpt`` on these codes matches the line items directly.
    """
    return {
        code
        for system in ("CPT", "HCPCS", "HCPCSLEVELII")
        for code in getattr(value_set, system, set())
    }


def coding_filter(value_set: type[ValueSet], prefix: str = "codings") -> Q:
    """A filter matching rows with a coding in ``value_set`` on ``<prefix>__system``/``code``."""
    query = Q(pk__in=[])
    for system, codes in value_set.values.items():
        url = value_set.CODE_SYSTEM_MAPPING[system]
        query = query | Q(**{f"{prefix}__system": url, f"{prefix}__code__in": codes})
    return query


def code_filter(system_url: str, code: str, prefix: str = "codings") -> Q:
    """A filter matching rows with the single coding ``system_url``/``code``."""
    return Q(**{f"{prefix}__system": system_url, f"{prefix}__code": code})


class EcqmPatient:
    """One patient's eCQM data and cross-cutting denominator exclusions for a measurement period."""

    def __init__(self, patient_id: str, measurement_period: Timeframe, age: int) -> None:
        self.patient_id = patient_id
        self.period = measurement_period
        self.age = age

    # ----- windows -----

    def before_and_during(self, **shift: int) -> Timeframe:
        """The measurement period extended back, e.g. ``before_and_during(years=1)``."""
        negated = {unit: -amount for unit, amount in shift.items()}
        return Timeframe(start=self.period.start.shift(**negated), end=self.period.end)

    def through_period_end(self) -> Timeframe:
        """Any time on or before the end of the measurement period."""
        return Timeframe(start=EARLIEST, end=self.period.end)

    # ----- conditions -----

    def conditions(self, match: Q, window: Timeframe):
        """Committed conditions matching ``match`` whose prevalence period overlaps ``window``."""
        return (
            Condition.objects.for_patient(self.patient_id)
            .committed()
            .filter(match)
            .filter(Q(onset_date__isnull=True) | Q(onset_date__lte=window.end.date()))
            .filter(
                Q(resolution_date__isnull=True) | Q(resolution_date__gte=window.start.date())
            )
            .distinct()
        )

    def has_condition(self, value_set: type[ValueSet], window: Timeframe) -> bool:
        """A condition in ``value_set`` whose prevalence period overlaps ``window``."""
        return self.conditions(coding_filter(value_set), window).exists()

    def has_condition_starting_by(self, match: Q, end: arrow.Arrow) -> bool:
        """A committed condition matching ``match`` with an onset on or before ``end``."""
        return (
            Condition.objects.for_patient(self.patient_id)
            .committed()
            .filter(match)
            .filter(Q(onset_date__isnull=True) | Q(onset_date__lte=end.date()))
            .exists()
        )

    # ----- encounters -----

    def encounters(self, codes: set[str], window: Timeframe):
        """Billing line items carrying one of ``codes`` within ``window``."""
        return BillingLineItem.objects.filter(patient__id=self.patient_id, cpt__in=codes).within(
            window
        )

    def has_encounter(self, value_set: type[ValueSet], window: Timeframe) -> bool:
        """A billing line item with a CPT or HCPCS code in ``value_set`` within ``window``."""
        return self.encounters(billing_codes(value_set), window).exists()

    def count_visits(self, codes: set[str], window: Timeframe) -> int:
        """Distinct notes billing one of ``codes`` within ``window``; a visit can bill several lines."""
        return self.encounters(codes, window).values("note").distinct().count()

    # ----- interventions and procedures -----

    def has_intervention(self, value_set: type[ValueSet], window: Timeframe) -> bool:
        """A committed instruction or procedure coded in ``value_set`` within ``window``."""
        dated = Q(note__datetime_of_service__range=(window.start.datetime, window.end.datetime))
        match = coding_filter(value_set)
        return (
            Instruction.objects.for_patient(self.patient_id).committed().filter(match).filter(dated)
        ).exists() or (
            Procedure.objects.for_patient(self.patient_id).committed().filter(match).filter(dated)
        ).exists()

    def has_procedure_by(self, value_set: type[ValueSet], end: arrow.Arrow) -> bool:
        """A procedure, or a surgical history condition, coded in ``value_set`` on or before ``end``."""
        match = coding_filter(value_set)
        performed = (
            Procedure.objects.for_patient(self.patient_id)
            .committed()
            .filter(match)
            .filter(note__datetime_of_service__lte=end.datetime)
        )
        return performed.exists() or self.has_condition_starting_by(match, end)

    def procedure_dates(self, value_set: type[ValueSet], window: Timeframe) -> list[arrow.Arrow]:
        """Dates of committed procedures coded in ``value_set`` within ``window``."""
        return [
            arrow.get(when)
            for when in Procedure.objects.for_patient(self.patient_id)
            .committed()
            .filter(coding_filter(value_set))
            .filter(note__datetime_of_service__range=(window.start.datetime, window.end.datetime))
            .values_list("note__datetime_of_service", flat=True)
        ]

    # ----- medications -----

    def has_active_medication(self, value_set: type[ValueSet], window: Timeframe) -> bool:
        """A committed medication in ``value_set`` whose active period overlaps ``window``."""
        return (
            Medication.objects.for_patient(self.patient_id)
            .committed()
            .find(value_set)
            .filter(Q(start_date__isnull=True) | Q(start_date__lte=window.end.datetime))
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=window.start.datetime))
            .exists()
        )

    def medication_start_dates(self, value_set: type[ValueSet], window: Timeframe) -> list[arrow.Arrow]:
        """Start dates of committed medications in ``value_set`` that started within ``window``."""
        return [
            arrow.get(when)
            for when in Medication.objects.for_patient(self.patient_id)
            .committed()
            .find(value_set)
            .filter(start_date__range=(window.start.datetime, window.end.datetime))
            .values_list("start_date", flat=True)
        ]

    # ----- laboratory tests -----

    def lab_results(self, match: Q, window: Timeframe) -> list[tuple[arrow.Arrow, str]]:
        """``(report date, result text)`` for lab values matching ``match`` in ``window``.

        Callers decide what counts as a result: ``parse_number`` for a numeric one, a
        non-empty text for any result at all.
        """
        rows = (
            LabValue.objects.filter(match)
            .filter(
                report__patient__id=self.patient_id,
                report__junked=False,
                report__original_date__range=(window.start.datetime, window.end.datetime),
            )
            .distinct()
            .values_list("report__original_date", "value")
        )
        return [(arrow.get(when), str(value or "").strip()) for when, value in rows]

    # ----- reports -----

    def report_dates(
        self, reports, value_set: type[ValueSet], window: Timeframe
    ) -> list[arrow.Arrow]:
        """``original_date`` of the patient's ``reports`` (imaging or referral) coded in ``value_set``."""
        return [
            arrow.get(when)
            for when in reports.filter(coding_filter(value_set))
            .filter(
                patient__id=self.patient_id,
                junked=False,
                original_date__range=(window.start.date(), window.end.date()),
            )
            .distinct()
            .values_list("original_date", flat=True)
        ]

    # ----- assessments -----

    def assessment_results(self, question_code: str, window: Timeframe) -> list[tuple[arrow.Arrow, str]]:
        """``(when, result code)`` for each answer to the coded assessment within ``window``.

        Reads committed questionnaire answers to a question coded ``question_code`` and
        observations coded ``question_code`` with a value coding.
        """
        start, end = window.start.datetime, window.end.datetime
        answers = (
            InterviewQuestionResponse.objects.filter(
                interview__patient__id=self.patient_id,
                interview__committer__isnull=False,
                interview__entered_in_error__isnull=True,
                interview__deleted=False,
                question__code=question_code,
                interview__created__range=(start, end),
            )
            .exclude(response_option__isnull=True)
            .values_list("interview__created", "response_option__code")
        )
        observations = (
            Observation.objects.for_patient(self.patient_id)
            .committed()
            .filter(codings__code=question_code, effective_datetime__range=(start, end))
            .values_list("effective_datetime", "value_codings__code")
        )
        results = [(arrow.get(when), code) for when, code in answers]
        results.extend((arrow.get(when), code) for when, code in observations if code)
        return results

    def has_assessment_result(self, question_code: str, results: set[str], window: Timeframe) -> bool:
        """An answer to the coded assessment within ``window`` whose result is in ``results``."""
        return any(code in results for _, code in self.assessment_results(question_code, window))

    # ----- HospiceQDM 7.0: "Has Hospice Services" -----

    def has_hospice_services(self) -> bool:
        """Hospice care for any part of the measurement period."""
        return (
            self.has_encounter(HospiceEncounter, self.period)
            or self.has_assessment_result(HOSPICE_CARE_ASSESSMENT, {YES}, self.period)
            or self.has_intervention(HospiceCareAmbulatory, self.period)
            or self.has_condition(HospiceDiagnosis, self.period)
        )

    # ----- PalliativeCareQDM 6.0: "Has Palliative Care In The Measurement Period" -----

    def has_palliative_care(self) -> bool:
        """Palliative care for any part of the measurement period."""
        return (
            bool(self.assessment_results(PALLIATIVE_CARE_ASSESSMENT, self.period))
            or self.has_condition(PalliativeCareDiagnosis, self.period)
            or self.has_encounter(PalliativeCareEncounter, self.period)
            or self.has_intervention(PalliativeCareIntervention, self.period)
        )

    # ----- AdvancedIllnessandFrailtyQDM 11.0 -----

    def is_66_or_older_living_long_term_in_nursing_home(self) -> bool:
        """Age 66+ whose most recent housing status, on or before the period end, is a nursing home."""
        if self.age < 66:
            return False
        results = sorted(self.assessment_results(HOUSING_STATUS, self.through_period_end()))
        return bool(results) and results[-1][1] == LIVES_IN_NURSING_HOME

    def has_criteria_indicating_frailty(self) -> bool:
        """A frailty device, diagnosis, encounter, or symptom during the measurement period."""
        return (
            self.has_assessment_result(MEDICAL_EQUIPMENT_USED, codes_in(FrailtyDevice), self.period)
            or self.has_condition(FrailtyDiagnosis, self.period)
            or self.has_encounter(FrailtyEncounter, self.period)
            or self.has_condition(FrailtySymptom, self.period)
        )

    def is_66_or_older_with_advanced_illness_and_frailty(self) -> bool:
        """Age 66+ with frailty plus an advanced illness or dementia medication in the past two years."""
        if self.age < 66 or not self.has_criteria_indicating_frailty():
            return False
        window = self.before_and_during(years=1)
        return self.has_condition(AdvancedIllness, window) or self.has_active_medication(
            DementiaMedications, window
        )

    # ----- combined -----

    def excluded(self) -> bool:
        """Hospice, palliative care, 66+ in a nursing home, or 66+ with frailty and advanced illness."""
        return (
            self.has_hospice_services()
            or self.is_66_or_older_living_long_term_in_nursing_home()
            or self.is_66_or_older_with_advanced_illness_and_frailty()
            or self.has_palliative_care()
        )
