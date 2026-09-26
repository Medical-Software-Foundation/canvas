"""Matches a note's committed prescriptions against every class's coverage.

This is the single place that decides whether a class covers a prescription. The note
header button calls it to decide whether to show at all, and the enrolment form calls
it to decide which classes to offer for which prescription, and neither of those
callers repeats the matching rule for itself.

A prescription's medication carries a classification path from the FDB ontology
catalogue, a four level hierarchy exposed as two parallel arrays, etc_path_id and
etc_path_name, most general first. A group coverage entry stores that same shape for
the one product the practice picked when it searched the catalogue, and it covers any
other prescription whose own path starts with every element of the stored path, in
order, which is what lets one entry cover a whole class of medication rather than only
the single product a search happened to return. A product entry stores one FDB code
and covers only a prescription carrying that exact code.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple

from django.db.models import Max

from canvas_sdk.commands.constants import CodeSystems
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data import MedicationCoding, Prescription

from medication_followup_protocol.models.enrollment import Enrollment
from medication_followup_protocol.models.program import (
    CoverageKind,
    MedicationClass,
    MedicationClassCoverage,
    ProgramStep,
)
from medication_followup_protocol.services.practice_time import to_practice_date, today


class PrescriptionMatch(NamedTuple):
    """One committed prescription and every active class its classification matches."""

    prescription: Prescription
    classes: list[MedicationClass]


class EligibleMatch(NamedTuple):
    """One prescription's still open door into one class it matches.

    Distinct from PrescriptionMatch, which groups every matched class under one
    prescription, because behaviour step 45's Eligible tab and its row 46 Start action
    both act on one prescription and one class at a time, the same pair a fresh
    enrolment is written against.
    """

    prescription: Prescription
    medication_class: MedicationClass


def _fdb_code(prescription: Prescription) -> str | None:
    """The FDB code carried by a prescription's own medication, or None when it has none.

    A compound formulation and a handful of other medication rows carry no FDB coding
    at all, and a prescription like that matches nothing rather than raising, which is
    what the caller reads a None back as.
    """
    if not prescription.medication_id:
        return None
    coding = MedicationCoding.objects.filter(
        medication_id=prescription.medication_id, system=CodeSystems.FDB.value
    ).first()
    if coding is None or not coding.code:
        return None
    return coding.code


def _classification_path(fdb_code: str) -> list[int] | None:
    """The etc_path_id the ontologies service carries for this FDB code.

    None when the service has nothing for the code, a fact about the catalogue rather
    than a plugin failure, and read the same way as a prescription with no coding, as
    no match rather than an error.

    The call itself is wrapped rather than left to raise, on the same footing as a
    response carrying no path at all. An unreachable ontologies service is an ordinary
    condition on a developer machine rather than an exceptional one, and a prescription
    whose classification cannot be resolved reads the same as one with no coding, no
    match rather than a broken listing.
    """
    try:
        payload = ontologies_http.get_json(f"/fdb/grouped-medication/{fdb_code}/").json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    etc_path_id = payload.get("etc_path_id")
    if not etc_path_id:
        return None
    return list(etc_path_id)


def _entry_matches(entry: MedicationClassCoverage, fdb_code: str, etc_path_id: list[int]) -> bool:
    """Whether one coverage entry covers this prescription's own classification."""
    if entry.kind == CoverageKind.PRODUCT:
        return bool(entry.med_medication_id) and entry.med_medication_id == fdb_code
    if entry.kind == CoverageKind.GROUP:
        stored = entry.etc_path_id or []
        if not stored or len(stored) > len(etc_path_id):
            return False
        return list(etc_path_id[: len(stored)]) == list(stored)
    # A kind outside the closed vocabulary matches nothing rather than raising, since a
    # row like that is a data problem for the configuration page to catch, not a reason
    # to fail every eligibility check on the instance.
    return False


def _match_prescriptions(prescriptions: Iterable[Prescription]) -> list[PrescriptionMatch]:
    """Every prescription in this iterable paired with the active classes it matches.

    Every active class and its coverage entries are read once, up front, rather than
    once per prescription, and the classification path for a given FDB code is looked
    up once even when more than one prescription in the batch shares it, since a walk
    over several prescriptions on the same medication should not cost the ontologies
    service more than one round trip for it. Shared by the note scoped read and the
    patient scoped read below, so the matching rule itself lives in exactly one place.
    """
    classes = list(MedicationClass.objects.filter(active=True))
    class_dbids = [c.dbid for c in classes]
    # Every coverage entry of every active class in one query, grouped here, rather than
    # one query per class. Reverse accessors are unavailable in the sandbox, so the
    # grouping is done by hand, the same way GET /classes groups its steps. Asking for
    # them through prefetch_related or through the reverse accessor both raise on the
    # instance while passing against the test database, which is what this shape avoids.
    #
    # Filtered by dbid rather than by the class instances themselves. program_api.py's
    # own _steps_by_class hit ValueError: Cannot query "<name>": Must be "MedicationClass"
    # instance from medication_class__in=classes on this exact instance on 2026-09-01, for
    # a row that was perfectly real, and this call carries the identical shape against the
    # same table, so it is exposed to the same failure even though it did not happen to
    # raise it in that run. A plain list of dbids, the pattern _enrollment_counts in
    # program_api.py already follows, sidesteps it rather than depending on understanding
    # what produced the mismatch.
    entries_by_class: dict[int, list[MedicationClassCoverage]] = {}
    for entry in MedicationClassCoverage.objects.filter(medication_class__dbid__in=class_dbids):
        entries_by_class.setdefault(entry.medication_class_id, []).append(entry)

    path_by_code: dict[str, list[int] | None] = {}
    results: list[PrescriptionMatch] = []

    for prescription in prescriptions:
        fdb_code = _fdb_code(prescription)
        if fdb_code is None:
            continue
        if fdb_code not in path_by_code:
            path_by_code[fdb_code] = _classification_path(fdb_code)
        etc_path_id = path_by_code[fdb_code]
        if etc_path_id is None:
            continue

        matched = [
            medication_class
            for medication_class in classes
            if any(
                _entry_matches(entry, fdb_code, etc_path_id)
                for entry in entries_by_class.get(medication_class.dbid, [])
            )
        ]
        if matched:
            results.append(PrescriptionMatch(prescription=prescription, classes=matched))

    return results


