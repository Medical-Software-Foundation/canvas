"""SimpleAPI for admin and patient views.

Handlers import SDK models and delivery helpers *inside* the methods that use
them. That is deliberate: the tests patch those names at their source module,
which only works when the import resolves at call time. Only names needed at
module scope are imported here.
"""
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.v1.data.patient import Patient
from logger import log

from appointment_reminders.services.authz import is_admin_staff
from appointment_reminders.services.business_line import (
    get_business_line_from_number,
    get_business_line_name,
)
from appointment_reminders.services.config import (
    CampaignConfig,
    get_effective_campaign_config,
    load_config,
    save_config,
    templates_locked,
)
from appointment_reminders.services.theming import theme_style_block
from appointment_reminders.services.delivery import is_testing_mode_active
from appointment_reminders.services.history import get_patient_history as fetch_patient_history
from appointment_reminders.services.history import (
    get_unresolved_senders as fetch_unresolved_senders,
)


# Campaign types with stored templates behind them. Manual sends are limited to
# these while copy is locked; there is no free-text campaign any more.
SENDABLE_CAMPAIGNS = frozenset(
    {"confirmation", "reminder", "telehealth", "noshow", "cancellation"}
)

# Routes under this prefix configure campaigns for the whole instance, so they
# need an admin role on top of a staff session. Everything else here serves the
# per-patient chart panel and stays open to any logged-in staff member.
_ADMIN_PATH_PREFIX = "/admin"


