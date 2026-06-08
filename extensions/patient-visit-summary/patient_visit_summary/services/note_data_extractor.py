"""Shared service for extracting all command data from a note.

This class centralizes the DB queries and data formatting logic
so that multiple UI handlers (Patient Visit Summary, Customize & Print)
can consume the same data without duplicating queries.
"""

from __future__ import annotations

from typing import Any

import arrow
from django.db.models import Q

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.assessment import Assessment
from canvas_sdk.v1.data.billing import BillingLineItemStatus
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.common import ContactPointSystem, ContactPointState
from canvas_sdk.v1.data.imaging import ImagingReport
from canvas_sdk.v1.data.lab import LabReport
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.prescription import Prescription
from canvas_sdk.v1.data.questionnaire import InterviewQuestionResponse
from canvas_sdk.v1.data.referral import ReferralReport
from canvas_sdk.v1.data.uncategorized_clinical_document import (
    UncategorizedClinicalDocument,
)
from canvas_sdk.v1.data.staff import StaffRole
from canvas_sdk.v1.data.goal import GoalPriority, GoalAchievementStatus

from patient_visit_summary.services.code_utils import coded_title


# `custom_html` is a new field on Command (per docs at
# https://docs.canvasmedical.com/sdk/data-command/#command — "stores HTML
# content that is rendered alongside the command in the note") that's still
# being rolled out. Detect at import time so we can gracefully omit it from
# the fetch on instances that haven't been migrated yet. We probe via
# ``hasattr`` on the model class rather than ``_meta`` because the plugin
# sandbox disallows attribute access to names starting with an underscore.
# Django model fields become class-level descriptors, so ``hasattr`` is a
# safe and accurate way to detect their presence.
_COMMAND_HAS_CUSTOM_HTML = hasattr(Command, "custom_html")


VITALS_ENUM_DICT = {
    "blood_pressure_position_and_site": {
        "0": "Sitting, Right Upper Extremity",
        "1": "Sitting, Left Upper Extremity",
        "2": "Sitting, Right Lower Extremity",
        "3": "Sitting, Left Lower Extremity",
        "4": "Standing, Right Upper Extremity",
        "5": "Standing, Left Upper Extremity",
        "6": "Standing, Right Lower Extremity",
        "7": "Standing, Left Lower Extremity",
        "8": "Supine, Right Upper Extremity",
        "9": "Supine, Left Upper Extremity",
        "10": "Supine, Right Lower Extremity",
        "11": "Supine, Left Lower Extremity",
    },
    "body_temperature_site": {
        "0": "Axillary",
        "1": "Oral",
        "2": "Rectal",
        "3": "Temporal",
        "4": "Tympanic",
    },
    "pulse_rhythm": {
        "0": "Regular",
        "1": "Irregularly Irregular",
        "2": "Regularly Irregular",
    },
}

ASSESSMENT_STATUS_DICT = {
    "improved": "Improved",
    "stable": "Unchanged",
    "deteriorated": "Deteriorated",
}


def format_icd10_code(icd10_code: str) -> str:
    """Format an ICD-10 code with a dot after the third character."""
    if not icd10_code:
        return ""
    icd10_code = icd10_code.strip().upper()
    if len(icd10_code) > 3:
        return icd10_code[:3] + "." + icd10_code[3:]
    return icd10_code


def _annotate_coded_titles(entries: list, field_key: str) -> None:
    """Attach a ``coded_title`` (name + CPT/CVX suffix) to each command dict.

    ``field_key`` is the entry's main coding field (e.g. "coding" for immunize,
    "perform" for procedures, "statement" for immunization statements).
    """
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        coding_field = entry.get(field_key)
        text = coding_field.get("text", "") if isinstance(coding_field, dict) else ""
        entry["coded_title"] = coded_title(text, coding_field)


