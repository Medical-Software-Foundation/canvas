import json

from canvas_sdk.v1.data.staff import Staff

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.task.task import AddTask
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.lab import LabOrder
from logger import log


class Protocol(BaseProtocol):
    """This protocol will create a Task command in response to a Lab Order Created event."""

    RESPONDS_TO = EventType.Name(EventType.LAB_ORDER_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """This method gets called when an event of the type RESPONDS_TO is fired."""

        patient_id = self.context["patient"]["id"]

        staff_name = self.context["fields"]["ordering_provider"]["value"]
        assignee_id = Staff.objects.get(dbid=staff_name).id

        effect = AddTask(
            patient_id=patient_id,
            assignee_id=assignee_id,
            title="Follow up with patient regarding lab order",
        )
        return [effect.apply()]
