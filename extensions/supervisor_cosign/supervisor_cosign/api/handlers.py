import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.task import AddTaskComment, TaskStatus, UpdateTask
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.staff import Staff
from logger import log

from supervisor_cosign.models.cosign_addendum import CoSignAddendum
from supervisor_cosign.models.cosign_record import CoSignRecord


SUPERVISEE_PLACEHOLDER = "{{supervisee}}"

ATTESTATION_TEMPLATES = {
    "teaching": (
        "I was present for and participated in the critical and key portions of "
        "the examination and agree with " + SUPERVISEE_PLACEHOLDER + "'s findings and treatment plan."
    ),
    "reviewed": (
        "I have reviewed " + SUPERVISEE_PLACEHOLDER + "'s documentation and agree with the "
        "assessment, findings, and plan as documented."
    ),
    "personally_performed": (
        "I personally performed the service. I have reviewed and agree with "
        "the documentation."
    ),
}


class SupervisorCoSignAPI(StaffSessionAuthMixin, SimpleAPI):
    # StaffSessionAuthMixin authenticates the session as a logged-in Staff user
    # (rejecting patients/anonymous). SessionCredentials already rejects requests
    # missing the Canvas-set user headers, so a non-empty user id is guaranteed.

    def _logged_in_user_id(self) -> str:
        # Read directly from headers in the request handler. Setting an attribute
        # in authenticate() does not work because Canvas instantiates a separate
        # handler instance for SIMPLE_API_AUTHENTICATE vs SIMPLE_API_REQUEST.
        return self.request.headers.get("canvas-logged-in-user-id") or ""

    @api.post("/cosign/<note_id>/")
    def submit_cosign(self) -> list[Response | Effect]:
        note_id = self.request.path_params["note_id"]
        body = self.request.json()
        template_key = body.get("template", "teaching")
        attestation_text = body.get("attestation_text", "").strip()
        additional_comments = body.get("additional_comments", "").strip()

        pending = list(CoSignRecord.objects.filter(note_id=note_id, status="pending"))
        log.info(f"supervisor_cosign.submit: note_id={note_id!r} template={template_key!r} pending_count={len(pending)}")
        if not pending:
            return [JSONResponse({"error": "no pending co-sign record for this note"}, status_code=HTTPStatus.NOT_FOUND)]

        record = pending[0]
        user_id = self._logged_in_user_id()
        if str(record.supervisor_id) != user_id:
            log.info(
                f"supervisor_cosign.submit: auth rejected note_id={note_id!r} "
                f"record.supervisor_id={record.supervisor_id!r} user_id={user_id!r}"
            )
            return [JSONResponse(
                {"error": "not authorized to co-sign this note"},
                status_code=HTTPStatus.FORBIDDEN,
            )]
        supervisor_credentialed = self._staff_credentialed_name(record.supervisor_id) or "supervisor"
        supervisee_name = self._staff_name(record.supervisee_id) or "the provider"
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M UTC")

        attestation_body = self._resolve_attestation(template_key, attestation_text, supervisee_name)
        if not attestation_body:
            return [JSONResponse({"error": "attestation text is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        # HTML content with <br> for line breaks. Plain-text \n collapses in Canvas's
        # custom command renderer; <br> preserves paragraph separation. No inline font
        # so the native serif body styling inherits. The \n -> <br> conversion applies
        # to both the attestation body (multi-paragraph custom text) and the comments.
        attestation_content = self._escape_html(attestation_body).replace("\n", "<br>")
        if additional_comments:
            comments_html = self._escape_html(additional_comments).replace("\n", "<br>")
            attestation_content += "<br><br><strong>Additional comments:</strong><br>" + comments_html
        attestation_content += (
            "<br><br>Co-signed by " + self._escape_html(supervisor_credentialed)
            + " on " + timestamp_str
        )

        # Plain-text version for the addendum log + task comment (cleaner without HTML).
        full_content_plain = attestation_body
        if additional_comments:
            full_content_plain += "\n\nAdditional comments:\n" + additional_comments
        full_content_plain += "\n\nCo-signed by " + supervisor_credentialed + " on " + timestamp_str

        # Build chart-write effects first. If construction fails (e.g., the SDK rejects
        # NoteEffect.unlock() because the instance has "only the provider can sign/unlock"
        # enabled, or any future construct-time validation), we abort with 500 BEFORE any
        # DB writes or task-side-effect emissions. Otherwise the records would be flipped
        # to "approved", the addendum row persisted, and the supervisor's task left OPEN
        # with no way to retry through this plugin (the retry path filters status=pending).
        chart_effects: list[Effect] = []
        try:
            attestation = CustomCommand(
                note_uuid=note_id,
                command_uuid=str(uuid.uuid4()),
                schema_key="attestation_review",
                content=attestation_content,
            )
            chart_effects.append(NoteEffect(instance_id=note_id).unlock())
            # CustomCommand only supports ORIGINATE - no COMMIT_CUSTOM_COMMAND_COMMAND
            # effect type exists in the proto. Originate is final for this command.
            chart_effects.append(attestation.originate())
            # Construct LOCK_NOTE and SIGN_NOTE effects directly: the SDK validates
            # against current DB state at construct time, but effects only apply in
            # order at runtime. Building them manually bypasses the construct-time
            # check so the chain unlock -> originate -> lock -> sign can land.
            chart_effects.append(
                Effect(
                    type=EffectType.LOCK_NOTE,
                    payload=json.dumps({"data": {"note": str(note_id)}}),
                )
            )
            chart_effects.append(
                Effect(
                    type=EffectType.SIGN_NOTE,
                    payload=json.dumps({"data": {"note": str(note_id)}}),
                )
            )
        except Exception as exc:
            log.exception(f"supervisor_cosign.submit: failed to build chart-write effects: {exc}")
            return [
                JSONResponse(
                    {"error": "failed to write attestation to chart"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        # Chart-write chain constructed cleanly. Now safe to persist DB state and
        # emit task-side-effects. Only approve records assigned to the authenticated
        # supervisor: NoteLockHandler dedups to one record per note, so in practice
        # this equals `pending`, but filtering keeps the authorization decision local
        # to this endpoint rather than relying on the producer's dedup guarantee.
        authorized = [r for r in pending if str(r.supervisor_id) == user_id]
        effects: list[Response | Effect] = list(chart_effects)
        for r in authorized:
            r.status = "approved"
            r.cosigned_at = now
            r.addendum_text = full_content_plain
            r.save()

            if r.task_id:
                comment_body = f"Co-signed by {supervisor_credentialed} at {timestamp_str}.\n\n{attestation_body}"
                if additional_comments:
                    comment_body += f"\n\n{additional_comments}"
                effects.append(AddTaskComment(task_id=r.task_id, body=comment_body).apply())
                effects.append(UpdateTask(id=r.task_id, status=TaskStatus.COMPLETED).apply())
            else:
                log.info(f"supervisor_cosign.submit: record dbid={r.dbid} has empty task_id; skipping task completion")

        CoSignAddendum(
            note_id=note_id,
            supervisor_id=record.supervisor_id,
            supervisor_name=supervisor_credentialed,
            addendum_text=full_content_plain,
        ).save()

        effects.append(JSONResponse({"status": "approved", "count": len(authorized)}, status_code=HTTPStatus.OK))
        return effects

    @api.get("/report/")
    def compliance_report(self) -> list[Response | Effect]:
        params = self.request.query_params
        start_str = params.get("start")
        end_str = params.get("end")

        # Each supervisor only sees their own supervisees' records.
        # Date filters use __date lookups so end="2026-05-31" includes records
        # from all of May 31, not just before midnight (which is what __lte on
        # the raw DateTimeField does - end-of-month reports would undercount
        # the last day).
        qs = CoSignRecord.objects.filter(supervisor_id=self._logged_in_user_id())
        if start_str:
            qs = qs.filter(selected_at__date__gte=start_str)
        if end_str:
            qs = qs.filter(selected_at__date__lte=end_str)

        records = list(
            qs.values(
                "note_id",
                "supervisee_id",
                "supervisor_id",
                "status",
                "selected_at",
                "cosigned_at",
                "due_date",
            )
        )

        # Canvas SDK JSONResponse uses stock json.dumps with no datetime
        # encoder, so raw datetime/date values would raise TypeError. Convert
        # to ISO strings (or null) before the records hit JSONResponse.
        for r in records:
            for key in ("selected_at", "cosigned_at", "due_date"):
                value = r.get(key)
                if value is not None and hasattr(value, "isoformat"):
                    r[key] = value.isoformat()

        summary: dict[str, dict] = {}
        for r in records:
            sid = r["supervisee_id"]
            if sid not in summary:
                summary[sid] = {"total": 0, "approved": 0, "pending": 0}
            counts = summary[sid]
            counts["total"] = counts["total"] + 1
            if r["status"] == "approved":
                counts["approved"] = counts["approved"] + 1
            else:
                counts["pending"] = counts["pending"] + 1

        for sid, counts in summary.items():
            counts["pct_cosigned"] = round(counts["approved"] / counts["total"] * 100, 1) if counts["total"] else 0

        return [JSONResponse({"summary": summary, "records": records}, status_code=HTTPStatus.OK)]

    def _resolve_attestation(self, template_key: str, custom_text: str, supervisee_name: str) -> str:
        # Prefer the supervisor's edited text whenever it is non-empty - the
        # modal lets supervisors edit the textarea even after picking a template,
        # so silently discarding their edits would be misleading. Fall back to
        # the canonical template only if the textarea is empty.
        text = (custom_text or "").strip()
        if text:
            return text
        template = ATTESTATION_TEMPLATES.get(template_key)
        if not template:
            return ""
        # str.format/format_map are blocked by the Canvas RestrictedPython sandbox.
        return template.replace(SUPERVISEE_PLACEHOLDER, supervisee_name)

    def _staff_name(self, staff_id: str) -> str:
        if not staff_id:
            return ""
        staff = Staff.objects.filter(id=staff_id).values("first_name", "last_name").first()
        if not staff:
            return ""
        return f"{staff['first_name']} {staff['last_name']}".strip()

    def _escape_html(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _staff_credentialed_name(self, staff_id: str) -> str:
        if not staff_id:
            return ""
        staff = Staff.objects.filter(id=staff_id).first()
        if not staff:
            return ""
        credentialed = getattr(staff, "credentialed_name", None)
        if credentialed:
            return credentialed
        return f"{staff.first_name} {staff.last_name}".strip()

