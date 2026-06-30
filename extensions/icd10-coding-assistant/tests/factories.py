"""Custom factories for icd10-coding-assistant tests."""

import datetime

import factory

from canvas_sdk.test_utils.factories.patient import PatientFactory
from canvas_sdk.test_utils.factories.user import CanvasUserFactory
from canvas_sdk.v1.data.condition import ClinicalStatus, Condition, ConditionCoding


class ConditionFactory(factory.django.DjangoModelFactory[Condition]):
    """Factory for creating test Condition records."""

    class Meta:
        model = Condition

    patient = factory.SubFactory(PatientFactory)
    committer = factory.SubFactory(CanvasUserFactory)
    entered_in_error = None
    deleted = False
    onset_date = datetime.date(2020, 1, 1)
    resolution_date = datetime.date(2025, 1, 1)
    clinical_status = ClinicalStatus.ACTIVE
    notes = ""
    surgical = False


class ConditionCodingFactory(factory.django.DjangoModelFactory[ConditionCoding]):
    """Factory for creating test ConditionCoding records."""

    class Meta:
        model = ConditionCoding

    condition = factory.SubFactory(ConditionFactory)
    system = "http://snomed.info/sct"
    display = "Test condition"
    code = "123456789"
