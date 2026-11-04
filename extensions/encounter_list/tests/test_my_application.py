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


class TestGetEncountersClaimLookup:
    """Rendering a row must resolve the note's claim once, not twice."""

    @patch("encounter_list.applications.my_application.Note")
    def test_get_claim_called_once_per_row(self, mock_note):
        """get_encounters resolves get_claim() a single time per encounter row."""
        note = MagicMock()
        note.datetime_of_service = None
        note.created = None
        note.patient.birth_date = None
        note.patient.nickname = ""
        note.get_claim.return_value = MagicMock()

        with (
            patch.object(EncounterListApi, "_sort_and_paginate_database", return_value=([note], 1, 1)),
            patch.object(EncounterListApi, "_calculate_delegated_orders_count", return_value=0),
        ):
            api = EncounterListApi()
            api.request = MagicMock()
            api.request.query_params.get = lambda key, default=None: default

            api.get_encounters()

        assert note.get_claim.call_count == 1


class TestGetNoteTypes:
    """The Note Type filter lists only note types that have open encounters."""

    @patch("encounter_list.applications.my_application.JSONResponse")
    @patch("encounter_list.applications.my_application.NoteType")
    @patch("encounter_list.applications.my_application.Note")
    def test_scoped_to_open_encounters(self, mock_note, mock_note_type, mock_json):
        """NoteType rows are filtered by the open-encounter set, not returned wholesale."""
        from encounter_list.applications import my_application as app

        open_set = mock_note.objects.exclude.return_value.exclude.return_value.values.return_value
        EncounterListApi().get_note_types()

        # Open set drops closed states, then MESSAGE/LETTER categories.
        mock_note.objects.exclude.assert_called_once_with(
            current_state__state__in=app.CLOSED_NOTE_STATES
        )
        mock_note.objects.exclude.return_value.exclude.assert_called_once_with(
            note_type_version__category__in=app.EXCLUDED_NOTE_TYPE_CATEGORIES
        )
        mock_note_type.objects.filter.assert_called_once_with(pk__in=open_set)
        # Never falls back to an unfiltered NoteType query.
        mock_note_type.objects.exclude.assert_not_called()
        filtered = mock_note_type.objects.filter.return_value
        filtered.exclude.assert_called_once_with(category__in=app.EXCLUDED_NOTE_TYPE_CATEGORIES)

    def test_closed_states_match_worklist_exclusions(self):
        """Terminal/non-worklist states stay out of the open set."""
        from encounter_list.applications import my_application as app

        assert len(app.CLOSED_NOTE_STATES) == 9
        assert len(app.EXCLUDED_NOTE_TYPE_CATEGORIES) == 2
