"""API endpoints for the Patient Instructions plugin."""

import json
from uuid import uuid4

from canvas_sdk.commands import InstructCommand
from canvas_sdk.commands.constants import CodeSystems, Coding
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import api
from canvas_sdk.handlers.simple_api.api import SimpleAPI
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin

from logger import log

from patient_instructions.models.instruction import Instruction


def _parse_body(request) -> dict:
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _instruction_to_dict(inst) -> dict:
    return {
        "id": inst.dbid,
        "coding_system": inst.coding_system,
        "code": inst.code,
        "display": inst.display,
        "comment": inst.comment or "",
        "tags": inst.tags or [],
        "active": inst.active,
    }


class PatientInstructionsApi(StaffSessionAuthMixin, SimpleAPI):
    """API for managing the instruction library and adding instructions to notes."""

    BASE_PATH = "/plugin-io/api/patient_instructions"

    # ---- Library CRUD ----

    @api.get("/library")
    def list_instructions(self) -> list[Response | Effect]:
        """Return all active instructions, optionally filtered by tag."""
        try:
            tag = self.request.query_params.get("tag", "")
            qs = Instruction.objects.filter(active=True).order_by("display")
            if tag:
                qs = qs.filter(tags__contains=tag)
            instructions = [_instruction_to_dict(i) for i in qs]
            return [JSONResponse({"status": "ok", "instructions": instructions})]
        except Exception as e:
            log.error("[PI GET] Error: %s" % e)
            return [JSONResponse({"status": "ok", "instructions": []})]

    @api.post("/library")
    def create_instruction(self) -> list[Response | Effect]:
        """Create or update an instruction in the library."""
        try:
            body = _parse_body(self.request)
            coding_system = body.get("coding_system", "UNSTRUCTURED")
            code = body.get("code", "")
            display = body.get("display", "")

            if not code or not display:
                return [JSONResponse({"status": "error", "message": "Missing code or display"})]

            tags = body.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            inst, created = Instruction.objects.update_or_create(
                coding_system=coding_system,
                code=code,
                defaults={
                    "display": display,
                    "comment": body.get("comment", ""),
                    "tags": tags,
                    "active": True,
                },
            )
            action = "Created" if created else "Updated"
            log.info("[PI] %s instruction %s: %s" % (action, inst.dbid, display))
            return [JSONResponse({"status": "ok", "instruction": _instruction_to_dict(inst)})]
        except Exception as e:
            log.error("[PI POST] Error: %s" % e)
            return [JSONResponse({"status": "error", "message": str(e)})]

    @api.put("/library")
    def update_instruction(self) -> list[Response | Effect]:
        """Update an existing instruction by dbid."""
        try:
            body = _parse_body(self.request)
            inst_id = body.get("id")
            if not inst_id:
                return [JSONResponse({"status": "error", "message": "Missing id"})]

            try:
                inst = Instruction.objects.get(dbid=inst_id)
            except Instruction.DoesNotExist:
                return [JSONResponse({"status": "error", "message": "Instruction not found"})]

            for field in ("display", "code", "coding_system", "comment"):
                if field in body:
                    setattr(inst, field, body[field])
            if "tags" in body:
                tags = body["tags"]
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
                inst.tags = tags
            inst.save()
            log.info("[PI] Updated instruction %s" % inst.dbid)
            return [JSONResponse({"status": "ok", "instruction": _instruction_to_dict(inst)})]
        except Exception as e:
            log.error("[PI PUT] Error: %s" % e)
            return [JSONResponse({"status": "error", "message": str(e)})]

    @api.delete("/library/<inst_id>")
    def delete_instruction(self) -> list[Response | Effect]:
        """Soft-delete an instruction by dbid."""
        try:
            inst_id = self.request.path_params["inst_id"]
            updated = Instruction.objects.filter(dbid=inst_id).update(active=False)
            if updated:
                log.info("[PI] Deactivated instruction %s" % inst_id)
            return [JSONResponse({"status": "ok"})]
        except Exception as e:
            log.error("[PI DELETE] Error: %s" % e)
            return [JSONResponse({"status": "error", "message": str(e)})]

    # ---- Tags ----

    @api.get("/tags")
    def list_tags(self) -> list[Response | Effect]:
        """Return all distinct tags across active instructions."""
        try:
            all_tags = set()
            for tags in Instruction.objects.filter(active=True).values_list("tags", flat=True):
                if tags:
                    for t in tags:
                        all_tags.add(t)
            return [JSONResponse({"status": "ok", "tags": sorted(all_tags)})]
        except Exception as e:
            log.error("[PI TAGS] Error: %s" % e)
            return [JSONResponse({"status": "ok", "tags": []})]

    # ---- Add to Note ----

    @api.post("/add-to-note")
    def add_to_note(self) -> list[Response | Effect]:
        """Commit InstructCommand effects to a patient's note.

        Body:
          - note_uuid: the note to add instructions to (required)
          - instructions: list of {coding_system, code, display, comment} (required)
        """
        try:
            body = _parse_body(self.request)
            note_uuid = body.get("note_uuid", "")
            instructions = body.get("instructions", [])

            if not note_uuid:
                return [JSONResponse({"status": "error", "message": "Missing note_uuid"})]
            if not instructions:
                return [JSONResponse({"status": "error", "message": "No instructions provided"})]

            effects: list[Response | Effect] = []
            for item in instructions:
                system = item.get("coding_system", "UNSTRUCTURED")
                code = item.get("code", "")
                display = item.get("display", "")
                comment = item.get("comment", "")

                if not code:
                    continue

                if system == "SNOMED":
                    coding = Coding(
                        system=CodeSystems.SNOMED, code=code, display=display
                    )
                else:
                    coding = Coding(system=CodeSystems.UNSTRUCTURED, code=code)

                cmd = InstructCommand(
                    note_uuid=note_uuid,
                    coding=coding,
                    comment=comment if comment else None,
                )
                cmd.command_uuid = str(uuid4())
                effects.append(cmd.originate())
                effects.append(cmd.commit())

            log.info(
                "[PI] Added %d instruction(s) to note %s"
                % (len(instructions), note_uuid[:8])
            )
            return [JSONResponse({"status": "ok", "added": len(instructions)})] + effects
        except Exception as e:
            log.error("[PI ADD] Error: %s" % e)
            return [JSONResponse({"status": "error", "message": str(e)})]
