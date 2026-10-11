"""Who clicked Resend on the dashboard."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, TextField, UniqueConstraint

from failed_fax_dashboard.models.proxies import NoteProxy, StaffProxy


class FaxResend(CustomModel):
    """One click of Resend: the note, the number (E.164), the staff member, and the time.

    Canvas sends the fax as Canvas Bot, so this row is how the plugin later credits the
    person who clicked.

    ``from_fax_number`` is the number of the row the resend was made from. It differs from
    ``fax_number`` when staff corrected the number, so the new attempt still belongs to the
    original row. Resends saved before the field existed read it as empty (None).

    ``claim`` is ``"{failed send id}:{n}"``, where n counts the earlier resends of that
    send. It is unique, so two clicks at the same instant can't both resend: the second
    one's claim clashes. Empty (None) on resends saved before the field existed.
    """

    note: ForeignKey = ForeignKey(NoteProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="fax_resends")
    staff: ForeignKey = ForeignKey(StaffProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="fax_resends")
    fax_number: TextField = TextField()
    resent_at: DateTimeField = DateTimeField()
    from_fax_number: TextField = TextField(default="", null=True)
    claim: TextField = TextField(null=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["claim"], name="uq_faxresend_claim"),
        ]
