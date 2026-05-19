import uuid
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.commands import LabOrderCommand, PerformCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.lab import LabPartner
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.staff import Staff, StaffRole

from order_sets.models.order_set import OrderSet

try:
    from canvas_sdk.v1.data.charge_description_master import ChargeDescriptionMaster
except ImportError:  # CDM path may vary across SDK versions
    ChargeDescriptionMaster = None  # type: ignore[assignment,misc]

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

VALID_ORDER_TYPES = {"lab", "imaging", "poc"}

# Defense-in-depth maximum lengths for free-form text body fields. Direct API
# clients could otherwise submit unbounded strings.
_MAX_NAME = 200
_MAX_DESCRIPTION = 2000
_MAX_COMMENT = 2000
_MAX_LAB_PARTNER = 100  # UUID-ish identifier
_MAX_LAB_PARTNER_NAME = 200
_MAX_ITEM_CODE = 100
_MAX_ITEM_NAME = 200
_MAX_DX_CODE = 50  # ICD-10 codes


def _serialize_set(s: OrderSet) -> dict:
    """Convert an OrderSet row to the JSON shape the frontend expects."""
    return {
        "id": s.set_id,
        "name": s.name,
        "description": s.description,
        "order_type": s.order_type,
        "is_shared": s.is_shared,
        "created_by": s.created_by,
        "created_by_name": s.created_by_name,
        "diagnosis_codes": s.diagnosis_codes,
        "lab_partner": s.lab_partner,
        "lab_partner_name": s.lab_partner_name,
        "items": s.items,
        "fasting_required": s.fasting_required,
        "comment": s.comment,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "Unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)


def _not_found() -> JSONResponse:
    return JSONResponse({"error": "Order set not found"}, status_code=HTTPStatus.NOT_FOUND)


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=HTTPStatus.BAD_REQUEST)


def _validate_str(
    value: object, field: str, *, max_length: int, required: bool = False
) -> tuple[str | None, str | None]:
    """Validate a body string field.

    Returns (cleaned_value, error_message). Exactly one is None.
    - `None`/missing is treated as empty string (or 400 if required).
    - Non-string values 400.
    - Strings over max_length 400.
    - When required, the stripped value must be non-empty.
    """
    if value is None:
        if required:
            return None, f"{field} is required"
        return "", None
    if not isinstance(value, str):
        return None, f"{field} must be a string, got {type(value).__name__}"
    if len(value) > max_length:
        return None, f"{field} exceeds maximum length of {max_length} characters"
    if required and not value.strip():
        return None, f"{field} is required"
    return value, None


def _coerce_bool(value: object, field: str) -> tuple[bool, str | None]:
    """Strictly accept only JSON booleans.

    Python's `bool()` treats any non-empty string as truthy, which silently
    flips `{"is_shared": "false"}` to True. Direct API clients that send
    string booleans must get a clear 400 instead of a silent inversion.
    Returns (value, None) on success, (False, error_message) on failure.
    """
    if isinstance(value, bool):
        return value, None
    return False, f"{field} must be a JSON boolean (true/false), got {type(value).__name__}"


def _validate_items(items: object) -> str | None:
    """Return an error message if items is not a list of unique {code, name} dicts.

    Each entry must have non-empty `code` and `name` strings within their length
    caps. Duplicate `code` values across entries are rejected — duplicates at
    execute time produce duplicate clinical orders on the patient's note.
    """
    if not isinstance(items, list):
        return "items must be a list"
    limits = {"code": _MAX_ITEM_CODE, "name": _MAX_ITEM_NAME}
    codes_seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"items[{i}] must be an object"
        for key in ("code", "name"):
            v = item.get(key)
            if not isinstance(v, str) or not v.strip():
                return f"items[{i}].{key} must be a non-empty string"
            if len(v) > limits[key]:
                return f"items[{i}].{key} exceeds maximum length of {limits[key]} characters"
        code = item["code"]
        if code in codes_seen:
            return f"items[{i}].code duplicates an earlier entry (code={code!r})"
        codes_seen.add(code)
    return None


def _validate_diagnosis_codes(codes: object) -> str | None:
    """Return an error message if diagnosis_codes is not a list of strings."""
    if not isinstance(codes, list):
        return "diagnosis_codes must be a list"
    for i, code in enumerate(codes):
        if not isinstance(code, str):
            return f"diagnosis_codes[{i}] must be a string"
        if len(code) > _MAX_DX_CODE:
            return f"diagnosis_codes[{i}] exceeds maximum length of {_MAX_DX_CODE} characters"
    return None


