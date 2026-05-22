from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import AddBillingLineItem
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from curated_cpt_picker.models.curated_cpt_code import CuratedCptCode
from curated_cpt_picker.lib.cdm_validation import filter_valid_cpt_codes


def _modifier_summary(modifiers: list[dict]) -> str:
    """Render a short '25, 59' string for the modal UI."""
    if not modifiers:
        return ""
    return ", ".join(m.get("code", "") for m in modifiers if m.get("code"))


class PickerAPI(StaffSessionAuthMixin, SimpleAPI):
    """Provider-facing endpoints powering the 'Quick add codes' modal."""

    @api.get("/picker")
    def render_picker(self) -> list[Response | Effect]:
        note_id = self.request.query_params.get("note_id", "")

        curated = list(CuratedCptCode.objects.filter(enabled=True).order_by("display_order", "cpt_code"))
        valid_cpt_codes = filter_valid_cpt_codes([entry.cpt_code for entry in curated])

        visible = [
            {
                "id": str(entry.pk),
                "cpt_code": entry.cpt_code,
                "description": entry.description,
                "default_units": entry.default_units,
                "modifier_summary": _modifier_summary(entry.modifiers),
            }
            for entry in curated
            if entry.cpt_code in valid_cpt_codes
        ]

        html = render_to_string(
            "templates/picker_modal.html",
            {"codes": visible, "note_id": note_id},
        )
        return [HTMLResponse(html)]

    @api.post("/apply")
    def apply_codes(self) -> list[Response | Effect]:
        """Apply selected curated codes to the note as billing line items.

        Accepts either of two payload shapes for backward compatibility:
          - New shape: {"note_id": str, "selected": [{"id", "units", "modifiers"}]}
          - Old shape: {"note_id": str, "selected_ids": [str]}
        """
        body = self.request.json()
        note_id = body.get("note_id")
        if not note_id:
            return [JSONResponse({"error": "Missing note_id"}, status_code=400)]

        # Normalize to a list of overrides keyed by entry id.
        selected_raw = body.get("selected")
        if isinstance(selected_raw, list) and selected_raw:
            overrides: dict[str, dict] = {}
            for item in selected_raw:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                overrides[str(item["id"])] = item
        else:
            ids = body.get("selected_ids") or []
            if not isinstance(ids, list) or not ids:
                return [JSONResponse({"error": "Missing selected"}, status_code=400)]
            overrides = {str(i): {} for i in ids}

        if not overrides:
            return [JSONResponse({"error": "Missing selected"}, status_code=400)]

        entries = list(CuratedCptCode.objects.filter(pk__in=list(overrides.keys()), enabled=True))
        valid_cpt_codes = filter_valid_cpt_codes([entry.cpt_code for entry in entries])

        effects: list[Response | Effect] = []
        added: list[str] = []
        skipped: list[str] = []

        for entry in entries:
            if entry.cpt_code not in valid_cpt_codes:
                skipped.append(entry.cpt_code)
                continue

            override = overrides.get(str(entry.pk), {})
            units = override.get("units")
            if not isinstance(units, int) or units <= 0:
                units = entry.default_units
            modifiers = override.get("modifiers")
            if not isinstance(modifiers, list):
                modifiers = entry.modifiers or []

            effects.append(
                AddBillingLineItem(
                    note_id=str(note_id),
                    cpt=entry.cpt_code,
                    units=units,
                    modifiers=modifiers,
                ).apply()
            )
            added.append(entry.cpt_code)

        effects.append(JSONResponse({"added": added, "skipped": skipped}))
        return effects