class NotificationAPI(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for admin configuration and notification history."""

    PREFIX = ""

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Require a staff session, plus an admin role for the ``/admin`` routes.

        The annotation on ``credentials`` is load-bearing: ``SimpleAPI`` reads it
        to decide which credentials class to build, so it has to stay.

        This is the enforceable boundary for the admin console. The provider-menu
        item cannot be hidden per user — ``visible()`` exists only on embedded
        applications, and ``ProviderMenuConfiguration`` explicitly does not apply
        to plugin-provided menu items — so a non-admin can always reach these URLs
        directly. Refusing them here is what actually protects the config.
        """
        if not super().authenticate(credentials):
            return False
        path = getattr(self.request, "path", "") or ""
        if not path.startswith(_ADMIN_PATH_PREFIX):
            return True
        return is_admin_staff(credentials.logged_in_user.get("id"), self.secrets)

    @api.get("/access-denied")
    def get_access_denied_page(self) -> list[Response | Effect]:
        """Serve the page shown when a non-admin opens the admin application.

        Deliberately outside the ``/admin`` prefix: the whole point is that it
        renders for someone the gate above turns away.
        """
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Appointment Reminders</title>
    {theme_style_block()}
    <style>
        body {{
            font-family: var(--font-stack);
            background: var(--surface-page);
            color: var(--text-body);
            margin: 0;
            padding: 48px 24px;
            text-align: center;
        }}
        h1 {{ color: var(--text-strong); font-size: 18px; margin: 0 0 8px; }}
        p {{ color: var(--text-muted); font-size: 14px; margin: 0; }}
    </style>
</head>
<body>
    <h1>You don't have access to Appointment Reminders</h1>
    <p>Configuring reminder campaigns is limited to administrator roles.
       Ask an administrator if you need access.</p>
</body>
</html>"""
        return [HTMLResponse(html)]

    @api.get("/admin")
    def get_admin_page(self) -> list[Response | Effect]:
        """Serve admin configuration page."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Appointment Reminders</title>
    {THEME_STYLE_PLACEHOLDER}
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: var(--font-stack);
            margin: 0;
            padding: 20px;
            background: var(--surface-page);
            color: var(--text-strong);
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 14px;
            box-shadow: 0 1px 4px rgba(26,35,50,0.06), 0 0 0 1px rgba(26,35,50,0.04);
        }
        .tabs {
            display: flex;
            align-items: center;
            border-bottom: 1.5px solid var(--border-default);
            position: sticky;
            top: 0;
            background: #fff;
            border-radius: 14px 14px 0 0;
            z-index: 10;
        }
        .tab {
            padding: 14px 24px;
            cursor: pointer;
            border-bottom: 2.5px solid transparent;
            font-weight: 600;
            font-size: 14px;
            color: var(--text-muted);
            transition: all 0.15s ease;
        }
        .tab:hover { color: var(--text-strong); }
        .tab.active {
            border-bottom-color: var(--brand-primary);
            color: var(--brand-primary);
        }
        .tab-content {
            display: none;
            padding: 24px;
        }
        .tab-content.active {
            display: block;
        }
        .campaign-card {
            border: 1.5px solid var(--border-default);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 16px;
            background: #fff;
        }
        .campaign-card.collapsed {
            margin-bottom: 12px;
        }
        .campaign-card.collapsed .campaign-header {
            margin-bottom: 0;
        }
        .campaign-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            cursor: pointer;
        }
        .campaign-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--text-strong);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .form-group {
            margin-bottom: 16px;
        }
        label {
            display: block;
            margin-bottom: 4px;
            font-weight: 600;
            font-size: 12.5px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        input[type="text"], textarea {
            width: 100%;
            padding: 7px 10px;
            border: 1.5px solid var(--border-default);
            border-radius: 7px;
            font-family: var(--font-stack);
            font-size: 13.5px;
            color: var(--text-strong);
            background: var(--surface-page);
            outline: none;
            box-sizing: border-box;
            transition: border-color 0.15s;
        }
        input[type="text"]:focus, textarea:focus {
            border-color: var(--brand-primary);
        }
        textarea {
            min-height: 80px;
            resize: vertical;
            line-height: 1.5;
        }
        .template-label-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            margin-bottom: 4px;
        }
        .template-label-row label {
            margin-bottom: 0;
        }
        .var-insert-btn {
            background: var(--surface-page);
            border: 1.5px solid var(--border-default);
            border-radius: 6px;
            padding: 3px 10px;
            cursor: pointer;
            font-size: 12px;
            font-family: var(--font-stack);
            color: var(--text-muted);
            line-height: 1.2;
            transition: all 0.15s;
        }
        .var-insert-btn:hover {
            background: rgba(74,111,165,0.06);
            color: var(--brand-primary);
            border-color: var(--brand-primary);
        }
        .var-dropdown {
            display: none;
            position: absolute;
            top: calc(100% + 4px);
            right: 0;
            background: white;
            border: 1.5px solid var(--border-default);
            border-radius: 10px;
            box-shadow: 0 4px 16px rgba(26,35,50,0.12);
            z-index: 10;
            min-width: 220px;
            max-height: 300px;
            padding: 6px;
            overflow-y: auto;
        }
        .var-dropdown.open {
            display: block;
        }
        .var-group-label {
            padding: 4px 8px 2px;
            font-size: 10px;
            font-weight: 600;
            color: var(--text-soft);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .var-group-label:not(:first-child) {
            margin-top: 4px;
        }
        .var-option {
            padding: 5px 10px;
            cursor: pointer;
            font-size: 13px;
            font-family: monospace;
            color: var(--text-strong);
            border-radius: 6px;
            margin: 1px 0;
        }
        .var-option:hover {
            background: rgba(74,111,165,0.08);
            color: var(--brand-primary);
        }
        .channel-card {
            border: 1.5px solid var(--border-default);
            border-radius: 8px;
            margin-bottom: 12px;
            transition: opacity 0.3s;
        }
        .channel-card:last-child {
            margin-bottom: 0;
        }
        .channel-card.disabled .channel-body {
            opacity: 0.4;
            pointer-events: none;
        }
        .channel-header {
            padding: 10px 14px;
            background: var(--surface-page);
            border-bottom: 1px solid var(--surface-hover);
            border-radius: 8px 8px 0 0;
        }
        .channel-card.disabled .channel-header {
            border-bottom-color: transparent;
            border-radius: 8px;
        }
        .channel-toggle {
            display: flex !important;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            font-weight: 600 !important;
            font-size: 13.5px;
            margin-bottom: 0 !important;
            text-transform: none;
            letter-spacing: 0;
            color: var(--text-strong);
        }
        .channel-toggle input[type="checkbox"] {
            position: absolute;
            opacity: 0;
            width: 0;
            height: 0;
        }
        .channel-check {
            width: 16px;
            height: 16px;
            border: 1.5px solid var(--border-strong);
            border-radius: 3px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
            flex-shrink: 0;
            background: white;
        }
        .channel-toggle input:checked ~ .channel-check {
            background: var(--brand-primary);
            border-color: var(--brand-primary);
        }
        .channel-toggle input:checked ~ .channel-check::after {
            content: "";
            width: 4px;
            height: 8px;
            border: solid white;
            border-width: 0 1.5px 1.5px 0;
            transform: rotate(45deg);
            margin-top: -2px;
        }
        .channel-body {
            padding: 14px;
        }
        .slash-menu {
            display: none;
            position: fixed;
            background: white;
            border: 1.5px solid var(--border-default);
            border-radius: 10px;
            box-shadow: 0 4px 16px rgba(26,35,50,0.15);
            max-height: 260px;
            overflow-y: auto;
            z-index: 9999;
            min-width: 200px;
            padding: 4px;
        }
        .slash-menu .var-option:hover {
            background: transparent;
            color: var(--text-strong);
        }
        .slash-menu .var-option.highlighted {
            background: rgba(74,111,165,0.08);
            color: var(--brand-primary);
        }
        .slash-menu-empty {
            padding: 8px 12px;
            color: var(--text-soft);
            font-size: 13px;
        }
        button {
            background: var(--brand-primary);
            color: white;
            border: none;
            padding: 8px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13.5px;
            font-weight: 600;
            font-family: var(--font-stack);
            transition: all 0.15s ease;
        }
        button:hover {
            background: var(--brand-primary-hover);
        }
        .save-btn {
            margin-left: auto;
            margin-right: 16px;
            white-space: nowrap;
        }
        .toggle {
            position: relative;
            display: inline-block;
            width: 44px;
            height: 22px;
        }
        .toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: var(--border-strong);
            border-radius: 22px;
            transition: .3s;
        }
        .slider:before {
            position: absolute;
            content: "";
            height: 16px;
            width: 16px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            border-radius: 50%;
            transition: .3s;
        }
        input:checked + .slider {
            background-color: var(--brand-primary);
        }
        input:checked + .slider:before {
            transform: translateX(22px);
        }
        .table-wrapper {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            padding-bottom: 8px;
        }
        .table-wrapper::-webkit-scrollbar {
            height: 6px;
        }
        .table-wrapper::-webkit-scrollbar-track {
            background: transparent;
        }
        .table-wrapper::-webkit-scrollbar-thumb {
            background: var(--border-strong);
            border-radius: 3px;
        }
        .table-wrapper::-webkit-scrollbar-thumb:hover {
            background: var(--text-soft);
        }
        .patient-link {
            color: var(--brand-primary);
            text-decoration: none;
            font-weight: 600;
        }
        .patient-link:hover {
            text-decoration: underline;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 16px;
            font-size: 12px;
            font-weight: 600;
            white-space: nowrap;
        }
        .status-delivered {
            background: var(--success-bg);
            color: var(--success-fg);
        }
        .status-failed {
            background: var(--danger-bg);
            color: var(--danger-fg);
        }
        .error-text {
            color: var(--danger-fg);
            font-size: 12px;
        }
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: var(--text-soft);
        }
        .global-settings {
            background: var(--surface-page);
            padding: 16px;
            border-radius: 10px;
            margin-bottom: 24px;
            border: 1.5px solid var(--border-default);
        }
        .interval-list {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 8px;
        }
        .interval-tag {
            background: rgba(74,111,165,0.08);
            border: 1px solid rgba(74,111,165,0.2);
            padding: 5px 12px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: var(--text-strong);
        }
        .interval-remove {
            cursor: pointer;
            color: var(--brand-primary);
            font-weight: bold;
        }
        .add-interval {
            display: flex;
            gap: 8px;
            margin-top: 8px;
        }
        .add-interval input[type="text"] {
            flex: 1;
            padding: 7px 10px;
            border: 1.5px solid var(--border-default);
            border-radius: 7px;
            font-family: var(--font-stack);
            font-size: 13.5px;
            color: var(--text-strong);
            background: var(--surface-page);
            box-sizing: border-box;
            transition: border-color 0.15s;
            outline: none;
        }
        .add-interval input[type="text"]:focus {
            border-color: var(--brand-primary);
        }
        .add-interval input[type="text"].valid {
            border-color: var(--success-fg);
        }
        .add-interval input[type="text"].invalid {
            border-color: var(--danger-fg);
        }
        .interval-hint {
            margin-top: 6px;
            font-size: 12px;
            color: var(--text-soft);
        }
        .interval-hint code {
            background: var(--surface-hover);
            border: 1px solid var(--border-default);
            border-radius: 4px;
            padding: 1px 5px;
            font-family: monospace;
            font-size: 12px;
            color: var(--text-strong);
        }
        .send-time-row {
            display: flex;
            gap: 8px;
            margin-top: 8px;
            align-items: center;
        }
        .send-time-row input[type="time"] {
            padding: 7px 10px;
            border: 1.5px solid var(--border-default);
            border-radius: 7px;
            font-family: var(--font-stack);
            font-size: 13.5px;
            color: var(--text-strong);
            background: var(--surface-page);
            outline: none;
        }
        .send-time-row input[type="time"]:focus {
            border-color: var(--brand-primary);
        }
        .send-time-row select {
            padding: 7px 10px;
            border: 1.5px solid var(--border-default);
            border-radius: 7px;
            font-family: var(--font-stack);
            font-size: 13.5px;
            color: var(--text-strong);
            background: var(--surface-page);
            outline: none;
        }
        .send-time-row select:focus {
            border-color: var(--brand-primary);
        }
        .modal-backdrop {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(26,35,50,0.5);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .modal-backdrop.open {
            display: flex;
        }
        .modal-card {
            background: white;
            border-radius: 14px;
            box-shadow: 0 8px 32px rgba(26,35,50,0.2);
            max-width: 700px;
            width: 90%;
            max-height: 80vh;
            display: flex;
            flex-direction: column;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            border-bottom: 1.5px solid var(--border-default);
        }
        .modal-header h3 {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
            color: var(--text-strong);
        }
        .modal-close {
            background: none;
            border: none;
            font-size: 20px;
            cursor: pointer;
            color: var(--text-soft);
            padding: 4px 8px;
            line-height: 1;
        }
        .modal-close:hover {
            color: var(--text-strong);
            background: var(--surface-hover);
            border-radius: 6px;
        }
        .modal-body {
            padding: 24px;
            overflow-y: auto;
            flex: 1;
        }
        .patient-info-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px 24px;
            margin-bottom: 20px;
        }
        .patient-info-grid .info-item {
            font-size: 13.5px;
        }
        .patient-info-grid .info-label {
            color: var(--text-soft);
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 2px;
        }
        .modal-actions {
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }
        .modal-actions a {
            display: inline-block;
            padding: 8px 18px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 13.5px;
            font-weight: 600;
        }
        .btn-primary {
            background: var(--brand-primary);
            color: white;
        }
        .btn-primary:hover {
            background: var(--brand-primary-hover);
        }
        .btn-secondary {
            background: var(--surface-hover);
            color: var(--text-muted);
        }
        .btn-secondary:hover {
            background: var(--border-default);
        }
        .consent-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 6px;
        }
        .consent-ok { background: var(--success-bg); color: var(--success-fg); }
        .consent-warn { background: var(--warning-bg); color: var(--warning-fg); }
        .consent-danger { background: var(--danger-bg); color: var(--danger-fg); }
        .patient-status-warn {
            background: var(--danger-bg);
            border: 1.5px solid var(--danger-bg);
            border-radius: 8px;
            padding: 8px 12px;
            margin-bottom: 16px;
            font-size: 13px;
            color: var(--danger-fg);
        }
        .modal-subtitle {
            color: var(--text-soft);
            font-size: 13px;
            margin: 0;
        }
        .next-appt {
            background: rgba(74,111,165,0.08);
            border-radius: 8px;
            padding: 8px 12px;
            margin-bottom: 16px;
            font-size: 13px;
            color: var(--brand-primary);
        }
        .toast {
            position: fixed;
            top: -60px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 24px;
            border-radius: 10px;
            font-size: 13.5px;
            font-weight: 600;
            color: white;
            z-index: 2000;
            transition: top 0.3s ease;
            box-shadow: 0 4px 12px rgba(26,35,50,0.15);
        }
        .toast.visible { top: 20px; }
        .toast.success { background: var(--success-fg); }
        .toast.error { background: var(--danger-fg); }
        .nt-card-body {
            padding: 10px 20px 20px;
        }
        .campaign-card.collapsed .nt-card-body {
            display: none;
        }
        .nt-expand-arrow {
            font-size: 11px;
            color: var(--text-soft);
            transition: transform 0.2s;
            margin-right: 10px;
        }
        .campaign-card:not(.collapsed) .nt-expand-arrow {
            transform: rotate(90deg);
        }
        /* cursor on campaign-header is in base rule */
        .nt-campaign-section {
            border: 1.5px solid var(--border-default);
            border-radius: 8px;
            margin-bottom: 12px;
            background: var(--surface-page);
        }
        .nt-campaign-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            user-select: none;
        }
        .nt-campaign-label {
            font-weight: 600;
            font-size: 13.5px;
            color: var(--text-strong);
        }
        .nt-campaign-body {
            padding: 14px;
            border-top: 1.5px solid var(--border-default);
        }
        .nt-section-controls {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .inherit-label {
            font-size: 12px;
            color: var(--text-soft);
            font-style: italic;
        }
        .override-btn {
            background: var(--surface-page);
            border: 1.5px solid var(--border-default);
            border-radius: 6px;
            padding: 3px 10px;
            cursor: pointer;
            font-size: 12px;
            font-family: var(--font-stack);
            color: var(--text-muted);
            line-height: 1.2;
            transition: all 0.15s;
        }
        .override-btn:hover {
            background: rgba(74,111,165,0.06);
            color: var(--brand-primary);
            border-color: var(--brand-primary);
        }
        .override-btn.active {
            background: rgba(74,111,165,0.08);
            color: var(--brand-primary);
            border-color: rgba(74,111,165,0.3);
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div id="slash-menu" class="slash-menu"></div>
    <div class="container">
        <div class="tabs">
            <div class="tab active" onclick="switchTab('campaigns')">Campaigns</div>
            <div class="tab" onclick="switchTab('business_lines_tab')">Business Line Overrides</div>
            <div class="tab" onclick="switchTab('overrides')">Visit Type Overrides</div>
            <div class="tab" onclick="switchTab('settings_tab')">Settings</div>
            <button class="save-btn" onclick="saveConfig()">Save</button>
        </div>

        <div id="campaigns" class="tab-content active">
            <div class="global-settings" style="margin-bottom:16px;">
                <h3 style="margin-top:0;font-size:15px;font-weight:600;color:var(--text-strong);">Integration Status</h3>
                <div id="integration_loading" style="color:var(--text-soft);">Checking configuration...</div>
                <div id="integration_details" style="display:none;">
                    <div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13.5px;">
                        <div><span id="twilio_status_icon"></span> Twilio SMS: <strong id="twilio_status_text">checking</strong></div>
                        <div><span id="sendgrid_status_icon"></span> SendGrid Email: <strong id="sendgrid_status_text">checking</strong></div>
                    </div>
                    <div id="integration_fallback_note" style="margin-top:8px;padding:8px;background:var(--warning-bg);border-radius:8px;font-size:13px;display:none;">
                        Direct delivery not fully configured. Add Twilio/SendGrid secrets to enable SMS/email.
                    </div>
                    <div id="broadcast_warning" style="margin-top:8px;padding:8px;background:var(--warning-bg);color:var(--warning-fg);border-radius:8px;font-size:13px;display:none;">
                        <strong>Live sending.</strong> A campaign is enabled and <strong>testing mode</strong> is off, so saved changes reach every patient with a consented phone or email. Before the first live run, confirm Canvas's native <strong>appointmentReminders</strong> organization setting has been cleared — if it is still set, patients receive two reminders.
                    </div>
                </div>
            </div>


            <div class="campaign-card collapsed" id="confirmation_card">
                <div class="campaign-header" onclick="toggleSettingsCard('confirmation')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="confirmation_arrow">&#9654;</span>
                        <div class="campaign-title">Booking Acknowledgement</div>
                    </div>
                    <label class="toggle" onclick="event.stopPropagation()">
                        <input type="checkbox" id="confirmation_enabled" onchange="syncGlobalCampaignToOverrides('confirmation', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                <div id="confirmation_body" class="nt-card-body" style="display:none">
                    <div class="channel-card" id="confirmation_sms_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="confirmation_channel_sms" checked onchange="toggleChannelCard('confirmation_sms_card', this.checked)">
                                <span class="channel-check"></span>
                                SMS
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="confirmation_sms_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                    <div class="channel-card" id="confirmation_email_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="confirmation_channel_email" checked onchange="toggleChannelCard('confirmation_email_card', this.checked)">
                                <span class="channel-check"></span>
                                Email
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="confirmation_email_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                </div>
            </div>

            <div class="campaign-card collapsed" id="reminder_card">
                <div class="campaign-header" onclick="toggleSettingsCard('reminder')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="reminder_arrow">&#9654;</span>
                        <div class="campaign-title">Appointment Reminders</div>
                    </div>
                    <label class="toggle" onclick="event.stopPropagation()">
                        <input type="checkbox" id="reminders_enabled" onchange="syncGlobalCampaignToOverrides('reminder', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                <div id="reminder_body" class="nt-card-body" style="display:none">
                    <div class="form-group">
                        <label>Default Intervals</label>
                        <div class="interval-list" id="global_interval_list"></div>
                        <div class="add-interval">
                            <input type="text" id="global_new_interval" placeholder="Enter interval" oninput="validateIntervalInput(this)" onkeydown="if(event.key==='Enter'){event.preventDefault();addGlobalInterval()}">
                            <button onclick="addGlobalInterval()">Add</button>
                        </div>
                        <div class="interval-hint">Use <code>w</code> weeks, <code>d</code> days, <code>h</code> hours, <code>m</code> minutes. Per-visit-type intervals override these.</div>
                    </div>
                    <div class="form-group" id="send_time_group">
                        <label>Send Time for Day-Out Reminders</label>
                        <div class="send-time-row">
                            <input type="time" id="reminder_send_time" value="09:00">
                            <select id="reminder_timezone">
                                <option value="America/New_York">Eastern (ET)</option>
                                <option value="America/Chicago">Central (CT)</option>
                                <option value="America/Denver">Mountain (MT)</option>
                                <option value="America/Los_Angeles">Pacific (PT)</option>
                                <option value="America/Anchorage">Alaska (AKT)</option>
                                <option value="Pacific/Honolulu">Hawaii (HT)</option>
                            </select>
                        </div>
                        <div class="interval-hint">Reminders 1 day or longer will be sent at this time. Shorter intervals are sent relative to the appointment.</div>
                    </div>
                    <div class="channel-card" id="reminder_sms_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="reminder_channel_sms" checked onchange="toggleChannelCard('reminder_sms_card', this.checked)">
                                <span class="channel-check"></span>
                                SMS
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="reminder_sms_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                    <div class="channel-card" id="reminder_email_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="reminder_channel_email" checked onchange="toggleChannelCard('reminder_email_card', this.checked)">
                                <span class="channel-check"></span>
                                Email
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="reminder_email_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                </div>
            </div>

            <div class="campaign-card collapsed" id="telehealth_card">
                <div class="campaign-header" onclick="toggleSettingsCard('telehealth')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="telehealth_arrow">&#9654;</span>
                        <div class="campaign-title">Join Telehealth</div>
                    </div>
                    <label class="toggle" onclick="event.stopPropagation()">
                        <input type="checkbox" id="telehealth_enabled" onchange="syncGlobalCampaignToOverrides('telehealth', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                <div id="telehealth_body" class="nt-card-body" style="display:none">
                    <div class="interval-hint" style="margin-bottom:12px">Sends a telehealth join link before appointments with telehealth visit types. Falls back to the provider's personal meeting room if no appointment-level link is set.</div>
                    <div class="form-group">
                        <label>Intervals</label>
                        <div class="interval-list" id="telehealth_interval_list"></div>
                        <div class="add-interval">
                            <input type="text" id="telehealth_new_interval" placeholder="e.g. 1h, 15m" oninput="validateIntervalInput(this)" onkeydown="if(event.key==='Enter'){event.preventDefault();addTelehealthInterval()}">
                            <button onclick="addTelehealthInterval()">Add</button>
                        </div>
                        <div class="interval-hint">When to send the telehealth join link before the appointment (minutes only).</div>
                    </div>
                    <div class="channel-card" id="telehealth_sms_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="telehealth_channel_sms" checked onchange="toggleChannelCard('telehealth_sms_card', this.checked)">
                                <span class="channel-check"></span>
                                SMS
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="telehealth_sms_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                    <div class="channel-card" id="telehealth_email_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="telehealth_channel_email" checked onchange="toggleChannelCard('telehealth_email_card', this.checked)">
                                <span class="channel-check"></span>
                                Email
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="telehealth_email_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                </div>
            </div>

            <div class="campaign-card collapsed" id="noshow_card">
                <div class="campaign-header" onclick="toggleSettingsCard('noshow')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="noshow_arrow">&#9654;</span>
                        <div class="campaign-title">No-Show Alert</div>
                    </div>
                    <label class="toggle" onclick="event.stopPropagation()">
                        <input type="checkbox" id="noshow_enabled" onchange="syncGlobalCampaignToOverrides('noshow', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                <div id="noshow_body" class="nt-card-body" style="display:none">
                    <div class="channel-card" id="noshow_sms_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="noshow_channel_sms" checked onchange="toggleChannelCard('noshow_sms_card', this.checked)">
                                <span class="channel-check"></span>
                                SMS
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="noshow_sms_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                    <div class="channel-card" id="noshow_email_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="noshow_channel_email" checked onchange="toggleChannelCard('noshow_email_card', this.checked)">
                                <span class="channel-check"></span>
                                Email
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="noshow_email_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                </div>
            </div>

            <div class="campaign-card collapsed" id="cancellation_card">
                <div class="campaign-header" onclick="toggleSettingsCard('cancellation')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="cancellation_arrow">&#9654;</span>
                        <div class="campaign-title">Cancellation Alert</div>
                    </div>
                    <label class="toggle" onclick="event.stopPropagation()">
                        <input type="checkbox" id="cancellation_enabled" onchange="syncGlobalCampaignToOverrides('cancellation', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                <div id="cancellation_body" class="nt-card-body" style="display:none">
                    <div class="channel-card" id="cancellation_sms_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="cancellation_channel_sms" checked onchange="toggleChannelCard('cancellation_sms_card', this.checked)">
                                <span class="channel-check"></span>
                                SMS
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="cancellation_sms_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                    <div class="channel-card" id="cancellation_email_card">
                        <div class="channel-header">
                            <label class="channel-toggle">
                                <input type="checkbox" id="cancellation_channel_email" checked onchange="toggleChannelCard('cancellation_email_card', this.checked)">
                                <span class="channel-check"></span>
                                Email
                            </label>
                        </div>
                        <div class="channel-body">
                            <div class="template-label-row">
                                <label>Template</label>
                                <button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>
                                <div class="var-dropdown"></div>
                            </div>
                            <textarea id="cancellation_email_template" placeholder="Type / to insert a field"></textarea>
                        </div>
                    </div>
                </div>
            </div>


        </div>

        <div id="overrides" class="tab-content">
            <h2 style="margin-top:0;">Visit Type Overrides</h2>
            <p style="color:var(--text-soft);font-size:13px;margin-top:0;">Each campaign fires for every visit type when enabled globally. Turn the per-visit-type toggle off to opt out for that visit type, or click <strong>Customize</strong> to override templates and channels. Reminders and Telehealth also accept per-visit-type intervals.</p>
            <div id="note_type_overrides_container"></div>
        </div>

        <div id="business_lines_tab" class="tab-content">
            <h2 style="margin-top:0;">Business Line Overrides</h2>
            <p style="color:var(--text-soft);font-size:13px;margin-top:0;">Customize messaging per business line (referral source). Set the <strong>attribution</strong> text used by the <code>{{business_line_attribution}}</code> placeholder (e.g. "Acme on behalf of Northwind Health") and, optionally, the outbound SMS <strong>from-number</strong> for that business line. Patients whose business line has no entry use the default attribution and the global Twilio number.</p>
            <div class="form-group" style="max-width:420px;">
                <label for="default_attribution_input" style="font-weight:600;">Default attribution</label>
                <input type="text" id="default_attribution_input" placeholder="Your Care Team" style="width:100%;">
                <p style="color:var(--text-soft);font-size:12px;margin:4px 0 0;">Used for patients with no business line or no override below.</p>
            </div>
            <div id="business_lines_loading" style="color:var(--text-soft);padding:12px 0;">Loading business lines...</div>
            <div id="business_line_overrides_container"></div>
        </div>

        <div id="settings_tab" class="tab-content">
            <h2 style="margin-top:0;">Settings</h2>
            <p style="color:var(--text-soft);font-size:13px;margin-top:0;">Set once and rarely revisited. Both cards start collapsed; click a header to open it.</p>

            <div class="campaign-card collapsed" id="testing_mode_card">
                <div class="campaign-header" onclick="toggleSettingsCard('testing_mode')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="testing_mode_arrow">&#9654;</span>
                        <div class="campaign-title">Testing mode</div>
                        <span id="testing_mode_state" style="display:none;font-size:11px;font-weight:600;padding:2px 6px;border-radius:4px;background:var(--warning-bg);color:var(--warning-fg);"></span>
                    </div>
                    <label class="toggle" onclick="event.stopPropagation()">
                        <input type="checkbox" id="testing_mode" onchange="updateTestingModeUI()">
                        <span class="slider"></span>
                    </label>
                </div>
                <div id="testing_mode_body" class="nt-card-body" style="display:none">
                    <p style="color:var(--text-soft);font-size:13px;margin-top:0;">
                        A safe-launch gate. While it is on, a message sends only when <strong>both</strong>
                        the patient and the destination address appear in the lists below. Everything
                        else is skipped, whatever the campaigns say.
                    </p>
                    <div id="testing_mode_closed_warning" style="margin-bottom:12px;padding:8px;background:var(--warning-bg);color:var(--warning-fg);border-radius:8px;font-size:13px;display:none;">
                        <strong>Nothing is sending.</strong> Testing mode is on and at least one list is
                        empty, so every message is being skipped. Add a patient and a recipient to test
                        with, or turn testing mode off to go live.
                    </div>
                    <div class="form-group">
                        <label for="testing_mode_patients">Allowed patients</label>
                        <textarea id="testing_mode_patients" rows="3" placeholder="One patient id per line" oninput="updateTestingModeUI()"></textarea>
                        <p style="color:var(--text-soft);font-size:12px;margin:4px 0 0;">Copy the id from the chart URL. Matched against the patient's id, key, or dbid, so whichever value you paste works.</p>
                    </div>
                    <div class="form-group">
                        <label for="testing_mode_recipients">Allowed recipients</label>
                        <textarea id="testing_mode_recipients" rows="3" placeholder="One phone or email per line" oninput="updateTestingModeUI()"></textarea>
                        <p style="color:var(--text-soft);font-size:12px;margin:4px 0 0;">Your own mobile and inbox. Phones compared in normalized E.164, emails case-insensitively; one list may mix both.</p>
                    </div>
                </div>
            </div>
            <!-- end testing mode -->

            <div class="campaign-card collapsed" id="task_routing_card">
                <div class="campaign-header" onclick="toggleSettingsCard('task_routing')">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span class="nt-expand-arrow" id="task_routing_arrow">&#9654;</span>
                        <div class="campaign-title">Task assignment</div>
                    </div>
                </div>
                <div id="task_routing_body" class="nt-card-body" style="display:none">
                    <p style="color:var(--text-soft);font-size:13px;margin-top:0;">
                        Which team receives the follow-up task raised when a patient declines an
                        appointment by SMS. Leave it unassigned and the task is still created, but
                        it lands in no team's queue and someone has to go looking for it.
                    </p>
                    <div class="form-group" style="max-width:420px;">
                        <label for="decline_task_team_id">Team for decline follow-ups</label>
                        <select id="decline_task_team_id"><option value="">Unassigned</option></select>
                        <p id="task_routing_note" style="color:var(--text-soft);font-size:12px;margin:4px 0 0;">Loading teams...</p>
                    </div>
                </div>
            </div>
            <!-- end task routing -->
        </div>

    </div>

    <div id="patient_modal" class="modal-backdrop" onclick="closePatientModal(event)">
        <div class="modal-card" onclick="event.stopPropagation()">
            <div class="modal-header">
                <h3 id="modal_patient_name">Loading...</h3>
                <button class="modal-close" onclick="closePatientModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div id="modal_loading" style="text-align:center;padding:20px;color:var(--text-soft);">Loading patient details...</div>
                <div id="modal_content" style="display:none;">
                    <div class="patient-info-grid" id="modal_patient_info"></div>
                    <div class="modal-actions" id="modal_actions"></div>
                </div>
            </div>
        </div>
    </div>

    <div id="toast" class="toast"></div>

    <script>
        let noteTypeIntervals = {};
        let noteTypeTelehealthIntervals = {};
        let noteTypes = [];
        let savedNoteTypeReminders = {};
        let savedBusinessLineOverrides = {};
        let businessLines = [];
        let globalIntervals = [];

        function showToast(message, type) {
            var toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type;
            toast.offsetHeight;
            toast.classList.add('visible');
            setTimeout(function() { toast.classList.remove('visible'); }, 3000);
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        function toggleSettingsCard(prefix) {
            var card = document.getElementById(prefix + '_card');
            var body = document.getElementById(prefix + '_body');
            if (!card || !body) return;
            var isCollapsed = card.classList.contains('collapsed');
            if (isCollapsed) {
                card.classList.remove('collapsed');
                body.style.display = '';
            } else {
                card.classList.add('collapsed');
                body.style.display = 'none';
            }
        }

        function syncGlobalCampaignToOverrides(campaignKey, enabled) {
            updateBroadcastWarning();
            // Per-type toggles mirror the effective state: global ON + not opted out.
            // When global flips, reset each per-type toggle accordingly — except for
            // note types the user has explicitly opted out (saved value === false).
            if (!noteTypes || !noteTypes.length) return;
            var enabledKey = campaignKey === 'reminder' ? 'reminders_enabled' : campaignKey + '_enabled';
            noteTypes.forEach(function(nt) {
                var toggle = document.getElementById('nt_' + campaignKey + '_enabled_' + nt.id);
                if (!toggle) return;
                var saved = (savedNoteTypeReminders[nt.id] || {})[enabledKey];
                var target = enabled && saved !== false;
                if (toggle.checked !== target) {
                    toggle.checked = target;
                    toggleNtCampaignEnabled(nt.id, campaignKey);
                }
            });
        }

        function toggleChannelCard(cardId, enabled) {
            var card = document.getElementById(cardId);
            if (!card) return;
            if (enabled) {
                card.classList.remove('disabled');
            } else {
                card.classList.add('disabled');
            }
        }

        var TEMPLATE_VARIABLES = [
            {group: 'Patient', vars: ['patient_first_name', 'patient_last_name', 'patient_preferred_name', 'patient_full_name']},
            {group: 'Appointment', vars: ['appointment_date', 'appointment_time', 'appointment_type', 'provider_name', 'credentials', 'location_name', 'telehealth_link']},
            {group: 'Organization', vars: ['organization_full_name', 'organization_short_name', 'organization_address', 'organization_phone']},
            {group: 'Location', vars: ['location_full_name', 'location_short_name', 'location_address', 'location_phone']},
            {group: 'Business Line', vars: ['business_line_attribution']}
        ];

        // Fields that reveal clinical/identifying detail — minimize on unsecure SMS/email (HIPAA).
        var SENSITIVE_VARS = {
            'appointment_type': 1, 'provider_name': 1, 'credentials': 1,
            'patient_last_name': 1, 'patient_full_name': 1,
            'organization_full_name': 1, 'organization_address': 1,
            'location_full_name': 1, 'location_address': 1
        };

        function buildVarDropdownHtml() {
            var html = '<div style="padding:5px 8px;font-size:11px;color:#888;">&#9888; = minimize on SMS/email (unsecure channel)</div>';
            TEMPLATE_VARIABLES.forEach(function(g, i) {
                html += '<div class="var-group-label">' + escapeHtml(g.group) + '</div>';
                g.vars.forEach(function(v) {
                    var sensitive = SENSITIVE_VARS[v];
                    var title = sensitive ? ' title="Minimize on unsecure SMS/email (HIPAA) — avoid unless necessary"' : '';
                    var mark = sensitive ? ' &#9888;' : '';
                    html += '<div class="var-option"' + title + ' onclick="insertVariable(this, \\'' + v + '\\')">' + escapeHtml('{{' + v + '}}') + mark + '</div>';
                });
            });
            return html;
        }

        function toggleVarDropdown(btn) {
            var dropdown = btn.nextElementSibling;
            var isOpen = dropdown.classList.contains('open');

            document.querySelectorAll('.var-dropdown.open').forEach(function(d) {
                d.classList.remove('open');
            });

            if (!isOpen) {
                if (!dropdown.innerHTML) {
                    dropdown.innerHTML = buildVarDropdownHtml();
                }
                dropdown.classList.add('open');
            }
        }

        function insertVariable(optionEl, varName) {
            var group = optionEl.closest('.form-group') || optionEl.closest('.channel-body') || optionEl.closest('.nt-campaign-body');
            var textarea = group ? group.querySelector('textarea') : null;
            if (!textarea) {
                var labelRow = optionEl.closest('.var-dropdown').parentElement;
                textarea = labelRow.parentElement.querySelector('textarea');
            }
            if (!textarea) return;
            var tag = '{{' + varName + '}}';
            var start = textarea.selectionStart;
            var end = textarea.selectionEnd;
            var val = textarea.value;
            textarea.value = val.substring(0, start) + tag + val.substring(end);
            textarea.focus();
            var newPos = start + tag.length;
            textarea.setSelectionRange(newPos, newPos);

            document.querySelectorAll('.var-dropdown.open').forEach(function(d) {
                d.classList.remove('open');
            });
        }

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.template-label-row')) {
                document.querySelectorAll('.var-dropdown.open').forEach(function(d) {
                    d.classList.remove('open');
                });
            }
            if (!e.target.closest('#slash-menu') && !(slashMenu.active && e.target === slashMenu.textarea)) {
                hideSlashMenu();
            }
        });

        // Slash command menu
        var slashMenu = { active: false, textarea: null, startPos: -1 };
        var slashMenuEl = document.getElementById('slash-menu');
        var slashMirrorDiv = null;

        function getCaretCoordinates(textarea, position) {
            if (!slashMirrorDiv) {
                slashMirrorDiv = document.createElement('div');
                slashMirrorDiv.style.position = 'absolute';
                slashMirrorDiv.style.left = '-9999px';
                slashMirrorDiv.style.top = '-9999px';
                slashMirrorDiv.style.visibility = 'hidden';
                document.body.appendChild(slashMirrorDiv);
            }
            var computed = window.getComputedStyle(textarea);
            var props = [
                'font', 'padding', 'border', 'lineHeight', 'letterSpacing',
                'whiteSpace', 'wordWrap', 'width', 'overflowWrap',
                'paddingLeft', 'paddingRight', 'paddingTop', 'paddingBottom',
                'borderLeftWidth', 'borderRightWidth', 'borderTopWidth', 'borderBottomWidth',
                'boxSizing', 'fontFamily', 'fontSize', 'fontWeight'
            ];
            props.forEach(function(p) { slashMirrorDiv.style[p] = computed[p]; });
            slashMirrorDiv.style.overflow = 'hidden';
            slashMirrorDiv.style.whiteSpace = 'pre-wrap';
            slashMirrorDiv.style.wordWrap = 'break-word';

            var text = textarea.value.substring(0, position);
            slashMirrorDiv.textContent = text;
            var span = document.createElement('span');
            span.textContent = '\\u200b';
            slashMirrorDiv.appendChild(span);

            return {
                top: span.offsetTop - textarea.scrollTop,
                left: span.offsetLeft
            };
        }

        function showSlashMenu(textarea, position) {
            slashMenu.active = true;
            slashMenu.textarea = textarea;
            slashMenu.startPos = position;

            var coords = getCaretCoordinates(textarea, position);
            var rect = textarea.getBoundingClientRect();
            var computed = window.getComputedStyle(textarea);
            var lineHeight = parseInt(computed.lineHeight) || parseInt(computed.fontSize) * 1.2;

            var top = rect.top + coords.top + lineHeight + window.scrollY;
            var left = rect.left + coords.left + window.scrollX;

            slashMenuEl.innerHTML = buildSlashMenuHtml('');
            slashMenuEl.style.display = 'block';

            var menuRect = slashMenuEl.getBoundingClientRect();
            if (left + menuRect.width > window.innerWidth + window.scrollX) {
                left = window.innerWidth + window.scrollX - menuRect.width - 8;
            }

            slashMenuEl.style.position = 'fixed';
            slashMenuEl.style.top = (top - window.scrollY) + 'px';
            slashMenuEl.style.left = (left - window.scrollX) + 'px';

            highlightSlashOption(0);
        }

        function hideSlashMenu() {
            slashMenu.active = false;
            slashMenu.textarea = null;
            slashMenu.startPos = -1;
            slashMenuEl.style.display = 'none';
        }

        function fuzzyMatch(query, target) {
            if (!query) return true;
            var q = query.toLowerCase();
            var t = target.toLowerCase();
            var qi = 0;
            for (var ti = 0; ti < t.length && qi < q.length; ti++) {
                if (t[ti] === q[qi]) qi++;
            }
            return qi === q.length;
        }

        function buildSlashMenuHtml(query) {
            var html = '';
            var hasAny = false;
            TEMPLATE_VARIABLES.forEach(function(g) {
                var matched = g.vars.filter(function(v) { return fuzzyMatch(query, v); });
                if (matched.length === 0) return;
                hasAny = true;
                html += '<div class="var-group-label">' + escapeHtml(g.group) + '</div>';
                matched.forEach(function(v) {
                    html += '<div class="var-option" data-var="' + v + '" onmousedown="event.preventDefault();slashSelect(this, \\'' + v + '\\')" onmouseenter="highlightSlashByEl(this)">' + escapeHtml('{{' + v + '}}') + '</div>';
                });
            });
            if (!hasAny) {
                html = '<div class="slash-menu-empty">No matching fields</div>';
            }
            return html;
        }

        function highlightSlashOption(index) {
            var options = slashMenuEl.querySelectorAll('.var-option');
            options.forEach(function(o) { o.classList.remove('highlighted'); });
            if (options[index]) {
                options[index].classList.add('highlighted');
                options[index].scrollIntoView({ block: 'nearest' });
            }
        }

        function highlightSlashByEl(el) {
            var options = Array.prototype.slice.call(slashMenuEl.querySelectorAll('.var-option'));
            var idx = options.indexOf(el);
            if (idx !== -1) highlightSlashOption(idx);
        }

        function getHighlightedIndex() {
            var options = Array.prototype.slice.call(slashMenuEl.querySelectorAll('.var-option'));
            for (var i = 0; i < options.length; i++) {
                if (options[i].classList.contains('highlighted')) return i;
            }
            return -1;
        }

        function filterSlashMenu() {
            var ta = slashMenu.textarea;
            if (ta.selectionStart <= slashMenu.startPos) {
                hideSlashMenu();
                return;
            }
            var query = ta.value.substring(slashMenu.startPos + 1, ta.selectionStart);
            if (query.indexOf(' ') !== -1) {
                hideSlashMenu();
                return;
            }
            slashMenuEl.innerHTML = buildSlashMenuHtml(query);
            highlightSlashOption(0);
        }

        function slashSelect(optionEl, varName) {
            var ta = slashMenu.textarea;
            var tag = '{{' + varName + '}}';
            var val = ta.value;
            var cursorPos = ta.selectionStart;
            ta.value = val.substring(0, slashMenu.startPos) + tag + val.substring(cursorPos);
            var newPos = slashMenu.startPos + tag.length;
            hideSlashMenu();
            ta.focus();
            ta.setSelectionRange(newPos, newPos);
        }

        document.addEventListener('input', function(e) {
            if (e.target.tagName !== 'TEXTAREA') return;
            if (slashMenu.active) {
                filterSlashMenu();
            } else {
                var ta = e.target;
                var pos = ta.selectionStart;
                if (pos > 0 && ta.value[pos - 1] === '/') {
                    showSlashMenu(ta, pos - 1);
                }
            }
        });

        document.addEventListener('keydown', function(e) {
            if (!slashMenu.active) return;
            if (e.target.tagName !== 'TEXTAREA') return;

            var options = slashMenuEl.querySelectorAll('.var-option');
            if (options.length === 0 && e.key !== 'Escape') return;

            var idx = getHighlightedIndex();

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                highlightSlashOption(Math.min(idx + 1, options.length - 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                highlightSlashOption(Math.max(idx - 1, 0));
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                var highlighted = slashMenuEl.querySelector('.var-option.highlighted');
                if (highlighted) slashSelect(highlighted, highlighted.dataset.var);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                hideSlashMenu();
            }
        });

        document.addEventListener('scroll', function(e) {
            if (slashMenu.active && e.target.tagName === 'TEXTAREA') {
                hideSlashMenu();
            }
        }, true);

        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(tabName).classList.add('active');

        }

        async function loadConfig() {
            const response = await fetch('/plugin-io/api/appointment_reminders/admin/config');
            const config = await response.json();


            document.getElementById('confirmation_enabled').checked = config.confirmation_enabled;
            document.getElementById('confirmation_sms_template').value = config.confirmation_sms_template || '';
            document.getElementById('confirmation_email_template').value = config.confirmation_email_template || '';
            setChannelCheckboxes('confirmation', config.confirmation_channels);

            document.getElementById('reminders_enabled').checked = config.reminders_enabled;
            document.getElementById('reminder_sms_template').value = config.reminder_sms_template || '';
            document.getElementById('reminder_email_template').value = config.reminder_email_template || '';
            setChannelCheckboxes('reminder', config.reminder_channels);
            globalIntervals = (config.reminder_intervals || []).slice();
            renderGlobalIntervals();
            document.getElementById('reminder_send_time').value = config.reminder_send_time || '09:00';
            document.getElementById('reminder_timezone').value = config.reminder_timezone || 'America/New_York';

            document.getElementById('telehealth_enabled').checked = config.telehealth_enabled;
            document.getElementById('telehealth_sms_template').value = config.telehealth_sms_template || '';
            document.getElementById('telehealth_email_template').value = config.telehealth_email_template || '';
            setChannelCheckboxes('telehealth', config.telehealth_channels);
            telehealthIntervals = (config.telehealth_intervals || []).slice();
            renderTelehealthIntervals();

            document.getElementById('noshow_enabled').checked = config.noshow_enabled;
            document.getElementById('noshow_sms_template').value = config.noshow_sms_template || '';
            document.getElementById('noshow_email_template').value = config.noshow_email_template || '';
            setChannelCheckboxes('noshow', config.noshow_channels);

            document.getElementById('cancellation_enabled').checked = config.cancellation_enabled;
            document.getElementById('cancellation_sms_template').value = config.cancellation_sms_template || '';
            document.getElementById('cancellation_email_template').value = config.cancellation_email_template || '';
            setChannelCheckboxes('cancellation', config.cancellation_channels);

            loadIntegrationStatus();

            savedNoteTypeReminders = config.note_type_reminders || {};
            loadNoteTypes();

            document.getElementById('default_attribution_input').value = config.default_attribution || '';
            savedBusinessLineOverrides = config.business_line_overrides || {};
            loadBusinessLines();

            // Absent means an older config row that predates the setting. Treat
            // that as ON, matching the server-side default — erring toward
            // "nothing sends" rather than showing a gate as open when the
            // server considers it closed.
            document.getElementById('testing_mode').checked =
                config.testing_mode === undefined ? true : !!config.testing_mode;
            document.getElementById('testing_mode_patients').value =
                (config.testing_mode_patients || []).join('\\n');
            document.getElementById('testing_mode_recipients').value =
                (config.testing_mode_recipients || []).join('\\n');
            savedDeclineTaskTeamId = config.decline_task_team_id || '';
            loadTeams();
            updateTestingModeUI();
        }

        var savedDeclineTaskTeamId = '';

        async function loadTeams() {
            var select = document.getElementById('decline_task_team_id');
            var note = document.getElementById('task_routing_note');
            try {
                var resp = await fetch('/plugin-io/api/appointment_reminders/admin/teams');
                var teams = await resp.json();
                select.innerHTML = '<option value="">Unassigned</option>';
                teams.forEach(function(team) {
                    var opt = document.createElement('option');
                    opt.value = team.id;
                    opt.textContent = team.name;
                    select.appendChild(opt);
                });
                // A configured team that no longer exists must not look like
                // "Unassigned" — the saved value would then be silently dropped
                // the next time someone hits Save.
                if (savedDeclineTaskTeamId &&
                    !teams.some(function(x) { return x.id === savedDeclineTaskTeamId; })) {
                    var stale = document.createElement('option');
                    stale.value = savedDeclineTaskTeamId;
                    stale.textContent = 'Team no longer exists (' + savedDeclineTaskTeamId + ')';
                    select.appendChild(stale);
                    note.textContent = 'The configured team was not found. Pick another, or tasks will be created unassigned.';
                } else {
                    note.textContent = teams.length
                        ? 'Teams are configured in Canvas settings.'
                        : 'No teams found on this instance. Tasks will be created unassigned.';
                }
                select.value = savedDeclineTaskTeamId;
            } catch (e) {
                note.textContent = 'Could not load teams.';
            }
        }

        function splitLines(id) {
            return document.getElementById(id).value
                .split(/[\\n,]/)
                .map(function(s) { return s.trim(); })
                .filter(function(s) { return s.length > 0; });
        }

        function updateTestingModeUI() {
            var on = document.getElementById('testing_mode').checked;
            // The card is collapsed by default, so surface the state in the header
            // too — otherwise a closed gate is invisible from the tab.
            var badge = document.getElementById('testing_mode_state');
            if (badge) {
                badge.style.display = on ? '' : 'none';
                badge.textContent = 'ON';
            }
            // Mirror the server's fail-closed rule: on, with either list empty,
            // means every send is skipped. Silent in that state is the failure
            // mode the banner exists to prevent.
            var starved = on && (splitLines('testing_mode_patients').length === 0 ||
                                 splitLines('testing_mode_recipients').length === 0);
            document.getElementById('testing_mode_closed_warning').style.display =
                starved ? '' : 'none';
            testingModeActive = on;
            updateBroadcastWarning();
        }

        function parseDuration(str) {
            str = str.trim().toLowerCase();
            if (!str) return null;
            if (/^\\d+$/.test(str)) return parseInt(str);
            var units = {w: 10080, d: 1440, h: 60, m: 1};
            var total = 0;
            var matched = false;
            var pattern = /(\\d+)\\s*(w|d|h|m)/g;
            var match;
            var lastIndex = 0;
            while ((match = pattern.exec(str)) !== null) {
                var between = str.substring(lastIndex, match.index).trim();
                if (between) return null;
                total += parseInt(match[1]) * units[match[2]];
                matched = true;
                lastIndex = pattern.lastIndex;
            }
            if (str.substring(lastIndex).trim()) return null;
            return matched && total > 0 ? total : null;
        }

        function validateIntervalInput(input) {
            var val = input.value.trim();
            if (!val) {
                input.classList.remove('valid', 'invalid');
                return;
            }
            var result = parseDuration(val);
            if (result !== null) {
                input.classList.add('valid');
                input.classList.remove('invalid');
            } else {
                input.classList.add('invalid');
                input.classList.remove('valid');
            }
        }

        function formatInterval(minutes) {
            var parts = [];
            if (minutes >= 10080) {
                var weeks = Math.floor(minutes / 10080);
                parts.push(weeks + 'w');
                minutes %= 10080;
            }
            if (minutes >= 1440) {
                var days = Math.floor(minutes / 1440);
                parts.push(days + 'd');
                minutes %= 1440;
            }
            if (minutes >= 60) {
                var hours = Math.floor(minutes / 60);
                parts.push(hours + 'h');
                minutes %= 60;
            }
            if (minutes > 0 || parts.length === 0) {
                parts.push(minutes + 'm');
            }
            return parts.join(' ');
        }

        function renderNtIntervals(ntId) {
            const container = document.getElementById('nt_interval_list_' + ntId);
            if (!container) return;
            const intervals = noteTypeIntervals[ntId] || [];
            container.innerHTML = '';
            intervals.forEach(function(interval, index) {
                const tag = document.createElement('div');
                tag.className = 'interval-tag';
                const label = formatInterval(interval);
                tag.innerHTML = '<span>' + escapeHtml(label) + '</span><span class="interval-remove" onclick="removeNtInterval(\\'' + ntId + '\\',' + index + ')">x</span>';
                container.appendChild(tag);
            });
        }

        function addNtInterval(ntId) {
            const input = document.getElementById('nt_new_interval_' + ntId);
            const minutes = parseDuration(input.value);
            if (minutes !== null) {
                if (!noteTypeIntervals[ntId]) noteTypeIntervals[ntId] = [];
                noteTypeIntervals[ntId].push(minutes);
                noteTypeIntervals[ntId].sort(function(a, b) { return b - a; });
                renderNtIntervals(ntId);
                input.value = '';
                input.classList.remove('valid', 'invalid');
            }
        }

        function removeNtInterval(ntId, index) {
            noteTypeIntervals[ntId].splice(index, 1);
            renderNtIntervals(ntId);
        }

        function renderNtTelehealthIntervals(ntId) {
            const container = document.getElementById('nt_telehealth_interval_list_' + ntId);
            if (!container) return;
            const intervals = noteTypeTelehealthIntervals[ntId] || [];
            container.innerHTML = '';
            intervals.forEach(function(interval, index) {
                const tag = document.createElement('div');
                tag.className = 'interval-tag';
                const label = formatInterval(interval);
                tag.innerHTML = '<span>' + escapeHtml(label) + '</span><span class="interval-remove" onclick="removeNtTelehealthInterval(\\'' + ntId + '\\',' + index + ')">x</span>';
                container.appendChild(tag);
            });
        }

        function addNtTelehealthInterval(ntId) {
            const input = document.getElementById('nt_telehealth_new_interval_' + ntId);
            const minutes = parseDuration(input.value);
            if (minutes !== null) {
                if (!noteTypeTelehealthIntervals[ntId]) noteTypeTelehealthIntervals[ntId] = [];
                noteTypeTelehealthIntervals[ntId].push(minutes);
                noteTypeTelehealthIntervals[ntId].sort(function(a, b) { return b - a; });
                renderNtTelehealthIntervals(ntId);
                input.value = '';
                input.classList.remove('valid', 'invalid');
            }
        }

        function removeNtTelehealthInterval(ntId, index) {
            noteTypeTelehealthIntervals[ntId].splice(index, 1);
            renderNtTelehealthIntervals(ntId);
        }

        function renderGlobalIntervals() {
            const container = document.getElementById('global_interval_list');
            if (!container) return;
            container.innerHTML = '';
            globalIntervals.forEach(function(interval, index) {
                const tag = document.createElement('div');
                tag.className = 'interval-tag';
                const label = formatInterval(interval);
                tag.innerHTML = '<span>' + escapeHtml(label) + '</span><span class="interval-remove" onclick="removeGlobalInterval(' + index + ')">x</span>';
                container.appendChild(tag);
            });
        }

        function addGlobalInterval() {
            const input = document.getElementById('global_new_interval');
            const minutes = parseDuration(input.value);
            if (minutes !== null) {
                globalIntervals.push(minutes);
                globalIntervals.sort(function(a, b) { return b - a; });
                renderGlobalIntervals();
                input.value = '';
                input.classList.remove('valid', 'invalid');
            }
        }

        function removeGlobalInterval(index) {
            globalIntervals.splice(index, 1);
            renderGlobalIntervals();
        }

        // --- Telehealth interval management ---
        let telehealthIntervals = [];

        function renderTelehealthIntervals() {
            const container = document.getElementById('telehealth_interval_list');
            if (!container) return;
            container.innerHTML = '';
            telehealthIntervals.forEach(function(interval, index) {
                const tag = document.createElement('div');
                tag.className = 'interval-tag';
                const label = formatInterval(interval);
                tag.innerHTML = '<span>' + escapeHtml(label) + '</span><span class="interval-remove" onclick="removeTelehealthInterval(' + index + ')">x</span>';
                container.appendChild(tag);
            });
        }

        function addTelehealthInterval() {
            const input = document.getElementById('telehealth_new_interval');
            const minutes = parseDuration(input.value);
            if (minutes !== null && minutes >= 1) {
                telehealthIntervals.push(minutes);
                telehealthIntervals.sort(function(a, b) { return b - a; });
                renderTelehealthIntervals();
                input.value = '';
                input.classList.remove('valid', 'invalid');
            }
        }

        function removeTelehealthInterval(index) {
            telehealthIntervals.splice(index, 1);
            renderTelehealthIntervals();
        }

        async function loadNoteTypes() {
            try {
                const response = await fetch('/plugin-io/api/appointment_reminders/admin/note-types');
                noteTypes = await response.json();
            } catch (e) {
                noteTypes = [];
            }
            renderNoteTypeCards();
        }

        async function loadBusinessLines() {
            try {
                const response = await fetch('/plugin-io/api/appointment_reminders/admin/business-lines');
                businessLines = await response.json();
            } catch (e) {
                businessLines = [];
            }
            renderBusinessLineCards();
        }

        function renderBusinessLineCards() {
            var container = document.getElementById('business_line_overrides_container');
            var loading = document.getElementById('business_lines_loading');
            if (loading) loading.style.display = 'none';
            // Union of active business lines and any saved override whose line is
            // no longer in the list (so edits aren't silently lost).
            var names = businessLines.map(function(b) { return b.name; });
            for (var k in savedBusinessLineOverrides) {
                if (names.indexOf(k) === -1) names.push(k);
            }
            if (!names.length) {
                container.innerHTML = '<p style="color:var(--text-soft);">No business lines found on this instance.</p>';
                return;
            }
            names.sort();
            var html = '';
            names.forEach(function() {
                html += '<div class="campaign-card" style="padding:12px;margin-bottom:8px;">'
                    + '<div class="bl-name" style="font-weight:600;margin-bottom:8px;"></div>'
                    + '<div class="form-group"><label>Attribution</label>'
                    + '<input type="text" class="bl-attribution" placeholder="(uses default attribution)" style="width:100%;"></div>'
                    + '<div class="form-group"><label>SMS from-number</label>'
                    + '<input type="text" class="bl-from-number" placeholder="(uses global Twilio number)" style="width:100%;"></div>'
                    + '</div>';
            });
            container.innerHTML = html;
            // Set names + values via properties (no HTML-attribute escaping needed).
            var cards = container.querySelectorAll('.campaign-card');
            names.forEach(function(name, i) {
                var card = cards[i];
                var saved = savedBusinessLineOverrides[name] || {};
                card.querySelector('.bl-name').textContent = name;
                card.querySelector('.bl-attribution').value = saved.attribution || '';
                card.querySelector('.bl-from-number').value = saved.from_number || '';
                card.dataset.blName = name;
            });
        }

        function gatherBusinessLineOverrides() {
            // Start from saved so per-BL fields the UI doesn't edit (e.g. future
            // template overrides set via API) are preserved.
            var result = {};
            for (var k in savedBusinessLineOverrides) {
                result[k] = Object.assign({}, savedBusinessLineOverrides[k]);
            }
            document.querySelectorAll('#business_line_overrides_container .campaign-card').forEach(function(card) {
                var name = card.dataset.blName;
                if (!name) return;
                var attr = (card.querySelector('.bl-attribution').value || '').trim();
                var from = (card.querySelector('.bl-from-number').value || '').trim();
                var entry = result[name] || {};
                if (attr) { entry.attribution = attr; } else { delete entry.attribution; }
                if (from) { entry.from_number = from; } else { delete entry.from_number; }
                if (Object.keys(entry).length) { result[name] = entry; } else { delete result[name]; }
            });
            return result;
        }

        function getGlobalTemplateForCampaign(campaign) {
            var smsId = campaign === 'reminder' ? 'reminder_sms_template' : campaign + '_sms_template';
            var emailId = campaign === 'reminder' ? 'reminder_email_template' : campaign + '_email_template';
            var smsChId = campaign === 'reminder' ? 'reminder_channel_sms' : campaign + '_channel_sms';
            var emailChId = campaign === 'reminder' ? 'reminder_channel_email' : campaign + '_channel_email';
            return {
                sms: (document.getElementById(smsId) || {}).value || '',
                email: (document.getElementById(emailId) || {}).value || '',
                smsEnabled: (document.getElementById(smsChId) || {}).checked !== false,
                emailEnabled: (document.getElementById(emailChId) || {}).checked !== false
            };
        }

        function prefillNtFromGlobal(ntId, campaign) {
            var prefix = 'nt_' + campaign + '_' + ntId;
            var global = getGlobalTemplateForCampaign(campaign);
            var smsTpl = document.getElementById(prefix + '_sms_tpl');
            var emailTpl = document.getElementById(prefix + '_email_tpl');
            var smsCheck = document.getElementById(prefix + '_channel_sms');
            var emailCheck = document.getElementById(prefix + '_channel_email');
            if (smsTpl && !smsTpl.value) smsTpl.value = global.sms;
            if (emailTpl && !emailTpl.value) emailTpl.value = global.email;
            if (smsCheck) { smsCheck.checked = global.smsEnabled; toggleChannelCard(prefix + '_sms_card', global.smsEnabled); }
            if (emailCheck) { emailCheck.checked = global.emailEnabled; toggleChannelCard(prefix + '_email_card', global.emailEnabled); }
            if (campaign === 'reminder' && (!noteTypeIntervals[ntId] || noteTypeIntervals[ntId].length === 0)) {
                noteTypeIntervals[ntId] = globalIntervals.slice();
                renderNtIntervals(ntId);
            }
            if (campaign === 'telehealth' && (!noteTypeTelehealthIntervals[ntId] || noteTypeTelehealthIntervals[ntId].length === 0)) {
                noteTypeTelehealthIntervals[ntId] = telehealthIntervals.slice();
                renderNtTelehealthIntervals(ntId);
            }
        }

        function toggleNtCampaignEnabled(ntId, campaign) {
            var enabledEl = document.getElementById('nt_' + campaign + '_enabled_' + ntId);
            var overrideBtn = document.getElementById('nt_' + campaign + '_override_btn_' + ntId);
            var inheritLabel = document.getElementById('nt_' + campaign + '_inherit_' + ntId);
            if (!enabledEl) return;
            var isEnabled = enabledEl.checked;
            // Show/hide override button and inherit label
            if (overrideBtn) overrideBtn.style.display = isEnabled ? '' : 'none';
            if (inheritLabel) inheritLabel.style.display = isEnabled ? '' : 'none';
            // If disabling, also close the override body
            if (!isEnabled) {
                var body = document.getElementById('nt_' + campaign + '_body_' + ntId);
                if (body) body.style.display = 'none';
                if (overrideBtn) overrideBtn.classList.remove('active');
            }
            updateNtMasterToggle(ntId);
        }

        function toggleNtCampaignOverride(ntId, campaign) {
            var body = document.getElementById('nt_' + campaign + '_body_' + ntId);
            var btn = document.getElementById('nt_' + campaign + '_override_btn_' + ntId);
            if (!body || !btn) return;
            var isOpen = body.style.display !== 'none';
            body.style.display = isOpen ? 'none' : '';
            btn.classList.toggle('active', !isOpen);
            // Update inherit label
            var inheritLabel = document.getElementById('nt_' + campaign + '_inherit_' + ntId);
            if (inheritLabel) inheritLabel.style.display = !isOpen ? 'none' : '';
            // Pre-fill from global when opening override with empty templates
            if (!isOpen) prefillNtFromGlobal(ntId, campaign);
            updateNtMasterToggle(ntId);
        }

        var ALL_CAMPAIGN_KEYS = ['confirmation', 'reminder', 'noshow', 'cancellation', 'telehealth'];

        function getNtCampaigns(ntId) {
            // Return only campaigns that exist in the DOM for this note type
            return ALL_CAMPAIGN_KEYS.filter(function(c) {
                return !!document.getElementById('nt_' + c + '_enabled_' + ntId);
            });
        }

        function toggleAllNtCampaigns(ntId) {
            var campaigns = getNtCampaigns(ntId);
            var masterToggle = document.getElementById('nt_master_' + ntId);
            var enable = masterToggle.checked;
            campaigns.forEach(function(c) {
                var toggle = document.getElementById('nt_' + c + '_enabled_' + ntId);
                if (toggle && toggle.checked !== enable) {
                    toggle.checked = enable;
                    toggleNtCampaignEnabled(ntId, c);
                }
            });
            updateNtMasterToggle(ntId);
        }

        function updateNtMasterToggle(ntId) {
            var campaigns = getNtCampaigns(ntId);
            var total = campaigns.length;
            var count = 0;
            var customized = 0;
            campaigns.forEach(function(c) {
                var toggle = document.getElementById('nt_' + c + '_enabled_' + ntId);
                if (toggle && toggle.checked) count++;
                var btn = document.getElementById('nt_' + c + '_override_btn_' + ntId);
                if (btn && btn.classList.contains('active')) customized++;
            });
            var masterToggle = document.getElementById('nt_master_' + ntId);
            var label = document.getElementById('nt_master_label_' + ntId);
            var customTag = document.getElementById('nt_custom_tag_' + ntId);
            if (masterToggle) masterToggle.checked = count > 0;
            if (label) label.textContent = count > 0 ? count + '/' + total : '';
            if (customTag) {
                if (customized > 0) {
                    customTag.textContent = customized + ' customized';
                    customTag.style.display = '';
                } else {
                    customTag.style.display = 'none';
                }
            }
        }

        function toggleNtCard(ntId) {
            var card = document.getElementById('nt_card_' + ntId);
            if (!card) return;
            card.classList.toggle('collapsed');
        }

        function buildChannelCardHtml(prefix, channelType, channels) {
            var checked = channels.indexOf(channelType) !== -1;
            var cardId = prefix + '_' + channelType + '_card';
            return '<div class="channel-card' + (!checked ? ' disabled' : '') + '" id="' + cardId + '">' +
                '<div class="channel-header">' +
                    '<label class="channel-toggle">' +
                        '<input type="checkbox" id="' + prefix + '_channel_' + channelType + '"' + (checked ? ' checked' : '') + ' onchange="toggleChannelCard(\\'' + cardId + '\\', this.checked)">' +
                        '<span class="channel-check"></span>' +
                        (channelType === 'sms' ? 'SMS' : 'Email') +
                    '</label>' +
                '</div>' +
                '<div class="channel-body">' +
                    '<div class="template-label-row">' +
                        '<label>Template</label>' +
                        '<button type="button" class="var-insert-btn" onclick="toggleVarDropdown(this)">+ Insert Field</button>' +
                        '<div class="var-dropdown"></div>' +
                    '</div>' +
                    '<textarea id="' + prefix + '_' + channelType + '_tpl" placeholder="Type / to insert a field"></textarea>' +
                '</div>' +
            '</div>';
        }

        function renderNoteTypeCards() {
            const container = document.getElementById('note_type_overrides_container');
            if (!container) return;
            container.innerHTML = '';

            if (noteTypes.length === 0) {
                container.innerHTML = '<p style="color:var(--text-soft);font-style:italic;">No schedulable visit types found.</p>';
                return;
            }

            var BASE_CAMPAIGNS = [
                {key: 'confirmation', label: 'Confirmation', hasIntervals: false},
                {key: 'reminder', label: 'Reminders', hasIntervals: true},
                {key: 'noshow', label: 'No-Show', hasIntervals: false},
                {key: 'cancellation', label: 'Cancellation', hasIntervals: false}
            ];
            var TELEHEALTH_CAMPAIGN = {key: 'telehealth', label: 'Join Telehealth', hasIntervals: true};

            noteTypes.forEach(function(nt) {
                var CAMPAIGNS = BASE_CAMPAIGNS.slice();
                if (nt.is_telehealth) CAMPAIGNS.push(TELEHEALTH_CAMPAIGN);
                const saved = savedNoteTypeReminders[nt.id] || {};
                const safeName = escapeHtml(nt.name);
                const teleLabel = nt.is_telehealth ? '<span style="display:inline-block;background:rgba(74,111,165,0.08);border:1px solid rgba(74,111,165,0.2);padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;color:var(--brand-primary);vertical-align:middle;">Telehealth</span>' : '';

                // Set up reminder and telehealth intervals
                noteTypeIntervals[nt.id] = (saved.reminder_intervals || []).slice();
                noteTypeTelehealthIntervals[nt.id] = (saved.telehealth_intervals || []).slice();

                const card = document.createElement('div');
                card.className = 'campaign-card collapsed';
                card.id = 'nt_card_' + nt.id;

                var sectionsHtml = '';
                CAMPAIGNS.forEach(function(c) {
                    var enabledKey, overrideKey, smsTplKey, emailTplKey, channelsKey;
                    if (c.key === 'reminder') {
                        enabledKey = 'reminders_enabled';
                        overrideKey = 'reminder_override';
                        smsTplKey = 'reminder_sms_template';
                        emailTplKey = 'reminder_email_template';
                        channelsKey = 'reminder_channels';
                    } else {
                        enabledKey = c.key + '_enabled';
                        overrideKey = c.key + '_override';
                        smsTplKey = c.key + '_sms_template';
                        emailTplKey = c.key + '_email_template';
                        channelsKey = c.key + '_channels';
                    }

                    // Global is the master switch. When on, each note type inherits
                    // unless the per-type record explicitly opts out (=== false).
                    var globalEnabledId = c.key === 'reminder' ? 'reminders_enabled' : c.key + '_enabled';
                    var globalEl = document.getElementById(globalEnabledId);
                    var globalOn = globalEl ? globalEl.checked : false;
                    var isEnabled = globalOn && saved[enabledKey] !== false;
                    var isOverride = saved[overrideKey] === true;
                    var smsTpl = saved[smsTplKey] || '';
                    var emailTpl = saved[emailTplKey] || '';
                    var channels = saved[channelsKey] || ['sms', 'email'];
                    var prefix = 'nt_' + c.key + '_' + nt.id;

                    sectionsHtml += '<div class="nt-campaign-section">' +
                        '<div class="nt-campaign-header">' +
                            '<span class="nt-campaign-label">' + c.label + '</span>' +
                            '<div class="nt-section-controls">' +
                                '<span class="inherit-label" id="nt_' + c.key + '_inherit_' + nt.id + '" style="' + (isEnabled && !isOverride ? '' : 'display:none') + '">Inherits global</span>' +
                                '<button type="button" class="override-btn' + (isOverride ? ' active' : '') + '" id="nt_' + c.key + '_override_btn_' + nt.id + '" style="' + (isEnabled ? '' : 'display:none') + '" onclick="toggleNtCampaignOverride(\\'' + nt.id + '\\', \\'' + c.key + '\\')">Customize</button>' +
                                '<label class="toggle">' +
                                    '<input type="checkbox" id="nt_' + c.key + '_enabled_' + nt.id + '"' + (isEnabled ? ' checked' : '') + ' onchange="toggleNtCampaignEnabled(\\'' + nt.id + '\\', \\'' + c.key + '\\')">' +
                                    '<span class="slider"></span>' +
                                '</label>' +
                            '</div>' +
                        '</div>' +
                        '<div id="nt_' + c.key + '_body_' + nt.id + '" class="nt-campaign-body" style="' + (isEnabled && isOverride ? '' : 'display:none') + '">';

                    if (c.hasIntervals && c.key === 'reminder') {
                        var ntSendTime = saved.reminder_send_time || '';
                        var ntTimezone = saved.reminder_timezone || '';
                        sectionsHtml += '<div class="form-group">' +
                            '<label>Reminder Intervals</label>' +
                            '<div class="interval-list" id="nt_interval_list_' + nt.id + '"></div>' +
                            '<div class="add-interval">' +
                                '<input type="text" id="nt_new_interval_' + nt.id + '" placeholder="Enter interval" oninput="validateIntervalInput(this)" onkeydown="if(event.key===\\'Enter\\'){event.preventDefault();addNtInterval(\\'' + nt.id + '\\')}">' +
                                '<button onclick="addNtInterval(\\'' + nt.id + '\\')">Add</button>' +
                            '</div>' +
                            '<div class="interval-hint">Use <code>w</code> weeks, <code>d</code> days, <code>h</code> hours, <code>m</code> minutes</div>' +
                        '</div>' +
                        '<div class="form-group">' +
                            '<label>Send Time for Day-Out Reminders</label>' +
                            '<div class="send-time-row">' +
                                '<input type="time" id="nt_reminder_send_time_' + nt.id + '" value="' + escapeHtml(ntSendTime) + '" placeholder="Inherit global">' +
                                '<select id="nt_reminder_timezone_' + nt.id + '">' +
                                    '<option value=""' + (!ntTimezone ? ' selected' : '') + '>Inherit global</option>' +
                                    '<option value="America/New_York"' + (ntTimezone === 'America/New_York' ? ' selected' : '') + '>Eastern (ET)</option>' +
                                    '<option value="America/Chicago"' + (ntTimezone === 'America/Chicago' ? ' selected' : '') + '>Central (CT)</option>' +
                                    '<option value="America/Denver"' + (ntTimezone === 'America/Denver' ? ' selected' : '') + '>Mountain (MT)</option>' +
                                    '<option value="America/Los_Angeles"' + (ntTimezone === 'America/Los_Angeles' ? ' selected' : '') + '>Pacific (PT)</option>' +
                                    '<option value="America/Anchorage"' + (ntTimezone === 'America/Anchorage' ? ' selected' : '') + '>Alaska (AKT)</option>' +
                                    '<option value="Pacific/Honolulu"' + (ntTimezone === 'Pacific/Honolulu' ? ' selected' : '') + '>Hawaii (HT)</option>' +
                                '</select>' +
                            '</div>' +
                            '<div class="interval-hint">Leave blank to inherit global send time.</div>' +
                        '</div>';
                    }

                    if (c.hasIntervals && c.key === 'telehealth') {
                        sectionsHtml += '<div class="form-group">' +
                            '<label>Telehealth Intervals</label>' +
                            '<div class="interval-list" id="nt_telehealth_interval_list_' + nt.id + '"></div>' +
                            '<div class="add-interval">' +
                                '<input type="text" id="nt_telehealth_new_interval_' + nt.id + '" placeholder="e.g. 15m, 1h" oninput="validateIntervalInput(this)" onkeydown="if(event.key===\\'Enter\\'){event.preventDefault();addNtTelehealthInterval(\\'' + nt.id + '\\')}">' +
                                '<button onclick="addNtTelehealthInterval(\\'' + nt.id + '\\')">Add</button>' +
                            '</div>' +
                            '<div class="interval-hint">Minutes before the appointment to send the telehealth link.</div>' +
                        '</div>';
                    }

                    sectionsHtml += buildChannelCardHtml(prefix, 'sms', channels);
                    sectionsHtml += buildChannelCardHtml(prefix, 'email', channels);

                    sectionsHtml += '</div></div>';
                });

                card.innerHTML =
                    '<div class="campaign-header" onclick="toggleNtCard(\\'' + nt.id + '\\')">' +
                        '<div style="display:flex;align-items:center;gap:8px;min-width:0;">' +
                            '<span class="nt-expand-arrow" id="nt_arrow_' + nt.id + '">&#9654;</span>' +
                            '<span class="campaign-title" style="white-space:nowrap;">' + safeName + '</span>' +
                            teleLabel +
                            '<span id="nt_custom_tag_' + nt.id + '" style="display:none;font-size:11px;font-weight:600;padding:1px 8px;border-radius:10px;background:rgba(74,111,165,0.08);border:1px solid rgba(74,111,165,0.2);color:var(--brand-primary);white-space:nowrap;"></span>' +
                        '</div>' +
                        '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;" onclick="event.stopPropagation()">' +
                            '<span id="nt_master_label_' + nt.id + '" style="font-size:12px;font-weight:600;color:var(--text-soft);"></span>' +
                            '<label class="toggle"><input type="checkbox" id="nt_master_' + nt.id + '" onchange="toggleAllNtCampaigns(\\'' + nt.id + '\\')"><span class="slider"></span></label>' +
                        '</div>' +
                    '</div>' +
                    '<div class="nt-card-body">' + sectionsHtml + '</div>';

                container.appendChild(card);

                // Populate textarea values after DOM insert
                CAMPAIGNS.forEach(function(c) {
                    var smsTplKey = c.key === 'reminder' ? 'reminder_sms_template' : c.key + '_sms_template';
                    var emailTplKey = c.key === 'reminder' ? 'reminder_email_template' : c.key + '_email_template';
                    var prefix = 'nt_' + c.key + '_' + nt.id;
                    var smsTplEl = document.getElementById(prefix + '_sms_tpl');
                    var emailTplEl = document.getElementById(prefix + '_email_tpl');
                    if (smsTplEl) smsTplEl.value = saved[smsTplKey] || '';
                    if (emailTplEl) emailTplEl.value = saved[emailTplKey] || '';
                });

                renderNtIntervals(nt.id);
                if (nt.is_telehealth) renderNtTelehealthIntervals(nt.id);
                updateNtMasterToggle(nt.id);
            });
        }

        function gatherNoteTypeReminders() {
            // Map campaign key to its global enabled checkbox id
            var globalEnabledMap = {
                'confirmation': 'confirmation_enabled',
                'reminder': 'reminders_enabled',
                'noshow': 'noshow_enabled',
                'cancellation': 'cancellation_enabled',
                'telehealth': 'telehealth_enabled'
            };

            var result = {};
            noteTypes.forEach(function(nt) {
                var CAMPAIGNS = ['confirmation', 'reminder', 'noshow', 'cancellation'];
                if (nt.is_telehealth) CAMPAIGNS.push('telehealth');
                var entry = {
                    note_type_id: nt.id,
                    note_type_name: nt.name,
                };

                CAMPAIGNS.forEach(function(c) {
                    var enabledKey = c === 'reminder' ? 'reminders_enabled' : c + '_enabled';
                    var overrideKey = c === 'reminder' ? 'reminder_override' : c + '_override';
                    var smsTplKey = c === 'reminder' ? 'reminder_sms_template' : c + '_sms_template';
                    var emailTplKey = c === 'reminder' ? 'reminder_email_template' : c + '_email_template';
                    var channelsKey = c === 'reminder' ? 'reminder_channels' : c + '_channels';

                    var globalEl = document.getElementById(globalEnabledMap[c]);
                    var globalEnabled = globalEl ? globalEl.checked : false;

                    var enabledEl = document.getElementById('nt_' + c + '_enabled_' + nt.id);
                    if (!enabledEl) return;

                    var overrideBtn = document.getElementById('nt_' + c + '_override_btn_' + nt.id);
                    var isOverride = overrideBtn ? overrideBtn.classList.contains('active') : false;

                    var prefix = 'nt_' + c + '_' + nt.id;
                    var ntChannels = [];
                    if ((document.getElementById(prefix + '_channel_sms') || {}).checked) ntChannels.push('sms');
                    if ((document.getElementById(prefix + '_channel_email') || {}).checked) ntChannels.push('email');

                    // Explicit true/false: false means "opt out for this visit type."
                    // When global is off, the per-type toggles are visually forced off
                    // by the UI; preserve the user's existing opt-out rather than
                    // silently converting every type into an opt-out.
                    var priorSaved = (savedNoteTypeReminders[nt.id] || {})[enabledKey];
                    var enabledValue;
                    if (globalEnabled) {
                        enabledValue = enabledEl.checked ? true : false;
                    } else {
                        enabledValue = priorSaved === false ? false : true;
                    }
                    entry[enabledKey] = enabledValue;
                    entry[overrideKey] = enabledValue === false ? false : isOverride;
                    entry[smsTplKey] = (document.getElementById(prefix + '_sms_tpl') || {}).value || '';
                    entry[emailTplKey] = (document.getElementById(prefix + '_email_tpl') || {}).value || '';
                    entry[channelsKey] = ntChannels;

                    if (c === 'reminder') {
                        entry['reminder_intervals'] = (noteTypeIntervals[nt.id] || []).slice();
                        entry['reminder_send_time'] = (document.getElementById('nt_reminder_send_time_' + nt.id) || {}).value || '';
                        entry['reminder_timezone'] = (document.getElementById('nt_reminder_timezone_' + nt.id) || {}).value || '';
                    }
                    if (c === 'telehealth') {
                        entry['telehealth_intervals'] = (noteTypeTelehealthIntervals[nt.id] || []).slice();
                    }
                });

                result[nt.id] = entry;
            });
            return result;
        }

        function getChannelCheckboxes(prefix) {
            var channels = [];
            if (document.getElementById(prefix + '_channel_sms').checked) channels.push('sms');
            if (document.getElementById(prefix + '_channel_email').checked) channels.push('email');
            return channels;
        }

        function setChannelCheckboxes(prefix, channels) {
            var ch = channels || ['sms', 'email'];
            document.getElementById(prefix + '_channel_sms').checked = ch.indexOf('sms') !== -1;
            document.getElementById(prefix + '_channel_email').checked = ch.indexOf('email') !== -1;
            toggleChannelCard(prefix + '_sms_card', ch.indexOf('sms') !== -1);
            toggleChannelCard(prefix + '_email_card', ch.indexOf('email') !== -1);
        }

        async function loadIntegrationStatus() {
            try {
                var response = await fetch('/plugin-io/api/appointment_reminders/admin/integration-status');
                var data = await response.json();
                document.getElementById('integration_loading').style.display = 'none';
                document.getElementById('integration_details').style.display = '';
                document.getElementById('twilio_status_icon').textContent = data.twilio_configured ? '\\u2705' : '\\u274c';
                document.getElementById('twilio_status_text').textContent = data.twilio_configured ? 'Configured' : 'Not configured';
                document.getElementById('sendgrid_status_icon').textContent = data.sendgrid_configured ? '\\u2705' : '\\u274c';
                document.getElementById('sendgrid_status_text').textContent = data.sendgrid_configured ? 'Configured' : 'Not configured';
                if (!data.twilio_configured && !data.sendgrid_configured) {
                    document.getElementById('integration_fallback_note').style.display = '';
                }
                // Testing mode is not read from here any more — it lives in the
                // config the form already holds, so the checkbox is the live
                // source and this response would go stale the moment it is
                // toggled. Only the credential checks come from this call.
                integrationStatusLoaded = true;
                updateBroadcastWarning();
            } catch (e) {
                document.getElementById('integration_loading').textContent = 'Could not check integration status.';
            }
        }

        // Mirrors the testing-mode checkbox, kept current by updateTestingModeUI.
        // The server re-checks on every send, so this only drives presentation.
        var testingModeActive = false;
        var integrationStatusLoaded = false;

        var CAMPAIGN_ENABLE_IDS = [
            'confirmation_enabled', 'reminders_enabled', 'telehealth_enabled',
            'noshow_enabled', 'cancellation_enabled'
        ];

        function updateBroadcastWarning() {
            // Stay silent until the secret state is known, so the warning never
            // implies TESTING_MODE is off when we simply haven't checked yet.
            if (!integrationStatusLoaded) return;
            var banner = document.getElementById('broadcast_warning');
            if (!banner) return;
            var anyEnabled = CAMPAIGN_ENABLE_IDS.some(function(id) {
                var el = document.getElementById(id);
                return el && el.checked;
            });
            banner.style.display = (anyEnabled && !testingModeActive) ? '' : 'none';
        }

        async function saveConfig() {
            const config = {
                confirmation_enabled: document.getElementById('confirmation_enabled').checked,
                confirmation_sms_template: document.getElementById('confirmation_sms_template').value,
                confirmation_email_template: document.getElementById('confirmation_email_template').value,
                confirmation_channels: getChannelCheckboxes('confirmation'),
                reminders_enabled: document.getElementById('reminders_enabled').checked,
                reminder_intervals: globalIntervals.slice(),
                reminder_sms_template: document.getElementById('reminder_sms_template').value,
                reminder_email_template: document.getElementById('reminder_email_template').value,
                reminder_channels: getChannelCheckboxes('reminder'),
                reminder_send_time: document.getElementById('reminder_send_time').value,
                reminder_timezone: document.getElementById('reminder_timezone').value,
                noshow_enabled: document.getElementById('noshow_enabled').checked,
                noshow_sms_template: document.getElementById('noshow_sms_template').value,
                noshow_email_template: document.getElementById('noshow_email_template').value,
                noshow_channels: getChannelCheckboxes('noshow'),
                cancellation_enabled: document.getElementById('cancellation_enabled').checked,
                cancellation_sms_template: document.getElementById('cancellation_sms_template').value,
                cancellation_email_template: document.getElementById('cancellation_email_template').value,
                cancellation_channels: getChannelCheckboxes('cancellation'),
                telehealth_enabled: document.getElementById('telehealth_enabled').checked,
                telehealth_sms_template: document.getElementById('telehealth_sms_template').value,
                telehealth_email_template: document.getElementById('telehealth_email_template').value,
                telehealth_channels: getChannelCheckboxes('telehealth'),
                telehealth_intervals: telehealthIntervals.slice(),
                note_type_reminders: gatherNoteTypeReminders(),
                default_attribution: document.getElementById('default_attribution_input').value.trim(),
                decline_task_team_id: document.getElementById('decline_task_team_id').value,
                testing_mode: document.getElementById('testing_mode').checked,
                testing_mode_patients: splitLines('testing_mode_patients'),
                testing_mode_recipients: splitLines('testing_mode_recipients'),
                business_line_overrides: gatherBusinessLineOverrides(),
            };

            const response = await fetch('/plugin-io/api/appointment_reminders/admin/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(config)
            });

            if (response.ok) {
                showToast('Configuration saved successfully!', 'success');
                return;
            }

            var message = 'Failed to save configuration';
            try {
                var err = await response.json();
                if (err && err.error) message = err.error;
            } catch (e) { /* non-JSON error body — keep the generic message */ }
            showToast(message, 'error');
        }

        const PATIENT_APP_HASH = btoa('appointment_reminders.handlers.patient_app:NotifyPatientApp');

        async function openPatientModal(patientId, patientName) {
            const modal = document.getElementById('patient_modal');
            const loading = document.getElementById('modal_loading');
            const content = document.getElementById('modal_content');

            document.getElementById('modal_patient_name').textContent = patientName || 'Patient Details';
            loading.style.display = 'block';
            content.style.display = 'none';
            modal.classList.add('open');

            try {
                const response = await fetch('/plugin-io/api/appointment_reminders/admin/patient/' + patientId);
                const patient = await response.json();

                if (patient.error) {
                    loading.textContent = 'Error: ' + patient.error;
                    return;
                }

                const fullName = ((patient.first_name || '') + ' ' + (patient.last_name || '')).trim();
                var headerHtml = escapeHtml(fullName || 'Patient Details');
                var subtitleParts = [];
                if (patient.mrn) subtitleParts.push('MRN: ' + escapeHtml(patient.mrn));
                if (patient.preferred_name) subtitleParts.push('Goes by "' + escapeHtml(patient.preferred_name) + '"');
                document.getElementById('modal_patient_name').innerHTML = headerHtml +
                    (subtitleParts.length ? '<p class="modal-subtitle">' + subtitleParts.join(' &middot; ') + '</p>' : '');

                var warningsHtml = '';
                if (patient.deceased) {
                    warningsHtml += '<div class="patient-status-warn">This patient is marked as deceased. Messages should not be sent.</div>';
                } else if (!patient.active) {
                    warningsHtml += '<div class="patient-status-warn">This patient is inactive.</div>';
                }

                var apptHtml = '';
                if (patient.next_appointment) {
                    var apptDate = new Date(patient.next_appointment.start_time).toLocaleString();
                    apptHtml = '<div class="next-appt">Next appointment: ' + escapeHtml(apptDate) + '</div>';
                }

                function consentBadge(consent, optedOut) {
                    if (optedOut) return '<span class="consent-badge consent-danger">opted out</span>';
                    if (consent === true) return '<span class="consent-badge consent-ok">consented</span>';
                    if (consent === false) return '<span class="consent-badge consent-warn">no consent</span>';
                    return '';
                }

                var dobDisplay = patient.date_of_birth || '\\u2014';
                if (patient.age !== null && patient.age !== undefined) {
                    dobDisplay += ' (age ' + patient.age + ')';
                }

                const infoGrid = document.getElementById('modal_patient_info');
                infoGrid.innerHTML = warningsHtml + apptHtml +
                    '<div class="info-item"><div class="info-label">Date of Birth</div><div>' + escapeHtml(dobDisplay) + '</div></div>' +
                    '<div class="info-item"><div class="info-label">Phone</div><div>' + escapeHtml(patient.phone || '\\u2014') + consentBadge(patient.sms_consent, patient.sms_opted_out) + '</div></div>' +
                    '<div class="info-item"><div class="info-label">Email</div><div>' + escapeHtml(patient.email || '\\u2014') + consentBadge(patient.email_consent, patient.email_opted_out) + '</div></div>' +
                    '<div class="info-item"><div class="info-label">Address</div><div>' + escapeHtml(patient.address || '\\u2014') + '</div></div>';

                const actions = document.getElementById('modal_actions');
                actions.innerHTML =
                    '<a class="btn-primary" href="/patient/' + patientId + '" target="_top">View Profile</a>' +
                    '<a class="btn-secondary" href="/patient/' + patientId + '/chart" target="_top">View Chart</a>';

                loading.style.display = 'none';
                content.style.display = 'block';
            } catch (err) {
                loading.textContent = 'Failed to load patient details.';
            }
        }

        function closePatientModal(event) {
            if (event && event.target !== document.getElementById('patient_modal')) return;
            document.getElementById('patient_modal').classList.remove('open');
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                document.getElementById('patient_modal').classList.remove('open');
            }
        });

        loadConfig();
    </script>
