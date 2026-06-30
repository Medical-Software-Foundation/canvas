"""Generic note-summary rendering for the group therapy templates.

The modal owns the per-template field schema and sends ordered (label, value)
section pairs; these renderers lay them out, so the same code handles any
configured template.
"""


def _esc(text: str) -> str:
    """Escape HTML and turn newlines into <br> (no html module in the sandbox)."""
    out = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return out.replace("\n", "<br>")


def _meta_html(meta_pairs: list) -> str:
    """Render the compact header row of (label, value) pairs."""
    items = ""
    for label, value in meta_pairs:
        if not value:
            continue
        items += (
            '<div style="display:flex;gap:4px;">'
            f'<span style="color:#6b7280;font-weight:400;">{_esc(label)}</span> '
            f'<span style="color:#111827;">{_esc(value)}</span></div>'
        )
    return items


def _sections_html(sections: list, label_color: str, body_color: str) -> str:
    """Render labeled section blocks; skips empty values."""
    blocks = ""
    for label, value in sections:
        if not value:
            continue
        blocks += (
            '<div style="margin-bottom:2px;">'
            f'<div style="font-size:12px;font-weight:700;letter-spacing:0.03em;color:{label_color};margin-bottom:4px;">{_esc(label)}</div>'
            f'<div style="font-size:13px;color:{body_color};line-height:1.6;">{_esc(value)}</div>'
            "</div>"
        )
    return blocks


def build_note_html(meta_pairs: list, sections: list) -> str:
    """On-screen note summary HTML from header meta + labeled sections."""
    meta = _meta_html(meta_pairs)
    body = _sections_html(sections, "#475569", "#1f2933")
    divider = '<div style="border-top:1px solid #e5e7eb;margin:12px 0;"></div>' if body else ""
    return (
        '<div style="font-family:Lato,-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'font-size:13px;line-height:1.5;color:#1f2933;">'
        f'<div style="display:flex;flex-wrap:wrap;gap:10px 16px;font-size:13px;">{meta}</div>'
        f"{divider}"
        f'<div style="display:flex;flex-direction:column;gap:10px;">{body}</div>'
        "</div>"
    )


def build_note_print(meta_pairs: list, sections: list) -> str:
    """Print-friendly note summary HTML."""
    meta_rows = "".join(
        f'<div style="display:inline;margin-right:20px;"><span style="color:#666;">{_esc(label)}:</span> {_esc(value)}</div>'
        for label, value in meta_pairs
        if value
    )
    sections_html = ""
    for label, value in sections:
        if not value:
            continue
        sections_html += (
            '<div style="margin-bottom:10px;">'
            f'<div style="font-weight:600;color:#333;margin-bottom:2px;">{_esc(label)}</div>'
            f'<div style="color:#444;">{_esc(value)}</div></div>'
        )
    divider = '<div style="border-top:1px solid #ccc;margin:10px 0;"></div>' if sections_html else ""
    return (
        '<div style="font-family:serif;font-size:12px;line-height:1.5;color:#333;">'
        f'<div style="font-size:12px;">{meta_rows}</div>{divider}{sections_html}</div>'
    )
