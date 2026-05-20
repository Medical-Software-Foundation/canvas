import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from django.db.models import Q

from canvas_sdk.commands import LabOrderCommand, PerformCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.lab import LabPartner, LabPartnerTest
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.staff import Staff, StaffRole
from logger import log

from order_sets.models.order_set import OrderSet

try:
    from canvas_sdk.v1.data.charge_description_master import ChargeDescriptionMaster
except ImportError:  # CDM path varies across SDK versions
    ChargeDescriptionMaster = None  # type: ignore[assignment,misc,unused-ignore]

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


def _auth_error() -> list[JSONResponse | Effect]:
    return [
        JSONResponse(
            {"error": "Authentication required"},
            status_code=HTTPStatus.UNAUTHORIZED,
        )
    ]


def _forbidden_error() -> list[JSONResponse | Effect]:
    return [
        JSONResponse(
            {"error": "Forbidden"},
            status_code=HTTPStatus.FORBIDDEN,
        )
    ]


def _bad_json_error() -> list[JSONResponse | Effect]:
    return [
        JSONResponse(
            {"error": "Invalid JSON body"},
            status_code=HTTPStatus.BAD_REQUEST,
        )
    ]


def _not_found_error() -> list[JSONResponse | Effect]:
    return [
        JSONResponse(
            {"error": "Order set not found"},
            status_code=HTTPStatus.NOT_FOUND,
        )
    ]


def _serialize(order_set: OrderSet) -> dict[str, Any]:
    """Render an OrderSet for the JSON API.

    The frontend looks for ``id`` (not ``set_id``) on every set in
    list/create/update responses; keep that contract stable.
    """
    return {
        "id": order_set.set_id,
        "name": order_set.name,
        "description": order_set.description,
        "order_type": order_set.order_type,
        "is_shared": order_set.is_shared,
        "created_by": order_set.created_by,
        "created_by_name": order_set.created_by_name,
        "diagnosis_codes": order_set.diagnosis_codes,
        "lab_partner": order_set.lab_partner,
        "lab_partner_name": order_set.lab_partner_name,
        "items": order_set.items,
        "fasting_required": order_set.fasting_required,
        "comment": order_set.comment,
        "created_at": order_set.created_at.isoformat() if order_set.created_at else None,
        "updated_at": order_set.updated_at.isoformat() if order_set.updated_at else None,
    }


