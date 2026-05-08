"""Visit-type → room (RR staff) mapping.

One row per allowed (note_type_code, room_staff_key) pair. A note type with
zero rows requires no room.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField


class VisitTypeRoomMapping(CustomModel):
    note_type_code = CharField(max_length=128)
    room_staff_key = CharField(max_length=64)
