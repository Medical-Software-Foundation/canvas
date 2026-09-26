"""PracticeLabel, the practice's own editable label list, per Section 3 of SPEC.md."""

from __future__ import annotations

from django.db.models import TextField, UniqueConstraint

from canvas_sdk.v1.data.base import CustomModel


class PracticeLabel(CustomModel):
    name = TextField()

    class Meta:
        constraints = [UniqueConstraint(fields=["name"], name="uq_practicelabel_name")]
