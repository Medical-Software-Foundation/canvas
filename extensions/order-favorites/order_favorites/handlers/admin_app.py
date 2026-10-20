from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import PanelApplication

from order_favorites.services.access import staff_dbid


class OrderFavoritesApp(PanelApplication):
    """App drawer icon for Order Favorites.

    Every active staff member sees it and gets "My favorites", to manage their own favorites without
    opening a note. Favorites admins also get the practice favorites and Settings tabs; the page and
    every admin route check admin status themselves. Needs a Canvas release with per-user app drawer
    icons (1.364 or later).
    """

    NAME = "Order Favorites"
    # Kept from when only admins saw this icon, so an installed drawer entry isn't duplicated.
    IDENTIFIER = "order_favorites__admin"
    ICON_URL = "/plugin-io/api/order_favorites/icon.svg"

    def _staff_id(self) -> str | None:
        user = self.event.context.get("user") or {}
        return user.get("id") if user.get("type") == "Staff" else None

    def visible(self) -> bool:
        return staff_dbid(self._staff_id()) is not None

    def on_open(self) -> Effect | list[Effect]:
        return LaunchModalEffect(
            url="/plugin-io/api/order_favorites/admin/",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Order Favorites",
        ).apply()
