"""Tests for the Encounter List API pagination and query construction."""
from unittest.mock import MagicMock, patch

from encounter_list.applications.my_application import EncounterListApi


class TestSortAndPaginateDatabase:
    """The worklist must page at the database, not materialize every open encounter."""

    def test_slices_queryset_at_the_database(self):
        """_sort_and_paginate_database applies LIMIT/OFFSET instead of loading all rows."""
        page_rows = [MagicMock(), MagicMock()]
        queryset = MagicMock()
        queryset.order_by.return_value = queryset
        queryset.count.return_value = 130
        queryset.__getitem__.return_value = page_rows

        api = EncounterListApi()
        notes, total_count, total_pages = api._sort_and_paginate_database(
            queryset, "dos", "desc", page=2, page_size=25
        )

        assert notes == page_rows
        assert total_count == 130
        assert total_pages == 6
        queryset.order_by.assert_called_once_with("-datetime_of_service")
        queryset.__getitem__.assert_called_once_with(slice(25, 50))
        queryset.__iter__.assert_not_called()

    def test_clamps_page_beyond_last_page(self):
        """An out-of-range page is clamped to the final page before slicing."""
        queryset = MagicMock()
        queryset.order_by.return_value = queryset
        queryset.count.return_value = 40
        queryset.__getitem__.return_value = []

        api = EncounterListApi()
        _, total_count, total_pages = api._sort_and_paginate_database(
            queryset, "dos", "asc", page=99, page_size=25
        )

        assert total_count == 40
        assert total_pages == 2
        queryset.__getitem__.assert_called_once_with(slice(25, 50))


class TestGetEncountersQuery:
    """The base queryset must eager-load the relations rendered for each row."""

    @patch("encounter_list.applications.my_application.Note")
    def test_selects_related_relations(self, mock_note):
        """get_encounters uses select_related to avoid per-row N+1 loads."""
        with patch.object(EncounterListApi, "_sort_and_paginate_database", return_value=([], 0, 0)):
            api = EncounterListApi()
            api.request = MagicMock()
            api.request.query_params.get = lambda key, default=None: default

            api.get_encounters()

        mock_note.objects.select_related.assert_called_once_with(
            "patient", "provider", "location", "note_type_version"
        )
