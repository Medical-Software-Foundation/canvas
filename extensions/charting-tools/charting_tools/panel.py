"""The in-command panel: its URLs, its HTML, and the charted diagnosis it reads."""

from typing import Any

from canvas_sdk.templates import render_to_string

from charting_tools.kinds import ORDER_SET, QUICKPICK
from charting_tools.models.note_template import NoteTemplate

PLUGIN_NAME = "charting_tools"
PANEL_PREFIX = "/panel"

_ICD10_KEYS = ("icd10_code", "icd_10_code", "icd10", "icd-10", "icd_10")


def charted_code_cache_key(command_uuid: str) -> str:
    """Cache key holding the ICD-10 charted on an Assess/Diagnose command."""
    return f"charting_tools_icd10:{command_uuid}"


def panel_written_cache_key(command_uuid: str) -> str:
    """Cache key marking a command that already has the panel attached."""
    return f"charting_tools_panel:{command_uuid}"


def _icd10_system(system: Any) -> bool:
    text = str(system or "").lower()
    return "icd" in text and "10" in text


def find_icd10(node: Any) -> str | None:
    """Find an ICD-10 code anywhere in a command's fields: an icd10 key, or an ICD-10 coding."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _ICD10_KEYS and isinstance(value, str) and value.strip():
                return value.strip()
        if _icd10_system(node.get("system")):
            code = node.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()
        for value in node.values():
            found = find_icd10(value)
            if found:
                return found
    elif isinstance(node, list | tuple):
        for item in node:
            found = find_icd10(item)
            if found:
                return found
    return None


def panel_url(base_url: str, route: str) -> str:
    """Absolute URL of a panel route, for the sandboxed command frame to call."""
    return f"{base_url}/plugin-io/api/{PLUGIN_NAME}{PANEL_PREFIX}{route}"


def panel_kinds() -> list[str]:
    """The panel tabs that have something in them: quickpicks, order sets, both, or neither."""
    present = set(
        NoteTemplate.objects.filter(active=True, show_in_panel=True, kind__in=(QUICKPICK, ORDER_SET))
        .values_list("kind", flat=True)
        .distinct()
    )
    return [kind for kind in (QUICKPICK, ORDER_SET) if kind in present]


def build_panel_html(base_url: str, token: str, kinds: list[str]) -> str:
    """Render the panel with its routes and token wired in, and a tab for each of ``kinds``.

    The quick-add buttons always show, so the panel has something to offer even
    with no quickpicks or order sets.
    """
    return str(
        render_to_string(
            "templates/command_panel.html",
            {
                "catalog_url": panel_url(base_url, "/catalog"),
                "apply_url": panel_url(base_url, "/apply"),
                "quick_add_url": panel_url(base_url, "/quick-add"),
                "token": token,
                "show_quickpicks": QUICKPICK in kinds,
                "show_order_sets": ORDER_SET in kinds,
            },
        )
    )
