"""Who clicked Resend on the dashboard."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, TextField

from failed_fax_dashboard.models.proxies import NoteProxy, StaffProxy


class FaxResend(CustomModel):
    """One click of Resend: the note, the number (E.164), the staff member, and the time.

    Canvas sends the fax as Canvas Bot, so this row is how the plugin later credits the
    person who clicked.
    """

    note: ForeignKey = ForeignKey(NoteProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="fax_resends")
    staff: ForeignKey = ForeignKey(StaffProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="fax_resends")
    fax_number: TextField = TextField()
    resent_at: DateTimeField = DateTimeField()
