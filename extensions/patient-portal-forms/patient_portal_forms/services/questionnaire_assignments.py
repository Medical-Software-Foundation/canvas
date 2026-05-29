"""CRUD over QuestionnaireAssignment rows.

Returns dict shapes compatible with the JSON the templates previously read
from PatientMetadata, so the templates and frontend JS do not need to change.

Outstanding vs. completed:
    A questionnaire can be re-taken (e.g. a monthly screen), so completed
    rows are retained as history. All assignment lookups below filter to
    outstanding rows (``completed_at IS NULL``) — the partial unique
    constraint on the model only applies to outstanding rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from logger import log

from patient_portal_forms.models import (
    CustomPatient,
    CustomStaff,
    QuestionnaireAssignment,
)


class QuestionnaireAssignmentService:
    """Persistence helpers for a patient's assigned questionnaires."""

    @staticmethod
    def _provider_display(provider: CustomStaff | None) -> dict:
        if provider is None:
            return {"key": "", "name": ""}
        name = getattr(provider, "credentialed_name", "") or " ".join(
            filter(None, [provider.first_name, provider.last_name])
        )
        return {"key": str(provider.id), "name": name}

    @classmethod
    def _serialize(cls, row: QuestionnaireAssignment) -> dict:
        return {
            "questionnaire_name": row.questionnaire_name,
            "due_date": row.due_date.isoformat() if row.due_date else "",
            "date_assigned": (
                row.date_assigned.date().isoformat() if row.date_assigned else ""
            ),
            "assigning_provider": cls._provider_display(row.assigning_provider),
        }

    @classmethod
    def list_for_patient(cls, patient_id: str) -> dict | None:
        """Return *outstanding* assignments for a patient in the legacy shape.

        Completed history is intentionally excluded — the patient and provider
        views only show what's still pending. Returns ``None`` when there are
        no outstanding rows, matching the previous metadata-based contract.
        """
        rows = list(
            QuestionnaireAssignment.objects.filter(
                patient__id=patient_id,
                completed_at__isnull=True,
            )
            .select_related("assigning_provider")
            .order_by("due_date", "questionnaire_name")
        )
        if not rows:
            return None
        return {"questionnaires": [cls._serialize(row) for row in rows]}

    @classmethod
    def get_one(cls, patient_id: str, questionnaire_name: str) -> dict | None:
        """Look up the patient's outstanding assignment for one questionnaire."""
        row = (
            QuestionnaireAssignment.objects.filter(
                patient__id=patient_id,
                questionnaire_name=questionnaire_name,
                completed_at__isnull=True,
            )
            .select_related("assigning_provider")
            .first()
        )
        return cls._serialize(row) if row else None

    @classmethod
    def get_outstanding_row(
        cls,
        patient_id: str,
        questionnaire_name: str,
    ) -> QuestionnaireAssignment | None:
        """Return the raw outstanding assignment row (or None).

        The submit endpoint uses this to derive the assigning provider from
        a trusted source (the row) rather than the request body, which the
        patient controls.
        """
        return (
            QuestionnaireAssignment.objects.filter(
                patient__id=patient_id,
                questionnaire_name=questionnaire_name,
                completed_at__isnull=True,
            )
            .select_related("assigning_provider")
            .first()
        )

    @classmethod
    def list_grouped(cls, patient_id: str) -> dict:
        """Return outstanding + completed history shaped for the tabbed views.

        ``pending_items``: list of serialized outstanding rows.
        ``completed_groups``: one entry per questionnaire that has any
        completed history, with ``submission_count`` and ``has_pending``
        for the "Pending responses" badge on the completed card.

        Always returns a dict (never None) so the templates have a stable
        shape to iterate over.
        """
        rows = list(
            QuestionnaireAssignment.objects.filter(patient__id=patient_id)
            .select_related("assigning_provider")
            .order_by("questionnaire_name", "-date_assigned")
        )

        pending_items: list[dict] = []
        completed_by_name: dict[str, list[QuestionnaireAssignment]] = {}
        pending_names: set[str] = set()
        for row in rows:
            if row.completed_at is None:
                pending_items.append(cls._serialize(row))
                pending_names.add(row.questionnaire_name)
            else:
                completed_by_name.setdefault(row.questionnaire_name, []).append(row)

        completed_groups: list[dict] = []
        for name, group_rows in completed_by_name.items():
            sorted_rows = sorted(
                group_rows,
                key=lambda r: r.completed_at or datetime.min,
                reverse=True,
            )
            latest = sorted_rows[0]
            completed_groups.append({
                "questionnaire_name": name,
                "latest_completed_date": (
                    latest.completed_at.date().isoformat()
                    if latest.completed_at
                    else ""
                ),
                "latest_assigning_provider": cls._provider_display(
                    latest.assigning_provider
                ),
                "submission_count": len(sorted_rows),
                "submission_dates": (submission_dates := [
                    (
                        r.completed_at.date().isoformat()
                        if r.completed_at
                        else ""
                    )
                    for r in sorted_rows
                ]),
                # JSON-string variant for the provider-view history popover's
                # `data-submission-dates` attribute, which expects a literal
                # JSON array in the rendered HTML.
                "submission_dates_json": json.dumps(submission_dates),
                "has_pending": name in pending_names,
            })
        completed_groups.sort(
            key=lambda g: g["latest_completed_date"], reverse=True
        )

        # Sort pending by due date so the most urgent shows first.
        pending_items.sort(key=lambda p: p.get("due_date") or "")

        return {
            "pending_items": pending_items,
            "completed_groups": completed_groups,
            "pending_names": sorted(pending_names),
        }

    @classmethod
    def get_completed_entries(
        cls,
        patient_id: str,
        questionnaire_name: str,
    ) -> list[dict]:
        """Return all completed submissions of this questionnaire, newest first.

        Each entry carries the serialized base fields plus ``submitted_answers``
        so the review template can render the patient's actual answers.
        """
        rows = (
            QuestionnaireAssignment.objects.filter(
                patient__id=patient_id,
                questionnaire_name=questionnaire_name,
                completed_at__isnull=False,
            )
            .select_related("assigning_provider")
            .order_by("-completed_at")
        )
        result: list[dict] = []
        for row in rows:
            entry = cls._serialize(row)
            entry["completed_date"] = (
                row.completed_at.date().isoformat() if row.completed_at else ""
            )
            entry["submitted_answers"] = row.submitted_answers or []
            result.append(entry)
        return result

    @classmethod
    def assign(
        cls,
        patient_id: str,
        questionnaires: list[dict],
        *,
        assigning_provider_uuid: str,
    ) -> list[QuestionnaireAssignment]:
        """Upsert outstanding assignments for a patient.

        Each entry must have ``questionnaire_name`` and ``due_date`` (ISO
        date string). The assigning staff is supplied once via the keyword
        arg by the caller — the API handler derives this from the trusted
        session header, so a malicious client cannot substitute another
        staff member's UUID per-entry in the request body.

        Reassigning a questionnaire that already has an outstanding row
        refreshes its due date and provider in place; reassigning a
        questionnaire whose previous assignment was completed creates a
        fresh outstanding row alongside the history. Raises
        ``CustomStaff.DoesNotExist`` if ``assigning_provider_uuid`` does
        not resolve.
        """
        patient = CustomPatient.objects.get(id=patient_id)
        provider = CustomStaff.objects.get(id=assigning_provider_uuid)
        results: list[QuestionnaireAssignment] = []
        for entry in questionnaires:
            name = entry["questionnaire_name"]
            # Pinned to outstanding rows via completed_at=None; that field is
            # part of the partial unique constraint and is therefore part of
            # the identity used for the upsert.
            row, _created = QuestionnaireAssignment.objects.update_or_create(
                patient=patient,
                questionnaire_name=name,
                completed_at=None,
                defaults={
                    "assigning_provider": provider,
                    "due_date": entry["due_date"],
                },
            )
            results.append(row)
        return results

    @classmethod
    def unassign(cls, patient_id: str, questionnaire_name: str) -> int:
        """Delete the outstanding assignment for this questionnaire, if any.

        Completed history rows are not touched — only the still-pending row
        is removed, which matches the "provider cancels an assignment"
        semantic without rewriting history.
        """
        deleted, _ = QuestionnaireAssignment.objects.filter(
            patient__id=patient_id,
            questionnaire_name=questionnaire_name,
            completed_at__isnull=True,
        ).delete()
        return deleted

    @classmethod
    def mark_completed(
        cls,
        patient_id: str,
        questionnaire_name: str,
        submitted_answers: list[dict] | None = None,
        completed_at: datetime | None = None,
    ) -> int:
        """Stamp the outstanding row as completed. Returns rows updated.

        ``submitted_answers`` is the list of ``{question_id, question_type,
        answer}`` dicts the patient submitted; it's snapshotted onto the row
        so the review template can render it later, independent of any
        questionnaire-version changes that may have happened since.

        Returns 0 when there is no outstanding assignment — callers (e.g.
        the submit endpoint) should treat that as a no-op so a duplicate
        submission does not produce a duplicate note.
        """
        return QuestionnaireAssignment.objects.filter(
            patient__id=patient_id,
            questionnaire_name=questionnaire_name,
            completed_at__isnull=True,
        ).update(
            completed_at=completed_at or datetime.now(timezone.utc),
            submitted_answers=submitted_answers or [],
        )

    @classmethod
    def migrate_from_metadata(
        cls,
        patient_id: str,
        metadata_payload: dict,
    ) -> dict:
        """Create rows from a legacy ``portal_forms`` metadata blob.

        Handles both metadata shapes:

        - **main / v0.0.2**: entries are all pending — no ``completed_date``.
          Each becomes an outstanding QuestionnaireAssignment row.
        - **v2 (v0.1.x)**: entries can have ``completed_date`` and
          ``submitted_answers``. Completed entries become history rows
          (``completed_at`` set, ``submitted_answers`` snapshotted).
          A top-level ``daily_notes`` map ({"YYYY-MM-DD": note_uuid})
          becomes PatientDailyNote rows.

        Returns ``{"created": n, "skipped": n, "errors": [...]}``.
        Idempotent:

        - Outstanding entries: skip if an outstanding row already exists
          for (patient, questionnaire_name).
        - Completed entries: skip if a completed row already exists for
          (patient, questionnaire_name, completed_at).
        - Daily notes: update_or_create on (patient, date).

        Rows whose ``assigning_provider.key`` does not resolve to a Staff
        record are logged and skipped.
        """
        created = 0
        skipped = 0
        errors: list[str] = []

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            errors.append(f"patient {patient_id} not found")
            return {"created": 0, "skipped": 0, "errors": errors}

        # Bulk-resolve every referenced provider in one query rather than
        # one CustomStaff.objects.get() per questionnaire entry. Missing
        # uuids surface as a None lookup below, preserving the original
        # per-entry skip-and-log behavior.
        provider_uuids = {
            (e.get("assigning_provider") or {}).get("key")
            for e in metadata_payload.get("questionnaires", []) or []
        }
        provider_uuids.discard(None)
        providers_by_uuid = CustomStaff.objects.in_bulk(
            provider_uuids, field_name="id"
        )

        for entry in metadata_payload.get("questionnaires", []) or []:
            name = entry.get("questionnaire_name")
            provider_block = entry.get("assigning_provider") or {}
            provider_uuid = provider_block.get("key")
            due_date = entry.get("due_date")
            completed_date_str = entry.get("completed_date")
            if not (name and provider_uuid and due_date):
                skipped += 1
                errors.append(
                    f"patient {patient_id} questionnaire {name!r}: missing required fields"
                )
                continue
            provider = providers_by_uuid.get(provider_uuid)
            if provider is None:
                skipped += 1
                errors.append(
                    f"patient {patient_id} questionnaire {name!r}: staff {provider_uuid} not found"
                )
                continue

            if completed_date_str:
                # v2 completed history row.
                completed_at = _parse_iso_date(completed_date_str)
                if completed_at is None:
                    skipped += 1
                    errors.append(
                        f"patient {patient_id} questionnaire {name!r}: "
                        f"could not parse completed_date {completed_date_str!r}"
                    )
                    continue
                already = QuestionnaireAssignment.objects.filter(
                    patient=patient,
                    questionnaire_name=name,
                    completed_at=completed_at,
                ).exists()
                if already:
                    skipped += 1
                    continue
                row = QuestionnaireAssignment.objects.create(
                    patient=patient,
                    questionnaire_name=name,
                    assigning_provider=provider,
                    due_date=due_date,
                    completed_at=completed_at,
                    submitted_answers=entry.get("submitted_answers") or [],
                )
                created += 1
            else:
                # Outstanding row (main-style or v2 pending entry).
                outstanding_exists = QuestionnaireAssignment.objects.filter(
                    patient=patient,
                    questionnaire_name=name,
                    completed_at__isnull=True,
                ).exists()
                if outstanding_exists:
                    skipped += 1
                    continue
                row = QuestionnaireAssignment.objects.create(
                    patient=patient,
                    questionnaire_name=name,
                    assigning_provider=provider,
                    due_date=due_date,
                )
                created += 1

            # Preserve the original assignment timestamp when present.
            original = entry.get("date_assigned")
            if original:
                parsed = _parse_iso_date(original)
                if parsed is not None:
                    QuestionnaireAssignment.objects.filter(pk=row.pk).update(
                        date_assigned=parsed
                    )

        # Migrate the daily-notes map. Imported here to keep the model
        # graph dependency local — the rest of the service doesn't need it.
        from patient_portal_forms.models import PatientDailyNote

        daily_notes_map = metadata_payload.get("daily_notes") or {}
        for date_str, note_uuid in daily_notes_map.items():
            if not (date_str and note_uuid):
                continue
            parsed_date = _parse_iso_date(date_str)
            if parsed_date is None:
                errors.append(
                    f"patient {patient_id} daily_notes: could not parse date {date_str!r}"
                )
                continue
            PatientDailyNote.objects.update_or_create(
                patient=patient,
                date=parsed_date.date(),
                defaults={"note_uuid": str(note_uuid)},
            )

        return {"created": created, "skipped": skipped, "errors": errors}


def _parse_iso_date(value: str) -> datetime | None:
    """Parse an ISO date or datetime string into a datetime, or None on failure.

    Python 3.11+ ``datetime.fromisoformat`` already accepts date-only strings
    (e.g. ``"2026-05-14"``) as well as full datetimes, so no separate fallback
    is needed.
    """
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        log.warning(f"[ppf migration] could not parse date_assigned: {value!r}")
        return None
