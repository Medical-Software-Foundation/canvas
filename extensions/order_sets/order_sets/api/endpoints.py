import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands import LabOrderCommand, PerformCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.lab import LabPartner, LabPartnerTest
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.staff import Staff, StaffRole

try:
    from canvas_sdk.v1.data.charge_description_master import ChargeDescriptionMaster
except ImportError:  # CDM path varies across SDK versions
    ChargeDescriptionMaster = None  # type: ignore[assignment,misc,unused-ignore]

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))
_CACHE_KEY = "order_sets_data"
_CACHE_TTL = 14 * 24 * 3600  # 14 days (max allowed)


def _get_all_sets() -> list[dict]:
    """Load all order sets from cache."""
    cache = get_cache()
    data = cache.get(_CACHE_KEY)
    if data is None:
        return []
    if isinstance(data, str):
        loaded: list[dict] = json.loads(data)
        return loaded
    sets: list[dict] = data
    return sets


def _save_all_sets(sets: list[dict]) -> None:
    """Save all order sets to cache."""
    cache = get_cache()
    cache.set(_CACHE_KEY, sets, timeout_seconds=_CACHE_TTL)


def _is_active_staff(staff: Staff) -> bool:
    """Check if a staff member is active."""
    try:
        return bool(staff.active)
    except Exception:
        return False


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
        try:
            staff = self._current_staff()
            staff_id = str(staff.id) if staff else ""
            all_sets = _get_all_sets()
            results = [
                s for s in all_sets
                if s.get("is_shared") or s.get("created_by") == staff_id
            ]
            results.sort(key=lambda x: x.get("name", ""))
            return [JSONResponse(results, status_code=HTTPStatus.OK)]
        except Exception as e:
            return [JSONResponse({"error": f"list_sets: {type(e).__name__}: {e}"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

    @api.post("/sets")
    def create_set(self) -> list[JSONResponse | Effect]:
        try:
            body = self.request.json()
            staff = self._current_staff()
            now = datetime.now(timezone.utc).isoformat()
            new_set = {
                "id": str(uuid.uuid4()),
                "name": body.get("name", "Untitled"),
                "description": body.get("description", ""),
                "order_type": body.get("order_type", "lab"),
                "is_shared": body.get("is_shared", False),
                "created_by": str(staff.id) if staff else "",
                "created_by_name": f"{staff.first_name} {staff.last_name}" if staff else "",
                "diagnosis_codes": body.get("diagnosis_codes", []),
                "lab_partner": body.get("lab_partner", ""),
                "lab_partner_name": body.get("lab_partner_name", ""),
                "items": body.get("items", []),
                "fasting_required": body.get("fasting_required", False),
                "comment": body.get("comment", ""),
                "created_at": now,
                "updated_at": now,
            }
            all_sets = _get_all_sets()
            all_sets.append(new_set)
            _save_all_sets(all_sets)
            return [JSONResponse(new_set, status_code=HTTPStatus.CREATED)]
        except Exception as e:
            return [JSONResponse({"error": f"create_set: {type(e).__name__}: {e}"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

    @api.put("/sets/<set_id>")
    def update_set(self) -> list[JSONResponse | Effect]:
        try:
            set_id = self.request.path.split("/sets/")[-1].split("?")[0]
            body = self.request.json()
            all_sets = _get_all_sets()
            for s in all_sets:
                if s["id"] == set_id:
                    s["name"] = body.get("name", s["name"])
                    s["description"] = body.get("description", s["description"])
                    s["order_type"] = body.get("order_type", s["order_type"])
                    s["is_shared"] = body.get("is_shared", s["is_shared"])
                    s["diagnosis_codes"] = body.get("diagnosis_codes", s["diagnosis_codes"])
                    s["lab_partner"] = body.get("lab_partner", s["lab_partner"])
                    s["lab_partner_name"] = body.get("lab_partner_name", s["lab_partner_name"])
                    s["items"] = body.get("items", s["items"])
                    s["fasting_required"] = body.get("fasting_required", s["fasting_required"])
                    s["comment"] = body.get("comment", s["comment"])
                    s["updated_at"] = datetime.now(timezone.utc).isoformat()
                    _save_all_sets(all_sets)
                    return [JSONResponse(s, status_code=HTTPStatus.OK)]
            return [JSONResponse({"error": "Order set not found"}, status_code=HTTPStatus.NOT_FOUND)]
        except Exception as e:
            return [JSONResponse({"error": f"update_set: {type(e).__name__}: {e}"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

    @api.delete("/sets/<set_id>")
    def delete_set(self) -> list[JSONResponse | Effect]:
        try:
            set_id = self.request.path.split("/sets/")[-1].split("?")[0]
            all_sets = _get_all_sets()
            new_sets = [s for s in all_sets if s["id"] != set_id]
            if len(new_sets) == len(all_sets):
                return [JSONResponse({"error": "Order set not found"}, status_code=HTTPStatus.NOT_FOUND)]
            _save_all_sets(new_sets)
            return [JSONResponse({"status": "deleted"}, status_code=HTTPStatus.OK)]
        except Exception as e:
            return [JSONResponse({"error": f"delete_set: {type(e).__name__}: {e}"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

    # ── Provider & Lab Data Endpoints ─────────────────────────────────

    @api.get("/providers")
    def list_providers(self) -> list[JSONResponse | Effect]:
        """Return active staff who have a PROVIDER role type (can place orders)."""
        try:
            # Collect staff IDs that have a PROVIDER role by iterating roles directly
            provider_staff_ids = set()
            for role in StaffRole.objects.filter(role_type="PROVIDER"):
                provider_staff_ids.add(str(role.staff.id))
            providers = []
            for s in Staff.objects.filter(active=True):
                if str(s.id) in provider_staff_ids:
                    providers.append({
                        "id": str(s.id),
                        "name": f"{s.first_name} {s.last_name}".strip(),
                        "credentials": getattr(s, "top_role_abbreviation", "") or "",
                    })
            providers.sort(key=lambda p: p["name"])
            return [JSONResponse(providers, status_code=HTTPStatus.OK)]
        except Exception as e:
            return [JSONResponse({"error": f"list_providers: {type(e).__name__}: {e}"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

    @api.get("/note-provider")
    def get_note_provider(self) -> list[JSONResponse | Effect]:
        """Check if the patient's open note has a valid clinical provider."""
        try:
            patient_id = self.request.query_params.get("patient_id", "")
            note_uuid, provider_key = self._find_open_note(patient_id)
            if not note_uuid:
                return [JSONResponse({"note_uuid": None, "provider_id": None, "provider_name": None}, status_code=HTTPStatus.OK)]

            if provider_key:
                provider = Staff.objects.filter(id=provider_key).first()
                if provider and _is_active_staff(provider):
                    return [JSONResponse({
                        "note_uuid": note_uuid,
                        "provider_id": provider_key,
                        "provider_name": f"{provider.first_name} {provider.last_name}".strip(),
                    }, status_code=HTTPStatus.OK)]

            return [JSONResponse({
                "note_uuid": note_uuid,
                "provider_id": None,
                "provider_name": None,
            }, status_code=HTTPStatus.OK)]
        except Exception as e:
            return [JSONResponse({"error": f"get_note_provider: {type(e).__name__}: {e}"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

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
            from django.db.models import Q
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
        all_sets = _get_all_sets()
        order_set = next((s for s in all_sets if s["id"] == set_id), None)
        if not order_set:
            return [
                JSONResponse(
                    {"error": "Order set not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]
        body = self.request.json() if self.request.body else {}
        patient_id = body.get("patient_id", "")
        provider_id = body.get("provider_id", "")
        return self._execute_order_set(order_set, order_set["items"], patient_id, provider_id)

    @api.post("/execute-custom")
    def execute_custom(self) -> list[JSONResponse | Effect]:
        body = self.request.json()
        set_id = body.get("set_id", "")
        all_sets = _get_all_sets()
        order_set = next((s for s in all_sets if s["id"] == set_id), None)
        if not order_set:
            return [
                JSONResponse(
                    {"error": "Order set not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]
        selected_codes = set(body.get("selected_codes", []))
        selected_items = [
            item for item in order_set["items"] if item["code"] in selected_codes
        ]
        patient_id = body.get("patient_id", "")
        provider_id = body.get("provider_id", "")
        return self._execute_order_set(order_set, selected_items, patient_id, provider_id)

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
        """Validate that the given provider_id has a PROVIDER role type. Returns ID or None."""
        if not provider_id:
            return None
        for role in StaffRole.objects.filter(role_type="PROVIDER"):
            if str(role.staff.id) == str(provider_id):
                return provider_id
        return None

    def _execute_order_set(
        self, order_set: dict, items: list[dict], patient_id: str, provider_id: str = ""
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

        # Determine ordering provider: note provider > explicit provider_id
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

        order_type = order_set.get("order_type", "lab")
        effects: list[JSONResponse | Effect] = []

        if order_type == "lab":
            lab_partner = order_set.get("lab_partner", "")
            test_codes = [item["code"] for item in items]
            diagnosis_codes = order_set.get("diagnosis_codes", [])
            fasting = order_set.get("fasting_required", False)
            comment = order_set.get("comment", "")

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
                        "set_name": order_set.get("name", ""),
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
                    diagnosis_codes=order_set.get("diagnosis_codes", []),
                    comment=order_set.get("comment", ""),
                )
                effects.append(command.originate())
                ordered_count += 1

            effects.append(
                JSONResponse(
                    {
                        "status": "ordered",
                        "order_type": "imaging",
                        "items_count": ordered_count,
                        "set_name": order_set.get("name", ""),
                    },
                    status_code=HTTPStatus.OK,
                )
            )

        elif order_type == "poc":
            comment = order_set.get("comment", "")
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
                        "set_name": order_set.get("name", ""),
                    },
                    status_code=HTTPStatus.OK,
                )
            )

        return effects
