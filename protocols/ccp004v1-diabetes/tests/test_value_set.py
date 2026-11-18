"""The protocol reads the 2027 Diabetes value set."""

from datetime import date

from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType
from canvas_sdk.test_utils.factories import CanvasUserFactory, PatientFactory
from canvas_sdk.v1.data.condition import Condition, ConditionCoding
from protocols.ccp004v1_diabetes import Ccp004v1

SNOMEDCT = "http://snomed.info/sct"


def test_counts_a_code_the_2027_value_set_added() -> None:
    """Glaucoma suspect due to type 2 diabetes, added to the value set after 2022, is a diagnosis."""
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
        condition=condition, system=SNOMEDCT, code="1003605004", display="1003605004"
    )
    request = EventRequest(type=EventType.CONDITION_CREATED, target=str(condition.id), context="{}")
    assert Ccp004v1(event=Event(request)).date_of_diagnosis == "2024-03-01"
