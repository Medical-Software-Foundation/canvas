"""
Chart Collision Detector Application

An application that monitors patient chart navigation and warns users
when another provider is already viewing the same patient's chart.
"""

import json

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.templates import render_to_string
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.v1.data.staff import Staff
from logger import log


class ChartCollisionApp(Application):
    """
    Application that detects when multiple users view the same patient chart.

    Tracks all viewers in a list and shows a warning modal when a collision
    is detected (other users are viewing the same patient's chart).
    """

    DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes

    def on_open(self) -> Effect | list[Effect] | None:
        """
        Called when the application is opened from the app drawer.

        Checks for collision and only shows warning modal if another user
        is viewing the same patient chart.
        """
        return self._check_collision_and_warn()

    def on_context_change(self) -> Effect | list[Effect] | None:
        """
        Called when the user navigates to a different page.

        Checks for collision and only shows warning modal if another user
        is viewing the same patient chart.
        """
        return self._check_collision_and_warn()

    def _check_collision_and_warn(self) -> Effect | None:
        """
        Check for chart collision and return warning modal if detected.

        Maintains a list of staff IDs viewing each patient chart.

        Returns:
            Warning modal effect if collision detected, None otherwise.
        """
        log.info(
            f"ChartCollisionApp: Checking for collision with event {self.event}"
        )

        context = self.event.context if self.event else {}

        # Extract patient and user from context
        patient_id = context.get("patient", {}).get("id")
        staff_id = context.get("user", {}).get("id")
        if not staff_id or not patient_id:
            return None

        # Check cache for existing viewers (stored as JSON list)
        cache = get_cache()
        cache_key = f"chart_viewers:{patient_id}"
        cached_value = cache.get(cache_key)

        # Parse existing viewers list or start with empty list
        if cached_value:
            try:
                current_viewers: list[str] = json.loads(cached_value)
            except (json.JSONDecodeError, TypeError):
                log.warning(
                    f"ChartCollisionApp: Invalid cache value for {cache_key}, resetting"
                )
                current_viewers = []
        else:
            current_viewers = []

        # Check for other viewers (excluding current staff)
        other_viewers = [v for v in current_viewers if v != staff_id]

        # Add current staff to viewers list if not already present
        if staff_id not in current_viewers:
            current_viewers.append(staff_id)

        timeout_seconds = int(self.secrets.get("CACHE_TTL_SECONDS") or self.DEFAULT_CACHE_TTL_SECONDS)
        # Save updated viewers list to cache
        cache.set(
            cache_key,
            json.dumps(current_viewers),
            timeout_seconds=timeout_seconds,
        )

        log.info(
            f"ChartCollisionApp: Patient {patient_id} viewers: {current_viewers}"
        )

        # Show warning if there are other viewers
        if other_viewers:
            log.info(
                f"ChartCollisionApp: Collision detected - "
                f"staff {staff_id} viewing patient {patient_id}, "
                f"other viewers: {other_viewers}"
            )
            other_viewer_names = Staff.objects.filter(id__in=other_viewers).values_list("first_name", "last_name")
            viewers = [f"{name[0]} {name[1]}" for name in other_viewer_names]
            return self._create_warning_modal(viewers)

        return None

    def _create_warning_modal(self, viewers: list[str]) -> Effect:
        """Create a warning modal effect for chart collision."""

        return LaunchModalEffect(
            content=render_to_string("templates/warning_modal.html", {"viewers": viewers}),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Chart Collision Detected",
        ).apply()
