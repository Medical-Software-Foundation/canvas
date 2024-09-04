from typing import Dict, List, Optional

import arrow

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    CONTEXT_REPORT,
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ExternallyAwareClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import (
    ImagingRecommendation,
    LabRecommendation,
    ReferRecommendation
)
from canvas_workflow_kit.timeframe import Timeframe
# @canvas-adr-0006
from canvas_workflow_kit.value_set.specials import CMS130v6CtColonography
# flake8: noqa
from canvas_workflow_kit.value_set.v2018 import (
    AnnualWellnessVisit,
    Colonoscopy,
    CtColonography,
    DischargedToHealthCareFacilityForHospiceCare,
    DischargedToHomeForHospiceCare,
    EncounterInpatient,
    Ethnicity,
    FaceToFaceInteraction,
    FecalOccultBloodTestFobt,
    FitDna,
    FlexibleSigmoidoscopy,
    HomeHealthcareServices,
    HospiceCareAmbulatory,
    MalignantNeoplasmOfColon,
    OfficeVisit,
    OncAdministrativeSex,
    Payer,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    Race,
    TotalColectomy
)


class ClinicalQualityMeasure130v6(ExternallyAwareClinicalQualityMeasure, ClinicalQualityMeasure):
    """
    Colorectal Cancer Screening

    Description: Percentage of adults 50-75 years of age who had appropriate screening for
    colorectal cancer

    Definition: None

    Rationale: An estimated 132,700 men and women were diagnosed with colon or rectal cancer in
    2015. In the same year, 49,700 were estimated to have died from the disease, making colorectal
    cancer the third leading cause of cancer death in the United States (National Cancer Institute
    2015, American Cancer Society 2015).

    Screening for colorectal cancer is extremely important as there are no signs or symptoms of the
    cancer in the early stages. If the disease is caught in its earliest stages, it has a five-year
    survival rate of 90%; however, the disease is often not caught this early. While screening is
    extremely effective in detecting colorectal cancer, it remains underutilized (American Cancer
    Society 2015).

    The U.S. Preventive Services Task Force has identified fecal occult blood tests, colonoscopy,
    and flexible sigmoidoscopy as effective screening methods (United States Preventive Services
    Task Force 2008).

    Guidance: Patient self-report for procedures as well as diagnostic studies should be recorded
    in "Procedure, Performed" template or "Diagnostic Study, Performed" template in QRDA-1. Patient
    self-report is not allowed for laboratory tests.

    More information: https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS130v6.html
    """

    class Meta:
        title = 'Colorectal Cancer Screening'
        version = '2020-02-24v1'
        default_display_interval_in_days = 365 * 10

        description = (
            'Adults 50-75 years of age who have not had appropriate screening for colorectal cancer.'
        )
        information = 'https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS130v6.html'

        identifiers = ['CMS130v6']

        types = ['CQM']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]

        authors = [
            'National Committee for Quality Assurance',
        ]

        references = [
            'American Cancer Society. 2015. "Cancer Prevention & Early Detection Facts & Figures 2015-2016." Atlanta: American Cancer Society.',
            'National Cancer Institute. 2015. "SEER Stat Fact Sheets: Colon and Rectum Cancer." Bethesda, MD, http://seer.cancer.gov/statfacts/html/colorect.html',
            'U.S. Preventive Services Task Force (USPSTF). 2008. "Screening for colorectal cancer: U.S. Preventive Services Task Force recommendation statement." Ann Intern Med 149(9):627-37.',
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
            ClinicalQualityMeasure.CHANGE_IMAGING_REPORT,
            ClinicalQualityMeasure.CHANGE_LAB_REPORT,
            ClinicalQualityMeasure.CHANGE_PATIENT,
            ClinicalQualityMeasure.CHANGE_REFERRAL_REPORT,
        ]

    AGE_RANGE_START = 50
    AGE_RANGE_END = 75
    _last_exam = None

    def first_due_in(self) -> Optional[int]:
        if self.patient.age_at(
                self.timeframe.end) < self.AGE_RANGE_START and not self.had_colon_exclusion():
            return (
                self.patient.birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.end).days
        return None

    def had_colon_exclusion(self) -> bool:
        # Past Surgical History: Total abdominal colectomy with proctectomy and ileostomy (procedure)
        if self.patient.conditions.find(TotalColectomy | MalignantNeoplasmOfColon).intersects(
                self.timeframe, still_active=self.patient.active_only):
            return True
        return False

    def in_initial_population(self) -> bool:
        """
        Initial population: Patients 50-75 years of age with a visit during the measurement period
        """
        return (self.patient.age_at_between(self.timeframe.end,
                                            self.AGE_RANGE_START,
                                            self.AGE_RANGE_END) and
                (self.patient.has_visit_within(self.timeframe,
                                               (OfficeVisit |
                                                PreventiveCareServicesEstablishedOfficeVisit18AndUp |
                                                PreventiveCareServicesInitialOfficeVisit18AndUp |
                                                HomeHealthcareServices |
                                                AnnualWellnessVisit))
                 if self.context == CONTEXT_REPORT else True))  # yapf: disable

    def in_denominator(self) -> bool:
        """
        Denominator: Equals Initial Population

        Exclusions: Patients with a diagnosis or past history of total colectomy or colorectal
        cancer.

        Exclude patients who were in hospice care during the measurement year.

        Exceptions: None
        """
        if not self.in_initial_population():
            return False

        if self.patient.hospice_within(self.timeframe):
            return False

        if self.had_colon_exclusion():
            return False

        return True

    def in_numerator(self) -> bool:
        """
        Numerator: Patients with one or more screenings for colorectal cancer. Appropriate
        screenings are defined by any one of the following criteria:
        - Fecal occult blood test (FOBT) during the measurement period
        - Flexible sigmoidoscopy during the measurement period or the four years prior to the
        measurement period
        - Colonoscopy during the measurement period or the nine years prior to the measurement
        period
        - FIT-DNA during the measurement period or the two years prior to the measurement period
        - CT Colonography during the measurement period or the four years prior to the measurement
        period

        Exclusions: Not Applicable
        """
        self._last_exam = None
        period = Timeframe(start=self.timeframe.start, end=self.timeframe.end)
        record = self.patient.lab_reports.find(FecalOccultBloodTestFobt).within(period).last()
        if record:
            self._last_exam = {
                'date': record['originalDate'],
                'what': 'FOBT',
                'days': period.duration,
            }
            return True

        if not self.period_adjustment:
            period.start = self.timeframe.end.shift(years=-3)
        record = self.patient.lab_reports.find(FitDna).within(period).last()
        if record:
            self._last_exam = {
                'date': record['originalDate'],
                'what': 'FIT-DNA',
                'days': period.duration,
            }
            return True

        if not self.period_adjustment:
            period.start = self.timeframe.end.shift(years=-5)
        record = (self.patient.referral_reports.find(FlexibleSigmoidoscopy).within(period).last()
                  or
                  self.patient.imaging_reports.find(FlexibleSigmoidoscopy).within(period).last())
        if record:
            self._last_exam = {
                'date': record['originalDate'],
                'what': 'Flexible sigmoidoscopy',
                'days': period.duration,
            }
            return True

        if not self.period_adjustment:
            period.start = self.timeframe.end.shift(years=-5)
        record = (self.patient.referral_reports.find(CtColonography |
                                                     CMS130v6CtColonography).within(period).last()
                  or
                  self.patient.imaging_reports.find(CtColonography |
                                                    CMS130v6CtColonography).within(period).last())
        if record:
            self._last_exam = {
                'date': record['originalDate'],
                'what': 'CT Colonography',
                'days': period.duration,
            }
            return True

        if not self.period_adjustment:
            period.start = self.timeframe.end.shift(years=-10)
        record = (self.patient.referral_reports.find(Colonoscopy).within(period).last() or
                  self.patient.imaging_reports.find(Colonoscopy).within(period).last())
        if record:
            self._last_exam = {
                'date': record['originalDate'],
                'what': 'Colonoscopy',
                'days': period.duration,
            }
            return True

        return False

    def recent_exam_context(self) -> str:
        recent_related_exam: Dict = {}

        record = (self.patient.referral_reports.find(Colonoscopy).last() or
                  self.patient.imaging_reports.find(Colonoscopy).last())
        if record:
            recent_related_exam = {
                'date': record['originalDate'],
                'what': 'Colonoscopy',
            }

        if not recent_related_exam:
            record = (
                self.patient.referral_reports.find(CtColonography | CMS130v6CtColonography).last()
                or
                self.patient.imaging_reports.find(CtColonography | CMS130v6CtColonography).last())
            if record:
                recent_related_exam = {
                    'date': record['originalDate'],
                    'what': 'CT Colonography',
                }

        if not recent_related_exam:
            record = (self.patient.referral_reports.find(FlexibleSigmoidoscopy).last() or
                      self.patient.imaging_reports.find(FlexibleSigmoidoscopy).last())
            if record:
                recent_related_exam = {
                    'date': record['originalDate'],
                    'what': 'Flexible sigmoidoscopy',
                }

        if not recent_related_exam:
            record = self.patient.lab_reports.find(FitDna).last()
            if record:
                recent_related_exam = {
                    'date': record['originalDate'],
                    'what': 'FIT-DNA',
                }

        if not recent_related_exam:
            record = self.patient.lab_reports.find(FecalOccultBloodTestFobt).last()
            if record:
                recent_related_exam = {
                    'date': record['originalDate'],
                    'what': 'FOBT',
                }

        if recent_related_exam:
            last_date = arrow.get(recent_related_exam['date'])
            return 'Last {what} done {date}.'.format(
                what=recent_related_exam['what'], date=self.display_date(last_date))
        else:
            return 'No relevant exams found.'

    def craft_satisfied_result(self):
        result = ProtocolResult()

        last_date = arrow.get(self._last_exam['date'])

        result.due_in = (last_date.shift(days=self._last_exam['days']) - self.now).days
        result.status = STATUS_SATISFIED
        result.add_narrative('{name} had a {what} {date}.'.format(
            name=self.patient.first_name,
            what=self._last_exam['what'],
            date=self.display_date(last_date)))

        return result

    def craft_unsatisfied_result(self):
        """
        Clinical recommendation: The United States Preventive Services Task Force (2008):

        [1] The USPSTF recommends screening for colorectal cancer using fecal occult blood testing,
        sigmoidoscopy, or colonoscopy in adults, beginning at age 50 years and continuing until age
        75 years (A recommendation).
        [2] The USPSTF concludes that the evidence is insufficient to assess the benefits and harms
        of computed tomographic (CT) colonography and fecal DNA testing as screening modalities for
        colorectal cancer (I statement).
        """
        result = ProtocolResult()

        result.due_in = -1
        result.status = STATUS_DUE

        result.add_narrative('{name} is due for a Colorectal Cancer Screening.'.format(
            name=self.patient.first_name))
        result.add_narrative(self.recent_exam_context())
        result.add_narrative(self.screening_interval_context())

        context = {
            'conditions': [[{
                'code': 'Z1211',
                'system': 'ICD-10',
                'display': 'Encounter for screening for malignant neoplasm of colon',
            }]]
        }

        result.add_recommendation(
            LabRecommendation(
                key='CMS130v6_RECOMMEND_FOBT',
                rank=1,
                button='Order',
                patient=self.patient,
                condition=MalignantNeoplasmOfColon,
                context=context,
                lab=FecalOccultBloodTestFobt,
                title='Order a FOBT'))

        result.add_recommendation(
            LabRecommendation(
                key='CMS130v6_RECOMMEND_FITDNA',
                rank=2,
                button='Order',
                patient=self.patient,
                condition=MalignantNeoplasmOfColon,
                context=context,
                lab=FitDna,
                title='Order a FIT-DNA'))

        result.add_recommendation(
            ReferRecommendation(
                key='CMS130v6_RECOMMEND_SIGMOIDOSCOPY',
                rank=3,
                button='Order',
                patient=self.patient,
                referral=FlexibleSigmoidoscopy,
                context={
                    **context, 'specialties': ['Gastroenterology', ]
                },
                title='Order a Flexible sigmoidoscopy'))

        result.add_recommendation(
            ImagingRecommendation(
                key='CMS130v6_RECOMMEND_COLONOGRAPHY',
                rank=4,
                button='Order',
                patient=self.patient,
                imaging=CtColonography,
                context={
                    **context, 'specialties': ['Radiology', ]
                },
                title='Order a CT Colonography'))

        result.add_recommendation(
            ReferRecommendation(
                key='CMS130v6_RECOMMEND_COLONOSCOPY',
                rank=5,
                button='Order',
                patient=self.patient,
                referral=Colonoscopy,
                context={
                    **context, 'specialties': ['Gastroenterology', ]
                },
                title='Order a Colonoscopy'))

        return result
