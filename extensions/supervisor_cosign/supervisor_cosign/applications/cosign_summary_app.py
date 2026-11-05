from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Busts the browser cache on the page shell so a deploy is visible without a
# hard refresh; the CSS and JS are fetched by the shell and inherit it.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class CoSignSummaryApp(Application):
    """Provider-menu entry for the co-sign summary page.

    Every staff member sees this item: a ``provider_menu_item`` application has
    no ``visible()`` hook, so the label cannot be hidden per viewer. Access is
    decided by the page itself - supervisors and oversight staff get the table,
    everyone else gets a neutral placeholder, and the JSON routes behind it
    return 403.
    """

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/supervisor_cosign/summary/view?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
