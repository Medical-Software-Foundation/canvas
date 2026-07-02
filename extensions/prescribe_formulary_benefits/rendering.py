"""Builds the custom HTML rendered alongside prescribe-family commands.

The HTML is shown in a sandboxed (`allow-scripts`, opaque-origin) iframe that
auto-sizes via a ResizeObserver on the body, so a native ``<details>`` collapsible
resizes the frame correctly with no JS of our own. Everything user-facing is
escaped and None-guarded so we never render a bare "None" or inject unescaped
Surescripts text.
"""

from __future__ import annotations

from html import escape
from typing import Any

_STYLE = """
*{box-sizing:border-box}
body{margin:0;padding:0;background:transparent;
  font:13px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:#1f2328;-webkit-font-smoothing:antialiased}
/* No outer margin on the card: a top/bottom margin here collapses out of the
   body box and isn't counted by the parent's height measurement, which leaves a
   few px of phantom scroll. Space stacked cards with an in-flow sibling margin. */
.card{border:1px solid #e6e3db;border-radius:10px;padding:14px 16px;margin:0;background:#fff}
.card+.card{margin-top:10px}
.hdr{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:#5b636d;margin-bottom:12px}
.cards{display:flex;flex-wrap:wrap;gap:10px}
.cell{flex:1 1 180px;background:#f7f4ec;border-radius:8px;padding:9px 11px;min-width:160px}
.lbl{font-size:10.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:#8a8f98;margin-bottom:6px}
.status{display:inline-flex;align-items:center;gap:6px;background:#f4ead2;color:#5a4a1e;
  border-radius:14px;padding:4px 10px;font-weight:500}
.status.good{background:#e2f1e6;color:#15703a}
.status.bad{background:#fbe4e2;color:#a31515}
.dot{width:9px;height:9px;border-radius:50%;background:#c79a3a;flex:none}
.status.good .dot{background:#2da44e}
.status.bad .dot{background:#cf3b2f}
.copay{display:inline-flex;align-items:center;gap:5px;background:#e7f2ea;color:#15703a;
  border-radius:14px;padding:4px 10px;font-weight:600}
.copay .sym{font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-block;border-radius:12px;padding:2px 9px;font-size:12px;font-weight:500;
  white-space:nowrap}
.chip.neutral{background:#edeef0;color:#5b636d}
.chip.warn{background:#fbecd2;color:#8a5a12}
.chip.generic{background:#e2f1e6;color:#15703a}
.chip.brand{background:#f1e7cf;color:#8a6a16}
.chip.tier{background:#f6edd6;color:#6f5512}
.muted{color:#8a8f98}
details.alts{margin-top:12px;border:1px solid #e6e3db;border-radius:8px;overflow:hidden}
details.alts>summary{display:flex;align-items:center;gap:8px;cursor:pointer;
  padding:10px 12px;font-weight:600;list-style:none;user-select:none}
details.alts>summary::-webkit-details-marker{display:none}
.summary-icon{color:#5b636d}
.count{color:#8a8f98;font-weight:500}
.chev{margin-left:auto;color:#8a8f98;transition:transform .15s ease}
details.alts[open]>summary .chev{transform:rotate(90deg)}
table{width:100%;border-collapse:collapse;border-top:1px solid #eceae3}
th{text-align:left;font-size:10.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:#8a8f98;padding:8px 12px;background:#fbfaf7}
td{padding:8px 12px;border-top:1px solid #f0eee8;vertical-align:top}
td.drug{font-weight:500}
td.rxclass{color:#5b636d}
.msg{color:#5b636d}
.msg .err{color:#a31515;margin-top:4px}
"""

_DOT = '<span class="dot"></span>'
# Two-node "alternatives" glyph for the collapsible header.
_ALT_ICON = (
    '<svg class="summary-icon" width="15" height="15" viewBox="0 0 16 16" fill="none" '
    'stroke="currentColor" stroke-width="1.4"><circle cx="4" cy="4" r="2"/>'
    '<circle cx="12" cy="12" r="2"/><path d="M6 4h4a2 2 0 0 1 2 2v4M10 12H6a2 2 0 0 1-2-2V6"/></svg>'
)
_CHEV = '<span class="chev">&#8250;</span>'


def _esc(value: Any) -> str:
    return escape(str(value))


def _document(inner: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_STYLE}</style></head><body>{inner}</body></html>"
    )


def _chip(text: str, cls: str = "neutral") -> str:
    return f'<span class="chip {cls}">{_esc(text)}</span>'


def _state_card(title: str, body_html: str) -> str:
    return _document(
        f'<div class="card"><div class="hdr">{_esc(title)}</div>'
        f'<div class="msg">{body_html}</div></div>'
    )


# --- transient / empty states ---------------------------------------------


def render_loading(medication_description: str) -> str:
    """HTML shown while the eligibility/benefits round-trip is in flight."""
    return _state_card(
        "Formulary & Benefits",
        f"Checking formulary coverage for <strong>{_esc(medication_description)}</strong>&hellip;",
    )


def render_error(medication_description: str, message: str) -> str:
    """HTML shown when eligibility or benefits returns an error."""
    return _state_card(
        "Formulary & Benefits",
        f"Could not retrieve formulary coverage for <strong>{_esc(medication_description)}</strong>."
        f'<div class="err">{_esc(message)}</div>',
    )


def render_no_active_coverage(medication_description: str) -> str:
    """HTML shown when eligibility returned no active plan (no/inactive coverage)."""
    return _state_card(
        "Formulary & Benefits",
        f"No active pharmacy benefit was found for <strong>{_esc(medication_description)}</strong>.",
    )


