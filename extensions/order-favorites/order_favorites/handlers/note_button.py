from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from order_favorites.services.notes import eligible_note_by_dbid

API_BASE = "/plugin-io/api/order_favorites"
# Changes on every install, so Canvas never shows a panel page cached from an older version.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))


class OrderFavoritesButton(ActionButton):
    """Note-header button that opens the favorites panel for that note.

    Shown only on open visit and chart review notes. Canvas sends the clicked note's id with the
    click, so orders always go into the note whose button was used.
    """

    BUTTON_TITLE = "Order Favorites"
    BUTTON_KEY = "ORDER_FAVORITES_PANEL"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        return eligible_note_by_dbid(self.context.get("note_id")) is not None

    def handle(self) -> list[Effect]:
        note = eligible_note_by_dbid(self.context.get("note_id"))
        if note is None:
            return []
        return [
            LaunchModalEffect(
                url=f"{API_BASE}/panel/?{urlencode({'note_id': str(note.id), 'v': _CACHE_BUST})}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Order Favorites",
            ).apply()
        ]
