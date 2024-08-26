from typing import List

import arrow

from canvas_workflow_kit.patient_recordset import (
    AppointmentRecordSet,
    BillingLineItemRecordSet,
)
from canvas_workflow_kit.protocol import (
    CHANGE_TYPE,
    STATUS_DUE,
    STATUS_NOT_APPLICABLE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult,
)
from canvas_workflow_kit.value_set import ValueSet

DEFAULT_TIMEZONE = 'America/Phoenix'


class AnnualAssessment(ValueSet):
    VALUE_SET_NAME = 'Annual Visit'
    CPT = {
        '99201',
        '99202',
        '99203',
        '99204',
        '99205',
        '99214',
        '99215',
        '99341',
        '99342',
        '99344',
        '99345',
        '99347',
        '99348',
        '99349',
        '99350',
        '99441',
        '99442',
        '99443',
    }


class AnnualAssessmentEngagement(ClinicalQualityMeasure):
    class Meta:
        title = 'Engagement: Annual Assessment'
        description = ()
        version = '1.0.0'
        information = 'https://canvasmedical.com/gallery'  # Replace with the link to your protocol.
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [
            CHANGE_TYPE.APPOINTMENT,
            CHANGE_TYPE.BILLING_LINE_ITEM,
        ]
        references: List[str] = []

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

    def _get_annual_assessments_between(
        self, start: arrow.Arrow, end: arrow.Arrow
    ) -> BillingLineItemRecordSet:
        '''
        Get annual assessments billed in the given time range.

        Args:
            start (arrow.Arrow): The start date of the time range.
            end (arrow.Arrow): The end date of the time range.

        Returns:
            BillingLineItemRecordSet: The annual assessments billed in the given time range.
        '''
        return self.patient.billing_line_items.find(AnnualAssessment).after(start).before(end)

    def _get_appointments_between(
        self, start: arrow.Arrow, end: arrow.Arrow
    ) -> AppointmentRecordSet:
        '''Get uncanceled appointments with check-ins in the given time range.

        Args:
            start (arrow.Arrow): The start time of the range.
            end (arrow.Arrow): The end time of the range.

        Returns:
            AppointmentRecordSet: A set of appointments within the specified time range.
        '''
        valid_appointments = [
            appointment
            for appointment in (a for a in self.patient.appointments if a['status'] != 'cancelled')
            if any(
                start <= arrow.get(state_update['created']) <= end
                for state_update in appointment['stateHistory']
                if state_update['state'] == 'CVD'
            )
        ]
        return AppointmentRecordSet(valid_appointments)

    def in_denominator(self) -> bool:
        '''
        Check for patients who have had an annual assessment last calendar year.

        Returns:
            bool: True if the patient satisfies the above condition, False otherwise.
        '''
        last_year_start = arrow.get(self._now.year - 1, 1, 1)
        last_year_end = arrow.get(self._now.year - 1, 12, 31)
        return bool(self._get_annual_assessments_between(last_year_start, last_year_end))

    def in_numerator(self) -> bool:
        '''
        Check for patients who either:
            - have had an annual assessment in the past 6 months
            - have had an appointment or assessment this calendar year.

        If it is within the first 6 months of the year, the calendar year and the past 6 months
        may not overlap.

        Returns:
            bool: True if the patient satisfies the above condition, False otherwise.
        '''
        this_year_start = arrow.get(self._now.year, 1, 1)
        six_months_ago = self._now.shift(months=-6)
        return (
            self._get_annual_assessments_between(six_months_ago, self._now)
            or self._get_annual_assessments_between(six_months_ago, self._now)
            or self._get_appointments_between(this_year_start, self._now)
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has had an annual assessment in the past 6 months.')
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative('Patient needs an annual assessment.')
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Patient does not need an annual assessment.')

        return result
