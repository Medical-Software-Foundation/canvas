"""The catalog: one admin-curated, patient-facing resource link."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    Q,
    TextField,
    UniqueConstraint,
)

from patient_resources.constants import STATUS_ACTIVE
from patient_resources.models.proxies import StaffProxy


class PatientResource(CustomModel):
    """One entry in the resource library.

    Three DDL-pipeline facts shape this class, and all three are easy to forget:

    * The pipeline emits no NOT NULL constraints and no column defaults, so every
      ``default=`` below applies only when this code creates the row. Anything
      reading these columns has to tolerate ``None``.
    * It maps every text column to ``text`` regardless of ``choices`` or
      ``max_length``, so neither is declared -- they would imply an enforcement
      that does not exist. Length and vocabulary are checked in
      ``services/validation.py``.
    * The schema is append-only: ``ADD COLUMN IF NOT EXISTS`` is the only
      mutation it emits. There is no DROP COLUMN, no ALTER TYPE and no RENAME, so
      this shape cannot be revised after the first install.
    """

    title = TextField(default="")

    # TextField rather than URLField: URLField is not in the sandbox's import
    # allowlist for django.db.models, so importing it stops the plugin loading.
    # The validation URLField would have given us has to be explicit anyway,
    # because the DDL emits no constraints.
    url = TextField(default="")

    # Free text, one value per resource. The filter vocabulary is derived from
    # the labels actually in use rather than configured, so an empty library
    # yields an empty filter instead of a stale hardcoded list.
    label = TextField(default="")

    # A text status rather than `active = BooleanField()`. Because the DDL emits
    # no NOT NULL, a null boolean cannot be told apart from one that was never
    # filled in, and reading null as "active" would publish a malformed row to
    # patients. Every reader treats anything but STATUS_ACTIVE as not listable,
    # so a malformed row is hidden instead.
    status = TextField(default=STATUS_ACTIVE)

    created_by = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="patient_resources_created",
    )
    updated_by = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="patient_resources_updated",
    )

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        # Foreign key columns are indexed automatically and declaring a
        # single-field index or constraint on one raises, so only the non-key
        # access paths appear here.
        indexes = [
            Index(fields=["status", "title"], name="pr_resource_status_title"),
            Index(fields=["label"], name="pr_resource_label"),
        ]
        constraints = [
            # Partial unique constraints are supported: the DDL pipeline compiles
            # `condition` into a WHERE clause on a CREATE UNIQUE INDEX. Scoping it
            # to active rows means archiving a resource frees its title+label for
            # reuse instead of blocking it forever.
            #
            # Postgres text comparison is case-sensitive, so this catches only
            # exact repeats; services/catalog.py additionally rejects a
            # case-insensitive collision before insert.
            UniqueConstraint(
                fields=["title", "label"],
                condition=Q(status=STATUS_ACTIVE),
                name="pr_resource_unique_live_title_label",
            ),
        ]
