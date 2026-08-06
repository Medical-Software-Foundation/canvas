from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DateTimeField, Index, TextField


class CoSignAddendum(CustomModel):
    note_id = TextField()
    supervisor_id = TextField()
    supervisor_name = TextField(default="")
    addendum_text = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["note_id", "created_at"]),
        ]
