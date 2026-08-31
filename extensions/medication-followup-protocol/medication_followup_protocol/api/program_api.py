"""The read and write surface both applications and the enrolment form call."""

from __future__ import annotations

import datetime
import json
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from django.db.models import Count

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data import (
    MedicationCoding,
    Note,
    NoteType,
    Patient,
    Prescription,
    Questionnaire,
    Staff,
    Team,
)

from medication_followup_protocol.api.routes import PREFIX, page
from medication_followup_protocol.models import (
    CoverageKind,
    EnrolledStep,
    Enrollment,
    EnrollmentStatus,
    MedicationClass,
    MedicationClassCoverage,
    ProgramStep,
    StepKind,
    StepStatus,
    current_defaults,
)
from medication_followup_protocol.services.banner import (
    apply_banner,
    new_banner_key,
    remove_banner,
)
from medication_followup_protocol.services.conditions import (
    CHOICES as CONDITION_CHOICES,
    CONDITIONS,
)
from medication_followup_protocol.services.eligibility import prescription_matches
from medication_followup_protocol.services.practice_time import today
from medication_followup_protocol.services.program_pane import render_sections

#: The clinical privilege level a staff member needs to build or edit a programme.
#:
#: Which staff may do this is an open question in the specification, section 7 item 1, and
#: this floor is the placeholder it names. The SDK's staff authentication confirms only
#: that the caller is staff and disregards roles, so any rule is the plugin's own. When the
#: practice answers, this constant is what changes.
CONFIGURE_PRIVILEGE_FLOOR = 1


def _may_configure(staff: Staff | None) -> bool:
    """Whether this caller may create or edit a medication class and its programme."""
    if staff is None:
        return False
    role = staff.top_clinical_role
    if role is None:
        return False
    return (role.domain_privilege_level or 0) >= CONFIGURE_PRIVILEGE_FLOOR


def _name_taken(name: str, exclude_dbid: int | None = None) -> bool:
    """Whether another medication class already carries this name.

    Compared without case and without surrounding space, because two classes whose names
    differ only in capitals are the same name to everybody reading the page. One definition
    serves the create, the rename and the clone, so the three cannot drift into disagreeing
    about what counts as a duplicate.
    """
    candidates = MedicationClass.objects.filter(name__iexact=name.strip())
    if exclude_dbid is not None:
        candidates = candidates.exclude(dbid=exclude_dbid)
    return candidates.exists()


def _duplicate_name_response(name: str) -> Response:
    """The one refusal every caller of _name_taken returns, worded for the form."""
    return JSONResponse(
        {"error": f"A medication class named {name.strip()} already exists."},
        status_code=HTTPStatus.CONFLICT,
    )


