from canvas_sdk.effects import Effect
from canvas_sdk.effects.provider_menu_configuration import ProviderMenuConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.staff import Staff

from hide_settings.models.config import SettingsAccessConfig

Items = ProviderMenuConfiguration.Items

# Every native menu item the SDK knows about except Settings. Built from the enum so items
# added to the SDK later stay visible.
ITEMS_WITHOUT_SETTINGS = [item for item in Items if item is not Items.SETTINGS]


class HideSettingsForUnlistedRoles(BaseHandler):
    """Hide the Settings menu item from staff who hold none of the allowed roles.

    Until an administrator saves a configuration with at least one allowed role, the
    menu is left alone for everyone.
    """

    RESPONDS_TO = EventType.Name(EventType.GET_PROVIDER_MENU_CONFIGURATION)

    def compute(self) -> list[Effect]:
        """Return a menu without Settings when the user holds no allowed role."""
        config = SettingsAccessConfig.objects.first()
        allowed_codes = set(config.allowed_role_codes or []) if config else set()
        if not allowed_codes:
            return []

        user = self.event.context.get("user") or {}
        if user.get("type") != "Staff" or not user.get("id"):
            return []

        try:
            staff = Staff.objects.get(id=user["id"])
        except Staff.DoesNotExist:
            return []

        user_role_codes = set(staff.roles.values_list("internal_code", flat=True))
        if user_role_codes & allowed_codes:
            return []

        return [ProviderMenuConfiguration(items=ITEMS_WITHOUT_SETTINGS).apply()]
