"""One resource, sent to one patient, at one moment."""

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

from patient_resources.models.proxies import PatientProxy, StaffProxy
from patient_resources.models.resource import PatientResource


class PatientResourceShare(CustomModel):
    """A record that a staff member gave a patient a resource.

    The portal renders the ``*_at_share`` snapshot rather than the live catalog
    row. A patient's list is a record of what their care team actually gave them,
    and it must not rewrite itself when an admin fixes a typo six months later.

    The live foreign key is kept anyway, for two reasons: the admin UI needs to
    answer "who has this?" before retiring a resource, and the portal query joins
    ``resource__status`` so that archiving a wrong or harmful link pulls it from
    every patient's list at once. Snapshot for history, join for retraction.

    As everywhere in this plugin, the DDL pipeline emits no NOT NULL and no
    column defaults, so every column here can be ``None`` on a row this code did
    not write, and the schema is append-only -- this shape cannot be revised
    after the first install.
    """

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="patient_resource_shares",
    )

    # Nullable because the DDL emits no NOT NULL: a row whose catalog entry was
    # removed out of band has to be readable, not a crash. Readers must tolerate
    # `share.resource is None`.
    resource = ForeignKey(
        PatientResource,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="shares",
    )

    shared_by = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="patient_resource_shares",
    )

    # Set explicitly by the service rather than auto_now_add: shares are written
    # with bulk_create and the response has to echo the timestamp, so it is
    # computed in Python where a test can pin it.
    shared_at = DateTimeField(null=True)

    # The frozen display snapshot. Written once, at share time, and never
    # updated. This is what the portal renders.
    title_at_share = TextField(default="")
    url_at_share = TextField(default="")
    label_at_share = TextField(default="")

    # Retraction. A withdrawn resource renders as a neutral notice rather than
    # silently disappearing -- a patient who was counselled on a handout should
    # not find their list quietly one item shorter.
    revoked_at = DateTimeField(null=True)
    revoked_reason = TextField(default="")

    # Stamped when the patient first loads their list. Drives the portal menu
    # badge. Patient-side read state, not send tracking.
    first_viewed_at = DateTimeField(null=True)

    class Meta:
        indexes = [
            # Composite, leading with the auto-indexed patient key column. A
            # single-field index on a foreign key raises, but a composite one
            # that merely starts with it is fine.
            Index(fields=["patient", "-shared_at"], name="pr_share_patient_recent"),
            Index(fields=["patient", "first_viewed_at"], name="pr_share_patient_unviewed"),
        ]
        constraints = [
            # Re-sharing a live resource is structurally impossible, so a double
            # click cannot put the same link in a patient's list twice. Scoped to
            # live shares so a revoked share does not block a deliberate re-send.
            UniqueConstraint(
                fields=["patient", "resource"],
                condition=Q(revoked_at__isnull=True),
                name="pr_share_unique_live_patient_resource",
            ),
        ]
