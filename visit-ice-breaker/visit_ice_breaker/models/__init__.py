from canvas_sdk.v1.data.base import CustomModel
from django.db.models import Index, TextField, UniqueConstraint


class ShownQuestion(CustomModel):
    note_id: TextField = TextField()
    patient_id: TextField = TextField()
    question_text: TextField = TextField()
    category: TextField = TextField()

    class Meta:
        constraints = [
            UniqueConstraint(fields=["note_id"], name="uq_shown_question_note_id"),
        ]
        indexes = [
            Index(fields=["patient_id"]),
        ]
