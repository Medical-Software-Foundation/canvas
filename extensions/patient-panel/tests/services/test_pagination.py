"""Tests for patient_panel.services.pagination (pure URL/page-number helpers)."""

__is_plugin__ = True

from urllib.parse import parse_qs, urlparse

from patient_panel.services.pagination import (
    build_page_numbers,
    create_paginated_url_multi,
)

BASE_PATH = "/plugin-io/api/patient_panel"
PREFIX = "/app"


class TestCreatePaginatedUrlMulti:
    def test_basic(self) -> None:
        url = create_paginated_url_multi(BASE_PATH, PREFIX, "table", 1, None, None, None, [], [])
        assert url == "/plugin-io/api/patient_panel/app/table?page=1&no_auto_filter=1"

    def test_with_lists(self) -> None:
        url = create_paginated_url_multi(
            BASE_PATH, PREFIX, "table", 2,
            facility_ids=["facility-123"],
            protocols=["Diabetes"],
            patient_search="John",
            staff_ids=["staff-1", "staff-2"],
            insurances=["Medicare", "Medicaid"],
        )
        qs = parse_qs(urlparse(url).query)
        assert qs["page"] == ["2"]
        assert qs["facility_ids"] == ["facility-123"]
        assert qs["protocols"] == ["Diabetes"]
        assert qs["patient_search"] == ["John"]
        assert qs["staff_ids"] == ["staff-1,staff-2"]
        assert qs["insurances"] == ["Medicare,Medicaid"]

    def test_metadata_filters_emitted(self) -> None:
        url = create_paginated_url_multi(
            BASE_PATH, PREFIX, "table", 1,
            metadata_filters={"risk_score": ["Low", "High"], "empty": []},
        )
        qs = parse_qs(urlparse(url).query)
        assert qs["metadata_risk_score"] == ["Low,High"]
        assert "metadata_empty" not in qs


class TestBuildPageNumbers:
    def test_all_pages_when_few(self) -> None:
        pages = build_page_numbers(BASE_PATH, PREFIX, 1, 3, {})
        assert [p["number"] for p in pages] == [1, 2, 3]
        assert pages[0]["is_current"] is True
        assert pages[1]["is_current"] is False

    def test_windowed_when_many(self) -> None:
        pages = build_page_numbers(BASE_PATH, PREFIX, 5, 20, {})
        numbers = [p["number"] for p in pages]
        assert len(numbers) == 5
        assert 5 in numbers
        # current page marked
        assert any(p["is_current"] and p["number"] == 5 for p in pages)

    def test_window_clamps_at_end(self) -> None:
        pages = build_page_numbers(BASE_PATH, PREFIX, 20, 20, {})
        numbers = [p["number"] for p in pages]
        assert numbers == [16, 17, 18, 19, 20]