def _class_payload(
    medication_class: MedicationClass,
    steps: list[ProgramStep] | None = None,
    note_type_names: dict[str, str] | None = None,
    assignee_names: dict[str, str] | None = None,
    sender_staff_names: dict[str, str] | None = None,
    owner_team_names: dict[str, str] | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """One medication class and its steps, as the configuration page reads it.

    Steps may be passed in when the caller already loaded them for several classes at
    once, which is what keeps the listing to two queries rather than one per class.
    """
    if steps is None:
        steps = list(
            ProgramStep.objects.filter(medication_class=medication_class).order_by(
                "day_offset", "sequence"
            )
        )
    if counts is None:
        counts = _enrollment_counts([medication_class]).get(medication_class.dbid, {})
    return {
        "id": medication_class.dbid,
        "name": medication_class.name,
        "description": medication_class.description,
        "active": medication_class.active,
        "recheck_note_type_id": medication_class.recheck_note_type_id,
        # The name beside the identifier, because the page has to show a practice which
        # appointment type counts as the recheck and an identifier tells nobody anything.
        "recheck_note_type_name": (note_type_names or {}).get(
            medication_class.recheck_note_type_id, ""
        ),
        "sender_staff_id": medication_class.sender_staff_id,
        "sender_staff_name": (sender_staff_names or {}).get(
            medication_class.sender_staff_id, ""
        ),
        "owner_team_id": medication_class.owner_team_id,
        "owner_team_name": (owner_team_names or {}).get(medication_class.owner_team_id, ""),
        # --- Two counts, because they answer two different questions
        #
        # Running says the class is live and worth reading. Total says whether it can ever be
        # removed, since the refusal counts every enrolment that has ever existed rather than
        # only the live ones. Both count enrolments and not people, so a patient stopped and
        # started again on the same class is two, which is why the page says programs.
        "running_count": counts.get("running", 0),
        "total_count": counts.get("total", 0),
        "steps": [
            {
                "id": step.dbid,
                "sequence": step.sequence,
                "day_offset": step.day_offset,
                "kind": step.kind,
                "condition": step.condition or "",
                "message_body": step.message_body,
                "attach_booking_link": step.attach_booking_link,
                "questionnaire_id": step.questionnaire_id,
                "task_title": step.task_title,
                "task_body": step.task_body,
                "assignee_staff_id": step.assignee_staff_id or "",
                "assignee_team_id": step.assignee_team_id or "",
                # Who a task goes to, in words. The proposal draws a task step reading
                # "Nursing, phone the patient about tolerability", which needs the name
                # rather than the identifier the row stores.
                "assignee_name": (assignee_names or {}).get(
                    step.assignee_team_id or step.assignee_staff_id or "", ""
                ),
            }
            for step in steps
        ],
    }


def _coverage_payload(entry: MedicationClassCoverage) -> dict[str, Any]:
    """One coverage entry, as the class editor's coverage list reads it.

    A group entry carries etc_path_id and etc_path_name and no med_medication_id, a
    product entry carries med_medication_id and neither array, and the payload always
    carries all three keys so the page never has to check the kind before reading one.
    """
    return {
        "id": entry.dbid,
        "medication_class_id": entry.medication_class_id,
        "kind": entry.kind,
        "display_name": entry.display_name,
        "etc_path_id": entry.etc_path_id or [],
        "etc_path_name": entry.etc_path_name or [],
        "med_medication_id": entry.med_medication_id or "",
    }


def _medication_labels(medications: list[Any]) -> dict[int, str]:
    """The drug name for each medication, keyed by dbid.

    A Medication carries no name of its own. The name lives on its codings, and the SDK
    model defines no string form, so str of one reads "Medication object (17)". That string
    was what the enrolment dropdown offered a prescriber, what got stored on the enrolment
    as its label, what the chart panel showed, and what the duplicate check compared.

    Queried through MedicationCoding rather than through medication.codings, because a
    reverse related manager comes back as None inside the plugin sandbox and calling .all()
    on it raises. One query for every medication rather than one each, for the same reason
    the class listing batches its steps.
    """
    if not medications:
        return {}

    labels: dict[int, str] = {}
    for coding in MedicationCoding.objects.filter(
        medication__dbid__in=[m.dbid for m in medications]
    ):
        # The first coding wins. A medication carries one coding per terminology system and
        # the display text is the same drug in each, so ordering between them buys nothing.
        labels.setdefault(coding.medication_id, coding.display)
    return labels


def _assignee_names(steps: list[ProgramStep]) -> dict[str, str]:
    """Team and staff names for whoever the given task steps are assigned to.

    Keyed by the identifier the step stores, so one lookup serves both kinds of assignee.
    Two queries for the whole listing rather than one per step.
    """
    team_ids = {s.assignee_team_id for s in steps if s.assignee_team_id}
    staff_ids = {s.assignee_staff_id for s in steps if s.assignee_staff_id}

    names: dict[str, str] = {}
    if team_ids:
        for team in Team.objects.filter(id__in=list(team_ids)):
            names[str(team.id)] = team.name
    if staff_ids:
        for staff in Staff.objects.filter(id__in=list(staff_ids)):
            names[str(staff.id)] = f"{staff.first_name} {staff.last_name}"
    return names


def _enrollment_counts(classes: list[MedicationClass]) -> dict[int, dict[str, int]]:
    """How many enrolments each class carries, running and in total.

    Two grouped queries for the whole listing rather than two per class. A count per card
    would be an N plus one that grows with the number of classes a practice defines, and a
    practice with forty classes is the case this page has to survive.
    """
    if not classes:
        return {}

    class_dbids = [c.dbid for c in classes]
    counts: dict[int, dict[str, int]] = {dbid: {"running": 0, "total": 0} for dbid in class_dbids}

    for row in (
        Enrollment.objects.filter(medication_class__dbid__in=class_dbids)
        .values("medication_class_id")
        .annotate(n=Count("dbid"))
    ):
        counts[row["medication_class_id"]]["total"] = row["n"]

    for row in (
        Enrollment.objects.filter(
            medication_class__dbid__in=class_dbids, status=EnrollmentStatus.ACTIVE
        )
        .values("medication_class_id")
        .annotate(n=Count("dbid"))
    ):
        counts[row["medication_class_id"]]["running"] = row["n"]

    return counts


def _staff_names(staff_ids: set[str]) -> dict[str, str]:
    """Names for the given staff identifiers, batched for a whole listing.

    Keyed by the identifier the caller passed in, so a class naming no sender maps to an
    empty string rather than a missing key.
    """
    if not staff_ids:
        return {}
    return {
        str(staff.id): f"{staff.first_name} {staff.last_name}"
        for staff in Staff.objects.filter(id__in=list(staff_ids))
    }


def _team_names(team_ids: set[str]) -> dict[str, str]:
    """Names for the given team identifiers, batched for a whole listing."""
    if not team_ids:
        return {}
    return {str(team.id): team.name for team in Team.objects.filter(id__in=list(team_ids))}


def _prescription_label(
    prescription: Prescription, medication_labels: dict[int, str]
) -> str:
    """What this prescription is called, in one place because three callers need to agree.

    --- Why this is a chain rather than one field

    Canvas names a medication as the display text of its first coding and has nothing else,
    Medication.text is exactly that. So a prescription whose medication is missing, or whose
    medication carries no coding, has no name at all as far as the platform is concerned.

    Both really happen. A real instance served two prescriptions on one note with no
    medication behind either, which read as "Unnamed medication" twice, enrolled the first
    one under an empty label, and then refused the second for already having a programme
    while the row above it still said no programme yet.

    So the compound formulation is tried next, since a compounded prescription carries its
    name there and not on a Medication at all, and the sig last, because a clinician reading
    "Inject 0.25 mg subcutaneously once weekly" knows what they are looking at where a blank
    tells them nothing. An empty answer is still possible and is a real answer, it means this
    prescription cannot be named, and the write refuses to enrol on it rather than storing a
    programme nobody can identify.
    """
    if prescription.medication:
        coded = medication_labels.get(prescription.medication.dbid, "").strip()
        if coded:
            return coded

    compound = prescription.compound_medication
    if compound and (compound.formulation or "").strip():
        return compound.formulation.strip()

    return (prescription.sig_original_input or "").strip()


def _blocked_reason(prescription: Prescription, label: str) -> str:
    """Why a programme cannot start on this prescription, empty when one can.

    --- Why the panel is told rather than working it out

    The panel used to decide this for itself, and it knew only about the missing name, so a
    prescription with a name and no prescriber was offered a button that could only ever
    return a refusal. The rules live here now, beside the write that enforces the same ones,
    because two copies of a rule is how they drift apart.

    --- Why a missing prescriber blocks, and why it is the test for a committed prescription

    The prescriber is who the questionnaire answers land on, and who a step falls back to
    when the programme names no sender of its own, so a programme cannot run without one.

    It is also the closest thing to a committed test the SDK offers. There is no committer
    field on the SDK prescription at all, and status is a transmission vocabulary rather than
    a commit one, so a draft typed into a note and a prescription somebody signed both read
    open. Prescriber is set when the command is committed, so its presence stands in for
    committed here. It is a proxy rather than the same fact, which is why this says what is
    missing rather than claiming the prescription is uncommitted.
    """
    if not label:
        return (
            "This prescription has no medication name recorded, so a program on it could "
            "not say which drug it follows up on. Name the medication on the note first."
        )
    if prescription.prescriber is None:
        return (
            "This prescription names no prescriber yet. Fill in the prescriber on the "
            "prescribe command and commit it, then a program can start here."
        )
    return ""


def _note_filter(note_id: str) -> dict[str, Any]:
    """The lookup for a note identifier that may be a database id or a public key.

    Both shapes really arrive. The note header control reads note_id off the event context
    and the platform puts the integer primary key there, while the SDK's Note.id is the
    public uuid. Filtering on one while holding the other raises inside the field's own
    to_python, which a browser sees as a 500 with no body. Resolved in one place so the
    prescription read and the enrolment write can never read it two different ways.
    """
    return {"dbid": int(note_id)} if note_id.isdigit() else {"id": note_id}


def _note_payload(note: Note | None) -> dict[str, Any] | None:
    """Which note this is, as the enrolment panel names it back to a provider.

    None when the note could not be resolved, so the panel renders no line rather than a
    guess.

    --- The moment leaves here as an instant, not as words

    The panel's whole job here is to be recognised as the same note the provider is reading,
    so its line has to match the one the home app draws at the top of that note. The home
    app formats that time in the browser, in whatever timezone the person reading it is
    sitting in, which was found by reading a note stamped by this instance and seeing CEST
    on a machine in CEST while the instance itself is configured for America/Los_Angeles.

    So the timestamp goes out as an ISO instant and the panel formats it the same way, in
    the browser. Formatting it here produced a line two hours off the note beside it, which
    is worse than no line at all on a clinical record.

    practice_time.PRACTICE_TIMEZONE is deliberately not used. That seam exists so the daily
    walk agrees with the practice about which day a step is due, which is a scheduling
    question and stays server side. Reusing it to render a label conflated the two.
    """
    if note is None:
        return None

    moment = note.datetime_of_service
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)

    provider = note.provider
    location = note.location

    return {
        # --- Two identifiers of two different kinds, deliberately
        #
        # The chart permalink is /patient/<key>#noteId=<note database id>, read in the home
        # app at PatientPage.tsx and honoured by Notes.tsx. The patient half is the public
        # key and the note half is the primary key, so the one address carries both kinds
        # and swapping them produces a chart that loads and scrolls nowhere.
        "dbid": note.dbid,
        "patient_key": str(note.patient.id) if note.patient_id else "",
        "note_type_name": note.note_type_version.name if note.note_type_version_id else "",
        "at": moment.isoformat(),
        "provider_name": f"{provider.first_name} {provider.last_name}" if provider else "",
        "location_name": location.full_name if location else "",
    }


def _enrollment_payload(enrollment: Enrollment) -> dict[str, Any]:
    """One enrolment and every step of it, as the chart panel reads it."""
    return {
        "id": enrollment.dbid,
        "medication_label": enrollment.medication_label,
        "medication_class": enrollment.medication_class.name,
        "status": enrollment.status,
        "start_date": enrollment.start_date.isoformat(),
        "stopped_reason": enrollment.stopped_reason,
        "steps": [
            {
                "day_offset": step.day_offset,
                "kind": step.kind,
                "condition": step.condition or "",
                "due_date": step.due_date.isoformat(),
                "status": step.status,
                "failure_reason": step.failure_reason,
                "summary": _step_summary(step),
            }
            for step in EnrolledStep.objects.filter(enrollment__dbid=enrollment.dbid)
            .select_related("program_step")
            .order_by("day_offset", "sequence")
        ],
    }


