from django.db.models import BooleanField, Index, JSONField, TextField

from canvas_sdk.v1.data.base import CustomModel


class Instruction(CustomModel):
    """A reusable patient instruction in the library.

    coding_system: "SNOMED" or "UNSTRUCTURED"
    code: SNOMED code or the free-text instruction itself
    display: Human-readable label (SNOMED display or same as code for unstructured)
    comment: Optional default comment to include with the instruction
    tags: List of tag strings (e.g. ["Post-Visit", "Dietary"])
    active: Soft-delete flag
    """

    coding_system = TextField(default="UNSTRUCTURED")
    code = TextField()
    display = TextField()
    comment = TextField(default="")
    tags = JSONField(default=list)
    active = BooleanField(default=True)

    class Meta:
        indexes = [
            Index(fields=["active"]),
        ]
