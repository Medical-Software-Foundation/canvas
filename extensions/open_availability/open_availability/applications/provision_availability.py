from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.v1.data.staff import Staff
from logger import log

API_KEY_PLACEHOLDER = "__API_KEY__"

ACCESS_DENIED_HTML = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 24px; color: #333; }
        h2 { margin-top: 0; color: #991b1b; }
        p { color: #666; line-height: 1.5; }
    </style>
</head>
<body>
    <h2>Access Denied</h2>
    <p>You are not authorized to use this application. Please contact an administrator.</p>
</body>
</html>
"""

PROVISION_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 24px; color: #333; }
        h2 { margin-top: 0; }
        p { color: #666; line-height: 1.5; }
        .btn-row { display: flex; gap: 12px; margin-top: 16px; }
        button {
            border: none; padding: 12px 24px;
            border-radius: 6px; font-size: 14px; cursor: pointer; font-weight: 500;
        }
        button:disabled { cursor: not-allowed; opacity: 0.5; }
        .btn-primary { background: #2563eb; color: white; }
        .btn-primary:hover:not(:disabled) { background: #1d4ed8; }
        .btn-warning { background: #d97706; color: white; }
        .btn-warning:hover:not(:disabled) { background: #b45309; }
        #status { margin-top: 16px; padding: 12px; border-radius: 6px; display: none; white-space: pre-line; }
        .success { background: #dcfce7; color: #166534; }
        .error { background: #fee2e2; color: #991b1b; }
        .loading { background: #dbeafe; color: #1e40af; }
        .hint { font-size: 12px; color: #999; margin-top: 8px; }
    </style>
</head>
<body>
    <h2>Provision Open Availability</h2>
    <p>
        Create availability calendars and events for all active staff members
        who have a schedulable role but don't yet have active availability.
    </p>
    <div class="btn-row">
        <button id="provision-btn" class="btn-primary" onclick="runProvisioning(false)">Run Provisioning</button>
        <button id="force-btn" class="btn-warning" onclick="runProvisioning(true)">Force Provision</button>
    </div>
    <p class="hint">
        <b>Run Provisioning</b> skips staff who already have active availability.<br>
        <b>Force Provision</b> ends existing events and creates new ones for all staff.
        Use this after changing time or timezone settings.
    </p>
    <div id="status"></div>
    <script>
        const API_KEY = "__API_KEY__";
        async function runProvisioning(force) {
            const provBtn = document.getElementById('provision-btn');
            const forceBtn = document.getElementById('force-btn');
            const status = document.getElementById('status');
            provBtn.disabled = true;
            forceBtn.disabled = true;
            status.style.display = 'block';
            status.className = 'loading';
            status.textContent = force
                ? 'Force provisioning - ending existing events and creating new ones...'
                : 'Provisioning availability for active staff...';
            const endpoint = force ? 'force-run' : 'run';
            try {
                const response = await fetch(`/plugin-io/api/open_availability/provision-availability/${endpoint}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': API_KEY,
                    },
                });
                const data = await response.json();
                if (response.ok) {
                    status.className = 'success';
                    let msg = `Done. Created: ${data.created}, Skipped: ${data.skipped}, Errors: ${data.errored}`;
                    if (data.ended > 0) {
                        msg += `, Events ended: ${data.ended}`;
                    }
                    if (data.errored_staff && data.errored_staff.length > 0) {
                        msg += `\nFailed staff: ${data.errored_staff.join('; ')}`;
                    }
                    status.textContent = msg;
                } else {
                    status.className = 'error';
                    status.textContent = data.error || 'An error occurred.';
                }
            } catch (err) {
                status.className = 'error';
                status.textContent = 'Failed to reach provisioning API: ' + err.message;
            }
            provBtn.disabled = false;
            forceBtn.disabled = false;
        }
    </script>
</body>
</html>
"""


def get_admin_users(secrets: dict[str, str]) -> set[str]:
    """Parse the ADMIN_USERS secret into a set of normalized name strings.

    Names are lowercased and stripped. Expected format: comma-separated
    "First Last" entries, e.g. "Jane Smith, John Doe".
    """
    admin_str = secrets.get("ADMIN_USERS", "")
    return {name.strip().lower() for name in admin_str.split(",") if name.strip()}


def is_user_authorized(user_id: str, admin_users: set[str]) -> bool:
    """Check if the staff member identified by user_id is in the admin_users set."""
    try:
        staff = Staff.objects.get(id=user_id)
    except Staff.DoesNotExist:
        log.warning(f"Staff not found for user id: {user_id}")
        return False

    full_name = f"{staff.first_name} {staff.last_name}".lower()
    return full_name in admin_users


class ProvisionAvailabilityApp(Application):
    """Admin application to manually provision open availability for all active staff."""

    def on_open(self) -> Effect:
        admin_users = get_admin_users(self.secrets)
        if not admin_users:
            log.warning("ADMIN_USERS secret is empty or missing, denying access")
            return LaunchModalEffect(
                content=ACCESS_DENIED_HTML,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Provision Open Availability",
            ).apply()

        user_id = self.event.context["user"]["id"]
        if not is_user_authorized(user_id, admin_users):
            log.info(f"User {user_id} is not authorized to use Provision Availability app")
            return LaunchModalEffect(
                content=ACCESS_DENIED_HTML,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Provision Open Availability",
            ).apply()

        api_key = self.secrets.get("simpleapi-api-key", "")
        html = PROVISION_HTML_TEMPLATE.replace(API_KEY_PLACEHOLDER, api_key)
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Provision Open Availability",
        ).apply()
