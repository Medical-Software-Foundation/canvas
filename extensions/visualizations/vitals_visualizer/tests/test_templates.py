"""Static checks on templates/index.html and templates/style.css.

The modal's behaviour lives in inline JS, so these tests pin the markup and
script hooks the history table and chart filtering depend on.
"""

from html.parser import HTMLParser
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, tuple[str, dict[str, str | None]]] = {}
        self.script = ""
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if "id" in attr_map:
            self.by_id[attr_map["id"]] = (tag, attr_map)
        self._in_script = tag == "script" and "src" not in attr_map

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.script += data


@pytest.fixture(scope="module")
def page() -> _Collector:
    collector = _Collector()
    collector.feed((TEMPLATES / "index.html").read_text())
    return collector


@pytest.fixture(scope="module")
def css() -> str:
    return (TEMPLATES / "style.css").read_text()


def test_history_toggle_button_starts_collapsed(page: _Collector) -> None:
    tag, attrs = page.by_id["historyToggleBtn"]
    assert tag == "button"
    assert attrs["aria-expanded"] == "false"
    assert attrs["aria-controls"] == "historyPanel"


def test_history_panel_is_hidden_by_default(page: _Collector) -> None:
    tag, attrs = page.by_id["historyPanel"]
    assert tag == "section"
    assert "hidden" in attrs


def test_history_table_markup_exists(page: _Collector) -> None:
    assert page.by_id["vitalsTable"][0] == "table"
    assert "vitals-table" in page.by_id["vitalsTable"][1]["class"]
    assert page.by_id["vitalsTableHead"][0] == "tr"
    assert page.by_id["vitalsTableBody"][0] == "tbody"
    assert "hidden" in page.by_id["historyEmpty"][1]


def test_history_table_limited_to_ten_readings(page: _Collector) -> None:
    assert "const HISTORY_LIMIT = 10;" in page.script
    assert "dates.length - HISTORY_LIMIT" in page.script


def test_history_table_cells_use_text_content_not_html(page: _Collector) -> None:
    # Values can be free-text strings from Observation.value.
    assert "innerHTML" not in page.script
    assert "td.textContent" in page.script


def test_toggle_flips_label_and_aria(page: _Collector) -> None:
    assert "'Hide History' : 'Show History'" in page.script
    assert "setAttribute('aria-expanded'" in page.script


def test_update_chart_filters_missing_values(page: _Collector) -> None:
    assert "function hasValue(val)" in page.script
    assert "val !== null && val !== undefined && val !== ''" in page.script
    assert "chart.data.labels = chartLabels;" in page.script


def test_chart_has_enhanced_point_styling(page: _Collector) -> None:
    for option in (
        "pointBackgroundColor: color",
        "pointBorderColor: '#ffffff'",
        "pointHoverBorderWidth: 3",
    ):
        assert option in page.script


def test_hidden_attribute_wins_over_component_display(css: str) -> None:
    assert "[hidden] {\n    display: none !important;" in css


def test_table_container_scrolls(css: str) -> None:
    block = css.split(".vitals-table-container {", 1)[1].split("}", 1)[0]
    assert "overflow: auto;" in block


def test_history_panel_stacks_under_720px(css: str) -> None:
    mobile = css.split("@media (max-width: 720px)", 1)[1]
    block = mobile.split(".history-panel {", 1)[1].split("}", 1)[0]
    assert "position: static;" in block
