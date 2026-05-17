from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
)

from clinical_pathways.models.pathway import Pathway


class Segment(CustomModel):
    """An ordered block of questions within a pathway.

    A pathway has one entry segment (is_entry=True). Branching rules on
    the preceding segment's responses determine which segment comes next.
    The last segment in a branch has no outgoing branch rules; the runner
    presents the pathway recommendation on reaching such a segment after
    all its questions are answered.
    """

    pathway = ForeignKey(
        Pathway,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="segments",
    )
    title = TextField()
    display_order = IntegerField(default=0)
    is_entry = BooleanField(default=False)

    class Meta:
        indexes = [
            Index(fields=["pathway", "display_order"]),
            Index(fields=["is_entry"]),
        ]
