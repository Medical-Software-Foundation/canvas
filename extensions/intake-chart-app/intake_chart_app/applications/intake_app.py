"""IntakeApp - the 'Intake' tab on the note body.

``visible()`` decides whether the tab shows on a given note (gated by
the optional ``intake-note-types`` secret keyword filter); ``handle()``
returns a ``LaunchModalEffect`` whose ``content`` is the entire form
HTML rendered server-side from ``templates/intake.html``.
"""
from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from django.db import DatabaseError
from logger import log

# Direct imports — RestrictedPython forbids module-attribute access on
# plugin-defined modules, so functions must be named explicitly.
from intake_chart_app.applications.render_context import build_intake_context
from intake_chart_app.data.chart_review import (
    active_allergies as _active_allergies,
    active_conditions as _active_conditions,
    active_medications as _active_medications,
    prior_medical_history as _prior_medical_history,
    prior_surgical_history as _prior_surgical_history,
)

INTAKE_NOTE_TYPES_SECRET = "intake-note-types"

# Bundled ATOD Social-History questionnaire. Canvas auto-creates
# the Questionnaire row on plugin install from
# ``questionnaires/atod_intake.yaml``; the SocialHistorySection reconciler
# resolves the row's UUID by this INTERNAL code at commit time.
SOCIAL_HX_QUESTIONNAIRE_CODE = "INTAKE_ATOD_V1"


def _note_type_name(note_dbid: str | int | None) -> str:
    if not note_dbid:
        return ""
    try:
        note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
    except Note.DoesNotExist:
        return ""
    return (note.note_type_version.name or "").lower()


def _allowed_keywords(secret_value: str | None) -> list[str]:
    """Parse the ``intake-note-types`` secret into a normalised keyword list."""
    raw = (secret_value or "").strip()
    if not raw:
        return []
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


def is_intake_note(
    note_dbid: str | int | None, secret_value: str | None
) -> bool:
    """Visibility rule for the Intake NoteApplication tab.

    Returns ``False`` whenever there is no note context — the Canvas
    global app drawer queries ``visible()`` with an empty event context,
    and without this guard the tab icon leaks into the drawer alongside
    chart-only/global apps (a NoteApplication should never appear there).

    With a real note context: if ``intake-note-types`` is unset, the tab
    is visible on every note type (wide-open default). If set, only note
    types whose name contains any keyword (case-insensitive) match.
    """
    if not note_dbid:
        return False
    keywords = _allowed_keywords(secret_value)
    if not keywords:
        return True
    name = _note_type_name(note_dbid)
    if not name:
        return False
    return any(k in name for k in keywords)


class IntakeApp(NoteApplication):
    """In-note tab rendering the guided 8-section intake form."""

    NAME = "Intake"
    IDENTIFIER = "intake_chart_app__intake_tab"

    def visible(self) -> bool:
        return is_intake_note(
            self.event.context.get("note_id"),
            self.secrets.get(INTAKE_NOTE_TYPES_SECRET),
        )

    def handle(self) -> list[Effect]:
        note_dbid = self.event.context.get("note_id")
        patient_id = self.event.context.get("patient_id", "") or str(
            self.event.target.id or ""
        )

        note_uuid = ""
        note_type_name = ""
        if note_dbid:
            try:
                note = Note.objects.select_related("note_type_version").get(
                    dbid=note_dbid
                )
                note_uuid = str(note.id)
                note_type_name = note.note_type_version.name or ""
            except Note.DoesNotExist:
                log.warning(f"[IntakeApp] Note dbid={note_dbid} not found")

        log.info(
            f"[IntakeApp] handle note_uuid={note_uuid} "
            f"patient_id={patient_id} note_type={note_type_name!r}"
        )

        chart = _safe_chart_review(patient_id)
        context = build_intake_context(
            note_uuid=note_uuid,
            patient_id=patient_id,
            note_type_name=note_type_name,
            chart=chart,
        )
        html = render_to_string("templates/intake.html", context)
        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.NOTE,
                content=html,
                title="Intake",
            ).apply()
        ]


def _safe_chart_review(patient_id: str) -> dict[str, Any]:
    """Build the pre-fill payload, swallowing per-source query failures so a
    flaky chart never blocks the modal from rendering.

    Family History intentionally has no pre-fill — Canvas's chart Family
    History sidebar (visible to the left of the modal) is the source of
    truth, and the data backing it is not reachable from plugin code
    (FHIR ``/FamilyMemberHistory`` 404s and Canvas's home-app API is not
    exposed to plugins). The Intake modal's Family History section is
    therefore Add-only and ``prior_family_history`` stays an empty list.
    """
    out: dict[str, Any] = {
        "patient_id": patient_id,
        "active_conditions": [],
        "active_allergies": [],
        "active_medications": [],
        "prior_medical_history": [],
        "prior_surgical_history": [],
        "prior_family_history": [],
    }
    if not patient_id:
        return out

    try:
        out["active_conditions"] = _active_conditions(patient_id)
    except DatabaseError as exc:
        log.error(f"[IntakeApp] active_conditions failed: {exc!r}")
    try:
        out["active_allergies"] = _active_allergies(patient_id)
    except DatabaseError as exc:
        log.error(f"[IntakeApp] active_allergies failed: {exc!r}")
    try:
        out["active_medications"] = _active_medications(patient_id)
    except DatabaseError as exc:
        log.error(f"[IntakeApp] active_medications failed: {exc!r}")
    try:
        out["prior_medical_history"] = _prior_medical_history(patient_id)
    except DatabaseError as exc:
        log.error(f"[IntakeApp] prior_medical_history failed: {exc!r}")
    try:
        out["prior_surgical_history"] = _prior_surgical_history(patient_id)
    except DatabaseError as exc:
        log.error(f"[IntakeApp] prior_surgical_history failed: {exc!r}")
    # Social History has no prior-summary pre-fill. The chart's Social
    # History sidebar is the source of truth for previously-committed
    # ATOD answers; the modal's Social History section is Add-only and
    # always renders a fresh form. Matches the Family History posture.

    return out
