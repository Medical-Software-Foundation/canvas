import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol


class Protocol(BaseProtocol):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_PORTAL__APPOINTMENT_CAN_BE_CANCELED)


    def compute(self) -> list[Effect]:
        return [Effect(type=EffectType.PATIENT_PORTAL__APPOINTMENT_IS_CANCELABLE, payload=json.dumps({"result": False}))]
