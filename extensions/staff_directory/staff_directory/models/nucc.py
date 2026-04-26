from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DateTimeField, Index, TextField, UniqueConstraint


class NuccTaxonomyCode(CustomModel):
    """A row from the NUCC Healthcare Provider Taxonomy Code Set."""

    code = TextField()
    grouping = TextField()
    classification = TextField()
    specialization = TextField(default="")
    definition = TextField(default="")
    display_name = TextField()

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["code"], name="unique_nucc_code"),
        ]
        indexes = [
            Index(fields=["classification"]),
            Index(fields=["specialization"]),
            Index(fields=["display_name"]),
        ]