def _positive_int(raw: str | None, default: int) -> int:
    """A query parameter read as a whole number of at least one.

    Anything absent, empty, negative or not a number falls back to the default rather than
    raising, because a paged page reached by a hand edited address should show its first
    page instead of a 500.
    """
    try:
        value = int(raw or "")
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def _enrolled_rows(enrollments: list[Enrollment]) -> list[dict[str, Any]]:
    """One page of enrolments as the enrolled patients page reads them.

    Every step of every enrolment on the page in one query, grouped here, with program_step
    joined because the summary of what happens next is read live off the class. Left to the
    lazy relation this would be one query per row for the steps and another per row for the
    class wording, which is the N plus one that a page of twenty five turns into fifty.
    """
    if not enrollments:
        return []

    steps_by_enrollment: dict[int, list[EnrolledStep]] = {}
    for step in EnrolledStep.objects.filter(
        enrollment__dbid__in=[e.dbid for e in enrollments]
    ).select_related("program_step").order_by("due_date", "day_offset", "sequence"):
        steps_by_enrollment.setdefault(step.enrollment_id, []).append(step)

    now = today()
    rows = []
    for enrollment in enrollments:
        steps = steps_by_enrollment.get(enrollment.dbid, [])
        settled = [s for s in steps if s.status in StepStatus.SETTLED]
        pending = [s for s in steps if s.status == StepStatus.PENDING]
        # The first step still waiting. Already ordered by due date above, so this is the
        # next thing that happens rather than the next one written.
        upcoming = pending[0] if pending else None
        patient = enrollment.patient

        rows.append(
            {
                "id": enrollment.dbid,
                "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                # The public key, because the chart address is /patient/<key> and the SDK
                # exposes that column as id. The note beside it is a database id instead,
                # which is why the two are named differently here.
                "patient_key": str(patient.id),
                "mrn": str(patient.mrn or ""),
                "medication_label": enrollment.medication_label,
                "start_date": enrollment.start_date.isoformat(),
                "day": (now - enrollment.start_date).days,
                "span": max((s.day_offset for s in steps), default=0),
                "steps_done": len(settled),
                "steps_total": len(steps),
                "next_summary": _step_summary(upcoming) if upcoming else "",
                "next_kind": upcoming.kind if upcoming else "",
                "next_due": upcoming.due_date.isoformat() if upcoming else "",
                "status": enrollment.status,
                "stopped_reason": enrollment.stopped_reason,
                "start_note_dbid": enrollment.start_note_dbid,
            }
        )
    return rows


def _step_summary(step: EnrolledStep) -> str:
    """What a step does, in the words the practice wrote, read live off the class."""
    program_step = step.program_step
    if step.kind == StepKind.TASK:
        return program_step.task_title
    if step.kind == StepKind.QUESTIONNAIRE:
        return program_step.message_body or "Questionnaire to the patient"
    return program_step.message_body


def _enrollment_step_detail_payload(enrollment: Enrollment) -> dict[str, Any]:
    """One enrolment's full step timeline, for the expanded row of the patients table.

    The patients table pages twenty five rows at a time and most rows are never expanded,
    so this reads only when a row actually opens rather than riding along on every page of
    the list. The assignee name is resolved here rather than carried on _enrolled_rows,
    since that read serves every row on a page while this one serves at most one enrolment
    at a time.
    """
    steps = list(
        EnrolledStep.objects.filter(enrollment__dbid=enrollment.dbid)
        .select_related("program_step")
        .order_by("day_offset", "sequence")
    )
    assignee_names = _assignee_names(
        [step.program_step for step in steps if step.kind == StepKind.TASK]
    )
    return {
        "id": enrollment.dbid,
        "medication_label": enrollment.medication_label,
        "start_date": enrollment.start_date.isoformat(),
        "steps": [
            {
                "day_offset": step.day_offset,
                "kind": step.kind,
                "condition": step.condition or "",
                "due_date": step.due_date.isoformat(),
                "status": step.status,
                "failure_reason": step.failure_reason,
                "summary": _step_summary(step),
                "assignee_name": (
                    assignee_names.get(
                        step.program_step.assignee_team_id
                        or step.program_step.assignee_staff_id
                        or "",
                        "",
                    )
                    if step.kind == StepKind.TASK
                    else ""
                ),
            }
            for step in steps
        ],
    }


