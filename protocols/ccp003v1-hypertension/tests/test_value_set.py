"""The protocol reads the 2027 Diagnosis Of Hypertension value set."""

from datetime import date

from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType
from canvas_sdk.test_utils.factories import CanvasUserFactory, PatientFactory
from canvas_sdk.v1.data.condition import Condition, ConditionCoding
from protocols.ccp003v1_hypertension import Ccp003v1

SNOMEDCT = "http://snomed.info/sct"


def test_counts_a_code_the_2027_value_set_added() -> None:
    """Diastolic co-occurrent with systolic hypertension, added to the value set after 2022, is a diagnosis."""
    condition = Condition.objects.create(
        patient=PatientFactory.create(),
        deleted=False,
        committer=CanvasUserFactory.create(),
        onset_date=date(2024, 3, 1),
        resolution_date=date(9999, 12, 31),
        clinical_status="active",
        notes="",
        surgical=False,
    )
    ConditionCoding.objects.create(
        condition=condition, system=SNOMEDCT, code="762463000", display="762463000"
    )
    request = EventRequest(type=EventType.CONDITION_CREATED, target=str(condition.id), context="{}")
    assert Ccp003v1(event=Event(request)).date_of_diagnosis == "2024-03-01"
