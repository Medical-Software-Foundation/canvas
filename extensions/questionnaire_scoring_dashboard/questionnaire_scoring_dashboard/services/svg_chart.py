"""Render a static inline-SVG line chart from a point list.

Built as a plain string so it runs in the Canvas command sandbox (no chart
libraries, no JS). Used for the read-only CustomCommand content.
"""

from __future__ import annotations

_W, _H = 520, 180
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 40, 12, 12, 28

# Muted, distinguishable palette shared with the on-screen compare chart.
PALETTE = ["#2c3e50", "#1f8a8a", "#5c6b79", "#9b6a9e", "#b07d4b", "#7a8450"]


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


def render_multi_line_svg(series: list[tuple[str, list[dict]]]) -> str:
    """Return an SVG overlaying several series on one shared axis.

    series: [(color, points), ...] where points are [{"date","value"}, ...].
    Raw values share a single 0-to-top axis (mirrors the on-screen compare
    view). x positions align to the sorted union of all dates across series.
    """
    all_dates = sorted({p["date"] for _, points in series for p in points})
    all_values = [p["value"] for _, points in series for p in points]
    if not all_dates:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}">'
            f'<text x="{_W // 2}" y="{_H // 2}" text-anchor="middle" '
            f'font-family="Inter,sans-serif" font-size="13" fill="#8a97a3">No data</text></svg>'
        )

    top = max(all_values) or 1
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    n = len(all_dates)
    index_of = {d: i for i, d in enumerate(all_dates)}

    def x_at(i: int) -> float:
        return _PAD_L + (plot_w * (i / (n - 1) if n > 1 else 0.5))

    def y_at(v: float) -> float:
        return _PAD_T + plot_h * (1 - (v / top if top else 0))

    lines = ""
    for color, points in series:
        coords = [(x_at(index_of[p["date"]]), y_at(p["value"])) for p in points]
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        circles = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'
            for x, y in coords
        )
        lines += (
            f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
            f'points="{polyline}"/>{circles}'
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
        f'<text x="{x_at(0):.1f}" y="{_H - 8}" text-anchor="middle" font-size="10" fill="#8a97a3">{all_dates[0]}</text>'
        f'<text x="{x_at(n - 1):.1f}" y="{_H - 8}" text-anchor="middle" font-size="10" fill="#8a97a3">{all_dates[-1]}</text>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" '
        f'font-family="Inter,sans-serif">'
        f"{axis}{y_labels}{x_labels}{lines}</svg>"
    )