class NoteDataExtractor:
    """Extracts all command and contextual data from a note for rendering.

    Usage:
        extractor = NoteDataExtractor(patient_id="123", note_id="456")
        context = extractor.get_template_context()
    """

    def __init__(self, patient_id: str, note_id: str) -> None:
        # `note_id` is the Note's external UUID (`Note.id`), not the internal dbid.
        self.patient = Patient.objects.get(id=patient_id)
        self.note = Note.objects.get(id=note_id)

    def _fetch_latest_command_data(self, schema_key: str) -> dict | None:
        """Fetch the data dict of the most recent committed command of a type in this note."""
        return (
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("-dbid")
            .values_list("data", flat=True)
            .first()
        )

    def _fetch_all_commands_data(self, schema_key: str) -> list[dict]:
        """Fetch data dicts for all committed commands of a type in this note.

        Each returned dict also carries the command's UUID under
        ``_command_uuid`` so callers / renderers don't have to position-match
        a separate UUID list back onto the data. When ``Command.custom_html``
        is available on the SDK, it's also stamped as ``_custom_html`` for
        the renderer to surface as an HTML body block. ``_``-prefixed keys
        are filtered out of ``extra_blocks`` and never re-emitted as fields,
        so it's safe to stash them here.
        """
        values_fields: tuple[str, ...] = ("data", "id")
        if _COMMAND_HAS_CUSTOM_HTML:
            values_fields = (*values_fields, "custom_html")
        rows = (
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .values(*values_fields)
        )
        out: list[dict] = []
        for row in rows:
            data = row.get("data")
            if not isinstance(data, dict):
                # Non-dict payloads are rare but possible; wrap so the
                # renderer's `isinstance(entry, dict)` checks don't drop us.
                data = {"_raw": data} if data is not None else {}
            entry = dict(data)
            cmd_id = row.get("id")
            if cmd_id:
                entry["_command_uuid"] = str(cmd_id)
            if custom_html := row.get("custom_html"):
                entry["_custom_html"] = custom_html
            out.append(entry)
        return out

    @staticmethod
    def _format_prescription_total_quantity(rx: Prescription) -> str:
        """Mirrors home-app's ``Prescription.pluralized_quantity_qualifier_description``
        (``home-app/api/models/prescription.py:421-428``): use the singular
        qualifier when ``potency_quantity == 1``, otherwise pluralize.
        Returns e.g. ``"30 Tablets"`` or ``"1 Capsule"``."""
        qty = rx.potency_quantity
        if qty is None:
            return ""
        qualifier = ""
        if rx.medication and rx.medication.quantity_qualifier_description:
            qualifier = rx.medication.quantity_qualifier_description
            if qty != 1 and not qualifier.endswith("s"):
                qualifier = qualifier + "s"
        qty_str = str(int(qty)) if qty == int(qty) else str(qty)
        return f"{qty_str} {qualifier}".strip()

    @staticmethod
    def _format_prescription_pharmacy(rx: Prescription) -> str:
        """Format pharmacy line like home-app's deny_refill/approve_refill
        layout (``"<name> (xxx) xxx-xxxx"``). Returns empty string when name
        or phone is missing — matches the home-app guard."""
        name = (rx.pharmacy_name or "").strip()
        phone = (rx.pharmacy_phone_number or "").strip()
        if not name or not phone:
            return ""
        if len(phone) == 10:
            phone = f"({phone[0:3]}) {phone[3:6]}-{phone[6:10]}"
        return f"{name} {phone}".strip()

    def _fetch_refill_decision_commands_data(self, schema_key: str) -> list[dict]:
        """Same as ``_fetch_all_commands_data`` but also stamps anchor
        Prescription details (``total_quantity``, ``directions``, ``pharmacy_display``)
        onto each entry. Used by approveRefill / denyRefill / approveChange /
        denyChange — the Canvas command UI surfaces these prescription-derived
        rows above the command's own fields, but ``commands_command.data``
        only stores the medication reference, not the prescription details.

        These keys are intentionally underscore-free (unlike most extractor
        stamps) because the patient-facing Django template needs to read
        them, and Django blocks attribute access on names starting with ``_``.
        ``pharmacy_display`` is suffixed to avoid colliding with the raw
        ``pharmacy`` data key on some refill commands."""
        values_fields: tuple[str, ...] = ("data", "id", "anchor_object_dbid")
        if _COMMAND_HAS_CUSTOM_HTML:
            values_fields = (*values_fields, "custom_html")
        rows = list(
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .values(*values_fields)
        )

        rx_dbids = [r["anchor_object_dbid"] for r in rows if r.get("anchor_object_dbid")]
        rx_by_dbid: dict[int, Prescription] = {}
        if rx_dbids:
            # Single query, prefetch medication so the qualifier lookup
            # doesn't N+1 inside the pluralize helper.
            rx_by_dbid = {
                rx.dbid: rx
                for rx in Prescription.objects.filter(dbid__in=rx_dbids).select_related("medication")
            }

        out: list[dict] = []
        for row in rows:
            data = row.get("data")
            if not isinstance(data, dict):
                data = {"_raw": data} if data is not None else {}
            entry = dict(data)
            if cmd_id := row.get("id"):
                entry["_command_uuid"] = str(cmd_id)
            if custom_html := row.get("custom_html"):
                entry["_custom_html"] = custom_html
            if rx := rx_by_dbid.get(row.get("anchor_object_dbid")):
                if qty := self._format_prescription_total_quantity(rx):
                    entry["total_quantity"] = qty
                if directions := (rx.sig_original_input or "").strip():
                    entry["directions"] = directions
                if pharmacy := self._format_prescription_pharmacy(rx):
                    entry["pharmacy_display"] = pharmacy
            out.append(entry)
        return out

    # ------------------------------------------------------------------
    # Review-command reference data
    #
    # Lab / Imaging / Referral / Uncategorized review commands attach to
    # one or more *report* anchor objects (LabReport, ImagingReport,
    # ReferralReport, UncategorizedClinicalDocument). The Canvas note print
    # surfaces those reports under a "Reference Data" section at the end —
    # we instead stamp pre-rendered HTML on each review entry as
    # ``_reference_html`` so the renderer can emit it inline as a
    # ``body_html`` block right after the review's own fields.
    #
    # The reverse relation in every case is ``<Review>.reports`` (see e.g.
    # ``canvas-plugins/canvas_sdk/v1/data/lab.py:72``,
    # ``imaging.py:118``, ``referral.py:127``,
    # ``uncategorized_clinical_document.py:64``). We bulk-fetch per review
    # type to keep the query count flat.
    # ------------------------------------------------------------------

    @staticmethod
    def _esc(s: Any) -> str:
        """Minimal HTML escape so user-entered comments can't inject markup
        when we stitch them into the pre-rendered reference-data HTML. We
        don't pull in Django's escape() because the plugin sandbox is
        restrictive about which imports are allowed."""
        if s is None:
            return ""
        return (
            str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _attach_lab_review_reference_html(self, entries: list[dict]) -> None:
        """For each labReview entry, render its linked LabReports as an HTML
        table (Name / Reference / Value / Units) — mirrors home-app's
        ``lab_review_document.html`` template."""
        if not entries:
            return
        cmd_uuids = [e["_command_uuid"] for e in entries if isinstance(e, dict) and e.get("_command_uuid")]
        if not cmd_uuids:
            return
        review_dbid_by_cmd: dict[str, int] = {}
        for row in Command.objects.filter(id__in=cmd_uuids).values("id", "anchor_object_dbid"):
            if dbid := row.get("anchor_object_dbid"):
                review_dbid_by_cmd[str(row["id"])] = dbid
        if not review_dbid_by_cmd:
            return
        # Bulk-prefetch reports → values (+ codings for the test name) and
        # tests (also for the test name on the report header).
        # ``entered_in_error__isnull=True`` and ``junked=False`` are both
        # required — retracted lab reports must NOT leak into the Reference
        # Data block, which lands in a finalized PDF attached to the chart
        # as a FHIR DocumentReference (REVIEW.md / CLAUDE.md 🔴 rule).
        # LabReport inherits from AuditedModel so it exposes both fields.
        reports_by_review: dict[int, list[LabReport]] = {}
        report_qs = (
            LabReport.objects
            .filter(
                review_id__in=review_dbid_by_cmd.values(),
                entered_in_error__isnull=True,
                junked=False,
            )
            .prefetch_related("values__codings", "tests")
            .order_by("original_date")
        )
        for report in report_qs:
            reports_by_review.setdefault(report.review_id, []).append(report)
        for entry in entries:
            cmd_uuid = entry.get("_command_uuid") if isinstance(entry, dict) else None
            review_dbid = review_dbid_by_cmd.get(cmd_uuid) if cmd_uuid else None
            reports = reports_by_review.get(review_dbid, []) if review_dbid else []
            if not reports:
                continue
            entry["_reference_html"] = self._format_lab_reports_html(reports)

    def _format_lab_reports_html(self, reports: list[LabReport]) -> str:
        """Render one or more LabReports as tables of Name / Reference / Value
        / Units. The per-report title (test name + date) is intentionally
        omitted — it's already in the review command's heading right above.

        TODO(canvas-plugins#1749): when ``LabReportRemark`` is exposed in the
        SDK, prepend ``<strong>Comment:</strong> <concatenated remarks>``
        above the table — same pattern as referral / uncategorized reports.
        See https://github.com/canvas-medical/canvas-plugins/issues/1749.
        """
        tables: list[str] = []
        for report in reports:
            rows_html: list[str] = []
            for value in report.values.all():
                if not value.value:
                    continue
                # Prefer LabValueCoding name (LOINC), fall back to linked
                # LabTest's ontology name.
                first_coding = next(iter(value.codings.all()), None)
                row_name = (first_coding.name if first_coding else "") or ""
                if not row_name and value.test_id:
                    for t in report.tests.all():
                        if t.dbid == value.test_id:
                            row_name = t.ontology_test_name
                            break
                ref = value.reference_range or "-"
                val_text = value.value
                if value.abnormal_flag:
                    val_text = f"{val_text} {value.abnormal_flag}"
                rows_html.append(
                    f"<tr><td>{self._esc(row_name)}</td>"
                    f"<td>{self._esc(ref)}</td>"
                    f"<td>{self._esc(val_text)}</td>"
                    f"<td>{self._esc(value.units)}</td></tr>"
                )
            if rows_html:
                tables.append(
                    "<table class='ref-data-table'>"
                    "<thead><tr><th>Name</th><th>Reference</th>"
                    "<th>Value</th><th>Units</th></tr></thead>"
                    f"<tbody>{''.join(rows_html)}</tbody></table>"
                )
        if not tables:
            return ""
        return (
            "<div class='ref-data-report'>"
            "<div class='ref-data-heading'>Reference Data:</div>"
            f"{''.join(tables)}</div>"
        )

    def _attach_imaging_review_reference_html(self, entries: list[dict]) -> None:
        """No-op until ImagingReportCoding is exposed in the SDK.

        TODO(canvas-plugins#1748): the per-field values that make up an
        ImagingReport body (Comment, Interpretation, etc.) live on
        ``ImagingReportCoding``, which isn't reachable from a plugin today.
        We have only the report's ``name`` and ``original_date`` — but those
        are already in the review command's heading right above, so rendering
        them again would be redundant. Surface a real "Reference Data:" block
        once the codings ship — see
        https://github.com/canvas-medical/canvas-plugins/issues/1748.
        """
        return

    def _attach_referral_review_reference_html(self, entries: list[dict]) -> None:
        """For each referralReview entry, surface the linked ReferralReports'
        comment text under a single ``Reference Data:`` heading. Per-report
        titles (specialty + date) are intentionally omitted — those are
        already in the review command's heading right above."""
        if not entries:
            return
        cmd_uuids = [e["_command_uuid"] for e in entries if isinstance(e, dict) and e.get("_command_uuid")]
        if not cmd_uuids:
            return
        review_dbid_by_cmd: dict[str, int] = {}
        for row in Command.objects.filter(id__in=cmd_uuids).values("id", "anchor_object_dbid"):
            if dbid := row.get("anchor_object_dbid"):
                review_dbid_by_cmd[str(row["id"])] = dbid
        if not review_dbid_by_cmd:
            return
        # Filter retracted reports out. ``ReferralReport`` inherits from
        # ``TimestampedModel`` (not ``AuditedModel``) in the SDK so it doesn't
        # expose ``entered_in_error`` — ``junked`` is the equivalent retraction
        # marker on this model (see canvas-plugins ``referral.py:114``).
        reports_by_review: dict[int, list[ReferralReport]] = {}
        for report in (
            ReferralReport.objects
            .filter(
                review_id__in=review_dbid_by_cmd.values(),
                junked=False,
            )
            .order_by("original_date")
        ):
            reports_by_review.setdefault(report.review_id, []).append(report)
        for entry in entries:
            cmd_uuid = entry.get("_command_uuid") if isinstance(entry, dict) else None
            review_dbid = review_dbid_by_cmd.get(cmd_uuid) if cmd_uuid else None
            reports = reports_by_review.get(review_dbid, []) if review_dbid else []
            if not reports:
                continue
            bodies = [
                f"<div class='ref-data-body'><strong>Comment:</strong> {self._esc(r.comment)}</div>"
                for r in reports if r.comment
            ]
            if not bodies:
                continue
            entry["_reference_html"] = (
                "<div class='ref-data-report'>"
                "<div class='ref-data-heading'>Reference Data:</div>"
                f"{''.join(bodies)}</div>"
            )

    def _attach_uncategorized_review_reference_html(self, entries: list[dict]) -> None:
        """For each uncategorizedDocumentReview entry, surface the linked
        UncategorizedClinicalDocuments' comment text under a single
        ``Reference Data:`` heading. Per-document titles are intentionally
        omitted — those are already in the review command's heading."""
        if not entries:
            return
        cmd_uuids = [e["_command_uuid"] for e in entries if isinstance(e, dict) and e.get("_command_uuid")]
        if not cmd_uuids:
            return
        review_dbid_by_cmd: dict[str, int] = {}
        for row in Command.objects.filter(id__in=cmd_uuids).values("id", "anchor_object_dbid"):
            if dbid := row.get("anchor_object_dbid"):
                review_dbid_by_cmd[str(row["id"])] = dbid
        if not review_dbid_by_cmd:
            return
        # Filter retracted documents out. ``UncategorizedClinicalDocument``
        # inherits from ``TimestampedModel`` (not ``AuditedModel``) in the SDK
        # so it doesn't expose ``entered_in_error`` — ``junked`` is the
        # equivalent retraction marker (see canvas-plugins
        # ``uncategorized_clinical_document.py:75``).
        reports_by_review: dict[int, list[UncategorizedClinicalDocument]] = {}
        for report in (
            UncategorizedClinicalDocument.objects
            .filter(
                review_id__in=review_dbid_by_cmd.values(),
                junked=False,
            )
        ):
            reports_by_review.setdefault(report.review_id, []).append(report)
        for entry in entries:
            cmd_uuid = entry.get("_command_uuid") if isinstance(entry, dict) else None
            review_dbid = review_dbid_by_cmd.get(cmd_uuid) if cmd_uuid else None
            reports = reports_by_review.get(review_dbid, []) if review_dbid else []
            if not reports:
                continue
            bodies = [
                f"<div class='ref-data-body'><strong>Comment:</strong> {self._esc(r.comment)}</div>"
                for r in reports if r.comment
            ]
            if not bodies:
                continue
            entry["_reference_html"] = (
                "<div class='ref-data-report'>"
                "<div class='ref-data-heading'>Reference Data:</div>"
                f"{''.join(bodies)}</div>"
            )

    @staticmethod
    def _attach_poc_value_rows(entries: list[dict]) -> None:
        """Stamp ``value_rows`` on each POC Lab Test entry — a template-ordered
        list of ``{label, units, value}`` dicts pulled from
        ``template.extra.fields`` + the ``test_values|<lowercase label>`` keys.

        The patient-facing Django template iterates this directly, which it
        can't do against the raw entry dict because (a) Django can't look up
        keys with computed names like ``test_values|hemoglobin a1c``, and
        (b) Django blocks attribute access to names starting with ``_``, so
        we don't underscore-prefix this stamp. ``_blocks_poc_lab_test``
        adds it to its ``shown_keys`` set so it doesn't leak into
        ``extra_blocks``.
        """
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            template = entry.get("template") if isinstance(entry.get("template"), dict) else {}
            fields = (template.get("extra") or {}).get("fields") if isinstance(template.get("extra"), dict) else None
            if not isinstance(fields, list):
                continue
            rows: list[dict] = []
            for f in fields:
                if not isinstance(f, dict):
                    continue
                label = (f.get("label") or "").strip()
                if not label:
                    continue
                rows.append({
                    "label": label,
                    "units": (f.get("units") or "").strip(),
                    "value": entry.get(f"test_values|{label.lower()}") or "",
                })
            if rows:
                entry["value_rows"] = rows

    # Reason-code → display text. Verbatim copy of the same mapping in
    # ``command_blocks._REFILL_REASON_CODE_DISPLAYS`` so the patient template
    # can render translated reasons without importing private helpers from
    # the block-builder module. Kept in sync with home-app's
    # ``builtin_content/core_types/commands/sdk/deny_refill.py:24-40`` —
    # the same 14 codes apply to both deny_refill and deny_change.
    _REFILL_REASON_CODE_DISPLAYS: dict[str, str] = {
        "AA": "Patient unknown to the prescriber",
        "AB": "Patient never under provider care",
        "AC": "Patient no longer under provider care",
        "AD": "Refill too soon",
        "AE": "Medication never prescribed for patient",
        "AF": "Patient should contact provider",
        "AG": "Refill not appropriate",
        "AH": "Patient has picked up prescription",
        "AJ": "Patient has picked up partial fill of prescription",
        "AK": "Patient has not picked up prescription, drug returned to stock",
        "AM": "Patient needs appointment",
        "AN": "Prescriber not associated with this practice or location",
        "AO": "No attempt will be made to obtain Prior Authorization",
        "AP": "Request already responded to by other means (e.g. phone or fax)",
    }

    @classmethod
    def _attach_refill_reason_displays(cls, entries: list[dict]) -> None:
        """Stamp ``reason_display`` on each deny refill / deny change entry —
        the human-readable label for ``reason_code``. Used by the patient
        template so it doesn't have to render the opaque 2-letter code.
        Not underscore-prefixed because Django blocks attribute access on
        ``_``-leading names; ``_blocks_refill_decision`` adds it to its
        ``shown_keys`` set so ``extra_blocks`` doesn't re-emit it."""
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            code = (entry.get("reason_code") or "").strip()
            if code:
                entry["reason_display"] = cls._REFILL_REASON_CODE_DISPLAYS.get(code, code)

    def _fetch_commands_fields(self, schema_key: str, *fields: str) -> list[dict]:
        """Fetch specific fields for all committed commands of a type in this note."""
        return list(
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .values(*fields)
            .all()
        )

    def _format_questionnaires(
        self,
        questionnaire_names: list[str] | None = None,
        questionnaire_type: str | None = None,
    ) -> list[dict]:
        """Format questionnaire or structured assessment commands into display dicts."""
        schema_key = questionnaire_type or "questionnaire"

        raw_data = self._fetch_commands_fields(schema_key, "data", "modified")

        if questionnaire_names:
            q_filter = Q()
            for name in questionnaire_names:
                q_filter = q_filter | Q(data__questionnaire__text=name)
            # Re-query with filter since we have a list
            raw_data = [d for d in raw_data if any(
                d["data"].get("questionnaire", {}).get("text", "") == name
                for name in questionnaire_names
            )]

        result = []
        for item in raw_data:
            last_updated_dt = arrow.get(item["modified"]).to("US/Eastern")
            last_updated = f'{last_updated_dt.format("M/D/YY")} at {last_updated_dt.format("h:mm A")} EDT'
            assessment: dict[str, Any] = {
                "name": item["data"]["questionnaire"]["text"],
                "last_updated": last_updated,
            }
            if item_result := item["data"].get("result"):
                assessment["result"] = item_result

            questions_and_answers = []
            for question in item["data"]["questionnaire"]["extra"]["questions"]:
                qa: dict[str, Any] = {
                    "label": question["label"],
                    "code": question["coding"]["code"],
                }
                response_type = question["type"]
                question_answer = item["data"][question["name"]]

                answer = ""
                if response_type == "MULT":
                    selected_parts = []
                    for q in question_answer or []:
                        if q.get("selected") is not True:
                            continue
                        text = q.get("text", "")
                        comment = (q.get("comment") or "").strip()
                        if comment:
                            selected_parts.append(f"{text} ({comment})")
                        else:
                            selected_parts.append(text)
                    answer = ", ".join(selected_parts)
                elif response_type in ("TXT", "INT"):
                    if question_answer is not None and question_answer != "":
                        answer = str(question_answer)
                elif response_type == "SING":
                    single = [
                        c["label"]
                        for c in question["options"]
                        if c["pk"] == question_answer
                    ]
                    if single:
                        answer = single[0]

                if not answer.strip():
                    continue

                qa["answer"] = answer
                questions_and_answers.append(qa)
            assessment["questions_and_answers"] = questions_and_answers
            result.append(assessment)
        return result

    def _format_ros_or_exam(self, schema_key: str) -> list[dict]:
        """Format ROS or physical exam commands into display dicts."""
        raw_data = self._fetch_all_commands_data(schema_key)
        result = []
        for ros in raw_data:
            ros_answers: dict[str, Any] = {
                "questionnaire": ros["questionnaire"]["text"],
                "questions_and_answers": [],
            }
            for question in ros["questionnaire"]["extra"]["questions"]:
                question_id = question["pk"]
                if ros.get(f"skip-{question_id}") is False:
                    continue
                answers = []
                question_name = question["label"]
                if question["type"] == "MULT":
                    for q in ros[question["name"]]:
                        if q.get("selected") is not True:
                            continue
                        text = q.get("text", "")
                        comment = (q.get("comment") or "").strip()
                        answers.append(f"{text} ({comment})" if comment else text)
                elif question["type"] == "TXT":
                    answers = [ros[question["name"]]]
                if answers:
                    ros_answers["questions_and_answers"].append(
                        {"label": question_name, "answer": ", ".join(answers)}
                    )
            result.append(ros_answers)
        return result

    def _get_diagnoses_from_structured_assessments(self) -> list[tuple[str, str]]:
        """Extract ICD-10 diagnoses triggered by structured assessment answers."""
        structured_data = self._fetch_all_commands_data("structuredAssessment")
        if not structured_data:
            return []

        # Resolve the ICD-10 trigger questions for every questionnaire on the
        # note in a single query, then group in Python — rather than one query
        # per structured assessment.
        questionnaire_ids = {
            a["questionnaire"]["extra"]["pk"] for a in structured_data
        }
        triggers_by_questionnaire: dict[Any, set] = {}
        for q_id, question_id in InterviewQuestionResponse.objects.filter(
            questionnaire_id__in=questionnaire_ids,
            question__response_option_set__code_system="ICD-10",
        ).values_list("questionnaire_id", "question_id"):
            triggers_by_questionnaire.setdefault(q_id, set()).add(question_id)

        icd10_codes: list[str] = []
        for assessment_data in structured_data:
            question_option_code_map: dict[str, dict] = {}
            questionnaire_id = assessment_data["questionnaire"]["extra"]["pk"]
            trigger_question_ids = triggers_by_questionnaire.get(questionnaire_id, set())

            for question in assessment_data["questionnaire"]["extra"]["questions"]:
                if question["pk"] in trigger_question_ids:
                    question_option_code_map[question["name"]] = {
                        "type": question["type"],
                        "codes": {opt["pk"]: opt["code"] for opt in question["options"]},
                    }

            for question_name, info in question_option_code_map.items():
                response = assessment_data[question_name]
                if info["type"] == "MULT":
                    codes = [
                        info["codes"][c["value"]]
                        for c in response
                        if c.get("selected") is True and info["codes"].get(c["value"])
                    ]
                    icd10_codes.extend(codes)
                elif info["type"] == "SING":
                    code = info["codes"].get(response)
                    if code:
                        icd10_codes.append(code)

        icd10_codes = list(set(icd10_codes))
        if not icd10_codes:
            return []

        note_assessments = (
            Assessment.objects.filter(
                note=self.note,
                condition__entered_in_error__isnull=True,
                condition__codings__system="ICD-10",
                condition__codings__code__in=icd10_codes,
                interview__isnull=False,
            )
            .select_related("condition")
            .prefetch_related("condition__codings")
        )

        result = []
        for assessment in note_assessments:
            # Read from the prefetched `condition__codings` cache (`.all()`) — a
            # `.filter()` here would issue a fresh query per assessment and defeat
            # the prefetch above.
            coding = next(
                (c for c in assessment.condition.codings.all() if c.system == "ICD-10"),
                None,
            )
            if coding:
                result.append((coding.display, format_icd10_code(coding.code)))
        return result

    def _get_header_context(self) -> dict[str, Any]:
        """Extract appointment, provider, and header info."""
        appointment = (
            Appointment.objects.filter(note=self.note)
            .order_by("-dbid")
            .only("id", "start_time", "provider")
            .first()
        )

        if appointment:
            appointment_date = arrow.get(appointment.start_time).to("US/Eastern").format("MMMM D, YYYY")
            provider = appointment.provider
        else:
            appointment_date = arrow.get(self.note.datetime_of_service).to("US/Eastern").format("MMMM D, YYYY")
            provider = self.note.provider

        provider_top_role = (
            provider.roles.filter(domain__in=StaffRole.RoleDomain.clinical_domains())
            .order_by("-domain_privilege_level")
            .first()
        )

        return {
            "appointment_date": appointment_date,
            "provider": provider,
            "provider_top_role": provider_top_role,
        }

    def _get_signature_lines(self) -> list[dict]:
        """Lines for the printout's SIGNATURES block.

        Mirrors home-app's ``get_nsce_for_print`` (``printer_data_preparer_service``):

        - For sig-required note types, walk SIGNED + LOCKED + UNLOCKED events
          in chronological order. Emit a "signed" line for each SIGNED
          event, and an "amendment" line for each UNLOCKED event whose
          immediate predecessor was SIGNED. LOCKED events serve as
          context only; they're an internal transition that always
          precedes the SIGNED event by a moment, so emitting one would
          duplicate the signature line (KOALA-style behaviour).
        - For non-sig-required note types, emit LOCKED + UNLOCKED events.

        Append an italicized "currently unsigned" trailer whenever the
        note is editable right now, or when there are no signature events
        at all.

        Each line is ``{text: str, italic: bool}``.
        """
        def _format_dt(dt) -> str:
            if dt is None:
                return ""
            local = arrow.get(dt).to("US/Eastern")
            tz_abbr = local.datetime.strftime("%Z") or ""
            base = local.format("M/D/YY [at] h:mm A")
            return f"{base} {tz_abbr}".strip()

        def _user_name(user) -> str:
            if user is None:
                return "Unknown"
            try:
                person = user.person_subclass
            except Exception:
                return "Unknown"
            first = (getattr(person, "first_name", "") or "").strip()
            last = (getattr(person, "last_name", "") or "").strip()
            full = f"{first} {last}".strip()
            return full or "Unknown"

        is_sig_required = bool(getattr(
            getattr(self.note, "note_type_version", None), "is_sig_required", False,
        ))
        if is_sig_required:
            lock_state = NoteStates.SIGNED
            relevant_states = {
                NoteStates.SIGNED,
                NoteStates.LOCKED,
                NoteStates.UNLOCKED,
            }
        else:
            lock_state = NoteStates.LOCKED
            relevant_states = {NoteStates.LOCKED, NoteStates.UNLOCKED}

        events = list(
            self.note.state_history
            .filter(state__in=list(relevant_states))
            .order_by("created", "id")
        )

        lines: list[dict] = []
        for i, event in enumerate(events):
            who = _user_name(event.originator)
            when = _format_dt(event.created)
            if event.state == lock_state:
                lines.append({
                    "text": f"Electronically signed by {who} on {when}",
                    "italic": False,
                })
            elif event.state == NoteStates.UNLOCKED and i > 0:
                # Match home-app: only count an UNLOCKED that immediately
                # follows the lock-equivalent (SIGNED for sig-required,
                # LOCKED otherwise) — that's what represents a true
                # amendment vs. some internal/abandoned unlock.
                if events[i - 1].state == lock_state:
                    lines.append({
                        "text": f"Amendment initiated by {who} on {when}",
                        "italic": False,
                    })

        current = getattr(self.note, "current_state", None)
        is_currently_editable = bool(current and current.editable())
        if is_currently_editable or not lines:
            lines.append({
                "text": "The latest version of this note is currently unsigned.",
                "italic": True,
            })
        return lines

    def _get_practice_location_info(self) -> dict:
        """Practice-location header info for the printout (clinic name, address,
        phone, fax, logo). Mirrors home-app's note-print header_v2 template,
        which uses `note.location` as the `primary_practice_location`.

        Returns an empty dict if the note has no location attached.
        """
        location = getattr(self.note, "location", None)
        if location is None:
            return {}
        address = location.addresses.first()
        active_telecom = location.telecom.filter(state=ContactPointState.ACTIVE)
        phone = active_telecom.filter(system=ContactPointSystem.PHONE).order_by("rank").first()
        fax = active_telecom.filter(system=ContactPointSystem.FAX).order_by("rank").first()
        organization = getattr(location, "organization", None)
        info: dict[str, str] = {
            "name": location.full_name or "",
            "phone": phone.value if phone else "",
            "fax": fax.value if fax else "",
            "logo_url": (organization.logo_url if organization else "") or "",
        }
        if address is not None:
            info.update({
                "address_line1": address.line1 or "",
                "address_line2": address.line2 or "",
                "city": address.city or "",
                "state_code": address.state_code or "",
                "postal_code": address.postal_code or "",
            })
        return info

    def _get_billing_line_items(self) -> list[dict]:
        """Active billing line items for the note as patient-facing rows.

        Each entry carries the CPT (with any modifier codes appended for the
        sidebar title, e.g. ``90686-25``), the description, units, and two
        lists of ``{code, display}`` dicts: ``modifiers`` (the line item's
        modifiers with their human-readable display) and ``diagnoses`` (the
        ICD-10 codings on conditions linked through the line item's
        Assessments). No charge amounts: this is patient-facing, not a
        superbill.

        Modifier displays and CPT descriptions are stored per-row and are often
        empty on some rows even when populated on another row with the same
        code in the same note. We fill those gaps cross-referentially before
        returning so the print never shows a bare code when a sibling row
        carried a name.
        """
        items = list(
            self.note.billing_line_items
            .filter(status=BillingLineItemStatus.ACTIVE)
            .order_by("dbid")
            .prefetch_related(
                "modifiers",
                "assessments__condition__codings",
            )
        )

        # First pass: collect rows + best-known display per modifier and CPT.
        modifier_display_by_code: dict[str, str] = {}
        cpt_description_by_code: dict[str, str] = {}
        rows: list[dict] = []
        for item in items:
            cpt = (item.cpt or "").strip()
            if not cpt:
                continue
            modifier_codings = []
            for m in item.modifiers.all():
                code = (m.code or "").strip()
                if not code:
                    continue
                display = (m.display or "").strip()
                if display and not modifier_display_by_code.get(code):
                    modifier_display_by_code[code] = display
                modifier_codings.append({"code": code, "display": display})
            description = (item.description or "").strip()
            if description and not cpt_description_by_code.get(cpt):
                cpt_description_by_code[cpt] = description
            # Pull ICD-10 codings from each associated Assessment's Condition,
            # deduping by code per line item. Both the Assessment and the
            # Condition are skipped when retracted — a billing line item
            # typically persists through chart corrections, but the
            # underlying clinical record can be marked entered-in-error
            # afterward. Without these guards, retracted diagnoses would
            # leak as ICD-10 codes into the "Related Diagnoses" cell of
            # the printed billing table — a patient-data correctness defect
            # on a finalized chart-attached PDF (REVIEW.md / CLAUDE.md 🔴
            # rule). See ``_get_note_diagnoses`` below for the same pattern
            # at the note-footer level.
            diagnoses: list[dict] = []
            seen_codes: set[str] = set()
            for assess in item.assessments.all():
                if assess.entered_in_error_id is not None:
                    continue
                condition = getattr(assess, "condition", None)
                if condition is None or condition.entered_in_error_id is not None:
                    continue
                for coding in condition.codings.all():
                    if coding.system != "ICD-10":
                        continue
                    formatted = format_icd10_code(coding.code or "")
                    if not formatted or formatted in seen_codes:
                        continue
                    seen_codes.add(formatted)
                    diagnoses.append({
                        "code": formatted,
                        "display": (coding.display or "").strip(),
                    })
            rows.append({
                "cpt": cpt,
                "description": description,
                "units": item.units,
                "modifiers": modifier_codings,
                "diagnoses": diagnoses,
            })

        # Second pass: backfill missing modifier displays and CPT descriptions
        # from siblings on the same note, then build the final composite code.
        result: list[dict] = []
        for row in rows:
            for m in row["modifiers"]:
                if not m["display"]:
                    m["display"] = modifier_display_by_code.get(m["code"], "")
            description = row["description"] or cpt_description_by_code.get(
                row["cpt"], ""
            )
            code = (
                "-".join([row["cpt"], *(m["code"] for m in row["modifiers"])])
                if row["modifiers"] else row["cpt"]
            )
            result.append({
                "code": code,
                "cpt": row["cpt"],
                "description": description,
                "units": row["units"],
                "modifiers": row["modifiers"],
                "diagnoses": row["diagnoses"],
            })
        return result

    def _get_note_diagnoses(self) -> list[dict]:
        """ICD-10 diagnoses to show in the billing footer, deduplicated by code.

        Approximates home-app's ``Note.get_billable_conditions`` from the
        plugin SDK. The home-app set is "committed, non-EIE Assessments on
        this note whose Condition is active OR resolved OR investigative+POC,
        minus any assessment whose Condition has a committed
        ``ResolveConditionEvent`` on this same note (KOALA-5345), minus any
        assessment that the property ``include_in_note_footer`` excludes".

        Two pieces of that logic aren't reachable from the SDK:

        - ``ResolveConditionEvent`` rows aren't exposed (no SDK model, no DB
          view), so we can't see which conditions were resolved on *this*
          note.
        - The "investigative + POC lab order" branch needs the lab-order
          reason-link traversal, which we don't reproduce here.

        To stay aligned with the visible footer rather than over-including,
        we conservatively restrict to **active** conditions. This matches the
        UI for the common case at the cost of dropping the rare
        "investigative + POC lab" and "resolved-on-another-note re-recorded
        here" cases.
        """
        assessments = (
            Assessment.objects
            .filter(
                note=self.note,
                committer__isnull=False,
                entered_in_error__isnull=True,
                condition__isnull=False,
                condition__entered_in_error__isnull=True,
                condition__clinical_status="active",
            )
            .order_by("created")
            .prefetch_related("condition__codings")
        )
        result: list[dict] = []
        seen: set[str] = set()
        for assess in assessments:
            condition = getattr(assess, "condition", None)
            if condition is None:
                continue
            for coding in condition.codings.all():
                if coding.system != "ICD-10":
                    continue
                formatted = format_icd10_code((coding.code or "").strip())
                if not formatted or formatted in seen:
                    continue
                seen.add(formatted)
                result.append({
                    "code": formatted,
                    "display": (coding.display or "").strip(),
                })
        return result

    def _get_reasons_for_visit(self) -> list[dict[str, str]]:
        """Extract each RFV as {text, comment}. Both fields may be present."""
        rfv_commands = Command.objects.filter(
            note__dbid=self.note.dbid,
            schema_key="reasonForVisit",
        ).order_by("dbid")
        results: list[dict[str, str]] = []
        for cmd in rfv_commands:
            coding = cmd.data.get("coding") or {}
            text = coding.get("text", "") if isinstance(coding, dict) else ""
            comment = (cmd.data.get("comment") or "").strip()
            # RFV skips empty commands, so positional UUID alignment is unsafe;
            # carry the command's own UUID here instead (used for note-body order).
            command_uuid = str(cmd.id)
            # If there's no coding, fall back to the comment as the main text.
            if not text and comment:
                results.append({"text": comment, "comment": "", "_command_uuid": command_uuid})
                continue
            if text or comment:
                results.append({"text": text, "comment": comment, "_command_uuid": command_uuid})
        return results

    def _get_reason_for_visit(self) -> str:
        """Single-string RFV for templates that expect a scalar (joins all RFVs)."""
        parts: list[str] = []
        for rfv in self._get_reasons_for_visit():
            text = rfv.get("text", "")
            comment = rfv.get("comment", "")
            if text and comment:
                parts.append(f"{text} ({comment})")
            elif text:
                parts.append(text)
            elif comment:
                parts.append(comment)
        return "; ".join(parts)

    # context_key -> schema_key for commands fetched in note (dbid) order. Each
    # entry list is 1:1 and identically ordered with its schema's committed
    # commands, so a positional zip attaches the right UUID. Derived RFV entries
    # attach their own UUID inline (see `_get_reasons_for_visit`).
    _CONTEXT_KEY_SCHEMA_KEYS: dict[str, str] = {
        "history_of_present_illness_commands_data": "hpi",
        "review_of_systems_data": "ros",
        "questionnaire_data": "questionnaire",
        "vitals_commands_data": "vitals",
        "physical_exam_data": "exam",
        "assessments_commands_data": "assess",
        "diagnose_commands_data": "diagnose",
        "resolve_condition_commands_data": "resolveCondition",
        "change_diagnosis_commands_data": "updateDiagnosis",
        "lab_reviews": "labReview",
        "imaging_reviews": "imagingReview",
        "consult_report_reviews": "referralReview",
        "uncategorized_document_reviews": "uncategorizedDocumentReview",
        "chart_section_review_commands_data": "chartSectionReview",
        "structured_assessment_data": "structuredAssessment",
        "plan_commands_data": "plan",
        "prescribe_commands_data": "prescribe",
        "refill_commands_data": "refill",
        "stop_medication_commands_data": "stopMedication",
        "adjust_prescription_commands_data": "adjustPrescription",
        "change_medication_commands_data": "changeMedication",
        "cancel_prescription_commands_data": "cancelPrescription",
        "approve_refill_commands_data": "approveRefill",
        "deny_refill_commands_data": "denyRefill",
        "approve_change_commands_data": "approveChange",
        "deny_change_commands_data": "denyChange",
        "referral_commands_data": "refer",
        "lab_order_commands_data": "labOrder",
        "imaging_order_commands_data": "imagingOrder",
        "poc_lab_test_commands_data": "pocLabTest",
        "instruct_commands_data": "instruct",
        "educational_material_commands_data": "educationalMaterial",
        "task_commands_data": "task",
        "goal_commands_data": "goal",
        "update_goal_commands_data": "updateGoal",
        "close_goal_commands_data": "closeGoal",
        "immunize_commands_data": "immunize",
        "perform_commands_data": "perform",
        "visual_exam_finding_commands_data": "visualExamFinding",
        "allergy_commands_data": "allergy",
        "remove_allergy_commands_data": "removeAllergy",
        "medication_statement_commands_data": "medicationStatement",
        "immunization_statement_commands_data": "immunizationStatement",
        "patient_family_history_commands_data": "familyHistory",
        "medical_history_commands_data": "medicalHistory",
        "surgical_history_commands_data": "surgicalHistory",
        "custom_commands_data": "customCommand",
        "create_coding_gap_commands_data": "createCodingGap",
        "assess_coding_gap_commands_data": "assessCodingGap",
        "validate_coding_gap_commands_data": "validateCodingGap",
        "defer_coding_gap_commands_data": "deferCodingGap",
        "snooze_protocol_commands_data": "snoozeProtocol",
        "clipboard_commands_data": "clipboard",
    }

    # Schema keys we deliberately exclude from the auto "render every
    # remaining schema_key as a custom command" path (`_fetch_unknown_command_data`).
    # `privateNotes` is provider-only and shouldn't appear on a patient-facing
    # printout. Add other "skip on purpose" keys here as they come up.
    _EXCLUDED_FROM_CUSTOM_FALLBACK: set[str] = {
        "privateNotes",
        "reasonForVisit",  # rendered via _get_reasons_for_visit
        "followUp",        # rendered via _follow_up_blocks in customize_print.py
    }

    def _fetch_unknown_command_data(self) -> list[dict]:
        """Pull any committed schema_key on this note that we don't have an
        explicit renderer for, treating each as a plugin-authored custom
        command. Plugin authors registering a customized command via
        home-app's ``customize_custom_command`` get to pick their own
        ``schema_key`` (e.g., ``observationSummary``), so we have to discover
        them at runtime rather than enumerating ahead of time.

        Each returned entry is tagged with ``_schema_key`` (for the title
        fallback) and ``_command_uuid`` (so the flat note-order sort can
        place the row at its real position in ``Note.body`` — without this
        the positional UUID-attach helper can't match a plugin-customized
        schema_key against the bare ``customCommand`` mapping).
        """
        known = set(self._CONTEXT_KEY_SCHEMA_KEYS.values())
        skip = known | self._EXCLUDED_FROM_CUSTOM_FALLBACK
        values_fields: tuple[str, ...] = ("schema_key", "data", "id")
        if _COMMAND_HAS_CUSTOM_HTML:
            values_fields = (*values_fields, "custom_html")
        rows = (
            Command.objects
            .filter(
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .exclude(schema_key__in=list(skip))
            .order_by("dbid")
            .values(*values_fields)
        )
        out: list[dict] = []
        for row in rows:
            sk = row.get("schema_key")
            data = row.get("data")
            cmd_id = row.get("id")
            if not isinstance(data, dict):
                continue
            entry = dict(data)
            if sk:
                entry["_schema_key"] = sk
            if cmd_id:
                entry["_command_uuid"] = str(cmd_id)
            if custom_html := row.get("custom_html"):
                entry["_custom_html"] = custom_html
            out.append(entry)
        return out

    def get_note_body_order(self) -> list[str]:
        """Return committed command UUIDs in the order they appear in the note body.

        `Note.body` is an ordered array intermixing text and command objects; each
        command object carries `data.command_uuid` (== `Command.id`). Commands not
        referenced in the body (or notes without a body) simply don't appear here.
        """
        body = self.note.body
        if not isinstance(body, list):
            return []
        order: list[str] = []
        for item in body:
            if not isinstance(item, dict) or item.get("type") != "command":
                continue
            data = item.get("data") or {}
            command_uuid = data.get("command_uuid") if isinstance(data, dict) else None
            if command_uuid:
                order.append(str(command_uuid))
        return order

    def _command_uuids_by_schema(self) -> dict[str, list[str]]:
        """Map each schema_key to its committed command UUIDs in dbid order.

        Mirrors the filter/order of `_fetch_all_commands_data`, so the i-th UUID
        lines up with the i-th rendered entry of that schema_key.
        """
        rows = (
            Command.objects.filter(
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .values_list("schema_key", "id")
        )
        out: dict[str, list[str]] = {}
        for schema_key, command_id in rows:
            out.setdefault(schema_key, []).append(str(command_id))
        return out

    def _attach_command_uuids(self, context: dict[str, Any]) -> None:
        """Attach `_command_uuid` to each command entry so print order can follow
        the note body. Mutates the entry dicts in `context` in place."""
        uuids_by_schema = self._command_uuids_by_schema()
        if not uuids_by_schema:
            return
        for context_key, schema_key in self._CONTEXT_KEY_SCHEMA_KEYS.items():
            entries = context.get(context_key)
            if not isinstance(entries, list):
                continue
            uuids = uuids_by_schema.get(schema_key, [])
            for index, entry in enumerate(entries):
                if isinstance(entry, dict) and index < len(uuids):
                    entry.setdefault("_command_uuid", uuids[index])

    def _attach_command_metadata(self, context: dict[str, Any]) -> None:
        """Attach every CommandMetadata row to its command entry as ``_metadata``.

        For every committed command on this note we read the related
        ``CommandMetadata`` rows and stash each ``{key, value}`` pair on the
        matching context entry. Block builders then surface them as plain
        fields beneath the command's main fields.

        Entries are matched to commands by ``(schema_key, dbid-order index)``
        — the same positional alignment ``_attach_command_uuids`` uses.
        """
        metadata_by_schema: dict[str, list[list[dict]]] = {}
        rows = (
            Command.objects
            .filter(
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .prefetch_related("metadata")
        )
        any_metadata = False
        for cmd in rows:
            entries: list[dict] = []
            for m in cmd.metadata.all():
                key = (m.key or "").strip()
                if not key:
                    continue
                entries.append({"key": key, "value": m.value or ""})
            if entries:
                any_metadata = True
            metadata_by_schema.setdefault(cmd.schema_key, []).append(entries)

        if not any_metadata:
            return

        for context_key, schema_key in self._CONTEXT_KEY_SCHEMA_KEYS.items():
            entries_list = context.get(context_key)
            if not isinstance(entries_list, list):
                continue
            command_metadata = metadata_by_schema.get(schema_key, [])
            for index, entry in enumerate(entries_list):
                if not isinstance(entry, dict) or index >= len(command_metadata):
                    continue
                printable = command_metadata[index]
                if printable:
                    entry.setdefault("_metadata", printable)

    def get_template_context(self) -> dict[str, Any]:
        """Build the full template context dict with all note data.

        Returns a dict suitable for passing directly to render_to_string
        for either the Patient Visit Summary or Customize & Print templates.
        """
        header = self._get_header_context()
        reasons_for_visit = self._get_reasons_for_visit()
        reason_for_visit = self._get_reason_for_visit()

        # Subjective
        hpi_data = self._fetch_all_commands_data("hpi")
        ros_data = self._format_ros_or_exam("ros")
        questionnaire_data = self._format_questionnaires()

        # Objective - Vitals
        # Local import avoids the command_blocks <-> note_data_extractor cycle.
        from patient_visit_summary.services.command_blocks import compute_bmi

        vitals_data = self._fetch_all_commands_data("vitals")
        for vitals in vitals_data:
            for key in VITALS_ENUM_DICT:
                description = VITALS_ENUM_DICT[key].get(vitals.get(key, ""), "")
                vitals[key] = description
            # Surface BMI on the printout, mirroring the Customize & Print path.
            vitals["bmi"] = compute_bmi(vitals)

        # Objective - Physical Exam
        physical_exam_data = self._format_ros_or_exam("exam")

        # Assessments
        assessments_data = self._fetch_all_commands_data("assess")
        for assessment in assessments_data:
            if assessment.get("status"):
                assessment["status"] = ASSESSMENT_STATUS_DICT.get(
                    assessment["status"], assessment["status"]
                )

        # Diagnoses
        diagnose_raw = self._fetch_commands_fields("diagnose", "data", "modified")
        diagnose_data = []
        for diag in diagnose_raw:
            modified_dt = arrow.get(diag["modified"]).to("US/Eastern")
            diagnose_data.append({
                "data": diag["data"],
                "modified": f'{modified_dt.format("M.D.YY")} at {modified_dt.format("h:mm A")} EDT',
            })

        diagnoses_from_sa = self._get_diagnoses_from_structured_assessments()

        # Reviews
        lab_reviews = self._fetch_all_commands_data("labReview")
        imaging_reviews = self._fetch_all_commands_data("imagingReview")
        referral_reviews = self._fetch_all_commands_data("referralReview")
        uncat_reviews = self._fetch_all_commands_data("uncategorizedDocumentReview")
        # Attach the underlying report content as pre-rendered HTML. Each
        # helper bulk-fetches per review-type and stamps ``_reference_html``
        # on entries; the block renderer surfaces it as a ``body_html`` block
        # after the review's own fields.
        self._attach_lab_review_reference_html(lab_reviews)
        self._attach_imaging_review_reference_html(imaging_reviews)
        self._attach_referral_review_reference_html(referral_reviews)
        self._attach_uncategorized_review_reference_html(uncat_reviews)
        structured_assessments = self._format_questionnaires(questionnaire_type="structuredAssessment")
        resolve_conditions = self._fetch_all_commands_data("resolveCondition")
        change_diagnoses = self._fetch_all_commands_data("updateDiagnosis")

        # Plan
        plan_data = self._fetch_all_commands_data("plan")
        prescribe_data = self._fetch_all_commands_data("prescribe")
        refill_data = self._fetch_all_commands_data("refill")
        stop_med_data = self._fetch_all_commands_data("stopMedication")
        adjust_rx_data = self._fetch_all_commands_data("adjustPrescription")
        change_med_data = self._fetch_all_commands_data("changeMedication")
        referral_data = self._fetch_all_commands_data("refer")
        lab_order_data = self._fetch_all_commands_data("labOrder")
        imaging_order_data = self._fetch_all_commands_data("imagingOrder")
        instruct_data = self._fetch_all_commands_data("instruct")

        # Follow-up(s)
        follow_ups: list[dict[str, str]] = []
        for row in self._fetch_commands_fields("followUp", "data", "id"):
            fu = row.get("data") or {}
            if not isinstance(fu, dict):
                continue
            requested = fu.get("requested_date") if isinstance(fu.get("requested_date"), dict) else {}
            raw_date = (requested.get("date") or "") if isinstance(requested, dict) else ""
            input_text = (requested.get("input") or "").strip() if isinstance(requested, dict) else ""
            # Preserve both parts so downstream can show "2 weeks (around 2026-04-17)".
            if input_text and raw_date and input_text != raw_date:
                date_str = f"{input_text} (around {raw_date})"
            else:
                date_str = input_text or raw_date
            if fu.get("coding"):
                rfv = fu.get("coding", {}).get("text", "")
            else:
                rfv = fu.get("reason_for_visit", "")
            note_type = fu.get("note_type", {}).get("text", "") if isinstance(fu.get("note_type"), dict) else ""
            comment = (fu.get("comment") or "").strip()
            if date_str or rfv or note_type or comment:
                entry: dict[str, str] = {
                    "date": date_str,
                    "rfv": rfv,
                    "note_type": note_type,
                    "comment": comment,
                }
                cmd_id = row.get("id")
                if cmd_id:
                    entry["_command_uuid"] = str(cmd_id)
                follow_ups.append(entry)

        # Keep the singular fields for templates that expect them (latest follow-up).
        if follow_ups:
            latest_fu = follow_ups[-1]
            follow_up_date = latest_fu["date"] or None
            follow_up_rfv = latest_fu["rfv"]
            follow_up_note_type = latest_fu["note_type"]
        else:
            follow_up_date = None
            follow_up_rfv = ""
            follow_up_note_type = ""

        # Tasks & Goals
        task_data = self._fetch_all_commands_data("task")
        goal_data = self._fetch_all_commands_data("goal")
        for goal in goal_data:
            if goal.get("priority"):
                goal["priority"] = GoalPriority(goal["priority"]).label
            if goal.get("achievement_status"):
                goal["achievement_status"] = GoalAchievementStatus(goal["achievement_status"]).label

        update_goal_data = self._fetch_all_commands_data("updateGoal")
        for goal in update_goal_data:
            if goal.get("priority"):
                goal["priority"] = GoalPriority(goal["priority"]).label
            if goal.get("achievement_status"):
                goal["achievement_status"] = GoalAchievementStatus(goal["achievement_status"]).label

        # Procedures
        immunize_data = self._fetch_all_commands_data("immunize")
        perform_data = self._fetch_all_commands_data("perform")
        # Surface CPT/CVX codes on the template's name line for each command type
        # whose coding field carries them.
        _annotate_coded_titles(immunize_data, "coding")
        _annotate_coded_titles(perform_data, "perform")

        # Billed services (patient-facing: CPT + description + units, no charges)
        billing_line_items = self._get_billing_line_items()

        # History
        allergy_data = self._fetch_all_commands_data("allergy")
        remove_allergy_data = self._fetch_all_commands_data("removeAllergy")
        med_statement_data = self._fetch_all_commands_data("medicationStatement")
        imm_statement_data = self._fetch_all_commands_data("immunizationStatement")
        _annotate_coded_titles(imm_statement_data, "statement")
        family_history_data = self._fetch_all_commands_data("familyHistory")
        medical_history_data = self._fetch_all_commands_data("medicalHistory")
        for mh in medical_history_data:
            if mh.get("past_medical_history", {}).get("annotations"):
                mh["past_medical_history"]["annotations"][0] = format_icd10_code(
                    mh["past_medical_history"]["annotations"][0]
                )
        surgical_history_data = self._fetch_all_commands_data("surgicalHistory")

        # Additional commands (newer SDK + home-app additions).
        cancel_prescription_data = self._fetch_all_commands_data("cancelPrescription")
        approve_refill_data = self._fetch_refill_decision_commands_data("approveRefill")
        deny_refill_data = self._fetch_refill_decision_commands_data("denyRefill")
        approve_change_data = self._fetch_refill_decision_commands_data("approveChange")
        deny_change_data = self._fetch_refill_decision_commands_data("denyChange")
        close_goal_data = self._fetch_all_commands_data("closeGoal")
        educational_material_data = self._fetch_all_commands_data("educationalMaterial")
        visual_exam_finding_data = self._fetch_all_commands_data("visualExamFinding")
        chart_section_review_data = self._fetch_all_commands_data("chartSectionReview")
        poc_lab_test_data = self._fetch_all_commands_data("pocLabTest")
        # The patient-facing Django template can't compute dynamic dict keys
        # (`test_values|<lowercase label>`) or translate reason codes inline,
        # so pre-build the patient-friendly fields server-side. Both helpers
        # are no-ops when their stamp would be empty.
        self._attach_poc_value_rows(poc_lab_test_data)
        self._attach_refill_reason_displays(deny_refill_data)
        self._attach_refill_reason_displays(deny_change_data)
        # Plugin-authored custom commands. `customCommand` is the SDK wrapper
        # name when the plugin author didn't override Meta.schema_key. When
        # they did override it (per home-app's `customize_custom_command`),
        # the row stores the plugin's chosen schema_key (e.g.,
        # `observationSummary`, `medicationReconciliation`). We pull both:
        # bare `customCommand` rows, plus anything else on the note we
        # don't explicitly handle elsewhere — they all go through the
        # `_blocks_custom_command` renderer.
        custom_commands_data = self._fetch_all_commands_data("customCommand")
        for entry in custom_commands_data:
            if isinstance(entry, dict):
                entry.setdefault("_schema_key", "customCommand")
        custom_commands_data.extend(self._fetch_unknown_command_data())

        # Coding-gap suite — created, assessed, validated, deferred. These
        # are billing-side decision-support actions but worth surfacing on
        # the visit summary so the patient/care team can see what was
        # touched.
        create_coding_gap_data = self._fetch_all_commands_data("createCodingGap")
        assess_coding_gap_data = self._fetch_all_commands_data("assessCodingGap")
        validate_coding_gap_data = self._fetch_all_commands_data("validateCodingGap")
        defer_coding_gap_data = self._fetch_all_commands_data("deferCodingGap")
        # Snoozed protocols — population-health protocol deferrals scoped to
        # this note.
        snooze_protocol_data = self._fetch_all_commands_data("snoozeProtocol")
        # Clipboard — free-form provider scratch attached to the note.
        clipboard_data = self._fetch_all_commands_data("clipboard")

        context: dict[str, Any] = {
            "patient": self.patient,
            "note": self.note,
            "provider": header["provider"],
            "provider_top_role": header["provider_top_role"],
            "appointment_date": header["appointment_date"],
            # Subjective
            "reason_for_visit": reason_for_visit,
            "reasons_for_visit": reasons_for_visit,
            "history_of_present_illness_commands_data": hpi_data,
            "review_of_systems_data": ros_data,
            "questionnaire_data": questionnaire_data,
            # Objective
            "vitals_commands_data": vitals_data,
            "physical_exam_data": physical_exam_data,
            "assessments_commands_data": assessments_data,
            "diagnose_commands_data": diagnose_data,
            "diagnoses_from_structured_assessments": diagnoses_from_sa,
            "resolve_condition_commands_data": resolve_conditions,
            "change_diagnosis_commands_data": change_diagnoses,
            "lab_reviews": lab_reviews,
            "imaging_reviews": imaging_reviews,
            "consult_report_reviews": referral_reviews,
            "uncategorized_document_reviews": uncat_reviews,
            "structured_assessment_data": structured_assessments,
            # Plan
            "plan_commands_data": plan_data,
            "prescribe_commands_data": prescribe_data,
            "refill_commands_data": refill_data,
            "stop_medication_commands_data": stop_med_data,
            "adjust_prescription_commands_data": adjust_rx_data,
            "change_medication_commands_data": change_med_data,
            "referral_commands_data": referral_data,
            "lab_order_commands_data": lab_order_data,
            "imaging_order_commands_data": imaging_order_data,
            "instruct_commands_data": instruct_data,
            "follow_up_date": follow_up_date,
            "follow_up_rfv": follow_up_rfv,
            "follow_up_note_type": follow_up_note_type,
            "follow_ups": follow_ups,
            "task_commands_data": task_data,
            "goal_commands_data": goal_data,
            "update_goal_commands_data": update_goal_data,
            # Procedures
            "immunize_commands_data": immunize_data,
            "perform_commands_data": perform_data,
            # History
            "allergy_commands_data": allergy_data,
            "remove_allergy_commands_data": remove_allergy_data,
            "medication_statement_commands_data": med_statement_data,
            "immunization_statement_commands_data": imm_statement_data,
            "patient_family_history_commands_data": family_history_data,
            "medical_history_commands_data": medical_history_data,
            "surgical_history_commands_data": surgical_history_data,
            # Additional command types (Assessment / Reviews / Plan / Objective)
            "chart_section_review_commands_data": chart_section_review_data,
            "cancel_prescription_commands_data": cancel_prescription_data,
            "approve_refill_commands_data": approve_refill_data,
            "deny_refill_commands_data": deny_refill_data,
            "approve_change_commands_data": approve_change_data,
            "deny_change_commands_data": deny_change_data,
            "close_goal_commands_data": close_goal_data,
            "educational_material_commands_data": educational_material_data,
            "poc_lab_test_commands_data": poc_lab_test_data,
            "visual_exam_finding_commands_data": visual_exam_finding_data,
            # Plugin-authored custom commands (one row per committed command;
            # decoded by `_blocks_custom_command`).
            "custom_commands_data": custom_commands_data,
            # Coding gap suite + snoozed protocols.
            "create_coding_gap_commands_data": create_coding_gap_data,
            "assess_coding_gap_commands_data": assess_coding_gap_data,
            "validate_coding_gap_commands_data": validate_coding_gap_data,
            "defer_coding_gap_commands_data": defer_coding_gap_data,
            "snooze_protocol_commands_data": snooze_protocol_data,
            "clipboard_commands_data": clipboard_data,
            # Billed services
            "billing_line_items_data": billing_line_items,
            # Practice location info for the printout header (clinic name,
            # address, phone, fax, organization logo URL). Mirrors what
            # home-app's standard note print pulls onto its header.
            "practice_location_info": self._get_practice_location_info(),
            # Lines for the SIGNATURES footer block (signed-by / amendment /
            # currently-unsigned). See `_get_signature_lines`.
            "signature_lines": self._get_signature_lines(),
            # Every billable ICD-10 diagnosis on this note (mimics
            # home-app's Note.get_billable_conditions). Surfaced in the
            # billing footer so the print covers diagnoses that aren't
            # linked to a specific CPT line item.
            "note_diagnoses": self._get_note_diagnoses(),
            # Ordered command UUIDs as they appear in the note body (for the
            # Customize & Print "note order" mode).
            "note_body_order": self.get_note_body_order(),
        }

        # Tag each command entry with its UUID so a print UI can reorder by note
        # body. Additive (keys are `_`-prefixed and ignored by renderers).
        self._attach_command_uuids(context)
        # Tag each entry with printable metadata (only keys prefixed `print:`
        # or `display:` are surfaced; everything else stays internal).
        self._attach_command_metadata(context)
        return context

    def get_commands_by_section(
        self, sections: list[dict] | None = None,
    ) -> list[dict]:
        """Return every command in the note grouped by section, with per-entry
        titles and pre-built display blocks — ready for any print UI.

        See `services.command_blocks.enumerate_sections` for the output shape.
        Pass a custom `sections` config to override the default mapping.
        """
        # Imported lazily to avoid a circular import at module load time.
        from patient_visit_summary.services.command_blocks import enumerate_sections
        return enumerate_sections(self.get_template_context(), sections=sections)
