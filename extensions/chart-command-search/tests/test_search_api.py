"""Tests for ChartSearchAPI handler."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.handlers.search_api import ChartSearchAPI
from chart_command_search.searchers import ALL_CATEGORY_LIMIT, CATEGORY_SEARCHERS

VALID_PATIENT_ID = "12345678-1234-1234-1234-123456789abc"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    req = MagicMock()
    req.query_params = query_params or {}
    req.headers = headers or {}
    return req


def _make_handler(query_params: dict[str, str] | None = None) -> ChartSearchAPI:
    handler = ChartSearchAPI.__new__(ChartSearchAPI)
    handler.request = _make_request(query_params=query_params)
    return handler


def _get_json(responses: list[Any]) -> dict[str, Any]:
    assert len(responses) == 1
    return json.loads(getattr(responses[0], "content"))


def make_result(category: str, summary: str, date_str: str = "2024-01-01") -> dict[str, Any]:
    return {
        "category": category,
        "type_label": category.title(),
        "summary": summary,
        "date": date_str,
        "details": [],
    }


# ---------------------------------------------------------------------------
# Missing patient_id
# ---------------------------------------------------------------------------


class TestChartSearchAPIMissingPatientId:
    def test_missing_patient_id_returns_400(self) -> None:
        handler = _make_handler(query_params={"q": "diabetes"})
        responses = handler.get()
        data = _get_json(responses)
        assert responses[0].status_code == 400
        assert "patient_id" in data["error"]

    def test_empty_patient_id_returns_400(self) -> None:
        handler = _make_handler(query_params={"patient_id": "", "q": "test"})
        responses = handler.get()
        data = _get_json(responses)
        assert responses[0].status_code == 400
        assert "patient_id" in data["error"]


# ---------------------------------------------------------------------------
# Single category search
# ---------------------------------------------------------------------------


class TestChartSearchAPISingleCategory:
    def test_single_category_returns_all_results(self) -> None:
        fake_results = [make_result("commands", f"Result {i}") for i in range(15)]
        mock_searcher = MagicMock(return_value=fake_results)

        with patch.dict(CATEGORY_SEARCHERS, {"commands": mock_searcher}, clear=True):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "test", "category": "commands"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert responses[0].status_code == 200
        assert data["count"] == 15
        assert len(data["results"]) == 15

    def test_single_category_passes_query_to_searcher(self) -> None:
        mock_searcher = MagicMock(return_value=[])

        with patch.dict(CATEGORY_SEARCHERS, {"notes": mock_searcher}, clear=True):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "diabetes", "category": "notes"}
            )
            handler.get()

        call_args = mock_searcher.call_args
        assert call_args.args[1] == "diabetes"

    def test_single_category_passes_status_to_searcher(self) -> None:
        mock_searcher = MagicMock(return_value=[])

        with patch.dict(CATEGORY_SEARCHERS, {"labs": mock_searcher}, clear=True):
            handler = _make_handler(
                query_params={
                    "patient_id": VALID_PATIENT_ID,
                    "q": "",
                    "category": "labs",
                    "status": "reviewed",
                }
            )
            handler.get()

        call_args = mock_searcher.call_args
        assert call_args.args[2] == "reviewed"


# ---------------------------------------------------------------------------
# Multi-category ("all") with per-category limit
# ---------------------------------------------------------------------------


class TestChartSearchAPIAllCategories:
    def test_all_category_limits_results_per_category(self) -> None:
        many_results = [
            make_result("commands", f"Cmd {i}", f"2024-01-{i+1:02d}")
            for i in range(ALL_CATEGORY_LIMIT + 5)
        ]
        mock_commands = MagicMock(return_value=many_results)
        mock_notes = MagicMock(return_value=[])

        with patch.dict(
            CATEGORY_SEARCHERS,
            {"commands": mock_commands, "notes": mock_notes},
            clear=True,
        ):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "all"}
            )
            responses = handler.get()
            data = _get_json(responses)

        # With two categories and only "commands" returning results,
        # max results from "commands" should be capped at ALL_CATEGORY_LIMIT.
        assert data["count"] <= ALL_CATEGORY_LIMIT

    def test_all_category_sorts_results_by_date_descending(self) -> None:
        results_commands = [
            make_result("commands", "Old command", "2023-06-01"),
            make_result("commands", "New command", "2024-12-01"),
        ]
        results_notes = [
            make_result("notes", "Mid note", "2024-01-15"),
        ]
        mock_commands = MagicMock(return_value=results_commands)
        mock_notes = MagicMock(return_value=results_notes)

        with patch.dict(
            CATEGORY_SEARCHERS,
            {"commands": mock_commands, "notes": mock_notes},
            clear=True,
        ):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "all"}
            )
            responses = handler.get()
            data = _get_json(responses)

        dates = [r["date"] for r in data["results"]]
        assert dates == sorted(dates, reverse=True)

    def test_multi_category_comma_separated(self) -> None:
        mock_commands = MagicMock(return_value=[make_result("commands", "Cmd")])
        mock_notes = MagicMock(return_value=[make_result("notes", "Note")])

        with patch.dict(
            CATEGORY_SEARCHERS,
            {"commands": mock_commands, "notes": mock_notes},
            clear=True,
        ):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "commands,notes"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert data["count"] == 2


# ---------------------------------------------------------------------------
# Unknown category
# ---------------------------------------------------------------------------


class TestChartSearchAPIUnknownCategory:
    def test_unknown_category_in_search_errors(self) -> None:
        with patch.dict(CATEGORY_SEARCHERS, {}, clear=True):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "ghost_category"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert responses[0].status_code == 200
        assert "search_errors" in data
        errors = data["search_errors"]
        assert any("ghost_category" in e for e in errors)

    def test_known_and_unknown_category_returns_known_results(self) -> None:
        mock_notes = MagicMock(return_value=[make_result("notes", "A note")])

        with patch.dict(CATEGORY_SEARCHERS, {"notes": mock_notes}, clear=True):
            handler = _make_handler(
                query_params={
                    "patient_id": VALID_PATIENT_ID,
                    "q": "",
                    "category": "notes,nonexistent",
                }
            )
            responses = handler.get()
            data = _get_json(responses)

        assert data["count"] == 1
        assert "search_errors" in data


# ---------------------------------------------------------------------------
# Category searcher exception handling
# ---------------------------------------------------------------------------


class TestChartSearchAPISearcherException:
    def test_throwing_searcher_populates_search_errors(self) -> None:
        broken = MagicMock(side_effect=RuntimeError("db timeout"))
        good = MagicMock(return_value=[make_result("notes", "Safe note")])

        with patch.dict(
            CATEGORY_SEARCHERS,
            {"broken": broken, "notes": good},
            clear=True,
        ):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "broken,notes"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert responses[0].status_code == 200
        assert "search_errors" in data
        errors = data["search_errors"]
        assert any("broken" in e for e in errors)

    def test_throwing_searcher_does_not_block_other_categories(self) -> None:
        broken = MagicMock(side_effect=ValueError("unexpected"))
        good = MagicMock(return_value=[make_result("notes", "Good note")])

        with patch.dict(
            CATEGORY_SEARCHERS,
            {"broken": broken, "notes": good},
            clear=True,
        ):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "broken,notes"}
            )
            responses = handler.get()
            data = _get_json(responses)

        # Good category must still appear in results
        assert data["count"] == 1
        assert data["results"][0]["summary"] == "Good note"

    def test_all_searchers_throwing_returns_empty_with_errors(self) -> None:
        broken1 = MagicMock(side_effect=RuntimeError("err1"))
        broken2 = MagicMock(side_effect=RuntimeError("err2"))

        with patch.dict(
            CATEGORY_SEARCHERS,
            {"cat1": broken1, "cat2": broken2},
            clear=True,
        ):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "all"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert responses[0].status_code == 200
        assert data["count"] == 0
        assert len(data["search_errors"]) == 2


# ---------------------------------------------------------------------------
# date_to adjusted by +1 day
# ---------------------------------------------------------------------------


class TestChartSearchAPIDateToAdjustment:
    def test_date_to_incremented_by_one_day(self) -> None:
        captured_kwargs: list[dict[str, Any]] = []

        def capturing_searcher(
            patient_id: str, q: str, status: str, **kwargs: Any
        ) -> list[Any]:
            captured_kwargs.append(kwargs)
            return []

        with patch.dict(CATEGORY_SEARCHERS, {"notes": capturing_searcher}, clear=True):
            handler = _make_handler(
                query_params={
                    "patient_id": VALID_PATIENT_ID,
                    "q": "",
                    "category": "notes",
                    "date_to": "2024-03-15",
                }
            )
            handler.get()

        assert len(captured_kwargs) == 1
        adjusted = captured_kwargs[0]["date_to"]
        expected = str(date(2024, 3, 15) + timedelta(days=1))
        assert adjusted == expected

    def test_invalid_date_to_passes_through_unchanged(self) -> None:
        """When date_to is not a valid ISO date, it passes through without modification."""
        captured_kwargs: list[dict[str, Any]] = []

        def capturing_searcher(
            patient_id: str, q: str, status: str, **kwargs: Any
        ) -> list[Any]:
            captured_kwargs.append(kwargs)
            return []

        with patch.dict(CATEGORY_SEARCHERS, {"notes": capturing_searcher}, clear=True):
            handler = _make_handler(
                query_params={
                    "patient_id": VALID_PATIENT_ID,
                    "q": "",
                    "category": "notes",
                    "date_to": "not-a-date",
                }
            )
            handler.get()

        assert captured_kwargs[0]["date_to"] == "not-a-date"

    def test_missing_date_to_passed_as_empty_string(self) -> None:
        captured_kwargs: list[dict[str, Any]] = []

        def capturing_searcher(
            patient_id: str, q: str, status: str, **kwargs: Any
        ) -> list[Any]:
            captured_kwargs.append(kwargs)
            return []

        with patch.dict(CATEGORY_SEARCHERS, {"notes": capturing_searcher}, clear=True):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "notes"}
            )
            handler.get()

        assert captured_kwargs[0]["date_to"] == ""


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


class TestChartSearchAPIResponseStructure:
    def test_response_has_results_and_count(self) -> None:
        mock_searcher = MagicMock(return_value=[])

        with patch.dict(CATEGORY_SEARCHERS, {"notes": mock_searcher}, clear=True):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "notes"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert "results" in data
        assert "count" in data
        assert data["count"] == len(data["results"])

    def test_no_search_errors_key_on_success(self) -> None:
        mock_searcher = MagicMock(return_value=[])

        with patch.dict(CATEGORY_SEARCHERS, {"notes": mock_searcher}, clear=True):
            handler = _make_handler(
                query_params={"patient_id": VALID_PATIENT_ID, "q": "", "category": "notes"}
            )
            responses = handler.get()
            data = _get_json(responses)

        assert "search_errors" not in data
