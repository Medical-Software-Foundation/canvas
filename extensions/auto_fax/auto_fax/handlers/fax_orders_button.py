"""The note's **Fax orders** button.

Shown on notes a ``fax_orders_button`` rule covers, while the plugin is on. A
click sends nothing: it opens a preview of what would go to whom, and the
staff member confirms there (see ``fax_orders_api.py``). The preview also says
plainly when there is nothing to send, for example when the patient's facility
has no fax number or the note has no committed orders.
"""

import json
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string

from auto_fax.services.config import MODE_DRY_RUN, SEND_WHOLE_NOTE, load_config
from auto_fax.services.orders import Plan, build_plan, find_note, type_names

PLUGIN_NAME = "auto_fax"
API_PATH = f"/plugin-io/api/{PLUGIN_NAME}/fax-orders/send"


def _format_fax(digits: str) -> str:
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _safe_json(value: Any) -> str:
    """JSON that can't close the inline <script> it is embedded in."""
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def preview_context(plan: Plan, dry_run: bool) -> dict[str, Any]:
    """Template context for the preview modal."""
    deliveries = []
    for delivery in plan.deliveries:
        deliveries.append(
            {
                "name": delivery.name or "Recipient",
                "fax": _format_fax(delivery.digits),
                "whole_note": delivery.send_as == SEND_WHOLE_NOTE,
                "fax_count": delivery.fax_count,
                "already_sent": delivery.already_sent,
                "last_sent": delivery.last_sent.isoformat()
                if delivery.last_sent
                else "",
                "orders": [
                    {"type": order.type_label, "label": order.label}
                    for order in delivery.orders
                ],
            }
        )
    return {
        "deliveries": deliveries,
        "problems": plan.problems,
        "has_orders": plan.has_orders,
        "all_already_sent": plan.all_already_sent,
        "order_types": type_names(plan.order_types),
        "metadata_notes": plan.metadata_notes,
        "dry_run": dry_run,
        "test_number": plan.test_number,
        "request_json": _safe_json({"note_id": plan.note_id}),
        "api_path": API_PATH,
    }


class FaxOrdersButton(ActionButton):
    """Opens a preview of the note's orders fax, with a button to send it."""

    BUTTON_TITLE = "Fax orders"
    BUTTON_KEY = "AUTO_FAX_FAX_ORDERS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        """Only on notes a button rule covers, while the plugin is on."""
        note_dbid = (self.event.context or {}).get("note_id")
        return find_note(load_config(self.secrets), dbid=note_dbid) is not None

    def handle(self) -> list[Effect]:
        """Open the preview. Nothing is faxed until the staff member confirms."""
        config = load_config(self.secrets)
        found = find_note(config, dbid=(self.event.context or {}).get("note_id"))
        if found is None:
            return []
        note, rules = found
        plan = build_plan(note, rules, config.test_fax_digits)
        html = render_to_string(
            "templates/fax_orders_modal.html",
            preview_context(plan, dry_run=config.mode == MODE_DRY_RUN),
        )
        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                content=html,
                title="Fax orders",
            ).apply()
        ]
