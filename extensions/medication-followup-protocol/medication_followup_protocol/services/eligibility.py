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

from typing import NamedTuple

from canvas_sdk.commands.constants import CodeSystems
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data import MedicationCoding, Prescription

from medication_followup_protocol.models.program import (
    CoverageKind,
    MedicationClass,
    MedicationClassCoverage,
)


class PrescriptionMatch(NamedTuple):
    """One committed prescription and every active class its classification matches."""

    prescription: Prescription
    classes: list[MedicationClass]


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
    """
    payload = ontologies_http.get_json(f"/fdb/grouped-medication/{fdb_code}/").json()
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


def prescription_matches(note_dbid: int) -> list[PrescriptionMatch]:
    """Every committed prescription on this note paired with the classes it matches.

    Every active class and its coverage entries are read once, up front, rather than
    once per prescription, and the classification path for a given FDB code is looked
    up once even when more than one prescription on the note shares it, since the walk
    over a note with several prescriptions on the same medication should not cost the
    ontologies service more than one round trip for it.
    """
    classes = list(MedicationClass.objects.filter(active=True))
    # Every coverage entry of every active class in one query, grouped here, rather than
    # one query per class. Reverse accessors are unavailable in the sandbox, so the
    # grouping is done by hand, the same way GET /classes groups its steps. Asking for
    # them through prefetch_related or through the reverse accessor both raise on the
    # instance while passing against the test database, which is what this shape avoids.
    entries_by_class: dict[int, list[MedicationClassCoverage]] = {}
    for entry in MedicationClassCoverage.objects.filter(medication_class__in=classes):
        entries_by_class.setdefault(entry.medication_class_id, []).append(entry)

    path_by_code: dict[str, list[int] | None] = {}
    results: list[PrescriptionMatch] = []

    for prescription in Prescription.objects.committed().filter(note_id=note_dbid):
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
