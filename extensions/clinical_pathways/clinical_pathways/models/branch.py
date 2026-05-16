from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    TextField,
)

from clinical_pathways.models.segment import Segment


class BranchRule(CustomModel):
    """Determines which segment follows a given segment.

    Evaluation model:
      - A segment may have zero or more BranchRule rows.
      - Each rule carries a `conditions` JSON blob (see services.branching).
      - Rules are evaluated in `priority` order (ascending); the first rule
        whose conditions are fully satisfied wins.
      - If no rule matches (or the segment has no rules), the pathway is
        complete and the runner presents the recommendation.

    Condition schema (list of clauses, all ANDed):
      [{"question_dbid": int, "operator": "eq"|"contains"|"gte"|"lte"|"in",
        "value": str | list[str]}]
    """

    from_segment = ForeignKey(
        Segment,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="outgoing_rules",
    )
    to_segment = ForeignKey(
        Segment,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="incoming_rules",
    )
    conditions = JSONField(default=list)
    priority = IntegerField(default=0)
    label = TextField(default="")

    class Meta:
        indexes = [
            Index(fields=["from_segment", "priority"]),
        ]