def prescription_matches(note_dbid: int) -> list[PrescriptionMatch]:
    """Every committed prescription on this note paired with the classes it matches."""
    return _match_prescriptions(Prescription.objects.committed().filter(note_id=note_dbid))


def matching_classes(note_dbid: int) -> list[MedicationClass]:
    """Every distinct active class matched by at least one prescription on this note."""
    seen: dict[int, MedicationClass] = {}
    for match in prescription_matches(note_dbid):
        for medication_class in match.classes:
            seen.setdefault(medication_class.dbid, medication_class)
    return list(seen.values())


def has_matching_prescription(note_dbid: int) -> bool:
    """Whether EnrollmentButton.visible() should show the control for this note.

    True the moment at least one committed prescription on the note matches at least
    one active class's coverage, which is the whole of what the note header control is
    gated on.
    """
    return bool(prescription_matches(note_dbid))


def patient_matches(patient_id: str) -> list[PrescriptionMatch]:
    """Every active prescription of this patient, paired with the classes it matches.

    Behaviour step 13. Runs Prescription.objects.for_patient(patient_id).active(),
    independent of which note carried the prescription, rather than a query scoped to
    one note from the start. This is what backs the chart's Eligible tab and the
    program chooser, per SPEC.md section 1, and what handlers/enrollment_button.py's
    own note header control now filters down to the note in front of the provider
    rather than repeating the matching rule for itself.
    """
    return _match_prescriptions(Prescription.objects.for_patient(patient_id).active())


def _effective_window(medication_class: MedicationClass) -> int:
    """How many days after its own written_date a match on this class stays eligible.

    Behaviour step 9. The class's own eligibility_window_days when the staff member set
    one, or, left blank, the class's own program span, the largest day_offset among its
    ProgramStep rows, so a class nobody has configured a window for still ages a
    prescription out of the Eligible tab rather than offering it forever.
    """
    if medication_class.eligibility_window_days is not None:
        return medication_class.eligibility_window_days
    # Filtered by dbid rather than by the instance, the same rule the class_dbids filter
    # above this function follows, since handing the instance itself into a relation
    # lookup is the shape confirmed live to raise ValueError: Cannot query "<name>": Must
    # be "MedicationClass" instance.
    return (
        ProgramStep.objects.filter(medication_class__dbid=medication_class.dbid).aggregate(
            Max("day_offset")
        )["day_offset__max"]
        or 0
    )


def eligible_unenrolled_matches(patient_id: str) -> list[EligibleMatch]:
    """Every prescription and class pair this patient could still be enrolled on.

    Behaviour steps 13, 43 and 45. A pair is offered once no `Enrollment` names this
    exact prescription under this exact class yet, read off `Enrollment.prescription_id`
    rather than off the medication label, since two classes whose coverage overlaps the
    same medication are allowed to run at once per SPEC.md section 1 and each is its own
    door, and once the prescription's own written_date still falls inside that class's
    own eligibility window. This is the single source both
    has_eligible_unenrolled_prescription below and the Eligible tab read from, so the
    control's own gate and the tab it opens onto can never disagree about what counts.
    """
    matches = patient_matches(patient_id)
    if not matches:
        return []

    prescription_ids = {str(match.prescription.id) for match in matches}
    # Every class an Enrollment already names against one of these prescriptions,
    # whatever its current status, since an enrolment that later stopped still means
    # this exact door was used once already. One query for the whole patient rather
    # than one per prescription and class pair.
    enrolled_pairs = {
        (enrollment.prescription_id, enrollment.medication_class_id)
        for enrollment in Enrollment.objects.filter(prescription_id__in=list(prescription_ids))
    }

    as_of = today()
    open_matches: list[EligibleMatch] = []
    for match in matches:
        prescription_id = str(match.prescription.id)
        written = to_practice_date(match.prescription.written_date)
        for medication_class in match.classes:
            if (prescription_id, medication_class.dbid) in enrolled_pairs:
                continue
            if (as_of - written).days > _effective_window(medication_class):
                continue
            open_matches.append(
                EligibleMatch(prescription=match.prescription, medication_class=medication_class)
            )
    return open_matches


def has_eligible_unenrolled_prescription(patient_id: str) -> bool:
    """Whether AllProgramsButton.visible() should show the Follow ups control for this reason.

    True the moment this patient carries at least one active prescription that matches
    an active class, carries no Enrollment yet on that exact class, and whose own
    written_date falls inside that class's eligibility window, per behaviour step 43.
    Answers from the same code path eligible_unenrolled_matches exposes for the Eligible
    tab, so the two can never disagree about what counts as still open.
    """
    return bool(eligible_unenrolled_matches(patient_id))