class OrderSetsAPI(StaffSessionAuthMixin, SimpleAPI):

    # ── UI Endpoints ──────────────────────────────────────────────────

    @api.get("/ui")
    def get_ui(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id", "")
        staff = self._current_staff()
        html = render_to_string(
            "templates/main.html",
            {
                "patient_id": patient_id,
                "staff_id": str(staff.id) if staff else "",
                "staff_name": f"{staff.first_name} {staff.last_name}" if staff else "",
                "cache_bust": _CACHE_BUST,
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/admin-ui")
    def get_admin_ui(self) -> list[Response | Effect]:
        staff = self._current_staff()
        html = render_to_string(
            "templates/admin.html",
            {
                "staff_id": str(staff.id) if staff else "",
                "staff_name": f"{staff.first_name} {staff.last_name}" if staff else "",
                "cache_bust": _CACHE_BUST,
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    # ── Static file endpoints ─────────────────────────────────────────

    @api.get("/static/css/styles.css")
    def get_css(self) -> list[Response | Effect]:
        content = render_to_string("static/css/styles.css").encode()
        return [Response(content, status_code=HTTPStatus.OK, content_type="text/css")]

    @api.get("/static/js/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        content = render_to_string("static/js/main.js").encode()
        return [
            Response(
                content, status_code=HTTPStatus.OK, content_type="text/javascript"
            )
        ]

    @api.get("/static/js/admin.js")
    def get_admin_js(self) -> list[Response | Effect]:
        content = render_to_string("static/js/admin.js").encode()
        return [
            Response(
                content, status_code=HTTPStatus.OK, content_type="text/javascript"
            )
        ]

    # ── Order Set CRUD ────────────────────────────────────────────────

    @api.get("/sets")
    def list_sets(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        staff_id = str(staff.id) if staff else ""
        # Indexed lookup: every result is either shared OR created by this caller.
        sets = (
            OrderSet.objects
            .filter(Q(is_shared=True) | Q(created_by=staff_id))
            .order_by("name")
        )
        return [JSONResponse([_serialize(s) for s in sets], status_code=HTTPStatus.OK)]

    @api.post("/sets")
    def create_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return _auth_error()
        try:
            body = self.request.json()
        except ValueError:
            return _bad_json_error()
        order_set = OrderSet.objects.create(
            set_id=str(uuid.uuid4()),
            name=body.get("name", "Untitled"),
            description=body.get("description", ""),
            order_type=body.get("order_type", "lab"),
            is_shared=body.get("is_shared", False),
            created_by=str(staff.id),
            created_by_name=f"{staff.first_name} {staff.last_name}",
            diagnosis_codes=body.get("diagnosis_codes", []),
            lab_partner=body.get("lab_partner", ""),
            lab_partner_name=body.get("lab_partner_name", ""),
            items=body.get("items", []),
            fasting_required=body.get("fasting_required", False),
            comment=body.get("comment", ""),
        )
        return [JSONResponse(_serialize(order_set), status_code=HTTPStatus.CREATED)]

    @api.put("/sets/<set_id>")
    def update_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return _auth_error()
        try:
            body = self.request.json()
        except ValueError:
            return _bad_json_error()
        set_id = self.request.path.split("/sets/")[-1].split("?")[0]
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        if order_set is None:
            return _not_found_error()
        if not self._can_modify(order_set, staff):
            return _forbidden_error()
        # Only fields actually present in the body get overwritten — the rest
        # keep their stored values.
        for field in (
            "name",
            "description",
            "order_type",
            "is_shared",
            "diagnosis_codes",
            "lab_partner",
            "lab_partner_name",
            "items",
            "fasting_required",
            "comment",
        ):
            if field in body:
                setattr(order_set, field, body[field])
        order_set.save()
        return [JSONResponse(_serialize(order_set), status_code=HTTPStatus.OK)]

    @api.delete("/sets/<set_id>")
    def delete_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return _auth_error()
        set_id = self.request.path.split("/sets/")[-1].split("?")[0]
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        if order_set is None:
            return _not_found_error()
        if not self._can_modify(order_set, staff):
            return _forbidden_error()
        order_set.delete()
        return [JSONResponse({"status": "deleted"}, status_code=HTTPStatus.OK)]

    # ── Provider & Lab Data Endpoints ─────────────────────────────────

    @api.get("/providers")
    def list_providers(self) -> list[JSONResponse | Effect]:
        """Return active staff who have a PROVIDER role type (can place orders).

        Uses ``role.staff_id`` (the FK column already on the row) to avoid the
        per-row Staff lookup that ``role.staff.id`` would trigger.
        """
        provider_staff_ids = {
            str(role.staff_id)
            for role in StaffRole.objects.filter(role_type="PROVIDER")
        }
        providers = [
            {
                "id": str(s.id),
                "name": f"{s.first_name} {s.last_name}".strip(),
                "credentials": getattr(s, "top_role_abbreviation", "") or "",
            }
            for s in Staff.objects.filter(active=True)
            if str(s.id) in provider_staff_ids
        ]
        providers.sort(key=lambda p: p["name"])
        return [JSONResponse(providers, status_code=HTTPStatus.OK)]

    @api.get("/note-provider")
    def get_note_provider(self) -> list[JSONResponse | Effect]:
        """Check if the patient's open note has a valid clinical provider."""
        patient_id = self.request.query_params.get("patient_id", "")
        note_uuid, provider_key = self._find_open_note(patient_id)
        if not note_uuid:
            return [
                JSONResponse(
                    {"note_uuid": None, "provider_id": None, "provider_name": None},
                    status_code=HTTPStatus.OK,
                )
            ]

        if provider_key:
            provider = Staff.objects.filter(id=provider_key).first()
            if provider and provider.active:
                return [
                    JSONResponse(
                        {
                            "note_uuid": note_uuid,
                            "provider_id": provider_key,
                            "provider_name": f"{provider.first_name} {provider.last_name}".strip(),
                        },
                        status_code=HTTPStatus.OK,
                    )
                ]

        return [
            JSONResponse(
                {
                    "note_uuid": note_uuid,
                    "provider_id": None,
                    "provider_name": None,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/lab-partners")
    def list_lab_partners(self) -> list[JSONResponse | Effect]:
        partners = LabPartner.objects.all()
        data = [
            {
                "id": str(p.id),
                "name": p.name,
                "electronic_ordering": getattr(
                    p, "electronic_ordering_enabled", False
                ),
            }
            for p in partners
        ]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/lab-tests/<partner_id>")
    def list_lab_tests(self) -> list[JSONResponse | Effect]:
        partner_id = self.request.path.split("/lab-tests/")[-1].split("?")[0]
        search = self.request.query_params.get("search", "")
        partner = LabPartner.objects.filter(id=partner_id).first()
        if not partner:
            return [JSONResponse([], status_code=HTTPStatus.OK)]
        tests = partner.available_tests.all()
        if search:
            tests = tests.filter(order_name__icontains=search)
        tests = tests.order_by("order_name")[:100]
        data = [
            {
                "code": t.order_code,
                "name": t.order_name,
                "cpt_code": getattr(t, "cpt_code", ""),
            }
            for t in tests
        ]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/cpt-search")
    def cpt_search(self) -> list[JSONResponse | Effect]:
        """Search ChargeDescriptionMaster for CPT codes (POC lab/in-office tests)."""
        if ChargeDescriptionMaster is None:
            return [JSONResponse([], status_code=HTTPStatus.OK)]
        query = self.request.query_params.get("q", "").strip()
        qs = ChargeDescriptionMaster.objects.all()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(cpt_code__icontains=query))
        qs = qs.order_by("name")[:50]
        data = []
        for cdm in qs:
            code = getattr(cdm, "cpt_code", "") or ""
            name = getattr(cdm, "name", "") or ""
            if not code:
                continue
            data.append({"code": code, "name": name})
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    # ── Order Execution ───────────────────────────────────────────────

    @api.post("/execute/<set_id>")
    def execute_set(self) -> list[JSONResponse | Effect]:
        set_id = self.request.path.split("/execute/")[-1].split("?")[0]
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        if order_set is None:
            return _not_found_error()
        body = self.request.json() if self.request.body else {}
        patient_id = body.get("patient_id", "")
        provider_id = body.get("provider_id", "")
        return self._execute_order_set(
            order_set, order_set.items, patient_id, provider_id
        )

    @api.post("/execute-custom")
    def execute_custom(self) -> list[JSONResponse | Effect]:
        body = self.request.json()
        set_id = body.get("set_id", "")
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        if order_set is None:
            return _not_found_error()
        selected_codes = set(body.get("selected_codes", []))
        selected_items = [
            item for item in order_set.items if item["code"] in selected_codes
        ]
        patient_id = body.get("patient_id", "")
        provider_id = body.get("provider_id", "")
        return self._execute_order_set(
            order_set, selected_items, patient_id, provider_id
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _current_staff(self) -> Staff | None:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return None
        return Staff.objects.filter(id=staff_id).first()

    def _admin_staff_ids(self) -> set[str]:
        """Return the configured admin staff IDs as a set.

        Fails closed: if ``ADMIN_STAFF_IDS`` is unset or empty, no caller is
        treated as an admin and only the creator can modify a set.
        """
        raw = self.secrets.get("ADMIN_STAFF_IDS", "") or ""
        admin_ids = {sid.strip() for sid in raw.split(",") if sid.strip()}
        if not admin_ids:
            log.warning(
                "ADMIN_STAFF_IDS is not configured; only set creators can modify "
                "their own order sets. Set this secret to a comma-separated list "
                "of staff UUIDs to allow admins to manage shared sets."
            )
        return admin_ids

    def _can_modify(self, order_set: OrderSet, staff: Staff) -> bool:
        """Authorize a write against an existing order set.

        Allowed if the caller created the set, or if their id appears in
        ``ADMIN_STAFF_IDS``. Empty ``created_by`` never matches (defense in
        depth against legacy rows that pre-date the create-time auth gate).
        """
        staff_id = str(staff.id)
        created_by = order_set.created_by
        if created_by and created_by == staff_id:
            return True
        return staff_id in self._admin_staff_ids()

    def _find_open_note(self, patient_id: str) -> tuple[str | None, str]:
        """Find the most recent open note for a patient. Returns (note_uuid, provider_key)."""
        open_states = [
            NoteStates.NEW,
            NoteStates.PUSHED,
            NoteStates.CONVERTED,
            NoteStates.UNLOCKED,
            NoteStates.RESTORED,
            NoteStates.UNDELETED,
        ]
        open_note_ids = CurrentNoteStateEvent.objects.filter(
            state__in=open_states
        ).values_list("note_id", flat=True)

        note = (
            Note.objects.filter(
                dbid__in=open_note_ids,
                patient__id=patient_id,
            )
            .order_by("-created")
            .first()
        )
        if note:
            provider_key = str(note.provider.id) if note.provider else ""
            return str(note.id), provider_key
        return None, ""

    def _resolve_provider(self, provider_id: str) -> str | None:
        """Return ``provider_id`` if it belongs to an *active* PROVIDER, else None.

        ``staff__active=True`` is the critical join: deactivated staff keep
        their PROVIDER role rows for audit/historical reasons, so without the
        active filter we'd happily originate orders under a since-disabled
        provider (e.g. an old open note whose original provider has left).

        Single ``.exists()`` query — no row iteration, no per-row Staff fetch.
        """
        if not provider_id:
            return None
        exists = (
            StaffRole.objects
            .filter(role_type="PROVIDER", staff_id=provider_id, staff__active=True)
            .exists()
        )
        return provider_id if exists else None

    def _execute_order_set(
        self,
        order_set: OrderSet,
        items: list[dict],
        patient_id: str,
        provider_id: str = "",
    ) -> list[JSONResponse | Effect]:
        if not items:
            return [
                JSONResponse(
                    {"error": "No items selected"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        note_uuid, note_provider_key = self._find_open_note(patient_id)
        if not note_uuid:
            return [
                JSONResponse(
                    {"error": "No open note found for this patient. Please open a note first."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Ordering provider precedence: note provider > explicit provider_id.
        provider_key = self._resolve_provider(note_provider_key)
        if not provider_key and provider_id:
            provider_key = self._resolve_provider(provider_id)

        if not provider_key:
            return [
                JSONResponse(
                    {
                        "error": "No valid ordering provider. Please select a provider.",
                        "needs_provider": True,
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        order_type = order_set.order_type or "lab"
        effects: list[JSONResponse | Effect] = []

        if order_type == "lab":
            lab_partner = order_set.lab_partner or ""
            test_codes = [item["code"] for item in items]
            diagnosis_codes = order_set.diagnosis_codes or []
            fasting = bool(order_set.fasting_required)
            comment = order_set.comment or ""

            command = LabOrderCommand(
                note_uuid=note_uuid,
                lab_partner=lab_partner,
                tests_order_codes=test_codes,
                ordering_provider_key=provider_key,
                diagnosis_codes=diagnosis_codes,
                fasting_required=fasting,
                comment=comment,
            )
            effects.append(command.originate())
            effects.append(
                JSONResponse(
                    {
                        "status": "ordered",
                        "order_type": "lab",
                        "items_count": len(test_codes),
                        "set_name": order_set.name,
                    },
                    status_code=HTTPStatus.OK,
                )
            )

        elif order_type == "imaging":
            from canvas_sdk.commands import ImagingOrderCommand

            ordered_count = 0
            for item in items:
                command = ImagingOrderCommand(
                    note_uuid=note_uuid,
                    image_code=item["code"],
                    ordering_provider_key=provider_key,
                    diagnosis_codes=order_set.diagnosis_codes or [],
                    comment=order_set.comment or "",
                )
                effects.append(command.originate())
                ordered_count += 1

            effects.append(
                JSONResponse(
                    {
                        "status": "ordered",
                        "order_type": "imaging",
                        "items_count": ordered_count,
                        "set_name": order_set.name,
                    },
                    status_code=HTTPStatus.OK,
                )
            )

        elif order_type == "poc":
            comment = order_set.comment or ""
            ordered_count = 0
            for item in items:
                notes = item.get("name", "")
                if comment:
                    notes = f"{notes} — {comment}" if notes else comment
                command = PerformCommand(
                    note_uuid=note_uuid,
                    cpt_code=item["code"],
                    notes=notes,
                )
                effects.append(command.originate())
                ordered_count += 1

            effects.append(
                JSONResponse(
                    {
                        "status": "ordered",
                        "order_type": "poc",
                        "items_count": ordered_count,
                        "set_name": order_set.name,
                    },
                    status_code=HTTPStatus.OK,
                )
            )

        return effects
