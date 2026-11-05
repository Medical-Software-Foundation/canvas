"""The send step behind the **Fax orders** button's preview.

``POST /fax-orders/send`` with ``{"note_id": "...", "resend": false}``. Only a
logged-in staff member can call it. It rebuilds the plan from the database
rather than trusting anything from the browser except the note id, so a stale
preview can't send something the rules no longer allow.

Double sends: without ``"resend": true``, a recipient that already has
everything is skipped, so a second click or a replayed request sends nothing
new. The preview only offers ``resend`` (as "Send again") when everything was
already sent.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from logger import log

from auto_fax.services.config import MODE_DRY_RUN, load_config
from auto_fax.services.orders import Plan, build_plan, fax_effects, find_note


class FaxOrdersAPI(StaffSessionAuthMixin, SimpleAPI):
    """Sends the orders fax a staff member confirmed in the preview."""

    PREFIX = "/fax-orders"

    @api.post("/send")
    def send(self) -> list[Response | Effect]:
        """Fax the note's orders to each recipient, per the button rules."""
        try:
            body = self.request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("note_id"), str):
            return [_error("note_id is required", HTTPStatus.BAD_REQUEST)]
        note_id = body["note_id"].strip()
        resend = body.get("resend") is True

        config = load_config(self.secrets)
        found = find_note(config, note_id=note_id) if note_id else None
        if found is None:
            return [
                _error(
                    "Fax orders is not available for this note.", HTTPStatus.NOT_FOUND
                )
            ]
        note, rules = found
        plan = build_plan(note, rules, config.test_fax_digits)
        if not plan.has_orders:
            return [
                JSONResponse(
                    {"status": "nothing", "faxes": 0, "message": _nothing_message(plan)}
                )
            ]

        dry_run = config.mode == MODE_DRY_RUN
        effects, count = fax_effects(plan, resend=resend, dry_run=dry_run)
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        log.info(
            f"[auto_fax] fax orders for note {note_id} by staff {staff_id}: "
            f"{count} fax(es){' (dry run)' if dry_run else ''}"
            f"{' (resend)' if resend else ''}"
        )
        if count == 0:
            status, message = (
                "already_sent",
                "These orders were already faxed. Nothing was sent.",
            )
        elif dry_run:
            status, message = (
                "dry_run",
                f"Dry run: {count} fax(es) would be sent. Nothing was sent.",
            )
        else:
            status, message = (
                "sent",
                f"Sent {count} fax(es). Delivery status shows in the fax history.",
            )
        return [
            JSONResponse({"status": status, "faxes": count, "message": message}),
            *effects,
        ]


def _nothing_message(plan: Plan) -> str:
    if plan.problems:
        return "Nothing was sent. " + " ".join(plan.problems)
    return "Nothing was sent: this note has no committed orders to fax."


def _error(message: str, status: HTTPStatus) -> JSONResponse:
    return JSONResponse({"status": "error", "message": message}, status_code=status)
