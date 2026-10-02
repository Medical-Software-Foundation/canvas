"""Base module class for AWV workflow sections."""

from __future__ import annotations

from abc import ABC, abstractmethod
from html import escape as html_escape
from typing import Any


class AWVType:
    """Constants for AWV visit types."""

    INITIAL = "initial"
    SUBSEQUENT = "subsequent"
    BOTH = "both"


class BaseModule(ABC):
    """
    Abstract base class for all AWV workflow section modules.

    Each module represents one accordion section of the guided AWV workflow.
    Modules control their own visibility based on AWV type, and render their
    own HTML content via the render() method.
    """

    # Display order within the accordion (lower = earlier)
    ORDER: int = 0

    # Human-readable section title
    TITLE: str = ""

    # Which AWV visit types show this module. Use AWVType constants.
    AWV_TYPES: str = AWVType.BOTH

    # Icon name (Font Awesome class or similar) for the section header
    ICON: str = "fa-clipboard"

    def __init__(self, note_id: str, patient_id: str, awv_type: str) -> None:
        """
        Initialize the module.

        Args:
            note_id: UUID of the current note
            patient_id: UUID of the patient
            awv_type: One of AWVType.INITIAL or AWVType.SUBSEQUENT
        """
        self.note_id = note_id
        self.patient_id = patient_id
        self.awv_type = awv_type

    def is_visible(self) -> bool:
        """Return True if this module should be shown for the current AWV type."""
        if self.AWV_TYPES == AWVType.BOTH:
            return True
        return self.awv_type == self.AWV_TYPES

    @abstractmethod
    def get_context(self) -> dict[str, Any]:
        """
        Return context data for rendering this module's section.

        Subclasses should query Canvas ORM here to build the context dict
        that will be passed to the HTML template for this section.
        """
        ...

    def render(self) -> dict[str, Any]:
        """
        Return full section descriptor for template rendering.

        Returns a dict with:
            - section_id: CSS-safe section identifier
            - title: Display title
            - icon: Icon class
            - order: Sort order
            - awv_type: Current visit type
            - context: Section-specific data from get_context()
        """
        return {
            "section_id": self.__class__.__name__.lower().replace("module", ""),
            "title": self.TITLE,
            "icon": self.ICON,
            "order": self.ORDER,
            "awv_type": self.awv_type,
            "context": self.get_context(),
        }

    # ------------------------------------------------------------------
    # HTML rendering helpers (vida pattern)
    # ------------------------------------------------------------------

    def render_content_html(self) -> str:
        """Render module content as form HTML. Override in subclasses."""
        return '<p style="color:#999;">No content template defined.</p>'

    # --- form element helpers ---

    # Defense-in-depth: every interpolated caller-supplied string flows
    # through ``html_escape`` so a chart-derived value (medication name,
    # condition coding display, etc.) containing ``<``/``&``/``"`` can't
    # break the surrounding markup or open an injection vector. Callers
    # used to pass values raw; this matches the v0.14.6 pharmacy fix and
    # v0.14.7 exception-escape pattern.

    def _text_input(
        self, name: str, label: str, placeholder: str = "", value: str = "",
        required: bool = False,
    ) -> str:
        req_star = ' <span class="awv-required">*</span>' if required else ""
        req_attr = ' data-required="true"' if required else ""
        return (
            f'<div class="awv-field">'
            f'<label class="awv-label">{html_escape(label)}{req_star}</label>'
            f'<input type="text" name="{html_escape(name)}" value="{html_escape(value)}" '
            f'placeholder="{html_escape(placeholder)}" class="awv-input"{req_attr}>'
            f'</div>'
        )

    def _number_input(
        self, name: str, label: str, min_val: str = "", max_val: str = "",
        step: str = "", value: str = "", readonly: bool = False,
        required: bool = False,
    ) -> str:
        req_star = ' <span class="awv-required">*</span>' if required else ""
        req_attr = ' data-required="true"' if required else ""
        attrs = ""
        if min_val:
            attrs += f' min="{html_escape(min_val)}"'
        if max_val:
            attrs += f' max="{html_escape(max_val)}"'
        if step:
            attrs += f' step="{html_escape(step)}"'
        if readonly:
            attrs += " readonly"
        return (
            f'<div class="awv-field">'
            f'<label class="awv-label">{html_escape(label)}{req_star}</label>'
            f'<input type="number" name="{html_escape(name)}" value="{html_escape(value)}"{attrs} class="awv-input"{req_attr}>'
            f'</div>'
        )

    def _textarea(
        self, name: str, label: str, placeholder: str = "", value: str = "",
        rows: int = 3, required: bool = False,
    ) -> str:
        req_star = ' <span class="awv-required">*</span>' if required else ""
        req_attr = ' data-required="true"' if required else ""
        return (
            f'<div class="awv-field">'
            f'<label class="awv-label">{html_escape(label)}{req_star}</label>'
            f'<textarea name="{html_escape(name)}" rows="{rows}" placeholder="{html_escape(placeholder)}" '
            f'class="awv-textarea"{req_attr}>{html_escape(value)}</textarea>'
            f'</div>'
        )

    def _radio_group(self, name: str, label: str, options: list, required: bool = False) -> str:
        req_star = ' <span class="awv-required">*</span>' if required else ""
        req_attr = ' data-required="true"' if required else ""
        opts = ""
        for opt in options:
            if isinstance(opt, dict):
                val = opt.get("value", opt.get("label", ""))
                lbl = opt.get("label", str(opt))
            else:
                val = str(opt)
                lbl = str(opt)
            opts += (
                f'<label class="awv-radio">'
                f'<input type="radio" name="{html_escape(name)}" value="{html_escape(str(val))}"> {html_escape(str(lbl))}'
                f'</label>'
            )
        return (
            f'<div class="awv-field">'
            f'<label class="awv-label">{html_escape(label)}{req_star}</label>'
            f'<div class="awv-radio-group"{req_attr}>{opts}</div>'
            f'</div>'
        )

    def _select(self, name: str, label: str, options: list, required: bool = False) -> str:
        req_star = ' <span class="awv-required">*</span>' if required else ""
        req_attr = ' data-required="true"' if required else ""
        opts = '<option value="">-- Select --</option>'
        for opt in options:
            if isinstance(opt, dict):
                val = opt.get("value", "")
                lbl = opt.get("label", str(opt))
            elif isinstance(opt, (list, tuple)):
                val, lbl = opt[0], opt[1]
            else:
                val = lbl = str(opt)
            opts += f'<option value="{html_escape(str(val))}">{html_escape(str(lbl))}</option>'
        return (
            f'<div class="awv-field">'
            f'<label class="awv-label">{html_escape(label)}{req_star}</label>'
            f'<select name="{html_escape(name)}" class="awv-select"{req_attr}>{opts}</select>'
            f'</div>'
        )

    def _checkbox_group(self, name: str, label: str, options: list, required: bool = False) -> str:
        req_star = ' <span class="awv-required">*</span>' if required else ""
        req_attr = ' data-required="true"' if required else ""
        opts = ""
        for opt in options:
            val = str(opt)
            opts += (
                f'<label class="awv-checkbox">'
                f'<input type="checkbox" name="{html_escape(name)}" value="{html_escape(val)}"> {html_escape(val)}'
                f'</label>'
            )
        return (
            f'<div class="awv-field">'
            f'<label class="awv-label">{html_escape(label)}{req_star}</label>'
            f'<div class="awv-checkbox-group"{req_attr}>{opts}</div>'
            f'</div>'
        )

    def _info_row(self, label: str, value: str) -> str:
        return (
            f'<div class="awv-info-row">'
            f'<span class="awv-info-label">{html_escape(label)}</span>'
            f'<span class="awv-info-value">{html_escape(value)}</span>'
            f'</div>'
        )

    def _subtitle(self, text: str) -> str:
        return f'<h3 class="awv-subtitle">{html_escape(text)}</h3>'

    def _alert(self, text: str, level: str = "info") -> str:
        # ``level`` is a plugin-controlled enum-ish string ("info", "warning",
        # etc.) but escape it for consistency. ``text`` is caller-supplied.
        return f'<div class="awv-alert awv-alert--{html_escape(level)}">{html_escape(text)}</div>'

    def _divider(self) -> str:
        return '<div class="awv-divider"></div>'

    def _save_button(self, save_fn_name: str, label: str = "Save") -> str:
        section_id = self.__class__.__name__.lower().replace("module", "")
        return (
            f'<div class="awv-save-row">'
            f'<button type="button" class="awv-save-btn" '
            f'id="{section_id}-save-btn" '
            f'onclick="{save_fn_name}()">{label}</button>'
            f'<span class="awv-status" id="{section_id}-status"></span>'
            f'</div>'
        )

    # --- data helpers ---

    @staticmethod
    def _dedup_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate rows from .values() joins that produce one row per coding."""
        seen: set[str] = set()
        result = []
        for row in rows:
            rid = str(row.get("id", ""))
            if rid not in seen:
                seen.add(rid)
                result.append(row)
        return result