</body>
</html>
        """
        html = html.replace("{THEME_STYLE_PLACEHOLDER}", theme_style_block())
        return [HTMLResponse(html)]

    @api.get("/admin/note-types")
    def get_note_types(self) -> list[Response | Effect]:
        """Return schedulable note types for per-type reminder configuration."""
        from canvas_sdk.v1.data.note import NoteType

        note_types = NoteType.objects.filter(
            is_scheduleable=True, is_active=True
        ).order_by("name")
        return [
            JSONResponse(
                [
                    {"id": str(nt.id), "name": nt.name, "is_telehealth": nt.is_telehealth}
                    for nt in note_types
                ],
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/admin/business-lines")
    def get_business_lines(self) -> list[Response | Effect]:
        """Return active business lines for per-business-line override config."""
        from canvas_sdk.v1.data import BusinessLine

        business_lines = BusinessLine.objects.filter(active=True).order_by("name")
        return [
            JSONResponse(
                [{"id": str(bl.id), "name": bl.name} for bl in business_lines],
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/admin/teams")
    def get_teams(self) -> list[Response | Effect]:
        """Teams available to receive the decline follow-up task."""
        from canvas_sdk.v1.data.team import Team

        teams = Team.objects.order_by("name")
        return [
            JSONResponse(
                [{"id": str(team.id), "name": team.name} for team in teams],
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/admin/unresolved-senders")
    def get_unresolved_senders_endpoint(self) -> list[Response | Effect]:
        """Verified inbound replies whose sender matched no patient, newest first.

        Under ``/admin`` because these rows belong to no patient, so there is no
        chart to scope them to and no per-patient endpoint that could return
        them. Role-gated like the rest of ``/admin*``.
        """
        return [
            JSONResponse(
                fetch_unresolved_senders(limit=100), status_code=HTTPStatus.OK
            )
        ]

    @api.get("/admin/integration-status")
    def get_integration_status(self) -> list[Response | Effect]:
        """Check whether Twilio and SendGrid secrets are configured."""
        twilio_keys = ("twilio-account-sid", "twilio-auth-token", "twilio-phone-number")
        sendgrid_keys = ("sendgrid-api-key", "sendgrid-from-email")
        twilio_configured = all(self.secrets.get(k) for k in twilio_keys)
        sendgrid_configured = all(self.secrets.get(k) for k in sendgrid_keys)
        return [
            JSONResponse(
                {
                    "twilio_configured": twilio_configured,
                    "sendgrid_configured": sendgrid_configured,
                    "templates_locked": templates_locked(self.secrets),
                    "testing_mode": is_testing_mode_active(load_config()),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/admin/config")
    def get_config(self) -> list[Response | Effect]:
        """Get current campaign configuration."""
        config = load_config()
        return [JSONResponse(config.to_dict(), status_code=HTTPStatus.OK)]

    @api.post("/admin/config")
    def save_config_endpoint(self) -> list[Response | Effect]:
        """Save campaign configuration."""
        data = self.request.json()
        try:
            config = CampaignConfig.from_dict(data)
        except TypeError as e:
            return [JSONResponse({"error": f"Invalid configuration: {e}"}, status_code=HTTPStatus.BAD_REQUEST)]

        # LOCK_MESSAGE_TEMPLATES deliberately does not apply here. Admins edit
        # the approved copy; the lock stops whoever sends a message by hand from
        # departing from it (see manual_send).
        save_config(config)
        return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

    @api.get("/admin/patient/<patient_id>")
    def get_patient_detail(self) -> list[Response | Effect]:
        """Get patient detail for modal display."""
        from datetime import date

        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.patient import Patient

        patient_id = self.request.path_params["patient_id"]
        try:
            patient = Patient.objects.prefetch_related("telecom", "addresses").get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]

        phone = ""
        email = ""
        sms_consent = None
        email_consent = None
        sms_opted_out = False
        email_opted_out = False
        for t in patient.telecom.all():
            if t.system == "phone" and not phone:
                phone = t.value or ""
                sms_consent = t.has_consent
                sms_opted_out = bool(t.opted_out)
            elif t.system == "email" and not email:
                email = t.value or ""
                email_consent = t.has_consent
                email_opted_out = bool(t.opted_out)

        address = ""
        for a in patient.addresses.all():
            if a.state == "active":
                parts = [p for p in [a.city, a.state_code] if p]
                if parts:
                    address = ", ".join(parts)
                    if a.use == "home":
                        break

        age = None
        if patient.birth_date:
            today = date.today()
            age = (
                today.year
                - patient.birth_date.year
                - (
                    (today.month, today.day)
                    < (patient.birth_date.month, patient.birth_date.day)
                )
            )

        next_appointment = None
        try:
            from django.utils import timezone

            appt = (
                Appointment.objects.filter(
                    patient__id=patient_id,
                    start_time__gte=timezone.now(),
                )
                .order_by("start_time")
                .first()
            )
            if appt:
                next_appointment = {
                    "start_time": appt.start_time.isoformat(),
                    "status": appt.status or "",
                }
        except Exception:
            pass

        nickname = patient.nickname or ""
        preferred_name = ""
        if nickname and nickname.lower() != (patient.first_name or "").lower():
            preferred_name = nickname

        return [
            JSONResponse(
                {
                    "id": str(patient.id),
                    "first_name": patient.first_name or "",
                    "last_name": patient.last_name or "",
                    "preferred_name": preferred_name,
                    "mrn": patient.mrn or "",
                    "date_of_birth": str(patient.birth_date)
                    if patient.birth_date
                    else "",
                    "age": age,
                    "active": patient.active,
                    "deceased": patient.deceased,
                    "phone": phone,
                    "email": email,
                    "sms_consent": sms_consent,
                    "sms_opted_out": sms_opted_out,
                    "email_consent": email_consent,
                    "email_opted_out": email_opted_out,
                    "address": address,
                    "next_appointment": next_appointment,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/patient/<patient_id>/history")
    def get_patient_history(self) -> list[Response | Effect]:
        """Get patient-specific notification history (newest first)."""
        patient_id = self.request.path_params["patient_id"]
        history = fetch_patient_history(patient_id, limit=100)
        return [JSONResponse(history, status_code=HTTPStatus.OK)]

    @api.get("/patient/<patient_id>/appointments")
    def get_patient_appointments(self) -> list[Response | Effect]:
        """Get recent appointments and standalone notes for a patient."""
        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.note import Note

        patient_id = self.request.path_params["patient_id"]

        # Fetch appointments (patient FK stores dbid, so filter via UUID traversal).
        # No location join: this endpoint never reads it. Only the two relations
        # whose fields are actually serialized below are joined.
        appointments = (
            Appointment.objects.filter(patient__id=patient_id)
            .select_related("provider", "note_type")
            .order_by("-start_time")[:20]
        )

        result = []
        linked_note_ids = set()
        for appt in appointments:
            if appt.note_id:
                linked_note_ids.add(appt.note_id)
            result.append({
                "type": "appointment",
                "appointment_id": str(appt.id),
                "note_id": "",
                "datetime": appt.start_time.isoformat() if appt.start_time else "",
                "description": appt.description or "",
                "note_type_id": str(appt.note_type.id) if appt.note_type else "",
                "note_type_name": appt.note_type.name if appt.note_type else "",
                "provider_name": (
                    f"{appt.provider.first_name} {appt.provider.last_name}"
                    if appt.provider else ""
                ),
                "status": appt.status or "",
            })

        # Fetch standalone notes (no linked appointment)
        # `body` and `related_data` are JSONFields holding the note's clinical
        # content — routinely the largest thing on the row, and nothing here
        # reads either. Deferring them keeps 20 note bodies per chart open out
        # of memory. Location is dropped for the same reason as above: unused.
        notes_qs = (
            Note.objects.filter(patient__id=patient_id)
            .select_related("provider", "note_type_version")
            .defer("body", "related_data")
            .order_by("-datetime_of_service")
        )
        if linked_note_ids:
            notes_qs = notes_qs.exclude(id__in=linked_note_ids)
        notes_qs = notes_qs[:20]

        for note in notes_qs:
            result.append({
                "type": "note",
                "appointment_id": "",
                "note_id": str(note.id),
                "datetime": note.datetime_of_service.isoformat() if note.datetime_of_service else "",
                "description": note.title or "",
                "note_type_id": str(note.note_type_version.id) if note.note_type_version else "",
                "note_type_name": note.note_type_version.name if note.note_type_version else "",
                "provider_name": (
                    f"{note.provider.first_name} {note.provider.last_name}"
                    if note.provider else ""
                ),
                "status": "",
            })

        # Sort combined list by datetime descending
        result.sort(key=lambda x: x["datetime"] or "", reverse=True)

        return [JSONResponse(result, status_code=HTTPStatus.OK)]

    def _render_campaign_message(
        self,
        patient_id: str,
        appointment_id: str,
        note_id: str,
        campaign_type: str,
        patient: Patient | None = None,
    ) -> tuple[Response | None, dict]:
        """Render a campaign's SMS and email body from the stored templates.

        Shared by the preview endpoint and by manual send while
        LOCK_MESSAGE_TEMPLATES is set, so a locked send delivers exactly the
        stored copy instead of whatever the client posted.

        Pass ``patient`` when the caller has already loaded it — manual send
        needs the same row with ``telecom`` prefetched for delivery, so handing
        it over avoids fetching the patient twice for one send.

        Returns ``(error_response, {})`` on failure, ``(None, payload)`` on
        success.
        """
        from canvas_sdk.v1.data.appointment import Appointment
        from canvas_sdk.v1.data.note import Note
        from canvas_sdk.v1.data.patient import Patient

        from appointment_reminders.services.templates import (
            get_note_template_variables,
            get_template_variables,
            render_template,
        )

        if (not appointment_id and not note_id) or not campaign_type:
            return (JSONResponse({"error": "campaign_type and either appointment_id or note_id are required"}, status_code=HTTPStatus.BAD_REQUEST), {})

        if patient is None:
            try:
                # business_line is selected because the template renderer resolves
                # {{business_line}} / {{business_line_attribution}} off the patient.
                patient = Patient.objects.select_related("business_line").get(id=patient_id)
            except Patient.DoesNotExist:
                return (JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND), {})

        config = load_config()

        if appointment_id:
            try:
                # Scoped to the patient in the path on purpose: the rendered
                # message carries the appointment's time, provider, location and
                # telehealth join link, so an id belonging to someone else must
                # not be renderable into this patient's message.
                appointment = Appointment.objects.filter(
                    patient__id=patient_id
                ).select_related(
                    "provider", "location", "note_type"
                ).prefetch_related(
                    "provider__roles", "location__addresses", "location__telecom"
                ).get(id=appointment_id)
            except Appointment.DoesNotExist:
                return (JSONResponse({"error": "Appointment not found"}, status_code=HTTPStatus.NOT_FOUND), {})

            note_type_id = str(appointment.note_type.id) if appointment.note_type else None
            variables = get_template_variables(
                patient, appointment, config.reminder_timezone, config=config
            )
        else:
            try:
                # Same patient scoping as the appointment branch above. The
                # prefetches match that branch too, since the shared renderer
                # reads provider roles and the location's address / telecom.
                note = Note.objects.filter(patient__id=patient_id).select_related(
                    "provider", "location", "note_type_version"
                ).prefetch_related(
                    "provider__roles", "location__addresses", "location__telecom"
                ).get(id=note_id)
            except Note.DoesNotExist:
                return (JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND), {})

            note_type_id = str(note.note_type_version.id) if note.note_type_version else None
            variables = get_note_template_variables(
                patient, note, config.reminder_timezone, config=config
            )

        enabled, channels, sms_template, email_template, *_ = (
            get_effective_campaign_config(config, note_type_id, campaign_type)
        )
        # For manual preview, fall back to global templates if per-note-type
        # config returned empty (e.g. reminders with no per-type override)
        if not sms_template and not email_template:
            global_map = {
                "reminder": (config.reminder_sms_template, config.reminder_email_template, config.reminder_channels),
                "confirmation": (config.confirmation_sms_template, config.confirmation_email_template, config.confirmation_channels),
                "noshow": (config.noshow_sms_template, config.noshow_email_template, config.noshow_channels),
                "cancellation": (config.cancellation_sms_template, config.cancellation_email_template, config.cancellation_channels),
                "telehealth": (config.telehealth_sms_template, config.telehealth_email_template, config.telehealth_channels),
            }
            if campaign_type in global_map:
                sms_template, email_template, channels = global_map[campaign_type]

        sms_content = render_template(sms_template, variables)
        email_content = render_template(email_template, variables)

        return (None, {
            "sms_content": sms_content,
            "email_content": email_content,
            "channels": channels,
        })

    @api.post("/patient/<patient_id>/preview")
    def preview_template(self) -> list[Response | Effect]:
        """Preview rendered template for a campaign + appointment or note."""
        body = self.request.json()
        error, payload = self._render_campaign_message(
            self.request.path_params["patient_id"],
            body.get("appointment_id", ""),
            body.get("note_id", ""),
            body.get("campaign_type"),
        )
        if error is not None:
            return [error]
        return [JSONResponse(
            {**payload, "enabled": True},  # Always allow manual sends
            status_code=HTTPStatus.OK,
        )]

    @api.post("/patient/<patient_id>/send")
    def manual_send(self) -> list[Response | Effect]:
        """Manually send a notification to a patient."""
        from canvas_sdk.v1.data.patient import Patient

        from appointment_reminders.services.delivery import deliver_to_patient
        from appointment_reminders.services.history import log_delivery
        from appointment_reminders.services.templates import unresolved_placeholders

        patient_id = self.request.path_params["patient_id"]
        body = self.request.json()
        appointment_id = body.get("appointment_id", "")
        note_id = body.get("note_id", "")
        campaign_type = body.get("campaign_type", "manual")
        sms_content = body.get("sms_content", "")
        email_content = body.get("email_content", "")
        channels = body.get("channels", [])

        if not channels:
            return [JSONResponse(
                {"error": "At least one channel must be selected"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        # With copy locked, a manual send may not carry client-supplied wording.
        # The read-only textareas in the panel are a convenience; this is the
        # actual boundary, since anything with a staff session could POST here
        # directly. A campaign we have no template for is refused rather than
        # sent as an empty message.
        locked = templates_locked(self.secrets)
        if locked and campaign_type not in SENDABLE_CAMPAIGNS:
            return [JSONResponse(
                {
                    "error": (
                        f"'{campaign_type}' has no approved copy to send while "
                        "message copy is locked by the LOCK_MESSAGE_TEMPLATES "
                        "setting."
                    )
                },
                status_code=HTTPStatus.FORBIDDEN,
            )]

        try:
            patient = (
                Patient.objects.select_related("business_line")
                .prefetch_related("telecom")
                .get(id=patient_id)
            )
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        if locked:
            # Reuse the patient just loaded: the renderer needs the same row and
            # would otherwise fetch it a second time for one send.
            error, rendered = self._render_campaign_message(
                patient_id, appointment_id, note_id, campaign_type, patient=patient
            )
            if error is not None:
                return [error]
            sms_content = rendered["sms_content"]
            email_content = rendered["email_content"]

        # Refuse to deliver a message that still carries template syntax. A
        # placeholder the renderer could not fill would otherwise reach the
        # patient verbatim as "{{telehealth_link}}". Only the channels actually
        # being sent are checked, so an unused template's typo cannot block a
        # send. Applies to client-supplied copy too, since an unlocked panel
        # posts the textarea contents straight through.
        _to_check = []
        if "sms" in channels:
            _to_check.append(sms_content)
        if "email" in channels:
            _to_check.append(email_content)
        _unresolved: list[str] = []
        for _body in _to_check:
            for _name in unresolved_placeholders(_body):
                if _name not in _unresolved:
                    _unresolved.append(_name)
        if _unresolved:
            log.error(
                "Refusing manual send for patient %s: unresolved placeholders %s",
                patient_id,
                ", ".join(_unresolved),
            )
            return [JSONResponse(
                {
                    "error": (
                        "Message still contains unfilled fields: "
                        + ", ".join("{{" + n + "}}" for n in _unresolved)
                        + ". Nothing was sent."
                    )
                },
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )]

        # Send from the patient's business-line number (same as the automated
        # reminder/confirmation paths) so the patient sees one consistent sender;
        # falls back to the global Twilio number when the line has no number.
        business_line = get_business_line_name(patient)
        # One read, used for both the business-line from-number and the
        # testing-mode gate inside delivery.
        config = load_config()
        effects, results = deliver_to_patient(
            patient,
            sms_content,
            email_content,
            channels,
            campaign_type,
            self.secrets,
            appointment_id or note_id,
            from_number=get_business_line_from_number(config, business_line),
            config=config,
        )

        # Skip appointment metadata effects for note-only sends
        if not appointment_id:
            effects = []

        log_key = appointment_id or note_id
        log_delivery(
            log_key, str(patient_id), campaign_type, results,
            sms_content=sms_content, email_content=email_content,
        )

        result_list = []
        for r in results:
            result_list.append({
                "channel": r.channel,
                "success": r.success,
                "error": r.error,
            })

        return effects + [JSONResponse({"results": result_list}, status_code=HTTPStatus.OK)]

    @api.get("/patient-view")
    def get_patient_view_page(self) -> list[Response | Effect]:
        """Serve the patient communication hub (Notifications)."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {THEME_STYLE_PLACEHOLDER}
    <title>Appointment Reminders</title>
    <style>
        * { box-sizing: border-box; }
        html, body { height: 100%; }
        body {
            font-family: var(--font-stack);
            margin: 0;
            padding: 0;
            background: var(--surface-page);
            color: var(--text-strong);
            /* Flex column: header rows take their natural height and the
               active tab panel fills the rest. This is what stops the chat
               from rendering behind the tab bar when the bar wraps on
               narrow screens. */
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Tab bar */
        .tab-bar {
            display: flex;
            background: #fff;
            border-bottom: 1.5px solid var(--border-default);
            padding: 0 8px;
            flex: 0 0 auto;
            z-index: 10;
        }
        .tab-btn {
            flex: 1;
            min-width: 0;
            height: 48px;
            padding: 14px 6px 0;
            background: none;
            border: none;
            border-bottom: 2px solid transparent;
            font-family: var(--font-stack);
            /* Sized + weighted to match Canvas EHR's chart/profile tabs:
               same #707070 text color in every state, with the active
               tab distinguished only by its bottom border. */
            font-size: 20px;
            font-weight: 600;
            color: #707070;
            cursor: pointer;
            transition: border-color 0.15s ease;
            text-align: center;
            line-height: normal;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        @media (max-width: 480px) {
            /* Step down one size before truncation kicks in. */
            .tab-btn { font-size: 16px; padding-top: 16px; }
        }
        .tab-btn.active {
            border-bottom-color: #707070;
        }

        /* Tab panels — the active one fills the remaining viewport. */
        .tab-panel {
            display: none;
            padding: 12px 8px;
        }
        .tab-panel.active {
            display: block;
            flex: 1 1 auto;
            min-height: 0;
            overflow-y: auto;
        }
        /* Flush panel hosts the chat, which manages its own internal
           scroll. Override .tab-panel.active overflow so we don't get a
           second scrollbar inside the chat. */
        .tab-panel.tab-panel-flush { padding: 0; }
        .tab-panel.tab-panel-flush.active {
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .container { max-width: 720px; margin: 0 auto; }

        /* Section cards */
        .card {
            background: #fff;
            border-radius: 14px;
            padding: 0;
            box-shadow: 0 1px 4px rgba(26,35,50,0.06), 0 0 0 1px rgba(26,35,50,0.04);
            margin-bottom: 12px;
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 20px;
            cursor: pointer;
            user-select: none;
            border-bottom: 1px solid var(--surface-hover);
        }
        .card-header h3 {
            margin: 0;
            font-size: 15px;
            font-weight: 600;
            color: var(--text-strong);
            letter-spacing: -0.01em;
        }
        .card-header .badge {
            font-size: 11px;
            font-weight: 500;
            color: var(--text-soft);
            background: var(--surface-hover);
            border-radius: 10px;
            padding: 2px 8px;
        }
        .chevron {
            font-size: 18px;
            color: var(--text-soft);
            transition: transform 0.2s ease;
        }
        .chevron.closed { transform: rotate(-90deg); }
        .card-body { padding: 18px 20px; }
        .card-body.collapsed { display: none; }

        /* Labels */
        .field-label {
            font-size: 12.5px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 5px;
        }

        /* Inputs */
        select, textarea {
            width: 100%;
            padding: 7px 10px;
            border: 1.5px solid var(--border-default);
            border-radius: 7px;
            font-family: var(--font-stack);
            font-size: 13.5px;
            color: var(--text-strong);
            background: var(--surface-page);
            outline: none;
            transition: border-color 0.15s;
        }
        select:focus, textarea:focus { border-color: var(--brand-primary); }
        textarea { resize: vertical; min-height: 60px; line-height: 1.5; }

        /* Form layout */
        .form-row {
            display: flex;
            gap: 10px;
            margin-bottom: 14px;
            align-items: flex-end;
        }
        .form-row .field { flex: 1; }

        /* Buttons */
        .btn {
            padding: 8px 24px;
            border: none;
            border-radius: 8px;
            font-family: var(--font-stack);
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .btn-primary {
            background: var(--brand-primary);
            color: #fff;
            box-shadow: 0 1px 3px rgba(74,111,165,0.3);
        }
        .btn-primary:hover { background: var(--brand-primary-hover); }
        .btn-primary:disabled { background: var(--text-soft); cursor: not-allowed; box-shadow: none; }
        .btn-secondary {
            background: #fff;
            color: var(--brand-primary);
            border: 1.5px solid var(--brand-primary);
        }
        .btn-secondary:hover { background: rgba(74,111,165,0.067); }
        .btn-secondary:disabled { color: var(--text-soft); border-color: var(--border-default); cursor: not-allowed; }

        /* Channel checkboxes */
        .channel-checks { display: flex; gap: 18px; margin-bottom: 14px; }
        .channel-check {
            display: flex;
            align-items: center;
            gap: 7px;
            font-size: 13px;
            cursor: pointer;
            user-select: none;
            color: var(--text-strong);
        }
        .channel-check input {
            width: 15px;
            height: 15px;
            margin: 0;
            cursor: pointer;
            accent-color: var(--brand-primary);
        }

        /* Send confirmation */
        .send-confirm {
            text-align: center;
            padding: 28px 20px;
        }
        .send-confirm-icon {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: rgba(90,143,107,0.09);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 12px;
            font-size: 22px;
        }
        .send-confirm h4 {
            margin: 0 0 4px;
            font-size: 16px;
            font-weight: 600;
            color: var(--text-strong);
        }
        .send-confirm p {
            margin: 0 0 16px;
            font-size: 13px;
            color: var(--text-muted);
        }
        .send-error {
            padding: 10px 14px;
            border-radius: 8px;
            background: var(--danger-bg);
            border: 1.5px solid var(--danger-bg);
            color: var(--danger-fg);
            font-size: 13px;
            margin-top: 10px;
        }

        /* History rows */
        .history-row {
            padding: 12px 14px;
            border-radius: 10px;
            border: 1.5px solid var(--border-default);
            background: var(--surface-page);
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .history-row:hover { border-color: var(--brand-primary); }
        .history-row-summary {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }
        .history-date {
            font-size: 12.5px;
            font-weight: 600;
            color: var(--text-muted);
            white-space: nowrap;
            flex-shrink: 0;
        }
        .history-campaign {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-strong);
            flex: 1;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .status-badge {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 10px;
            border-radius: 12px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }
        .status-delivered { background: rgba(90,143,107,0.09); color: var(--success-fg); }
        .status-failed { background: var(--danger-bg); color: var(--danger-fg); }
        .status-skipped { background: var(--warning-bg); color: var(--warning-fg); }
        .channel-badge {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 10px;
            white-space: nowrap;
            flex-shrink: 0;
        }
        .channel-sms { background: rgba(74,111,165,0.067); color: var(--brand-primary); }
        .channel-email { background: rgba(123,31,162,0.08); color: #7B1FA2; }
        .channel-delivered { background: rgba(90,143,107,0.12); color: var(--success-fg); }
        .channel-failed { background: rgba(192,57,43,0.10); color: var(--danger-fg); }
        .channel-skipped { background: rgba(212,133,15,0.10); color: var(--warning-fg); }

        /* History detail (expandable) */
        .history-detail {
            display: none;
            margin-top: 10px;
            padding: 10px 12px;
            background: var(--surface-hover);
            border-radius: 7px;
        }
        .history-detail.open { display: block; }
        .detail-channel {
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--surface-hover);
        }
        .detail-channel:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
        .detail-channel-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }
        .detail-recipient {
            font-size: 12px;
            color: var(--text-muted);
        }
        .detail-content {
            font-size: 12.5px;
            color: var(--text-strong);
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 160px;
            overflow-y: auto;
            background: #fff;
            border-radius: 6px;
            padding: 8px 10px;
            border: 1px solid var(--surface-hover);
        }

        .portal-status-bar {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 4px 14px;
            font-size: 12px;
            color: var(--text-muted);
            background: #fff;
            flex: 0 0 auto;
        }
        .portal-status-bar.hidden { display: none; }
        .portal-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-weight: 600;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 10px;
        }
        .portal-badge.registered { background: var(--success-bg); color: var(--success-fg); }
        .portal-badge.not-registered { background: var(--danger-bg); color: var(--danger-fg); }

        /* Placeholder state for upcoming tabs */
        .placeholder-state {
            text-align: center;
            padding: 48px 24px;
        }
        .placeholder-icon {
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: rgba(74,111,165,0.07);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 14px;
            font-size: 24px;
        }
        .placeholder-state h4 {
            margin: 0 0 6px;
            font-size: 15px;
            font-weight: 600;
            color: var(--text-strong);
        }
        .placeholder-state p {
            margin: 0;
            font-size: 13px;
            color: var(--text-soft);
            line-height: 1.5;
        }

        .empty-state {
            text-align: center;
            padding: 28px;
            color: var(--text-soft);
            font-size: 13px;
        }
        .hidden { display: none; }
    </style>
</head>
<body>

<div id="portal-status-bar" class="portal-status-bar hidden"></div>

<!-- Notifications (single panel; secure-messaging removed) -->
<div class="tab-panel active" id="tab-notifications">
    <div class="container">
        <!-- Send Message -->
        <div class="card">
            <div class="card-header" onclick="toggleSection('send')">
                <h3>Send Message</h3>
                <span class="chevron" id="send-chevron">&#9662;</span>
            </div>
            <div class="card-body" id="send-body">
                <div id="send-form">
                    <div style="background:rgba(74,111,165,0.06);border:1px solid rgba(74,111,165,0.15);border-radius:8px;padding:8px 12px;margin-bottom:14px;font-size:12.5px;color:var(--brand-primary);font-weight:500;">
                        Do not include PHI (Protected Health Information) in messages sent via SMS or email.
                    </div>
                    <div class="form-row">
                        <div class="field">
                            <div class="field-label">Appointment / Note</div>
                            <select id="appt-select" onchange="onApptChange()">
                                <option value="">Loading...</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="field">
                            <div class="field-label">Campaign Type</div>
                            <select id="campaign-select">
                                <option value="confirmation">Booking Acknowledgement</option>
                                <option value="reminder">Reminder</option>
                                <option value="telehealth">Telehealth Join</option>
                                <option value="noshow">No-Show</option>
                                <option value="cancellation">Cancellation</option>
                            </select>
                        </div>
                        <div class="field" style="flex:0 0 auto">
                            <div class="field-label">&nbsp;</div>
                            <button class="btn btn-secondary" id="preview-btn" onclick="previewMessage()">Preview</button>
                        </div>
                    </div>

                    <div id="preview-section" class="hidden">
                        <div style="margin-bottom:14px">
                            <div class="field-label">SMS Message</div>
                            <textarea id="sms-textarea" rows="3"></textarea>
                        </div>
                        <div style="margin-bottom:14px">
                            <div class="field-label">Email Message</div>
                            <textarea id="email-textarea" rows="4"></textarea>
                        </div>
                        <div class="field-label">Channels</div>
                        <div class="channel-checks">
                            <label class="channel-check">
                                <input type="checkbox" id="ch-sms" checked> SMS
                            </label>
                            <label class="channel-check">
                                <input type="checkbox" id="ch-email" checked> Email
                            </label>
                        </div>
                        <button class="btn btn-primary" id="send-btn" onclick="sendMessage()">Send Message</button>
                        <div id="send-error"></div>
                    </div>
                </div>
                <div id="send-confirm" class="send-confirm hidden">
                    <div class="send-confirm-icon">&#10003;</div>
                    <h4>Message Sent</h4>
                    <p id="send-confirm-detail"></p>
                    <button class="btn btn-secondary" onclick="resetSendForm()">Send Another</button>
                </div>
            </div>
        </div>

        <!-- Reminder History -->
        <div class="card">
            <div class="card-header" onclick="toggleSection('history')">
                <div style="display:flex;align-items:center;gap:8px">
                    <h3>Reminder History</h3>
                    <span class="badge" id="history-count" style="display:none"></span>
                </div>
                <span class="chevron" id="history-chevron">&#9662;</span>
            </div>
            <div class="card-body" id="history-body">
                <div id="history-content">
                    <div class="empty-state">Loading...</div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    const BASE = '/plugin-io/api/appointment_reminders';
    const urlParams = new URLSearchParams(window.location.search);
    const patientId = urlParams.get('patient_id');

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    function toggleSection(id) {
        const body = document.getElementById(id + '-body');
        const chev = document.getElementById(id + '-chevron');
        body.classList.toggle('collapsed');
        chev.classList.toggle('closed', body.classList.contains('collapsed'));
    }

    // --- Appointments + Notes ---
    let itemsData = [];

    async function loadAppointments() {
        const sel = document.getElementById('appt-select');
        if (!patientId) { sel.innerHTML = '<option value="">No patient</option>'; return; }
        try {
            const resp = await fetch(BASE + '/patient/' + patientId + '/appointments', {cache: 'no-store'});
            if (!resp.ok) { sel.innerHTML = '<option value="">Error loading</option>'; return; }
            itemsData = await resp.json();
            sel.innerHTML = '<option value="">Select appointment or note...</option>';
            if (itemsData.length === 0) {
                sel.innerHTML = '<option value="">No appointments or notes found</option>';
                return;
            }
            itemsData.forEach((a, idx) => {
                const dt = a.datetime ? new Date(a.datetime).toLocaleString([], {month:'short', day:'numeric', year:'numeric', hour:'numeric', minute:'2-digit'}) : '';
                const desc = a.description || a.note_type_name || '';
                const prov = a.provider_name ? ' \\u2013 ' + a.provider_name : '';
                const tag = a.type === 'note' ? '[Note] ' : '';
                const opt = document.createElement('option');
                opt.value = String(idx);
                opt.textContent = tag + dt + (desc ? ' (' + desc + ')' : '') + prov;
                sel.appendChild(opt);
            });
        } catch (e) {
            sel.innerHTML = '<option value="">Error loading</option>';
        }
    }

    function getSelectedItem() {
        const idx = parseInt(document.getElementById('appt-select').value, 10);
        if (isNaN(idx) || idx < 0 || idx >= itemsData.length) return null;
        return itemsData[idx];
    }

    // Every option here must be backed by a stored template. The free-text
    // "Custom" campaign was removed from the product, and the send endpoint
    // rejects it while copy is locked, so offering it only produced a dead
    // dropdown entry.
    const APPT_CAMPAIGNS = [
        {value: 'confirmation', label: 'Confirmation'},
        {value: 'reminder', label: 'Reminder'},
        {value: 'telehealth', label: 'Telehealth Join'},
        {value: 'noshow', label: 'No-Show'},
        {value: 'cancellation', label: 'Cancellation'},
    ];
    const NOTE_CAMPAIGNS = [
        {value: 'telehealth', label: 'Telehealth Join'},
    ];

    function onApptChange() {
        document.getElementById('preview-section').classList.add('hidden');
        document.getElementById('send-error').innerHTML = '';

        const item = getSelectedItem();
        const sel = document.getElementById('campaign-select');
        const prev = sel.value;
        const opts = (item && item.type === 'note') ? NOTE_CAMPAIGNS : APPT_CAMPAIGNS;
        sel.innerHTML = '';
        opts.forEach(o => {
            const opt = document.createElement('option');
            opt.value = o.value;
            opt.textContent = o.label;
            sel.appendChild(opt);
        });
        // Restore previous selection if still available
        if (opts.some(o => o.value === prev)) sel.value = prev;
    }

    // --- Preview ---
    async function previewMessage() {
        const item = getSelectedItem();
        const campaign = document.getElementById('campaign-select').value;
        if (!item) { alert('Please select an appointment or note'); return; }

        const btn = document.getElementById('preview-btn');
        btn.disabled = true; btn.textContent = 'Loading...';
        try {
            const resp = await fetch(BASE + '/patient/' + patientId + '/preview', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    appointment_id: item.appointment_id || '',
                    note_id: item.note_id || '',
                    campaign_type: campaign,
                }),
            });
            const data = await resp.json();
            if (data.error) { alert(data.error); return; }

            document.getElementById('sms-textarea').value = data.sms_content || '';
            document.getElementById('email-textarea').value = data.email_content || '';
            const hasSms = (data.channels || []).includes('sms');
            const hasEmail = (data.channels || []).includes('email');
            document.getElementById('ch-sms').checked = hasSms;
            document.getElementById('ch-email').checked = hasEmail;
            document.getElementById('preview-section').classList.remove('hidden');
            document.getElementById('send-error').innerHTML = '';
        } catch (e) {
            alert('Preview failed: ' + e.message);
        } finally {
            btn.disabled = false; btn.textContent = 'Preview';
        }
    }

    // --- Send ---
    async function sendMessage() {
        const item = getSelectedItem();
        const campaign = document.getElementById('campaign-select').value;
        const sms = document.getElementById('sms-textarea').value;
        const email = document.getElementById('email-textarea').value;
        const channels = [];
        if (document.getElementById('ch-sms').checked) channels.push('sms');
        if (document.getElementById('ch-email').checked) channels.push('email');
        if (channels.length === 0) { alert('Select at least one channel'); return; }

        const btn = document.getElementById('send-btn');
        btn.disabled = true; btn.textContent = 'Sending...';
        document.getElementById('send-error').innerHTML = '';

        try {
            const resp = await fetch(BASE + '/patient/' + patientId + '/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    appointment_id: item ? item.appointment_id || '' : '',
                    note_id: item ? item.note_id || '' : '',
                    campaign_type: campaign,
                    sms_content: sms,
                    email_content: email,
                    channels: channels,
                }),
            });
            const data = await resp.json();

            if (data.error) {
                document.getElementById('send-error').innerHTML = '<div class="send-error">' + escapeHtml(data.error) + '</div>';
                return;
            }

            const results = data.results || [];
            const succeeded = results.filter(r => r.success);
            const failed = results.filter(r => !r.success && !r.error?.startsWith('skipped:'));

            if (failed.length > 0 && succeeded.length === 0) {
                // All channels failed — show error but keep form usable
                const msgs = failed.map(r => r.channel.toUpperCase() + ': ' + (r.error || 'failed'));
                document.getElementById('send-error').innerHTML = '<div class="send-error">' + escapeHtml(msgs.join('; ')) + '</div>';
                loadHistory();
                return;
            }

            if (failed.length > 0) {
                // Partial failure — some succeeded, some failed
                const failMsgs = failed.map(r => r.channel.toUpperCase() + ': ' + (r.error || 'failed'));
                const okChs = succeeded.map(r => r.channel.toUpperCase()).join(' & ');
                document.getElementById('send-error').innerHTML =
                    '<div style="background:rgba(243,156,18,0.08);border:1px solid rgba(243,156,18,0.2);border-radius:8px;padding:8px 12px;margin-top:8px;font-size:12.5px;color:var(--warning-fg);">' +
                    'Sent via ' + escapeHtml(okChs) + ', but ' + escapeHtml(failMsgs.join('; ')) +
                    '</div>';
            }

            // Show confirmation
            const sentChs = succeeded.length > 0 ? succeeded.map(r => r.channel.toUpperCase()).join(' & ') : channels.map(c => c.toUpperCase()).join(' & ');
            document.getElementById('send-confirm-detail').textContent = campaign.charAt(0).toUpperCase() + campaign.slice(1) + ' sent via ' + sentChs;
            document.getElementById('send-form').classList.add('hidden');
            document.getElementById('send-confirm').classList.remove('hidden');
            loadHistory();
        } catch (e) {
            document.getElementById('send-error').innerHTML = '<div class="send-error">Send failed: ' + escapeHtml(e.message) + '</div>';
        } finally {
            btn.disabled = false; btn.textContent = 'Send Message';
        }
    }

    function resetSendForm() {
        document.getElementById('send-form').classList.remove('hidden');
        document.getElementById('send-confirm').classList.add('hidden');
        document.getElementById('preview-section').classList.add('hidden');
        document.getElementById('send-error').innerHTML = '';
        document.getElementById('appt-select').value = '';
    }

    // --- History ---
    async function loadHistory() {
        if (!patientId) return;
        try {
            const resp = await fetch(BASE + '/patient/' + patientId + '/history', {cache: 'no-store'});
            const entries = await resp.json();

            if (entries.length === 0) {
                document.getElementById('history-content').innerHTML = '<div class="empty-state">No notifications sent yet</div>';
                document.getElementById('history-count').style.display = 'none';
                return;
            }

            // Group entries by timestamp + campaign_type
            const groups = [];
            const groupMap = {};
            entries.forEach(e => {
                const key = e.timestamp + '|' + e.campaign_type;
                if (!groupMap[key]) {
                    groupMap[key] = { timestamp: e.timestamp, campaign_type: e.campaign_type, channels: [] };
                    groups.push(groupMap[key]);
                }
                groupMap[key].channels.push(e);
            });

            const countEl = document.getElementById('history-count');
            countEl.textContent = groups.length;
            countEl.style.display = 'inline';

            let html = '';
            groups.forEach((g, gi) => {
                const date = new Date(g.timestamp).toLocaleString([], {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
                const campaign = g.campaign_type || '';
                const campaignLabel = campaign.charAt(0).toUpperCase() + campaign.slice(1);

                // Channel badges color-coded by individual delivery status
                const badges = g.channels.map(c => {
                    let colorCls = 'channel-' + c.channel;
                    if (c.status === 'delivered') colorCls = 'channel-delivered';
                    else if (c.status === 'failed' && !c.error?.startsWith('skipped:')) colorCls = 'channel-failed';
                    else if (c.status !== 'delivered') colorCls = 'channel-skipped';
                    return '<span class="channel-badge ' + colorCls + '">' + c.channel.toUpperCase() + '</span>';
                }).join(' ');

                html += '<div class="history-row" onclick="toggleDetail(' + gi + ')">';
                html += '<div class="history-row-summary">';
                html += '<span class="history-date">' + escapeHtml(date) + '</span>';
                html += '<span class="history-campaign">' + escapeHtml(campaignLabel) + '</span>';
                html += badges;
                html += '</div>';

                // Detail panel
                html += '<div class="history-detail" id="detail-' + gi + '">';
                g.channels.forEach(c => {
                    const chLabel = c.channel === 'sms' ? 'SMS' : 'Email';
                    const recipient = c.recipient || '';
                    const content = c.content || '';
                    const stClass = 'status-badge status-' + c.status;

                    html += '<div class="detail-channel">';
                    html += '<div class="detail-channel-header">';
                    html += '<span class="channel-badge channel-' + c.channel + '">' + chLabel + '</span>';
                    html += '<span class="' + stClass + '">' + c.status + '</span>';
                    if (recipient) html += '<span class="detail-recipient">' + escapeHtml(recipient) + '</span>';
                    html += '</div>';
                    if (content) html += '<div class="detail-content">' + escapeHtml(content) + '</div>';
                    if (c.error && !c.error.startsWith('skipped:')) {
                        var errText = c.error;
                        // Truncate long raw HTTP errors to just the friendly part
                        if (errText.length > 120) errText = errText.substring(0, 120) + '...';
                        html += '<div style="font-size:12px;color:var(--danger-fg);margin-top:4px">' + escapeHtml(errText) + '</div>';
                    }
                    html += '</div>';
                });
                html += '</div>';
                html += '</div>';
            });
            document.getElementById('history-content').innerHTML = html;
        } catch (err) {
            document.getElementById('history-content').innerHTML = '<div class="empty-state">Error: ' + escapeHtml(err.message) + '</div>';
        }
    }

    function toggleDetail(gi) {
        document.getElementById('detail-' + gi).classList.toggle('open');
    }

    // Init
    if (!patientId) {
        document.body.innerHTML = '<div class="empty-state" style="padding-top:40px">No patient ID provided</div>';
    } else {
        // Load notifications immediately
        loadAppointments();
        loadHistory();
    }
</script>
</body>
</html>
        """
        html = html.replace("{THEME_STYLE_PLACEHOLDER}", theme_style_block())

        # Apply the copy lock while building the page rather than from a fetch
        # after load: the markup then arrives already correct, with no window in
        # which Custom is selectable. The send endpoint enforces this regardless.
        if templates_locked(self.secrets):
            _hint = "Message copy is locked by the LOCK_MESSAGE_TEMPLATES setting."
            html = html.replace(
                '<textarea id="sms-textarea" rows="3"></textarea>',
                f'<textarea id="sms-textarea" rows="3" readonly title="{_hint}"></textarea>',
            )
            html = html.replace(
                '<textarea id="email-textarea" rows="4"></textarea>',
                f'<textarea id="email-textarea" rows="4" readonly title="{_hint}"></textarea>',
            )
        return [HTMLResponse(html)]
