"""Render a static inline-SVG line chart from a point list.

Built as a plain string so it runs in the Canvas command sandbox (no chart
libraries, no JS). Used for the read-only CustomCommand content.
"""

from __future__ import annotations

_W, _H = 520, 180
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 40, 12, 12, 28


def render_line_svg(points: list[dict], max_score: int | None) -> str:
    """Return an SVG string for the given sorted points.

    points: [{"date": "YYYY-MM-DD", "value": float}, ...]
    """
    if not points:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}">'
            f'<text x="{_W // 2}" y="{_H // 2}" text-anchor="middle" '
            f'font-family="Inter,sans-serif" font-size="13" fill="#8a97a3">No data</text></svg>'
        )

    values = [p["value"] for p in points]
    top = max_score if max_score else (max(values) or 1)
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    n = len(points)

    def x_at(i: int) -> float:
        return _PAD_L + (plot_w * (i / (n - 1) if n > 1 else 0.5))

    def y_at(v: float) -> float:
        return _PAD_T + plot_h * (1 - (v / top if top else 0))

    coords = [(x_at(i), y_at(p["value"])) for i, p in enumerate(points)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#2c3e50"/>'
        for x, y in coords
    )
    axis = (
        f'<line x1="{_PAD_L}" y1="{_PAD_T}" x2="{_PAD_L}" y2="{_PAD_T + plot_h}" stroke="#e3e8ed"/>'
        f'<line x1="{_PAD_L}" y1="{_PAD_T + plot_h}" x2="{_W - _PAD_R}" y2="{_PAD_T + plot_h}" stroke="#e3e8ed"/>'
    )
    y_labels = (
        f'<text x="{_PAD_L - 6}" y="{_PAD_T + 4}" text-anchor="end" font-size="10" fill="#8a97a3">{int(top)}</text>'
        f'<text x="{_PAD_L - 6}" y="{_PAD_T + plot_h}" text-anchor="end" font-size="10" fill="#8a97a3">0</text>'
    )
    x_labels = (
        f'<text x="{coords[0][0]:.1f}" y="{_H - 8}" text-anchor="middle" font-size="10" fill="#8a97a3">{points[0]["date"]}</text>'
        f'<text x="{coords[-1][0]:.1f}" y="{_H - 8}" text-anchor="middle" font-size="10" fill="#8a97a3">{points[-1]["date"]}</text>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" '
        f'font-family="Inter,sans-serif">'
        f"{axis}{y_labels}{x_labels}"
        f'<polyline fill="none" stroke="#2c3e50" stroke-width="2.5" points="{polyline}"/>'
        f"{circles}</svg>"
    )