class ProgramAPI(StaffSessionAuthMixin, SimpleAPI):
    """Reads and writes medication classes, programme steps and enrolments."""

    PREFIX = PREFIX

    # The pages.

    @api.get("/admin")
    def admin_page(self) -> list[Response | Effect]:
        """The configuration page, reachable without a patient open."""
        return [
            HTMLResponse(
                render_to_string(
                    "templates/program_admin.html",
                    {"base": page(""), "conditions": json.dumps(CONDITION_CHOICES)},
                )
            )
        ]

    @api.get("/panel")
    def panel_page(self) -> list[Response | Effect]:
        """The chart panel for one patient, its own programs each as one section.

        Behaviour step 39. The section shape, its steps with their due dates and
        statuses and the link back to the note a program started from, is
        program_pane.render_sections, the same renderer the note scoped read at
        GET /prescriptions builds on above, so this pane and that one can never drift
        into showing two different ideas of what a program looks like. Handed to the
        template as context here, and the page currently reads the same shape again
        over the wire at GET /enrollments below rather than straight out of what it was
        served, which is the template's own concern rather than this route's.
        """
        patient_id = self.request.query_params.get("patient_id", "")
        enrollments = (
            list(
                Enrollment.objects.filter(patient__id=patient_id).select_related(
                    "medication_class"
                )
            )
            if patient_id
            else []
        )
        return [
            HTMLResponse(
                render_to_string(
                    "templates/program_panel.html",
                    {
                        "base": page(""),
                        "patient_id": patient_id,
                        "sections": render_sections(enrollments),
                    },
                )
            )
        ]

    @api.get("/enrol")
    def enrol_page(self) -> list[Response | Effect]:
        """The enrolment form, opened over the note."""
        note_id = self.request.query_params.get("note_id", "")
        return [
            HTMLResponse(
                render_to_string(
                    "templates/enrollment_form.html",
                    {"base": page(""), "note_id": note_id},
                )
            )
        ]

    # The design system, served to those pages.

    @api.get("/canvas-plugin-ui.css")
    def plugin_ui_css(self) -> list[Response | Effect]:
        """The design system stylesheet."""
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-plugin-ui.js")
    def plugin_ui_js(self) -> list[Response | Effect]:
        """The design system components."""
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    @api.get("/chart-note-scroll.js")
    def chart_note_scroll_js(self) -> list[Response | Effect]:
        """The shared script that scrolls the chart to a note rather than reloading it.

        Both panes load this, the note scoped one and the patient scoped one, because it
        recognises a note by reading the home app's own chart markup, the note header
        timestamp attribute, the note wrapper, the collapsed class and the header toggle.
        A copy in each template would mean the day Canvas changes any of those, only one
        of the two gets fixed, and the sentence it matches on has to be built character
        for character the way the home app builds it or the match silently finds nothing.
        """
        return [
            Response(
                render_to_string("static/chart-note-scroll.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    # Configuration.

    @api.get("/classes")
    def list_classes(self) -> list[Response | Effect]:
        """Every medication class the practice has defined."""
        classes = list(MedicationClass.objects.all().order_by("name"))
        # Every step of every class in one query, grouped here, rather than one query per
        # class. Reverse accessors are unavailable in the sandbox, so the grouping is done
        # by hand rather than with prefetch_related.
        steps_by_class: dict[int, list[ProgramStep]] = {}
        for step in ProgramStep.objects.filter(medication_class__in=classes).order_by(
            "day_offset", "sequence"
        ):
            steps_by_class.setdefault(step.medication_class_id, []).append(step)

        # Both name maps resolved once for the whole listing rather than per class or per
        # step, which is the same batching rule the steps above follow.
        note_type_names = {
            str(n.id): n.name
            for n in NoteType.objects.filter(
                id__in=[c.recheck_note_type_id for c in classes if c.recheck_note_type_id]
            )
        }
        assignee_names = _assignee_names(
            [step for steps in steps_by_class.values() for step in steps]
        )
        sender_staff_names = _staff_names({c.sender_staff_id for c in classes if c.sender_staff_id})
        owner_team_names = _team_names({c.owner_team_id for c in classes if c.owner_team_id})
        counts_by_class = _enrollment_counts(classes)

        return [
            JSONResponse(
                {
                    "classes": [
                        _class_payload(
                            c,
                            steps_by_class.get(c.dbid, []),
                            note_type_names,
                            assignee_names,
                            sender_staff_names,
                            owner_team_names,
                            counts_by_class.get(c.dbid, {}),
                        )
                        for c in classes
                    ]
                }
            )
        ]

    @api.post("/classes")
    def create_class(self) -> list[Response | Effect]:
        """Create a medication class, naming it and choosing its recheck type."""
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        body = self.request.json()
        name = (body.get("name") or "").strip()
        if not name:
            return [JSONResponse({"error": "A medication class needs a name."}, status_code=HTTPStatus.BAD_REQUEST)]
        if _name_taken(name):
            return [_duplicate_name_response(name)]

        medication_class = MedicationClass.objects.create(
            name=name,
            description=body.get("description", ""),
            active=bool(body.get("active", True)),
            recheck_note_type_id=body.get("recheck_note_type_id", ""),
            sender_staff_id=body.get("sender_staff_id", ""),
            owner_team_id=body.get("owner_team_id", ""),
        )
        return [JSONResponse(_class_payload(medication_class), status_code=HTTPStatus.CREATED)]

    @api.post("/classes/<class_id>/steps")
    def add_step(self) -> list[Response | Effect]:
        """Add a step to a class. Steps are ordered by day offset then sequence."""
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        medication_class = MedicationClass.objects.filter(
            dbid=self.request.path_params["class_id"]
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        body = self.request.json()
        kind = body.get("kind", "")
        if kind not in StepKind.ALL:
            return [JSONResponse({"error": f"Unknown kind of step, {kind}."}, status_code=HTTPStatus.BAD_REQUEST)]

        condition = body.get("condition") or None
        if condition and condition not in CONDITIONS:
            return [JSONResponse({"error": f"Unknown condition, {condition}."}, status_code=HTTPStatus.BAD_REQUEST)]

        step = ProgramStep.objects.create(
            medication_class=medication_class,
            sequence=int(body.get("sequence", 0)),
            day_offset=int(body.get("day_offset", 0)),
            kind=kind,
            condition=condition,
            message_body=body.get("message_body", ""),
            attach_booking_link=bool(body.get("attach_booking_link", False)),
            questionnaire_id=body.get("questionnaire_id", ""),
            task_title=body.get("task_title", ""),
            task_body=body.get("task_body", ""),
            assignee_staff_id=body.get("assignee_staff_id") or None,
            assignee_team_id=body.get("assignee_team_id") or None,
        )
        return [JSONResponse({"id": step.dbid}, status_code=HTTPStatus.CREATED)]

    @api.get("/classes/<class_id>/coverage")
    def list_coverage(self) -> list[Response | Effect]:
        """Every coverage entry on one class, in the order they were added.

        Ungated the same way the class listing is, since the configuration page has to
        render a class's coverage for somebody who cannot configure, and the write
        endpoints below answer to the same floor the other writes on this page do.
        """
        medication_class = MedicationClass.objects.filter(
            dbid=self.request.path_params["class_id"]
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        entries = MedicationClassCoverage.objects.filter(
            medication_class=medication_class
        ).order_by("dbid")
        return [JSONResponse({"coverage": [_coverage_payload(e) for e in entries]})]

    @api.post("/classes/<class_id>/coverage")
    def add_coverage(self) -> list[Response | Effect]:
        """Add a coverage entry to a class, a group's classification path or one product.

        The staff member picks a result off the combo box search below rather than
        typing either shape by hand, so what lands here is what that search already
        returned. A group entry stores the full etc_path_id and etc_path_name arrays,
        which is what lets one entry cover every strength and every other product that
        shares the same classification path rather than only the product a search
        happened to return. A product entry stores one FDB code and covers only that
        exact product.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        medication_class = MedicationClass.objects.filter(
            dbid=self.request.path_params["class_id"]
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        body = self.request.json()
        kind = body.get("kind", "")
        if kind not in CoverageKind.ALL:
            return [
                JSONResponse(
                    {"error": f"Unknown kind of coverage entry, {kind}."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        display_name = (body.get("display_name") or "").strip()

        if kind == CoverageKind.GROUP:
            etc_path_id = body.get("etc_path_id") or []
            if not etc_path_id:
                return [
                    JSONResponse(
                        {"error": "A group entry needs a classification path."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            entry = MedicationClassCoverage.objects.create(
                medication_class=medication_class,
                kind=kind,
                etc_path_id=list(etc_path_id),
                etc_path_name=list(body.get("etc_path_name") or []),
                display_name=display_name,
            )
        else:
            med_medication_id = str(body.get("med_medication_id") or "").strip()
            if not med_medication_id:
                return [
                    JSONResponse(
                        {"error": "A product entry needs a medication code."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            entry = MedicationClassCoverage.objects.create(
                medication_class=medication_class,
                kind=kind,
                med_medication_id=med_medication_id,
                display_name=display_name,
            )

        return [JSONResponse(_coverage_payload(entry), status_code=HTTPStatus.CREATED)]

    @api.delete("/coverage/<coverage_id>")
    def delete_coverage(self) -> list[Response | Effect]:
        """Remove a coverage entry.

        Removing the last entry on a class leaves it matching nothing, which is a
        configuration choice rather than a refusal this endpoint has any reason to make,
        the same way a class carrying no steps yet is allowed to exist.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        entry = MedicationClassCoverage.objects.filter(
            dbid=self.request.path_params["coverage_id"]
        ).first()
        if entry is None:
            return [JSONResponse({"error": "No such coverage entry."}, status_code=HTTPStatus.NOT_FOUND)]

        entry.delete()
        return [JSONResponse({"deleted": True})]

    @api.get("/medication-search")
    def search_medication_groups(self) -> list[Response | Effect]:
        """Proxy the ontologies grouped medication search for the coverage combo box.

        Behaviour step 5. The combo box lists medication groups from a full text search
        against the ontologies catalogue rather than a classification path typed by
        hand, and picking a result is what the coverage write above turns into a group
        entry.

        --- Why one row per classification path rather than one row per product

        AC29 asks the combo box to list medication groups, and the catalogue answers
        this search with products. Searching lisinopril on the local catalogue returns
        two rows, 10 mg and 20 mg, carrying byte identical classification paths, so
        listing the catalogue's own rows offered the same group twice under two names
        that both read as a single strength. Picking either one stored exactly the same
        coverage entry, which made the choice between them meaningless and the list
        misleading about what was being chosen.

        So the rows are folded by classification path here, one row per distinct group,
        named by the most specific step of the path, Statins rather than atorvastatin
        20 mg tablet. The products that matched the query travel with each row in
        matched_products, because a group name alone does not tell somebody who typed a
        drug name that they found the right group, and the page shows them as the
        reason the row is there.

        The search is still by drug name, since the catalogue exposes no way to search
        the classification taxonomy itself, only these product rows. That is the right
        door anyway, a practice thinks in terms of the drug it just prescribed rather
        than in terms of the taxonomy above it.

        --- Why this reads results rather than the bare object eligibility.py reads

        This calls the search form of the endpoint, GET /fdb/grouped-medication/ with a
        search query string, which answers with a results list. eligibility.py calls a
        different form of the same endpoint, GET /fdb/grouped-medication/{code}/ with a
        single FDB code as the path segment, which answers with a bare object carrying
        the same fields and no results wrapper. Driven against the running local
        instance and confirmed the two shapes really differ, so this reads the results
        list explicitly rather than falling back to the bare shape the other caller uses.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        query = (self.request.query_params.get("query") or "").strip()
        if not query:
            return [JSONResponse({"results": []})]

        payload = ontologies_http.get_json(
            f"/fdb/grouped-medication/?{urlencode({'search': query})}"
        ).json()
        raw_results = payload.get("results") if isinstance(payload, dict) else None

        groups: dict[tuple[int, ...], dict] = {}
        for result in raw_results or []:
            if not isinstance(result, dict):
                continue
            path_id = tuple(result.get("etc_path_id") or [])
            # A product the catalogue carries no classification for belongs to no group,
            # so it is left out rather than offered as a group covering nothing. The
            # matching rule would read a stored empty path as matching no prescription
            # at all, which is a row that looks like coverage and is not.
            if not path_id:
                continue
            product = (
                result.get("description_and_quantity")
                or result.get("med_medication_description")
                or ""
            )
            group = groups.get(path_id)
            if group is None:
                path_name = [str(step) for step in (result.get("etc_path_name") or [])]
                groups[path_id] = {
                    "etc_path_id": list(path_id),
                    "etc_path_name": path_name,
                    # The most specific step of the path, which is the name a practice
                    # would recognise. The steps above it travel too, as the context the
                    # page shows beneath the name.
                    "display_name": path_name[-1] if path_name else "Unnamed medication group",
                    "matched_products": [product] if product else [],
                    # The first product this group answered with, kept because a product
                    # coverage entry is still a shape the write endpoint accepts and this
                    # is the only place a code for one comes from.
                    "med_medication_id": str(result.get("med_medication_id", "")),
                }
                continue
            if product and product not in group["matched_products"]:
                group["matched_products"].append(product)

        return [JSONResponse({"results": list(groups.values())})]

    @api.post("/classes/<class_id>/clone")
    def clone_class(self) -> list[Response | Effect]:
        """Copy a class and every step on it under a new name.

        The copy is made here rather than by the page reading a class and posting it back
        one step at a time, so a clone is one request that either happens or does not, and
        a page that dies halfway through cannot leave a class carrying half a programme.

        Everything about the class travels except its name, the description, whether it is
        active, the recheck type, the sender and the owning team, every step with its
        day, order, kind, condition and content, and every coverage entry. Nothing about an
        enrolment is copied, because an enrolment belongs to a patient rather than to the
        programme's shape.

        Coverage travels for a reason worth stating. A class matches a prescription only
        through its coverage entries, so a clone that copied the steps and left the coverage
        behind would look complete on the configuration page and match nothing at all, and
        the failure would show up as a note header control that never appears.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        original = MedicationClass.objects.filter(
            dbid=self.request.path_params["class_id"]
        ).first()
        if original is None:
            return [
                JSONResponse(
                    {"error": "That medication class no longer exists."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        body = self.request.json()
        name = (body.get("name") or "").strip()
        if not name:
            return [
                JSONResponse(
                    {"error": "A medication class needs a name."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if _name_taken(name):
            return [_duplicate_name_response(name)]

        copy = MedicationClass.objects.create(
            name=name,
            description=original.description,
            active=original.active,
            recheck_note_type_id=original.recheck_note_type_id,
            sender_staff_id=original.sender_staff_id,
            owner_team_id=original.owner_team_id,
        )
        for step in ProgramStep.objects.filter(medication_class=original).order_by(
            "day_offset", "sequence"
        ):
            ProgramStep.objects.create(
                medication_class=copy,
                sequence=step.sequence,
                day_offset=step.day_offset,
                kind=step.kind,
                condition=step.condition,
                message_body=step.message_body,
                attach_booking_link=step.attach_booking_link,
                questionnaire_id=step.questionnaire_id,
                task_title=step.task_title,
                task_body=step.task_body,
                assignee_staff_id=step.assignee_staff_id,
                assignee_team_id=step.assignee_team_id,
            )

        for entry in MedicationClassCoverage.objects.filter(medication_class=original):
            MedicationClassCoverage.objects.create(
                medication_class=copy,
                kind=entry.kind,
                display_name=entry.display_name,
                etc_path_id=entry.etc_path_id,
                etc_path_name=entry.etc_path_name,
                med_medication_id=entry.med_medication_id,
            )

        return [JSONResponse(_class_payload(copy), status_code=HTTPStatus.CREATED)]

    @api.patch("/classes/<class_id>")
    def update_class(self) -> list[Response | Effect]:
        """Rename a class, or take it in and out of use.

        Only the keys present in the body are touched, so renaming does not disturb whether
        the class is active and the reverse holds too.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        medication_class = MedicationClass.objects.filter(
            dbid=self.request.path_params["class_id"]
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        body = self.request.json()

        if "name" in body:
            name = (body.get("name") or "").strip()
            if not name:
                return [
                    JSONResponse(
                        {"error": "A medication class needs a name."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            if _name_taken(name, exclude_dbid=medication_class.dbid):
                return [_duplicate_name_response(name)]
            medication_class.name = name

        if "active" in body:
            medication_class.active = bool(body.get("active"))

        if "recheck_note_type_id" in body:
            medication_class.recheck_note_type_id = body.get("recheck_note_type_id") or ""

        if "sender_staff_id" in body:
            medication_class.sender_staff_id = body.get("sender_staff_id") or ""

        if "owner_team_id" in body:
            medication_class.owner_team_id = body.get("owner_team_id") or ""

        medication_class.save()
        return [JSONResponse(_class_payload(medication_class))]

    @api.delete("/classes/<class_id>")
    def delete_class(self) -> list[Response | Effect]:
        """Remove a class, but never one somebody has been enrolled on.

        An enrolment reads its wording live from the class it was started on, so deleting a
        class out from under a running programme would leave the chart panel unable to say
        what a step even was. Deactivating is the move there, which is why the refusal says so.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        medication_class = MedicationClass.objects.filter(
            dbid=self.request.path_params["class_id"]
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        enrolled = Enrollment.objects.filter(medication_class=medication_class).count()
        if enrolled:
            return [
                JSONResponse(
                    {
                        "error": (
                            f"{enrolled} patient programs were started on this class, so it "
                            "cannot be removed. Make it inactive instead and no new program "
                            "will use it."
                        )
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        ProgramStep.objects.filter(medication_class=medication_class).delete()
        medication_class.delete()
        return [JSONResponse({"deleted": True})]

    @api.patch("/steps/<step_id>")
    def update_step(self) -> list[Response | Effect]:
        """Edit a step in place. Only the keys present in the body are touched."""
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        step = ProgramStep.objects.filter(dbid=self.request.path_params["step_id"]).first()
        if step is None:
            return [JSONResponse({"error": "No such step."}, status_code=HTTPStatus.NOT_FOUND)]

        body = self.request.json()

        if "kind" in body:
            kind = body.get("kind", "")
            if kind not in StepKind.ALL:
                return [
                    JSONResponse(
                        {"error": f"Unknown kind of step, {kind}."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            step.kind = kind

        if "condition" in body:
            condition = body.get("condition") or None
            if condition and condition not in CONDITIONS:
                return [
                    JSONResponse(
                        {"error": f"Unknown condition, {condition}."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            step.condition = condition

        # Written out one at a time rather than looped with setattr, which the plugin sandbox
        # blocks outright. Nothing here is clever enough to need it anyway.
        if "message_body" in body:
            step.message_body = body.get("message_body") or ""
        if "questionnaire_id" in body:
            step.questionnaire_id = body.get("questionnaire_id") or ""
        if "task_title" in body:
            step.task_title = body.get("task_title") or ""
        if "task_body" in body:
            step.task_body = body.get("task_body") or ""

        if "day_offset" in body:
            step.day_offset = int(body.get("day_offset") or 0)
        if "sequence" in body:
            step.sequence = int(body.get("sequence") or 0)
        if "attach_booking_link" in body:
            step.attach_booking_link = bool(body.get("attach_booking_link"))
        if "assignee_staff_id" in body:
            step.assignee_staff_id = body.get("assignee_staff_id") or None
        if "assignee_team_id" in body:
            step.assignee_team_id = body.get("assignee_team_id") or None

        step.save()
        return [JSONResponse({"id": step.dbid})]

    @api.delete("/steps/<step_id>")
    def delete_step(self) -> list[Response | Effect]:
        """Remove a step, but never one a running programme already scheduled.

        An enrolled step reads its wording live from the programme step it was copied from,
        so removing that row would leave a scheduled step with nothing to say.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        step = ProgramStep.objects.filter(dbid=self.request.path_params["step_id"]).first()
        if step is None:
            return [JSONResponse({"error": "No such step."}, status_code=HTTPStatus.NOT_FOUND)]

        scheduled = EnrolledStep.objects.filter(program_step=step).count()
        if scheduled:
            return [
                JSONResponse(
                    {
                        "error": (
                            f"This step is already scheduled on {scheduled} patient programs, "
                            "so it cannot be removed. Editing its wording still reaches them."
                        )
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        step.delete()
        return [JSONResponse({"deleted": True})]

    @api.get("/questionnaires")
    def list_questionnaires(self) -> list[Response | Effect]:
        """The questionnaires on this instance, so a step picks one rather than describing it.

        A questionnaire step needs to name a questionnaire that exists. Before this, the only
        field a step had was a body of text, which fits a message and fits neither of the
        other two kinds.
        """
        return [
            JSONResponse(
                {
                    "questionnaires": [
                        {"id": str(q.id), "name": q.name}
                        for q in Questionnaire.objects.filter(status="AC").order_by("name")
                    ]
                }
            )
        ]

    @api.get("/assignees")
    def list_assignees(self) -> list[Response | Effect]:
        """Every team on the instance and every active staff member.

        Every team, without exception. A team record carries no active or archived state
        to filter on, so narrowing this list is not something the platform can support.
        """
        return [
            JSONResponse(
                {
                    "teams": [{"id": str(t.id), "name": t.name} for t in Team.objects.all()],
                    "staff": [
                        {"id": str(s.id), "name": f"{s.first_name} {s.last_name}"}
                        for s in Staff.objects.filter(active=True)
                    ],
                }
            )
        ]

    @api.get("/note-types")
    def list_note_types(self) -> list[Response | Effect]:
        """The appointment types that can count as a recheck.

        Only types the patient can book themselves, so a recheck the patient can act on is
        the only kind offered. The portal flag alone is not enough, since the portal also
        refuses a type carrying no online duration, so a type flagged but left at zero
        minutes would be offered here and be unbookable there.
        """
        note_types = NoteType.objects.filter(
            is_active=True, is_scheduleable_via_patient_portal=True, online_duration__gt=0
        )
        return [JSONResponse({"note_types": [{"id": str(n.id), "name": n.name} for n in note_types]})]

    # The practice defaults for a new class.

    @api.get("/defaults")
    def read_defaults(self) -> list[Response | Effect]:
        """What a new medication class starts from, for the whole practice.

        Ungated, the same as every other read this page makes. Only the writes ask for
        configure rights. Gating this one would 403 a staff member who may look at the
        page without changing it, leaving a console error under a page that rendered
        correctly, and the two identifiers it returns are already in the classes payload
        beside it.
        """
        defaults = current_defaults()
        return [
            JSONResponse(
                {
                    "sender_staff_id": defaults.sender_staff_id,
                    "owner_team_id": defaults.owner_team_id,
                }
            )
        ]

    @api.put("/defaults")
    def write_defaults(self) -> list[Response | Effect]:
        """Store what a new class starts from, so the choice is made once.

        Absent keys are left alone rather than cleared, the same rule the class patch
        follows, so a caller sending one field never wipes the other by omission.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        body = self.request.json()
        defaults = current_defaults()
        if "sender_staff_id" in body:
            defaults.sender_staff_id = body.get("sender_staff_id") or ""
        if "owner_team_id" in body:
            defaults.owner_team_id = body.get("owner_team_id") or ""
        defaults.save()
        return [
            JSONResponse(
                {
                    "sender_staff_id": defaults.sender_staff_id,
                    "owner_team_id": defaults.owner_team_id,
                }
            )
        ]

    # Enrolment.

    @api.get("/prescriptions")
    def list_prescriptions(self) -> list[Response | Effect]:
        """The prescriptions committed on this note, and which classes each one matched.

        Identifiers are keys rather than database ids, the same as every other endpoint
        here. The enrolment form hands what it reads straight back to the write below, so
        the two have to speak one vocabulary. They did not, and the result was that every
        enrolment submitted through the form failed on the server with an empty body.

        --- Behaviour step 14, offering only what eligibility already matched

        Every prescription on the note is still listed, the same as every prescription
        blocked on a missing name or a missing prescriber is still listed with a reason
        attached rather than dropped, the pattern the running program check below this
        one already set. What changes is the classes carried on each row. Only the
        classes eligibility.py already matched for that prescription's own
        classification are named, so a class the write would refuse is never one of
        them, which is what actually answers step 14, the dropdown never offers a
        choice the write would reject. A prescription eligibility matched nothing
        carries an empty list rather than every class on the instance.
        """
        note_id = self.request.query_params.get("note_id", "")
        if not note_id:
            return [JSONResponse({"note": None, "prescriptions": []})]

        # Whichever shape arrived, resolved by the one helper so this read and the enrolment
        # write below it cannot disagree. The same filter answers the note lookup and the
        # prescription lookup, prefixed with note__ for the second.
        note_filter = _note_filter(note_id)
        note = (
            Note.objects.filter(**note_filter)
            .select_related("note_type_version", "provider", "location", "patient")
            .first()
        )

        prescriptions = list(
            Prescription.objects.filter(
                **{f"note__{key}": value for key, value in note_filter.items()}
            ).select_related("patient", "prescriber", "medication")
        )

        # eligibility.py's own read of this note, only for which classes it matched per
        # prescription. Its query carries none of the relations this endpoint needs, so
        # the prescriptions above are read again through the batched query this endpoint
        # already had rather than through what eligibility.py returns.
        classes_by_prescription_id = {
            match.prescription.id: match.classes for match in prescription_matches(note.dbid)
        } if note is not None else {}

        labels = _medication_labels([p.medication for p in prescriptions if p.medication])

        # --- Which of these already has a program running
        #
        # The same match the write below refuses a duplicate on, one patient, one medication
        # label, one active enrolment, read here instead of caught there, so the dropdown
        # never offers a choice the write would only reject. Batched over every patient and
        # label on the note rather than queried once per prescription.
        #
        # Built as a dict comprehension rather than assigned into an empty dict one row at a
        # time. The plugin sandbox's write guard refuses a subscript assignment whose key is a
        # tuple, an AttributeError the browser sees as a 500 carrying no body, the same shape
        # of failure this endpoint already met once over the note identifier above. A
        # comprehension has no assignment statement for the guard to catch, so the tuple key
        # that reads naturally, one patient and one label, stays exactly that.
        patient_dbids = {p.patient.dbid for p in prescriptions if p.patient}
        running_labels = {
            label for label in (_prescription_label(p, labels) for p in prescriptions) if label
        }
        running_by_patient_and_label: dict[tuple[int, str], Enrollment] = {}
        if patient_dbids and running_labels:
            running_by_patient_and_label = {
                (enrollment.patient_id, enrollment.medication_label): enrollment
                for enrollment in Enrollment.objects.filter(
                    patient__dbid__in=list(patient_dbids),
                    medication_label__in=list(running_labels),
                    status=EnrollmentStatus.ACTIVE,
                ).select_related("medication_class")
            }

        # One render_sections call for every running enrolment this note's prescriptions
        # point at, rather than one per prescription, so program_pane.py is the only
        # place that ever renders what a section looks like. Deduplicated by database id
        # first, because two prescriptions on the same note can share the same running
        # enrolment and rendering its section twice would cost that section's own steps
        # query twice for nothing.
        distinct_running = list(
            {e.dbid: e for e in running_by_patient_and_label.values()}.values()
        )
        running_sections_by_dbid = {
            section["id"]: section for section in render_sections(distinct_running)
        }

        def _running_payload(prescription: Prescription) -> dict[str, Any] | None:
            # Keyed on the label this row actually shows rather than on the prescription
            # having a medication. Returning early on a missing medication made a row read
            # "No program yet" while the write endpoint refused it for already having one,
            # so the panel contradicted itself on the same screen.
            if not prescription.patient:
                return None
            label = _prescription_label(prescription, labels)
            if not label:
                return None
            running = running_by_patient_and_label.get((prescription.patient.dbid, label))
            if running is None:
                return None
            return running_sections_by_dbid.get(running.dbid)

        return [
            JSONResponse(
                {
                    "note": _note_payload(note),
                    "prescriptions": [
                        {
                            "id": str(p.id),
                            "label": _prescription_label(p, labels),
                            "patient_id": str(p.patient.id) if p.patient else "",
                            "prescriber_id": str(p.prescriber.id) if p.prescriber else "",
                            "prescriber_name": (
                                f"{p.prescriber.first_name} {p.prescriber.last_name}"
                                if p.prescriber
                                else ""
                            ),
                            # Every active class this prescription's own classification
                            # matched, so the form picks among only these rather than
                            # every class the practice has ever defined.
                            "classes": [
                                {"id": c.dbid, "name": c.name}
                                for c in classes_by_prescription_id.get(p.id, [])
                            ],
                            # Why this prescription cannot be enrolled, empty when it can.
                            # Decided here rather than in the panel, so one place holds the
                            # rule and the panel only draws what it is told.
                            "blocked_reason": _blocked_reason(p, _prescription_label(p, labels)),
                            "running_enrollment": _running_payload(p),
                        }
                        for p in prescriptions
                    ],
                }
            )
        ]

    #: How many rows the enrolled patients page asks for at once, and the ceiling on what a
    #: caller may ask for. Twenty five fills a screen without paging becoming the interaction.
    ENROLLED_PAGE_SIZE = 25
    ENROLLED_PAGE_SIZE_MAX = 100

    @api.get("/class-enrollments")
    def list_class_enrollments(self) -> list[Response | Effect]:
        """One page of the patients on one class, for the enrolled patients page.

        --- Why this is not the patient scoped read next to it

        GET /enrollments answers what one patient is on, returns every step of every
        enrolment, and is read by the chart panel and the enrolment form. This answers who is
        on one class, has to page, and carries a patient name and an MRN that the other one
        has no reason to know. One endpoint serving both would return a payload meaning two
        things, and widening the patient read would change what its two existing callers get.

        --- Why it is gated when the other reads on the page are not

        Every other read the configuration page makes is ungated, because the page has to
        render for somebody who cannot configure. This one is an administrative list of
        patients rather than the shape of a programme, so it answers to the same floor the
        writes do. If that floor turns out to be wrong it is already wrong for every write,
        which is better than a third rule that only this endpoint knows about.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        medication_class = MedicationClass.objects.filter(
            dbid=self.request.query_params.get("class_id") or 0
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        scope = self.request.query_params.get("scope", "running")
        if scope not in {"running", "ended"}:
            scope = "running"

        page_number = _positive_int(self.request.query_params.get("page"), 1)
        page_size = min(
            _positive_int(self.request.query_params.get("page_size"), self.ENROLLED_PAGE_SIZE),
            self.ENROLLED_PAGE_SIZE_MAX,
        )

        # Both tab counts in one grouped query, so the tabs are right without a second read
        # and without the page having to ask twice.
        by_status = {
            row["status"]: row["n"]
            for row in Enrollment.objects.filter(medication_class=medication_class)
            .values("status")
            .annotate(n=Count("dbid"))
        }
        running_count = by_status.get(EnrollmentStatus.ACTIVE, 0)
        ended_count = sum(n for status, n in by_status.items() if status != EnrollmentStatus.ACTIVE)

        # Ended folds stopped and completed together, because both are done and a reader
        # sorting them apart reads the status column. Ordered newest first with the database
        # id as the tiebreak, because offset paging over a non unique ordering can show one
        # row twice and skip another.
        rows = Enrollment.objects.filter(medication_class=medication_class)
        rows = (
            rows.filter(status=EnrollmentStatus.ACTIVE)
            if scope == "running"
            else rows.exclude(status=EnrollmentStatus.ACTIVE)
        )
        total = running_count if scope == "running" else ended_count
        offset = (page_number - 1) * page_size
        window = list(
            rows.select_related("patient").order_by("-start_date", "-dbid")[
                offset : offset + page_size
            ]
        )

        return [
            JSONResponse(
                {
                    "class_id": medication_class.dbid,
                    "class_name": medication_class.name,
                    "scope": scope,
                    "page": page_number,
                    "page_size": page_size,
                    "total": total,
                    "running_count": running_count,
                    "ended_count": ended_count,
                    "rows": _enrolled_rows(window),
                }
            )
        ]

    @api.get("/enrollments/<enrollment_id>/steps")
    def list_enrollment_steps(self) -> list[Response | Effect]:
        """The full step timeline of one enrolment, for the expanded row of the patients table.

        Lazy rather than carried on the list read, because the list pages twenty five rows
        at once and most rows are never expanded. Gated the same way the list itself is,
        since this is the detail behind an administrative list of patients rather than the
        shape of a programme.
        """
        if not _may_configure(self._caller()):
            return [self._forbidden()]

        enrollment = Enrollment.objects.filter(
            dbid=self.request.path_params["enrollment_id"]
        ).first()
        if enrollment is None:
            return [JSONResponse({"error": "No such program."}, status_code=HTTPStatus.NOT_FOUND)]

        return [JSONResponse(_enrollment_step_detail_payload(enrollment))]

    @api.get("/enrollments")
    def list_enrollments(self) -> list[Response | Effect]:
        """Every enrolment for one patient, as one section per program.

        Built on program_pane.render_sections, the same renderer the panel page above
        already handed its own template context, so a change to what a section carries
        reaches both at once rather than two renderers drifting apart on what a program
        looks like.
        """
        patient_id = self.request.query_params.get("patient_id", "")
        if not patient_id:
            return [JSONResponse({"enrollments": []})]

        enrollments = list(
            Enrollment.objects.filter(patient__id=patient_id).select_related(
                "medication_class"
            )
        )
        return [JSONResponse({"enrollments": render_sections(enrollments)})]

    @api.post("/enrollments")
    def create_enrollment(self) -> list[Response | Effect]:
        """Start a patient on a class, scheduling every step of it."""
        body = self.request.json()
        medication_class = MedicationClass.objects.filter(
            dbid=body.get("medication_class_id"), active=True
        ).first()
        if medication_class is None:
            return [JSONResponse({"error": "No such active medication class."}, status_code=HTTPStatus.NOT_FOUND)]

        medication_label = (body.get("medication_label") or "").strip()

        # --- An unnamed medication is refused rather than stored
        #
        # The label is the only thing identifying which drug a programme follows up on. It is
        # what the duplicate check compares, what the chart panel shows and what a message to
        # a patient is about. Stored empty it does real damage rather than looking untidy,
        # because every unnamed prescription on that patient then collides into one, so the
        # first one blocks the rest and the refusal reads "already has a running program for"
        # with nothing after it. That happened on a real instance.
        #
        # Canvas has no second name for a drug, Medication.text is the first coding's display
        # and nothing else, so a prescription this plugin cannot name is one it must not
        # enrol. Refused here at the write, where it is cheap, rather than left to surface as
        # a programme nobody can identify.
        if not medication_label:
            return [
                JSONResponse(
                    {
                        "error": (
                            "This prescription has no medication name recorded, so a program "
                            "started on it could not say which drug it follows up on. Check "
                            "the prescription on the note."
                        )
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # --- Keys in, database ids stored
        #
        # Every identifier this API hands out is a key, the thirty two character public one,
        # and every foreign key on the models below is declared to_field dbid. So the write
        # resolves rather than assigns. Assigning a key straight through is what broke every
        # enrolment made from the form, with the runner raising that dbid expected a number
        # and the browser getting a 500 carrying no body to explain it.
        patient = Patient.objects.filter(id=body.get("patient_id")).first()
        if patient is None:
            return [JSONResponse({"error": "No such patient."}, status_code=HTTPStatus.NOT_FOUND)]

        # Who a fired step is sent as is now a decision the medication class makes, read
        # live each time a step goes out, so this write no longer takes a sender at all.
        # The prescriber still has to be named here, because the questionnaire answers
        # land on them and a step falls back to them whenever the class names no sender
        # of its own or that sender has since left. It resolves from the body first, and
        # when the body names none, from the prescriber already recorded on the
        # prescription being enrolled.
        prescriber = Staff.objects.filter(id=body.get("prescriber_staff_id")).first()
        if prescriber is None:
            prescription_id = body.get("prescription_id")
            if prescription_id:
                selected_prescription = (
                    Prescription.objects.filter(id=prescription_id)
                    .select_related("prescriber")
                    .first()
                )
                if selected_prescription is not None:
                    prescriber = selected_prescription.prescriber
        if prescriber is None:
            return [
                JSONResponse(
                    {
                        "error": (
                            "This program needs a prescriber named, so the questionnaire "
                            "answers and any message sent under nobody else's name have "
                            "someone to land on. Check the prescription on the note."
                        )
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # One running programme per medication. Two racing each other on one medication is
        # a failure that stays invisible until the patient gets two messages.
        already = Enrollment.objects.filter(
            patient__dbid=patient.dbid,
            medication_label=medication_label,
            status=EnrollmentStatus.ACTIVE,
        ).first()
        if already is not None:
            # The identifier rides along with the refusal, because the form offers to stop
            # the running programme and an offer cannot act on a sentence.
            return [
                JSONResponse(
                    {
                        "error": (
                            f"This patient already has a running program for {medication_label}."
                        ),
                        "running_enrollment_id": already.dbid,
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        # Which note this was started from, kept so the enrolled patients page can link a
        # reader to it. Resolved to a database id here rather than stored as it arrived,
        # because the chart permalink is read as a note primary key. A note that cannot be
        # resolved leaves this null and the page shows no link, which is the honest outcome.
        start_note_dbid = None
        submitted_note_id = (body.get("note_id") or "").strip()
        if submitted_note_id:
            start_note = Note.objects.filter(**_note_filter(submitted_note_id)).first()
            if start_note is not None:
                start_note_dbid = start_note.dbid

        start_date = today()
        enrollment = Enrollment.objects.create(
            patient_id=patient.dbid,
            medication_class=medication_class,
            medication_label=medication_label,
            prescription_id=body.get("prescription_id") or None,
            sender_staff_id=None,
            prescriber_staff_id=prescriber.dbid,
            start_date=start_date,
            start_note_dbid=start_note_dbid,
            recheck_note_type_id=medication_class.recheck_note_type_id,
            # Minted fresh here rather than derived from the row, because banner.py's own
            # AddBannerAlert below needs a key the moment this enrolment exists, and a
            # key derived from the database id would need the row saved first anyway.
            banner_key=new_banner_key(),
        )

        # The timing and the shape are copied now, the content stays live on the class.
        for program_step in ProgramStep.objects.filter(
            medication_class=medication_class
        ).order_by("day_offset", "sequence"):
            EnrolledStep.objects.create(
                enrollment=enrollment,
                program_step=program_step,
                sequence=program_step.sequence,
                day_offset=program_step.day_offset,
                kind=program_step.kind,
                condition=program_step.condition,
                due_date=start_date + datetime.timedelta(days=program_step.day_offset),
            )

        # Behaviour step 17. A text only banner naming the class, keyed on this
        # enrolment's own banner_key, so a patient with two enrolments carries two
        # banners and stopping one later never touches the other, per AC24. The
        # response leads the list, since this project's own test harness reads the
        # first item back as the response and nothing here needs the banner effect to
        # land before it.
        return [
            JSONResponse(_enrollment_payload(enrollment), status_code=HTTPStatus.CREATED),
            apply_banner(enrollment),
        ]

    @api.post("/enrollments/<enrollment_id>/stop")
    def stop_enrollment(self) -> list[Response | Effect]:
        """Stop an enrolment, recording who stopped it and why."""
        enrollment = Enrollment.objects.filter(
            dbid=self.request.path_params["enrollment_id"]
        ).first()
        if enrollment is None:
            return [JSONResponse({"error": "No such program."}, status_code=HTTPStatus.NOT_FOUND)]

        body = self.request.json()
        caller = self._caller()
        enrollment.status = EnrollmentStatus.STOPPED
        enrollment.stopped_reason = (body.get("reason") or "").strip()
        enrollment.stopped_by = str(caller.id) if caller else None
        enrollment.save()
        # Every pending step is left pending. The walk ignores a stopped enrolment, so
        # nothing has to be rewritten for the remaining steps to stop happening.
        #
        # Behaviour step 41, AC24. Keyed on this enrolment's own banner_key, which is
        # what keeps a second running enrolment's banner for the same patient standing
        # when this one stops. The response leads the list for the same reason it does
        # on the write above.
        return [
            JSONResponse(_enrollment_payload(enrollment)),
            remove_banner(enrollment),
        ]

    # Shared.

    def _caller(self) -> Staff | None:
        """The staff member who made this request."""
        logged_in = getattr(self.request, "headers", {})
        staff_id = logged_in.get("canvas-logged-in-user-id") if logged_in else None
        if not staff_id:
            return None
        return Staff.objects.filter(id=staff_id).first()

    def _forbidden(self) -> Response:
        """The refusal a caller below the configuration floor gets."""
        return JSONResponse(
            {"error": "You do not have permission to change follow up programs."},
            status_code=HTTPStatus.FORBIDDEN,
        )
