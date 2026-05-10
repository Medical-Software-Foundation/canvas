from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    ForeignKey,
    TextField,
    UniqueConstraint,
)

from patient_tags.models.label import Label


class LabelRule(CustomModel):
    """A rule applied when a label is manually assigned to a patient.

    `trigger_label` is the label whose assignment fires the rule.
    `action` is one of "auto_assign" / "auto_remove" (see constants.py).
    `target_label` is the label that gets assigned or removed by the rule.

    Rules fire only on manual assignment and run a single pass — labels added
    by rule cascades do NOT re-trigger rules. Conflict policy: if the same
    target is both auto_assign'd and auto_remove'd by overlapping rules in a
    single save, auto_remove wins.
    """

    trigger_label = ForeignKey(
        Label,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="rules_as_trigger",
    )
    action = TextField()
    target_label = ForeignKey(
        Label,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="rules_as_target",
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["trigger_label", "action", "target_label"],
                name="unique_label_rule",
            ),
        ]
