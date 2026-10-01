"""Each staff member's saved dashboard settings (search, filters, sort, collapsed sections)."""

from typing import Any

from failed_fax_dashboard.models import DashboardPreference, StaffProxy

TABS = ("sent", "received")
SORT_KEYS = {
    "sent": ("patient", "item", "problem", "recipient", "sender", "when", "pages", "attempts"),
    "received": ("recipient", "problem", "pages", "when", "task"),
}
MAX_TEXT = 200
MAX_LIST = 200


def default_tab_view(tab: str) -> dict[str, Any]:
    """The settings a tab starts with, and returns to on Reset view."""
    view: dict[str, Any] = {
        "q": "",
        "people": [],
        "sort": {"key": "when", "dir": -1},
        "collapsed": {"mine": False, "rest": False},
    }
    if tab == "sent":
        view["kinds"] = []
    return view


def _strings(raw: Any) -> list[str]:
    """A bounded list of strings from untrusted input."""
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)][:MAX_LIST]


def clean_tab_view(tab: str, raw: Any) -> dict[str, Any]:
    """Keep only known settings of the right type, filling the rest with defaults."""
    view = default_tab_view(tab)
    if not isinstance(raw, dict):
        return view
    if isinstance(raw.get("q"), str):
        view["q"] = raw["q"][:MAX_TEXT]
    view["people"] = _strings(raw.get("people"))
    if tab == "sent":
        view["kinds"] = _strings(raw.get("kinds"))
    sort = raw.get("sort")
    if isinstance(sort, dict) and sort.get("key") in SORT_KEYS[tab] and sort.get("dir") in (1, -1):
        view["sort"] = {"key": sort["key"], "dir": sort["dir"]}
    collapsed = raw.get("collapsed")
    if isinstance(collapsed, dict):
        view["collapsed"] = {
            "mine": collapsed.get("mine") is True,
            "rest": collapsed.get("rest") is True,
        }
    return view


def clean_views(raw: Any) -> dict[str, dict[str, Any]]:
    """Settings for both tabs, cleaned."""
    source = raw if isinstance(raw, dict) else {}
    return {tab: clean_tab_view(tab, source.get(tab)) for tab in TABS}


def load_views(staff_id: str) -> dict[str, dict[str, Any]]:
    """The staff member's saved settings for both tabs (defaults when nothing is saved)."""
    saved = DashboardPreference.objects.filter(staff__id=staff_id).first()
    return clean_views(saved.settings if saved is not None else {})


def save_views(staff_id: str, raw: Any) -> bool:
    """Save the staff member's settings. False when the staff member does not exist."""
    staff = StaffProxy.objects.filter(id=staff_id).first()
    if staff is None:
        return False
    DashboardPreference.objects.update_or_create(
        staff=staff, defaults={"settings": clean_views(raw)}
    )
    return True


def reset_views(staff_id: str) -> None:
    """Clear the staff member's saved settings."""
    DashboardPreference.objects.filter(staff__id=staff_id).delete()