def _validate_string_list(value: object, field: str, max_item_length: int) -> str | None:
    """Validate a list-of-strings body field (e.g. selected_codes)."""
    if not isinstance(value, list):
        return f"{field} must be a list"
    for i, v in enumerate(value):
        if not isinstance(v, str):
            return f"{field}[{i}] must be a string"
        if len(v) > max_item_length:
            return f"{field}[{i}] exceeds maximum length of {max_item_length} characters"
    return None


def _validate_lab_partner_for_type(order_type: str, lab_partner: object) -> str | None:
    """Lab order sets require a non-empty lab_partner."""
    if order_type != "lab":
        return None
    if not isinstance(lab_partner, str) or not lab_partner.strip():
        return "lab_partner is required for lab order sets"
    return None


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
                "is_admin": _is_admin(staff),
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
        return [Response(content, status_code=HTTPStatus.OK, content_type="text/javascript")]

    @api.get("/static/js/admin.js")
    def get_admin_js(self) -> list[Response | Effect]:
        content = render_to_string("static/js/admin.js").encode()
        return [Response(content, status_code=HTTPStatus.OK, content_type="text/javascript")]

    # ── Order Set CRUD ────────────────────────────────────────────────

    @api.get("/sets")
    def list_sets(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return [_unauthorized()]
        # Shared sets are visible to all staff; personal sets only to creator.
        qs = OrderSet.objects.filter(
            models_q_shared_or_owned(str(staff.id))
        ).order_by("name")
        return [JSONResponse([_serialize_set(s) for s in qs], status_code=HTTPStatus.OK)]

    @api.post("/sets")
    def create_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return [_unauthorized()]

        body = self.request.json()

        # String-field validation (type + length + required-ness)
        name, err = _validate_str(body.get("name"), "name", max_length=_MAX_NAME, required=True)
        if err:
            return [_bad_request(err)]
        assert name is not None
        name = name.strip()

        description, err = _validate_str(
            body.get("description"), "description", max_length=_MAX_DESCRIPTION
        )
        if err:
            return [_bad_request(err)]

        comment, err = _validate_str(body.get("comment"), "comment", max_length=_MAX_COMMENT)
        if err:
            return [_bad_request(err)]

        lab_partner, err = _validate_str(
            body.get("lab_partner"), "lab_partner", max_length=_MAX_LAB_PARTNER
        )
        if err:
            return [_bad_request(err)]
        assert lab_partner is not None

        lab_partner_name, err = _validate_str(
            body.get("lab_partner_name"), "lab_partner_name", max_length=_MAX_LAB_PARTNER_NAME
        )
        if err:
            return [_bad_request(err)]

        order_type = body.get("order_type", "lab")
        if order_type not in VALID_ORDER_TYPES:
            return [_bad_request(
                f"Invalid order_type: {order_type!r}. Must be one of: lab, imaging, poc"
            )]

        items = body.get("items", [])
        items_err = _validate_items(items)
        if items_err:
            return [_bad_request(items_err)]

        if "diagnosis_codes" in body:
            dx_err = _validate_diagnosis_codes(body["diagnosis_codes"])
            if dx_err:
                return [_bad_request(dx_err)]

        lp_err = _validate_lab_partner_for_type(order_type, lab_partner)
        if lp_err:
            return [_bad_request(lp_err)]

        is_shared, bool_err = _coerce_bool(body.get("is_shared", False), "is_shared")
        if bool_err:
            return [_bad_request(bool_err)]

        fasting_required, bool_err = _coerce_bool(
            body.get("fasting_required", False), "fasting_required"
        )
        if bool_err:
            return [_bad_request(bool_err)]

        if is_shared and not _is_admin(staff):
            return [JSONResponse(
                {"error": "Only administrators can create shared order sets"},
                status_code=HTTPStatus.FORBIDDEN,
            )]

        new_set = OrderSet.objects.create(
            set_id=str(uuid.uuid4()),
            name=name,
            description=description or "",
            order_type=order_type,
            is_shared=is_shared,
            created_by=str(staff.id),
            created_by_name=f"{staff.first_name} {staff.last_name}",
            diagnosis_codes=body.get("diagnosis_codes", []),
            lab_partner=lab_partner,
            lab_partner_name=lab_partner_name or "",
            items=items,
            fasting_required=fasting_required,
            comment=comment or "",
        )
        return [JSONResponse(_serialize_set(new_set), status_code=HTTPStatus.CREATED)]

    @api.put("/sets/<set_id>")
    def update_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return [_unauthorized()]

        set_id = self.request.path_params.get("set_id", "")
        body = self.request.json()

        if "order_type" in body and body["order_type"] not in VALID_ORDER_TYPES:
            return [_bad_request(
                f"Invalid order_type: {body['order_type']!r}. Must be one of: lab, imaging, poc"
            )]

        if "items" in body:
            items_err = _validate_items(body["items"])
            if items_err:
                return [_bad_request(items_err)]

        if "diagnosis_codes" in body:
            dx_err = _validate_diagnosis_codes(body["diagnosis_codes"])
            if dx_err:
                return [_bad_request(dx_err)]

        # String-field validation for any text field present in body
        _str_fields_with_limits = [
            ("name", _MAX_NAME, True),
            ("description", _MAX_DESCRIPTION, False),
            ("comment", _MAX_COMMENT, False),
            ("lab_partner", _MAX_LAB_PARTNER, False),
            ("lab_partner_name", _MAX_LAB_PARTNER_NAME, False),
        ]
        for field, max_length, required in _str_fields_with_limits:
            if field in body:
                cleaned, err = _validate_str(
                    body[field], field, max_length=max_length, required=required
                )
                if err:
                    return [_bad_request(err)]
                assert cleaned is not None  # err was None
                body[field] = cleaned.strip() if field == "name" else cleaned

        order_set = OrderSet.objects.filter(set_id=set_id).first()
        # Return 404 (not 403) when the caller can't view the set so we
        # don't confirm the set's existence to unauthorized requesters.
        # Mirrors execute_set / execute_custom.
        if not order_set or not _can_view(staff, order_set):
            return [_not_found()]

        if not _can_modify(staff, order_set):
            return [JSONResponse(
                {"error": "Not authorized to modify this order set"},
                status_code=HTTPStatus.FORBIDDEN,
            )]

        # Cross-field validation against the resulting order_type after
        # this PUT applies (body's value wins if present, else current row).
        effective_order_type = body.get("order_type", order_set.order_type)
        if "lab_partner" in body or effective_order_type != order_set.order_type:
            effective_lab_partner = body.get("lab_partner", order_set.lab_partner)
            lp_err = _validate_lab_partner_for_type(effective_order_type, effective_lab_partner)
            if lp_err:
                return [_bad_request(lp_err)]

        # Changing the is_shared flag (in either direction) requires admin
        # status. Without this gate, the creator of a personal set could
        # promote it to shared, then immediately lose modify rights to it
        # under the standard shared-set rule (admin-only).
        if "is_shared" in body:
            requested_is_shared, bool_err = _coerce_bool(body["is_shared"], "is_shared")
            if bool_err:
                return [_bad_request(bool_err)]
            if requested_is_shared != order_set.is_shared and not _is_admin(staff):
                return [JSONResponse(
                    {"error": "Only administrators can change a set's shared status"},
                    status_code=HTTPStatus.FORBIDDEN,
                )]
            order_set.is_shared = requested_is_shared

        if "fasting_required" in body:
            fasting_required, bool_err = _coerce_bool(
                body["fasting_required"], "fasting_required"
            )
            if bool_err:
                return [_bad_request(bool_err)]
            order_set.fasting_required = fasting_required

        for field in (
            "name", "description", "order_type",
            "diagnosis_codes", "lab_partner", "lab_partner_name",
            "items", "comment",
        ):
            if field in body:
                setattr(order_set, field, body[field])
        order_set.save()
        return [JSONResponse(_serialize_set(order_set), status_code=HTTPStatus.OK)]

    @api.delete("/sets/<set_id>")
    def delete_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return [_unauthorized()]

        set_id = self.request.path_params.get("set_id", "")
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        # Same visibility-or-404 pattern as execute_set / update_set.
        if not order_set or not _can_view(staff, order_set):
            return [_not_found()]

        if not _can_modify(staff, order_set):
            return [JSONResponse(
                {"error": "Not authorized to delete this order set"},
                status_code=HTTPStatus.FORBIDDEN,
            )]

        order_set.delete()
        return [JSONResponse({"status": "deleted"}, status_code=HTTPStatus.OK)]

    # ── Provider & Lab Data Endpoints ─────────────────────────────────

    @api.get("/providers")
    def list_providers(self) -> list[JSONResponse | Effect]:
        """Return active staff who have a PROVIDER role type (can place orders)."""
        providers = (
            Staff.objects.filter(active=True, roles__role_type="PROVIDER")
            .distinct()
            .order_by("first_name", "last_name")
        )
        data = [
            {
                "id": str(s.id),
                "name": f"{s.first_name} {s.last_name}".strip(),
                "credentials": getattr(s, "top_role_abbreviation", "") or "",
            }
            for s in providers
        ]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/note-provider")
    def get_note_provider(self) -> list[JSONResponse | Effect]:
        """Check if the patient's open note has a valid clinical provider."""
        patient_id = self.request.query_params.get("patient_id", "")
        note_uuid, provider_key = self._find_open_note(patient_id)
        if not note_uuid:
            return [JSONResponse(
                {"note_uuid": None, "provider_id": None, "provider_name": None},
                status_code=HTTPStatus.OK,
            )]

        if provider_key and _is_active_provider(provider_key):
            provider = Staff.objects.filter(id=provider_key).first()
            if provider:
                return [JSONResponse({
                    "note_uuid": note_uuid,
                    "provider_id": provider_key,
                    "provider_name": f"{provider.first_name} {provider.last_name}".strip(),
                }, status_code=HTTPStatus.OK)]

        return [JSONResponse(
            {"note_uuid": note_uuid, "provider_id": None, "provider_name": None},
            status_code=HTTPStatus.OK,
        )]

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
        partner_id = self.request.path_params.get("partner_id", "")
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
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=query) | Q(cpt_code__icontains=query))
        qs = qs.order_by("name")[:50]
        data = [
            {"code": cdm.cpt_code, "name": cdm.name}
            for cdm in qs
            if getattr(cdm, "cpt_code", "")
        ]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    # ── Order Execution ───────────────────────────────────────────────

    @api.post("/execute/<set_id>")
    def execute_set(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return [_unauthorized()]

        set_id = self.request.path_params.get("set_id", "")
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        # Return 404 (not 403) when the caller can't view the set so we
        # don't confirm the set's existence to an unauthorized requester.
        if not order_set or not _can_view(staff, order_set):
            return [_not_found()]

        body = self.request.json() if self.request.body else {}
        return self._execute_order_set(
            staff,
            order_set,
            order_set.items,
            body.get("patient_id", ""),
            body.get("provider_id", ""),
        )

    @api.post("/execute-custom")
    def execute_custom(self) -> list[JSONResponse | Effect]:
        staff = self._current_staff()
        if not staff:
            return [_unauthorized()]

        body = self.request.json()

        selected_codes_raw = body.get("selected_codes", [])
        sc_err = _validate_string_list(
            selected_codes_raw, "selected_codes", max_item_length=_MAX_ITEM_CODE
        )
        if sc_err:
            return [_bad_request(sc_err)]

        set_id = body.get("set_id", "")
        order_set = OrderSet.objects.filter(set_id=set_id).first()
        if not order_set or not _can_view(staff, order_set):
            return [_not_found()]

        selected_codes = set(selected_codes_raw)
        selected_items = [
            item for item in order_set.items if item.get("code") in selected_codes
        ]
        return self._execute_order_set(
            staff,
            order_set,
            selected_items,
            body.get("patient_id", ""),
            body.get("provider_id", ""),
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _current_staff(self) -> Staff | None:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return None
        return Staff.objects.filter(id=staff_id).first()

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
            Note.objects.filter(dbid__in=open_note_ids, patient__id=patient_id)
            .select_related("provider")
            .order_by("-created")
            .first()
        )
        if note:
            provider_key = str(note.provider.id) if note.provider else ""
            return str(note.id), provider_key
        return None, ""

    def _execute_order_set(
        self,
        staff: Staff,
        order_set: OrderSet,
        items: list[dict],
        patient_id: str,
        body_provider_id: str,
    ) -> list[JSONResponse | Effect]:
        if not items:
            return [JSONResponse(
                {"error": "No items selected"}, status_code=HTTPStatus.BAD_REQUEST
            )]

        note_uuid, _ = self._find_open_note(patient_id)
        if not note_uuid:
            return [JSONResponse(
                {"error": "No open note found for this patient. Please open a note first."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        staff_id = str(staff.id)

        order_type = order_set.order_type or "lab"
        if order_type not in VALID_ORDER_TYPES:
            return [JSONResponse(
                {"error": f"Unsupported order_type on set: {order_type!r}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        # Provider attribution applies only to lab/imaging orders. POC orders go
        # through PerformCommand which has no ordering_provider_key field, so we
        # skip the gate entirely for POC.
        # For lab/imaging:
        # - If the logged-in staff IS a provider, the order is placed under
        #   their ID. The body's provider_id is ignored (no impersonation).
        # - If the logged-in staff is NOT a provider, the body MUST supply a
        #   valid PROVIDER as provider_id; we use that ID.
        provider_key: str = ""
        if order_type != "poc":
            if _is_active_provider(staff_id):
                provider_key = staff_id
            else:
                if not body_provider_id or not _is_active_provider(body_provider_id):
                    return [JSONResponse(
                        {
                            "error": "An ordering provider is required.",
                            "needs_provider": True,
                        },
                        status_code=HTTPStatus.BAD_REQUEST,
                    )]
                provider_key = body_provider_id

        effects: list[JSONResponse | Effect] = []

        if order_type == "lab":
            command = LabOrderCommand(
                note_uuid=note_uuid,
                lab_partner=order_set.lab_partner,
                tests_order_codes=[item["code"] for item in items],
                ordering_provider_key=provider_key,
                diagnosis_codes=order_set.diagnosis_codes,
                fasting_required=order_set.fasting_required,
                comment=order_set.comment,
            )
            effects.append(command.originate())
            effects.append(JSONResponse(
                {
                    "status": "ordered",
                    "order_type": "lab",
                    "items_count": len(items),
                    "set_name": order_set.name,
                },
                status_code=HTTPStatus.OK,
            ))

        elif order_type == "imaging":
            from canvas_sdk.commands import ImagingOrderCommand

            for item in items:
                command = ImagingOrderCommand(
                    note_uuid=note_uuid,
                    image_code=item["code"],
                    ordering_provider_key=provider_key,
                    diagnosis_codes=order_set.diagnosis_codes,
                    comment=order_set.comment,
                )
                effects.append(command.originate())

            effects.append(JSONResponse(
                {
                    "status": "ordered",
                    "order_type": "imaging",
                    "items_count": len(items),
                    "set_name": order_set.name,
                },
                status_code=HTTPStatus.OK,
            ))

        else:  # order_type == "poc"
            for item in items:
                notes = item.get("name", "")
                if order_set.comment:
                    notes = f"{notes} — {order_set.comment}" if notes else order_set.comment
                effects.append(PerformCommand(
                    note_uuid=note_uuid,
                    cpt_code=item["code"],
                    notes=notes,
                ).originate())

            effects.append(JSONResponse(
                {
                    "status": "ordered",
                    "order_type": "poc",
                    "items_count": len(items),
                    "set_name": order_set.name,
                },
                status_code=HTTPStatus.OK,
            ))

        return effects


# ── Module-level helpers (testable without instantiating the handler) ──

def _is_active_provider(staff_id: str) -> bool:
    """True iff the given staff ID is active and has a PROVIDER role."""
    if not staff_id:
        return False
    return StaffRole.objects.filter(
        role_type="PROVIDER",
        staff__id=staff_id,
        staff__active=True,
    ).exists()


def _is_admin(staff: Staff | None) -> bool:
    """True iff the staff member has any administrative role.

    Admin = at least one StaffRole with domain == "ADM".
    """
    if not staff:
        return False
    return StaffRole.objects.filter(
        staff=staff, domain=StaffRole.RoleDomain.ADMINISTRATIVE
    ).exists()


def _can_view(staff: Staff | None, order_set: OrderSet) -> bool:
    """Visibility rule (read + execute).

    - Shared sets are visible to any authenticated staff.
    - Personal sets are visible only to their creator.
    """
    if not staff:
        return False
    if order_set.is_shared:
        return True
    return order_set.created_by == str(staff.id)


def _can_modify(staff: Staff | None, order_set: OrderSet) -> bool:
    """Authorization rule for update/delete on an order set.

    - Personal sets (is_shared=False): only the creator may modify.
    - Shared sets (is_shared=True): only admins may modify.
    """
    if not staff:
        return False
    if order_set.is_shared:
        return _is_admin(staff)
    return order_set.created_by == str(staff.id)


def models_q_shared_or_owned(staff_id: str):
    """Build a Q clause for list_sets visibility: shared OR owned by this staff."""
    from django.db.models import Q

    return Q(is_shared=True) | Q(created_by=staff_id)
