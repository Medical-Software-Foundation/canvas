from unittest.mock import MagicMock, patch

from surescripts_med_history.protocols.mock_data import _MOCK_ROWS, mock_history_items


class TestMockHistoryItems:
    def test_builds_one_item_per_fill(self):
        items = mock_history_items(set(), set(), [])
        assert len(items) == sum(len(row["fills"]) for row in _MOCK_ROWS)

    def test_items_have_the_history_item_shape(self):
        from surescripts_med_history.protocols.action_button import _build_history_item

        med = MagicMock()
        med.codings.all.return_value = []
        med.last_fill_date = None
        med.written_date = None
        real_keys = set(_build_history_item(med, False).keys())

        for item in mock_history_items(set(), set(), []):
            assert set(item.keys()) == real_keys

    def test_unmatched_by_default(self):
        assert all(not item["is_match"] for item in mock_history_items(set(), set(), []))

    def test_matches_active_med_by_rxnorm(self):
        items = mock_history_items({"866083"}, set(), [])
        buspirone = [i for i in items if i["rxnorm_codes"] == ["866083"]]
        assert buspirone and all(i["is_match"] for i in buspirone)
        assert all(i["match_method"] == "rxnorm" for i in buspirone)
        # Other drugs are untouched.
        assert any(not i["is_match"] for i in items)

    def test_matches_active_med_by_ndc(self):
        items = mock_history_items(set(), {"00131247835"}, [])
        vimpat = [i for i in items if i["ndc_codes"] == ["00131247835"]]
        assert vimpat and all(i["match_method"] == "ndc" for i in vimpat)

    def test_matches_active_med_by_description(self):
        items = mock_history_items(set(), set(), ["vimpat 50 mg tablet, 30 count"])
        vimpat = [i for i in items if i["drug_description"].startswith("Vimpat")]
        assert vimpat and all(i["match_method"] == "description" for i in vimpat)

    def test_fill_dates_are_recent_and_sortable(self):
        import arrow

        today = arrow.utcnow().date().isoformat()
        for item in mock_history_items(set(), set(), []):
            assert item["last_fill_date_sort"] < today
            assert item["last_fill_date"]

    def test_grouping_collapses_multi_fill_rows(self):
        from surescripts_med_history.protocols.action_button import (
            _group_history_items,
        )

        groups = _group_history_items(mock_history_items(set(), set(), []))
        assert len(groups) == len(_MOCK_ROWS)
        lorazepam = [g for g in groups if g["drug_description"].startswith("LORazepam")]
        assert len(lorazepam) == 1
        assert lorazepam[0]["unique_fill_count"] == 2


class TestBuildHistoryPayloadMock:
    @staticmethod
    def _payload(include_mock):
        from surescripts_med_history.protocols import action_button

        patient = MagicMock(dbid=1, id="patient-1")

        with (
            patch.object(action_button, "MedicationHistoryMedication") as mock_hist,
            patch.object(action_button, "Medication") as mock_med,
            patch.object(action_button, "MedicationDismissal") as mock_dis,
            patch.object(action_button, "_last_requested_display", return_value=""),
            patch.object(action_button, "_request_status") as mock_status,
        ):
            hist_qs = MagicMock()
            mock_hist.objects.filter.return_value = hist_qs
            hist_qs.prefetch_related.return_value = hist_qs
            hist_qs.order_by.return_value = hist_qs
            hist_qs.__getitem__ = MagicMock(return_value=[])

            active_qs = MagicMock()
            mock_med.objects.active.return_value = active_qs
            active_qs.filter.return_value = active_qs
            active_qs.prefetch_related.return_value = iter([])

            mock_dis.objects.filter.return_value = []
            mock_status.return_value = {"state": "no_data", "detail": ""}

            payload, _ = action_button.build_history_payload(
                patient, include_mock=include_mock
            )
            return payload, mock_status

    def test_no_mock_rows_by_default(self):
        payload, mock_status = self._payload(include_mock=False)
        assert payload["grouped_items"] == []
        assert mock_status.call_args.kwargs == {"has_history": False}

    def test_mock_rows_injected_and_flagged(self):
        payload, mock_status = self._payload(include_mock=True)
        groups = payload["grouped_items"]
        assert len(groups) == len(_MOCK_ROWS)
        assert all(g["is_mock"] for g in groups)
        # Mock rows count as history so the banner doesn't say "no data".
        assert mock_status.call_args.kwargs == {"has_history": True}

    def test_last_pulled_stays_empty_for_mock_only(self):
        payload, _ = self._payload(include_mock=True)
        assert payload["last_pulled"] == ""
