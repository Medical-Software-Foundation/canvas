"""
Chart Collision Detector Application

An application that monitors patient chart navigation and warns users
when another provider is already viewing the same patient's chart.
"""

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log


class ChartCollisionApp(Application):
    """
    Application that detects when multiple users view the same patient chart.

    When the user navigates to a patient chart:
    - If no one is viewing: cache current user, no warning
    - If same user refreshes: refresh cache TTL, no warning
    - If different user loads: show warning modal
    """

    CACHE_TTL_SECONDS = 300  # 5 minutes

    def on_open(self) -> Effect | list[Effect]:
        """Called when the application is opened from the app drawer."""
        return LaunchModalEffect(
            content=self._get_app_html(),
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Chart Monitor",
        ).apply()

    def on_context_change(self) -> Effect | list[Effect] | None:
        """
        Called when the user navigates to a different page.

        Checks if navigating to a patient chart and handles collision detection.
        """
        context = self.event.context if self.event else {}
        current_url = context.get("url", "")

        # Check if we're on a patient chart page
        # Patient chart URLs typically contain /patient/ in the path
        if "/patient/" not in current_url:
            return None

        # Extract patient context
        patient_data = context.get("patient")
        if not patient_data:
            return None

        patient_id = patient_data.get("id")
        if not patient_id:
            return None

        # Get current user from context
        user_data = context.get("user")
        staff_id = user_data.get("staff") if user_data else None

        if not staff_id:
            log.warning(
                f"ChartCollisionApp: Missing staff_id for patient {patient_id}"
            )
            return None

        # Check cache for existing viewer
        cache = get_cache()
        cache_key = f"chart_viewer:{patient_id}"
        current_viewer = cache.get(cache_key)

        if current_viewer is None:
            # No one viewing - register this user
            cache.set(cache_key, staff_id, timeout_seconds=self.CACHE_TTL_SECONDS)
            log.info(
                f"ChartCollisionApp: Staff {staff_id} now viewing patient {patient_id}"
            )
            return None

        if current_viewer == staff_id:
            # Same user - refresh TTL
            cache.set(cache_key, staff_id, timeout_seconds=self.CACHE_TTL_SECONDS)
            return None

        # Different user is viewing - show warning
        log.info(
            f"ChartCollisionApp: Collision detected - "
            f"staff {staff_id} viewing patient {patient_id} "
            f"already being viewed by {current_viewer}"
        )
        return self._create_warning_modal()

    def _create_warning_modal(self) -> Effect:
        """Create a warning modal effect for chart collision."""
        warning_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 20px;
                    text-align: center;
                    background: #fffbeb;
                }
                .warning-container {
                    padding: 20px;
                    max-width: 400px;
                    margin: 0 auto;
                }
                .warning-icon {
                    font-size: 48px;
                    margin-bottom: 16px;
                }
                h3 {
                    color: #d97706;
                    margin: 0 0 16px 0;
                    font-size: 20px;
                }
                p {
                    color: #374151;
                    margin: 0 0 12px 0;
                    line-height: 1.5;
                }
            </style>
        </head>
        <body>
            <div class="warning-container">
                <div class="warning-icon">&#9888;</div>
                <h3>Chart In Use</h3>
                <p>Another user is currently viewing this patient's chart.</p>
                <p>Please be aware that concurrent editing may cause conflicts.</p>
            </div>
        </body>
        </html>
        """
        return LaunchModalEffect(
            content=warning_html,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Chart Warning",
        ).apply()

    def _get_app_html(self) -> str:
        """Get the HTML content for the application panel."""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: #f9fafb;
                }
                .container {
                    max-width: 400px;
                    margin: 0 auto;
                    text-align: center;
                }
                .icon {
                    font-size: 48px;
                    margin-bottom: 16px;
                }
                h2 {
                    color: #111827;
                    margin: 0 0 12px 0;
                    font-size: 20px;
                }
                p {
                    color: #6b7280;
                    margin: 0 0 8px 0;
                    line-height: 1.5;
                    font-size: 14px;
                }
                .status {
                    margin-top: 20px;
                    padding: 12px;
                    background: #ecfdf5;
                    border-radius: 8px;
                    color: #065f46;
                    font-size: 14px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon">&#128274;</div>
                <h2>Chart Collision Monitor</h2>
                <p>This application monitors patient chart access and warns you
                   when another provider is currently viewing the same chart.</p>
                <p>Keep this panel open while you work to receive collision alerts.</p>
                <div class="status">
                    &#10003; Monitoring active
                </div>
            </div>
        </body>
        </html>
        """
