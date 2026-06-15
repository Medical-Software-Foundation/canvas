from questionnaire_scoring_dashboard.services.svg_chart import render_line_svg


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
