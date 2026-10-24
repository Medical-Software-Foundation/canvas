from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DateField, DateTimeField, Index, TextField


class CoSignRecord(CustomModel):
    # TextField not ForeignKey - FK to_field="dbid" + filter(fk__id=uuid) is broken in CustomModel
    note_id = TextField()
    supervisee_id = TextField()
    supervisor_id = TextField()
    task_id = TextField(default="")
    status = TextField(default="pending")
    selected_at = DateTimeField(auto_now_add=True)
    due_date = DateField(default=None)
    cosigned_at = DateTimeField(default=None)
    addendum_text = TextField(default="")

    class Meta:
        indexes = [
            Index(fields=["note_id"]),
            Index(fields=["supervisor_id", "status"]),
        ]
