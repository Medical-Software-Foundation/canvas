# type: ignore
from typing import List

import arrow

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import LabRecommendation
from canvas_workflow_kit.value_set.medication_class_path2018 import AceInhibitors
from canvas_workflow_kit.value_set.specials import CMS134v6Dialysis
# flake8: noqa
from canvas_workflow_kit.value_set.v2018 import (
    Diabetes,
    DiabeticNephropathy,
    DialysisEducation,
    GlomerulonephritisAndNephroticSyndrome,
    HypertensiveChronicKidneyDisease,
    KidneyFailure,
    KidneyTransplant,
    Proteinuria,
    UrineProteinTests
)
from .diabetes_quality_measure import DiabetesQualityMeasure


class ClinicalQualityMeasure134v6(DiabetesQualityMeasure):
    """
    Diabetes: Medical Attention for Nephropathy

    Description: The percentage of patients 18-75 years of age with diabetes who had a nephropathy
    screening test or evidence of nephropathy during the measurement period

    Definition: None

    Rationale: As the seventh leading cause of death in the U.S., diabetes kills approximately
    75,000 people a year (CDC FastStats 2015). Diabetes is a group of diseases marked by high blood
    glucose levels, resulting from the body's inability to produce or use insulin (CDC Statistics
    2014, ADA Basics 2013). People with diabetes are at increased risk of serious health
    complications including vision loss, heart disease, stroke, kidney failure, amputation of toes,
    feet or legs, and premature death. (CDC Fact Sheet 2014).

    In 2012, diabetes cost the U.S. an estimated $245 billion: $176 billion in direct medical costs
    and $69 billion in reduced productivity. This is a 41 percent increase from the estimated $174
    billion spent on diabetes in 2007 (ADA Economic 2013).

    In 2011, diabetes accounted for 44% of new kidney failure cases. In the same year, 49,677
    diabetics started treatment for kidney failure and 228,924 people of all ages with kidney
    failure due to diabetes were living on chronic dialysis or with a kidney transplant (CDC
    Statistics, 2014).

    Guidance: Only patients with a diagnosis of Type 1 or Type 2 diabetes should be included in the
    denominator of this measure; patients with a diagnosis of secondary diabetes due to another
    condition should not be included

    More information: https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS134v6.html
    """

    class Meta:
        title = 'Diabetes: Medical Attention for Nephropathy'
        version = '2019-02-12v1'
        description = (
            'Patients 18-75 years of age with diabetes who have not had a nephropathy screening test '
            'in the last year or evidence of nephropathy.')
        information = 'https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS134v6.html'

        identifiers = ['CMS134v6']

        types = ['CQM']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]

        authors = [
            'National Committee for Quality Assurance',
        ]

        references = [
            'American Diabetes Association. Microvascular complications and foot care. Sec. 10. In Standards of Medical Care in Diabetes-2017. Diabetes Care 2017;40(Suppl. 1):S88-S98.',
            'American Diabetes Association. 2013. Diabetes Basics. www.diabetes.org/diabetes-basics/?loc=GlobalNavDB.',
            'American Diabetes Association (ADA). April 2013. Economic Costs of Diabetes in the U.S. in 2012. Diabetes Care. Vol. 36 no. 4 1033-46. http://care.diabetesjournals.org/content/36/4/1033.full.',
            'Centers for Disease Control and Prevention (CDC). 2014. National Diabetes Statistics Report. http://www.cdc.gov/diabetes/pdfs/data/2014-report-estimates-of-diabetes-and-its-burden-in-the-united-states.pdf',
            'Centers for Disease Control and Prevention (CDC). 2015. FastStats: Deaths and Mortality. www.cdc.gov/nchs/fastats/deaths.htm.',
            'Centers for Disease Control and Prevention. 2014. CDC Features. Diabetes Latest. www.cdc.gov/features/diabetesfactsheet/.',
            'Handelsman Y, Bloomgarden ZT, Grunberger G, Umpierrez G, Zimmerman RS, Bailey TS, et al. (2015) American Association of Clinical Endocrinologists and American College of Endocrinology-Clinical Practice Guidelines for Developing a Diabetes Mellitus Comprehensive Care Plan-2015. Endocr Pract 21 Suppl 1: 1-87.',
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
            ClinicalQualityMeasure.CHANGE_INSTRUCTION,
            ClinicalQualityMeasure.CHANGE_LAB_REPORT,
            ClinicalQualityMeasure.CHANGE_MEDICATION,
            ClinicalQualityMeasure.CHANGE_PATIENT,
            ClinicalQualityMeasure.CHANGE_REFERRAL_REPORT,
        ]

    @classmethod
    def enabled(cls) -> bool:
        return True

    message: str = None
    _due_in: int = -1

    DISMISSING_CONDITIONS = [
        (HypertensiveChronicKidneyDisease, 'Hypertensive Chronic Kidney Disease'),
        (KidneyFailure, 'Kidney Failure'),
        (GlomerulonephritisAndNephroticSyndrome, 'Glomerulonephritis and Nephrotic Syndrome'),
        (DiabeticNephropathy, 'Diabetic Nephropathy'),
        (Proteinuria, 'Proteinuria'),
    ]

    def in_denominator(self) -> bool:
        """
        Denominator: Equals Initial Population

        Exclusions: Exclude patients who were in hospice care during the measurement year

        Exceptions: None
        """
        if not self.in_initial_population():
            return False

        if self.patient.hospice_within(self.timeframe):
            return False

        return True

    def in_numerator(self) -> bool:
        """
        Numerator: Patients with a screening for nephropathy or evidence of nephropathy during the
        measurement period

        Exclusions: Not Applicable
        """
        self.message = None
        self._due_in = -1

        # VascularAccessForDialysis, DialysisServices and OtherServicesRelatedToDialysis
        #  replaced with CMS134v6Dialysis
        record = self.patient.referral_reports.find(CMS134v6Dialysis).within(self.timeframe).last()
        if record:
            self.message = '{name} has diabetes and had a Dialysis Related Service {date}'.format(
                name=self.patient.first_name,
                date=self.display_date(arrow.get(record['originalDate'])))
            return True

        # medication
        records = (self.patient.medications.find(AceInhibitors).intersects(
            self.timeframe, still_active=self.patient.active_only))
        if records:
            self.message = '{name} has diabetes and is under Ace Inhibitors medication'.format(
                name=self.patient.first_name)
            return True

        # conditions
        for (condition, label) in self.DISMISSING_CONDITIONS:
            records = (self.patient.conditions.find(condition).intersects(
                self.timeframe, still_active=self.patient.active_only))
            if records:
                self.message = '{name} has diabetes and has been diagnosed {label}'.format(
                    name=self.patient.first_name, label=label)
                return True

        records = (self.patient.conditions.find(KidneyTransplant).intersects(
            self.timeframe, still_active=self.patient.active_only))
        if records:
            self.message = '{name} has diabetes and had a Kidney Transplant'.format(
                name=self.patient.first_name)
            return True

        # instruction
        record = (self.patient.instructions.find(DialysisEducation).within(self.timeframe).last())
        if record:
            self.message = '{name} has diabetes and had an ESRD Monthly Outpatient Services {date}'.format(
                name=self.patient.first_name, date=self.display_date(arrow.get(record['noteTimestamp'])))
            return True

        # lab test
        record = self.patient.lab_reports.find(UrineProteinTests).within(self.timeframe).last()
        if record:
            on_date = arrow.get(record['originalDate'])
            self._due_in = (on_date.shift(days=self.timeframe.duration) - self.now).days
            self.message = '{name} has diabetes and a urine protein test was done {date}'.format(
                name=self.patient.first_name, date=self.display_date(on_date))
            return True

        return False

    def compute_results(self) -> ProtocolResult:
        """
        Clinical recommendation: American Diabetes Association (2017):

        Screening
        - At least once a year, quantitatively assess urinary albumin (eg, spot urinary albumin-to-
        creatinine ratio [UACR]) and estimated glomerular filtration rate (eGFR) in patients with
        type 1 diabetes duration of greater than or equal to 5 years in all patients with type 2
        diabetes, and in all patients with comorbid hypertension. (Level of evidence: B)

        Treatment
        - An angiotensin-converting enzyme (ACE) inhibitor or angiotensin receptor blocker (ARB) is
        not recommended for the primary prevention of diabetic kidney disease in patients with
        diabetes who have normal blood pressure, normal UACR (<30 mg/g), and normal estimated
        glomerular filtration rate. (Level of evidence: B)
        - Either an ACE inhibitor or ARB is suggested for the treatment of the nonpregnant patient
        with modestly elevated UACR (30-299 mg/day) (Level of evidence: C) and is strongly
        recommended for those with urinary albumin excretion >=300 mg/day. (Level of evidence: A)
        - When ACE inhibitors, ARBs, or diuretics are used, monitor serum creatinine and potassium
        levels for the development of increased creatinine or changes in potassium. (Level of
        evidence: E)
        - Continued monitoring of UACR in patients with albuminuria treated with an ACE inhibitor
        or ARBs is reasonable to assess progression of diabetic kidney disease. (Level of evidence:
        E)

        American Association of Clinical Endocrinologists (2015):
        - Beginning 5 years after diagnosis in patients with type 1 diabetes (if diagnosed before
        age 30) or at diagnosis in patients with type 2 diabetes and those with type 1 diabetes
        diagnosed after age 30, annual assessment of serum creatinine to determine the estimated
        glomerular filtration rate (eGFR) and urine albumin excretion rate (AER) should be
        performed to identify, stage, and monitor progression of diabetic nephropathy (Grade C;
        best evidence level 3).
        - Patients with nephropathy should be counseled regarding the need for optimal glycemic
        control, blood pressure control, dyslipidemia control, and smoking cessation (Grade B; best
        evidence level 2).
        - In addition, they should have routine monitoring of albuminuria, kidney function
        electrolytes, and lipids (Grade B; best evidence level 2).
        - Associated conditions such as anemia and bone and mineral disorders should be assessed as
        kidney function declines (Grade D; best evidence level 4).
        - Referral to a nephrologist is recommended well before the need for renal replacement
        therapy (Grade D; best evidence level 4).
        """
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(self.message)
                result.due_in = self._due_in
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    '{name} has diabetes and a urine microalbumin test'
                    ' is due to screen for nephropathy'.format(name=self.patient.first_name))
                result.add_recommendation(
                    LabRecommendation(
                        key='CMS134v6_RECOMMEND_URINE_TEST',
                        rank=1,
                        button='Order',
                        patient=self.patient,
                        condition=Diabetes,
                        lab=UrineProteinTests,
                        title='Order a urine microalbumin test'))
        else:
            result.due_in = self.first_due_in()

        return result
