"""One patient on one medication under one class, and the steps scheduled for them."""

from __future__ import annotations

from django.db.models import (
    CASCADE,
    DO_NOTHING,
    CharField,
    DateField,
    DateTimeField,
    ForeignKey,
    IntegerField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel

from medication_followup_protocol.models.program import MedicationClass, ProgramStep
from medication_followup_protocol.models.proxy import PatientProxy, StaffProxy


class EnrollmentStatus:
    """The three states an enrolment can be in."""

    ACTIVE = "active"
    STOPPED = "stopped"
    COMPLETED = "completed"

    CHOICES = [(ACTIVE, "Running"), (STOPPED, "Stopped"), (COMPLETED, "Completed")]


class StepStatus:
    """The four states a scheduled step can end in. Pending is the only one it starts in."""

    PENDING = "pending"
    FIRED = "fired"
    SKIPPED = "skipped"
    FAILED = "failed"

    CHOICES = [
        (PENDING, "Not yet due"),
        (FIRED, "Sent"),
        (SKIPPED, "Skipped"),
        (FAILED, "Not delivered"),
    ]

    #: A step has left pending once it reaches any of these.
    SETTLED = frozenset({FIRED, SKIPPED, FAILED})


class Enrollment(CustomModel):
    """One patient on one medication under one class."""

    created = DateTimeField(auto_now_add=True)
    modified = DateTimeField(auto_now=True)

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__enrollments",
    )
    medication_class = ForeignKey(
        MedicationClass,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="enrollments",
    )
    medication_label = TextField(default="", blank=True)
    prescription_id = CharField(max_length=64, null=True, blank=True)

    # Who a message went out from at enrolment time. Nothing reads this any more, because
    # a fired step now resolves its own sender off the medication class, live, rather than
    # carrying a name copied here that outlives the staff member it named. Nullable
    # because a fresh enrolment writes none, and the field stays only so existing rows
    # keep the value they were written with.
    sender_staff = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__sent_enrollments",
        null=True,
        blank=True,
    )
    prescriber_staff = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__prescribed_enrollments",
    )

    start_date = DateField()

    # The note the program was started from, kept so the enrolled patients page can carry a
    # reader straight to it. The database id rather than the public key, because the chart's
    # own permalink is read as a note primary key and handing it a key scrolls to nothing.
    # Null on every enrolment written before this field existed, and the link is left off
    # rather than guessed for those.
    start_note_dbid = IntegerField(null=True, blank=True)

    recheck_note_type_id = CharField(max_length=64, default="", blank=True)
    recheck_booked_appointment_id = CharField(max_length=64, null=True, blank=True)

    status = CharField(max_length=16, choices=EnrollmentStatus.CHOICES, default=EnrollmentStatus.ACTIVE)
    stopped_reason = TextField(default="", blank=True)
    stopped_by = CharField(max_length=64, null=True, blank=True)

    # The key services/banner.py applies and removes this enrolment's own chart banner
    # under. Minted once when the enrolment is created and never reused, even by a
    # later enrolment for the same patient, which is what lets one program stopping
    # remove exactly its own banner while every other running enrolment's banner for
    # the same patient is left standing.
    banner_key = TextField(default="", blank=True)

    def __str__(self) -> str:
        return f"{self.medication_label} for patient {self.patient_id}"


class EnrolledStep(CustomModel):
    """One step of one enrolment, its copied timing and its outcome.

    The timing and the shape are copied at enrolment and the content is read live
    through program_step. That split is what makes an edit to a step's wording reach a
    running enrolment while an edit to its timing does not.
    """

    created = DateTimeField(auto_now_add=True)
    modified = DateTimeField(auto_now=True)

    enrollment = ForeignKey(
        Enrollment,
        to_field="dbid",
        on_delete=CASCADE,
        related_name="steps",
    )
    program_step = ForeignKey(
        ProgramStep,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="enrolled_steps",
    )

    sequence = IntegerField(default=0)
    day_offset = IntegerField(default=0)
    kind = CharField(max_length=16)
    condition = CharField(max_length=64, null=True, blank=True)
    due_date = DateField()

    status = CharField(max_length=16, choices=StepStatus.CHOICES, default=StepStatus.PENDING)
    fired_at = DateTimeField(null=True, blank=True)
    failure_reason = TextField(default="", blank=True)
    message_id = CharField(max_length=64, null=True, blank=True)
    interview_id = CharField(max_length=64, null=True, blank=True)
    # Which staff member this step actually went out as, resolved and recorded at fire
    # time. The sender is no longer copied onto the enrolment up front, so this is what
    # keeps the history honest once the class's own sender changes or is cleared.
    sent_as_staff_id = CharField(max_length=64, default="", blank=True)

    class Meta:
        ordering = ["day_offset", "sequence"]

    def __str__(self) -> str:
        return f"day {self.day_offset}, {self.kind}, {self.status}"
