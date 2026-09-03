"""The practice built side of a programme. A medication class and its timed steps."""

from __future__ import annotations

from django.db.models import (
    CASCADE,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    IntegerField,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel


class StepKind:
    """The three things a step can do. The vocabulary is closed."""

    MESSAGE = "message"
    QUESTIONNAIRE = "questionnaire"
    TASK = "task"

    CHOICES = [
        (MESSAGE, "Message the patient"),
        (QUESTIONNAIRE, "Questionnaire to the patient"),
        (TASK, "Task for a team or a person"),
    ]

    ALL = frozenset({MESSAGE, QUESTIONNAIRE, TASK})


class MedicationClass(CustomModel):
    """One practice defined medication class carrying a programme."""

    created = DateTimeField(auto_now_add=True)
    modified = DateTimeField(auto_now=True)

    name = TextField()
    description = TextField(default="", blank=True)
    active = BooleanField(default=True)
    # The NoteType that counts as the recheck for patients on this class. Held as an
    # identifier rather than a foreign key, because the target is a platform model and
    # nothing here needs to traverse to it.
    recheck_note_type_id = CharField(max_length=64, default="", blank=True)
    # Who a fired step is sent as, and which team owns a task step naming neither an
    # assignee nor a team. Both are decisions about how the class is run, so they sit
    # here rather than on the enrolment, and both are read live when a step fires
    # rather than copied at enrolment time. Held as identifiers for the same reason as
    # recheck_note_type_id above.
    sender_staff_id = CharField(max_length=64, default="", blank=True)
    owner_team_id = CharField(max_length=64, default="", blank=True)
    # How many days after a prescription's own written_date it still counts as eligible
    # for this class, per behaviour step 9. Left null on purpose rather than defaulted,
    # both because a class configured before this field existed has to read the same
    # way a class whose staff member left it blank does, and because the platform adds
    # a field to an existing custom data table as a nullable column with no default
    # applied to the rows already there, so a default declared here would never reach
    # them anyway. When null, services/eligibility.py falls back to the class's own
    # program span, the largest day_offset among its ProgramStep rows.
    eligibility_window_days = IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class CoverageKind:
    """The two ways a coverage entry can be defined. The vocabulary is closed."""

    GROUP = "group"
    PRODUCT = "product"

    CHOICES = [
        (GROUP, "A classification path from the ontologies catalogue"),
        (PRODUCT, "One named product"),
    ]

    ALL = frozenset({GROUP, PRODUCT})


class MedicationClassCoverage(CustomModel):
    """One coverage entry on a class, matched against a prescription's own classification.

    A group entry stores the full etc_path_id and etc_path_name arrays the ontologies
    search returned for the representative product the practice picked, and it covers
    every other product that shares that classification path, not only the one picked.
    A product entry stores a single FDB code and covers only that exact product. Which
    entry a given prescription satisfies is decided in services/eligibility.py, this
    model only carries what the practice picked.
    """

    created = DateTimeField(auto_now_add=True)
    modified = DateTimeField(auto_now=True)

    medication_class = ForeignKey(
        MedicationClass,
        to_field="dbid",
        on_delete=CASCADE,
        related_name="coverage_entries",
    )
    kind = CharField(max_length=16, choices=CoverageKind.CHOICES)
    # Populated on a group entry and left null on a product entry. Two parallel arrays
    # rather than one joined string, because the prefix match in eligibility.py walks
    # them element by element and a joined string would only need splitting back apart
    # to do that.
    etc_path_id = JSONField(null=True, blank=True)
    etc_path_name = JSONField(null=True, blank=True)
    # Populated on a product entry and left blank on a group entry. The FDB code the
    # ontologies catalogue returned as med_medication_id.
    med_medication_id = CharField(max_length=64, null=True, blank=True)
    # What the coverage list on the configuration page shows. Taken from the catalogue
    # search result the practice picked and never compared against anything, a display
    # label only, the same rule the class's own name follows.
    display_name = TextField(default="", blank=True)

    def __str__(self) -> str:
        return self.display_name or f"{self.kind} coverage entry"


class ProgramStep(CustomModel):
    """One timed step of a class programme, its kind, its condition and its content."""

    created = DateTimeField(auto_now_add=True)
    modified = DateTimeField(auto_now=True)

    medication_class = ForeignKey(
        MedicationClass,
        to_field="dbid",
        on_delete=CASCADE,
        related_name="steps",
    )
    sequence = IntegerField(default=0)
    day_offset = IntegerField(default=0)
    kind = CharField(max_length=16, choices=StepKind.CHOICES)
    # Null when the step always fires. Otherwise one of the strings in the condition
    # vocabulary, which services/conditions.py owns.
    condition = CharField(max_length=64, null=True, blank=True)

    # Content for a message step.
    message_body = TextField(default="", blank=True)
    attach_booking_link = BooleanField(default=False)

    # Content for a questionnaire step.
    questionnaire_id = CharField(max_length=64, default="", blank=True)

    # Content for a task step.
    task_title = TextField(default="", blank=True)
    task_body = TextField(default="", blank=True)
    assignee_staff_id = CharField(max_length=64, null=True, blank=True)
    assignee_team_id = CharField(max_length=64, null=True, blank=True)

    class Meta:
        ordering = ["day_offset", "sequence"]

    def __str__(self) -> str:
        return f"day {self.day_offset}, {self.kind}"