def render_no_coverage(medication_description: str) -> str:
    """HTML shown when the benefits response came back with no coverage rows."""
    return _state_card(
        "Formulary & Benefits",
        "No formulary coverage information was returned for "
        f"<strong>{_esc(medication_description)}</strong>.",
    )


def render_rejected(medication_description: str, reasons: list[str]) -> str:
    """HTML shown when eligibility returned only rejected plans."""
    cleaned = [r for r in (reasons or []) if r]
    items = "".join(f"<li>{_esc(r)}</li>" for r in cleaned) or "<li>Rejected by plan</li>"
    return _state_card(
        "Formulary & Benefits",
        f"The pharmacy benefit check for <strong>{_esc(medication_description)}</strong> was rejected."
        f'<ul class="err" style="margin:4px 0 0 18px;padding:0">{items}</ul>',
    )


# --- benefits detail -------------------------------------------------------


_STATUS_NEGATIVE = (
    "not covered",
    "no coverage",
    "non-formulary",
    "non formulary",
    "not on formulary",
    "excluded",
)


def _status_class(coverage: Any) -> str:
    """Classify a formulary status pill.

    'bad' (red)     — rejected, not covered, or non-formulary.
    'good' (green)  — preferred (on-formulary/preferred).
    ''   (yellow)   — everything else, incl. on-formulary/non-preferred and unknown.
    """
    if coverage.rejected:
        return "bad"
    status = (coverage.formulary_status or "").lower()
    if any(term in status for term in _STATUS_NEGATIVE):
        return "bad"
    # Green only for preferred; a non-preferred plan stays neutral/yellow.
    if "preferred" in status and "non-preferred" not in status and "non preferred" not in status:
        return "good"
    return ""


def _restriction_chips(coverage: Any) -> str:
    chips = []
    if coverage.prior_authorization_required:
        chips.append(_chip("PA required", "warn"))
    else:
        chips.append(_chip("No PA", "neutral"))
    if coverage.step_therapy_required:
        chips.append(_chip("Step therapy", "warn"))
    else:
        chips.append(_chip("No step therapy", "neutral"))
    for limit in coverage.quantity_limits or []:
        if limit:
            chips.append(_chip(limit, "warn"))
    return "".join(chips)


def _copay_text(copays: list[str]) -> str:
    cleaned = [c for c in (copays or []) if c]
    return "; ".join(cleaned)


def _alternative_tier_chips(alt: Any) -> str:
    copays = [c for c in (getattr(alt, "copays", None) or []) if c]
    if not copays:
        return '<span class="muted">&mdash;</span>'
    return "".join(_chip(c, "tier") for c in copays)


def _alternative_type_chip(alt: Any) -> str:
    value = getattr(alt, "brand_or_generic", None)
    if not value:
        return '<span class="muted">&mdash;</span>'
    cls = "generic" if value.strip().lower() == "generic" else "brand"
    return _chip(value, cls)


def _alternative_row(alt: Any) -> str:
    description = getattr(alt, "description", None) or getattr(alt, "ndc", "") or "Unknown"
    ndc = getattr(alt, "ndc", "")
    rx_class = getattr(alt, "formulary_status", None) or ""
    drug = _esc(description)
    if ndc:
        drug += f' <span class="muted">({_esc(ndc)})</span>'
    return (
        f'<tr><td class="drug">{drug}</td>'
        f"<td>{_alternative_type_chip(alt)}</td>"
        f"<td>{_alternative_tier_chips(alt)}</td>"
        f'<td class="rxclass">{_esc(rx_class) if rx_class else "&mdash;"}</td></tr>'
    )


def _alternatives_block(coverage: Any) -> str:
    alternatives = coverage.alternatives or []
    if not alternatives:
        return ""
    rows = "".join(_alternative_row(a) for a in alternatives)
    return (
        '<details class="alts">'
        f'<summary>{_ALT_ICON} Formulary alternatives <span class="count">'
        f"({len(alternatives)})</span>{_CHEV}</summary>"
        "<table><thead><tr><th>Drug</th><th>Type</th><th>Tier</th><th>Rx class</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></details>"
    )


def _coverage_card(coverage: Any) -> str:
    pbm = coverage.pbm_name or "Plan"
    header = f"Formulary &amp; Benefits &mdash; {_esc(pbm)}"

    status_cls = _status_class(coverage)
    status_label = (
        coverage.reject_reason or "Rejected by plan"
        if coverage.rejected
        else (coverage.formulary_status or "Unknown")
    )
    status = f'<span class="status {status_cls}">{_DOT}{_esc(status_label)}</span>'

    copay = _copay_text(coverage.copays)
    copay_html = (
        f'<span class="copay"><span class="sym">$</span>{_esc(copay)}</span>'
        if copay
        else '<span class="muted">Not specified</span>'
    )

    return (
        '<div class="card">'
        f'<div class="hdr">{header}</div>'
        '<div class="cards">'
        f'<div class="cell"><div class="lbl">Formulary status</div><div>{status}</div></div>'
        f'<div class="cell"><div class="lbl">Copay tier</div><div>{copay_html}</div></div>'
        '<div class="cell"><div class="lbl">Restrictions</div>'
        f'<div class="chips">{_restriction_chips(coverage)}</div></div>'
        "</div>"
        f"{_alternatives_block(coverage)}"
        "</div>"
    )


def render_benefits(medication_description: str, coverages: list[Any]) -> str:
    """HTML summarizing the Surescripts benefits/formulary response."""
    if not coverages:
        return render_no_coverage(medication_description)
    return _document("".join(_coverage_card(c) for c in coverages))
