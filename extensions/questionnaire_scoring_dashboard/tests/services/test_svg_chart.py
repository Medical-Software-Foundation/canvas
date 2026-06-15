from questionnaire_scoring_dashboard.services.svg_chart import (
    render_line_svg,
    render_multi_line_svg,
)


def test_render_line_svg_basic_structure():
    pts = [{"date": "2026-01-01", "value": 20}, {"date": "2026-01-20", "value": 16}]
    svg = render_line_svg(pts, max_score=27)
    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert "polyline" in svg
    assert "circle" in svg
    assert "2026-01-01" in svg and "2026-01-20" in svg


def test_render_line_svg_empty_points_renders_placeholder():
    svg = render_line_svg([], max_score=27)
    assert "<svg" in svg
    assert "No data" in svg


def test_render_line_svg_autoscale_without_max():
    pts = [{"date": "2026-01-01", "value": 5}, {"date": "2026-02-01", "value": 9}]
    svg = render_line_svg(pts, max_score=None)
    assert "<svg" in svg and "polyline" in svg


def test_render_line_svg_single_point():
    pts = [{"date": "2026-01-01", "value": 5}]
    svg = render_line_svg(pts, max_score=27)
    assert "circle" in svg


def test_render_multi_line_svg_draws_one_polyline_per_series():
    series = [
        ("#2c3e50", [{"date": "2026-01-01", "value": 20}, {"date": "2026-02-01", "value": 16}]),
        ("#1f8a8a", [{"date": "2026-01-01", "value": 15}, {"date": "2026-02-01", "value": 9}]),
    ]
    svg = render_multi_line_svg(series)
    assert svg.startswith("<svg") and "</svg>" in svg
    assert svg.count("polyline") == 2
    # Each series keeps its own colour and the union of dates labels the x-axis.
    assert 'stroke="#2c3e50"' in svg and 'stroke="#1f8a8a"' in svg
    assert "2026-01-01" in svg and "2026-02-01" in svg


def test_render_multi_line_svg_aligns_unequal_date_sets():
    # Two series with different dates share one x-axis spanning the union.
    series = [
        ("#2c3e50", [{"date": "2026-01-01", "value": 10}]),
        ("#1f8a8a", [{"date": "2026-03-01", "value": 4}]),
    ]
    svg = render_multi_line_svg(series)
    assert "2026-01-01" in svg and "2026-03-01" in svg


def test_render_multi_line_svg_empty_renders_placeholder():
    assert "No data" in render_multi_line_svg([])
    assert "No data" in render_multi_line_svg([("#2c3e50", [])])
