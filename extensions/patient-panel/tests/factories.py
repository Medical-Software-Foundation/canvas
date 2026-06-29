import factory
from canvas_sdk.test_utils.factories import PatientFactory

from patient_panel.models import PatientPanelStats


class PatientPanelStatsFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatientPanelStats

    patient = factory.SubFactory(PatientFactory)
    last_visit_dt = None
    next_visit_dt = None
    room_number = ""
    tasks_open_count = 0
    gaps_due_count = 0
    updated = factory.LazyFunction(lambda: __import__("arrow").utcnow().datetime)
