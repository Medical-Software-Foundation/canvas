import json
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.utils.http import Http
from logger import log

LOG_PREFIX = "[new-staff-password]"


class NewStaffPasswordResetHandler(BaseHandler):
    """Send a Canvas password-reset email when a staff member is activated.

    Fires on STAFF_ACTIVATED - a staff record created with active=True, or an
    existing staff reactivated - and invokes the Canvas FHIR
    `$send-reset-password-email` operation for the matching Practitioner so the
    staff member receives an account-activation email automatically.
    """

    RESPONDS_TO = EventType.Name(EventType.STAFF_ACTIVATED)

    def compute(self) -> list[Effect]:
        """Send the reset email for the activated staff member. Emits no effects."""
        staff_id = self.event.target.id

        secrets = self.secrets or {}
        client_id = secrets.get("CANVAS_FHIR_CLIENT_ID")
        client_secret = secrets.get("CANVAS_FHIR_CLIENT_SECRET")
        if not client_id or not client_secret:
            log.error(
                f"{LOG_PREFIX} Missing CANVAS_FHIR_CLIENT_ID/CANVAS_FHIR_CLIENT_SECRET; "
                f"cannot send reset for staff {staff_id}."
            )
            return []

        environment = self.environment or {}
        subdomain = environment.get("CUSTOMER_IDENTIFIER")
        if not subdomain:
            log.error(
                f"{LOG_PREFIX} CUSTOMER_IDENTIFIER unavailable; cannot send reset for staff {staff_id}."
            )
            return []

        token = self._get_token(subdomain, client_id, client_secret)
        if not token:
            return []

        self._send_reset_email(subdomain, token, staff_id)
        return []

    def _get_token(self, subdomain: str, client_id: str, client_secret: str) -> str | None:
        """Fetch an OAuth client-credentials access token from the EMR instance."""
        url = f"https://{subdomain}.canvasmedical.com/auth/token/"
        body = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        )
        response = Http().post(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not response.ok:
            log.error(f"{LOG_PREFIX} Token request failed: HTTP {response.status_code}.")
            return None

        access_token = response.json().get("access_token")
        if not access_token:
            log.error(f"{LOG_PREFIX} Token response did not contain an access_token.")
            return None
        return str(access_token)

    def _send_reset_email(self, subdomain: str, token: str, staff_id: str) -> None:
        """Invoke the FHIR Practitioner $send-reset-password-email operation."""
        url = (
            f"https://fumage-{subdomain}.canvasmedical.com"
            f"/Practitioner/{staff_id}/$send-reset-password-email"
        )
        response = Http().post(
            url,
            data=json.dumps({"resourceType": "Parameters"}),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "accept": "application/json",
            },
        )
        if response.ok:
            log.info(f"{LOG_PREFIX} Password reset email sent for staff {staff_id}.")
        else:
            log.error(
                f"{LOG_PREFIX} Reset email failed for staff {staff_id}: HTTP {response.status_code}."
            )
