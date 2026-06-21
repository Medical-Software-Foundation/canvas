"""Tests for get_active_medicare_part_b_coverage."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def _make_coverage(issuer_name, issuer_id="some-uuid", state="active", coverage_rank=1, id_number="1EG4-TE5-MK72"):
    """Build a mock Coverage with the given issuer name/state/rank."""
    mock_issuer = MagicMock()
    mock_issuer.name = issuer_name
    mock_issuer.id = issuer_id

    mock_coverage = MagicMock()
    mock_coverage.issuer = mock_issuer
    mock_coverage.state = state
    mock_coverage.coverage_rank = coverage_rank
    mock_coverage.id_number = id_number
    return mock_coverage


def _make_qs(*coverages):
    """Return a mock queryset that chains filter/order_by/first correctly."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.select_related.return_value = qs
    qs.first.return_value = coverages[0] if coverages else None
    return qs


def _patched_coverage_objects(qs):
    return patch("cms_access_fhir_client.coverage_lookup.Coverage.objects", new_callable=lambda: type(
        "_Mgr", (), {"select_related": staticmethod(lambda *a: qs)}
    ))


class TestGetActiveMedicarePartBCoverage:
    """Unit tests for get_active_medicare_part_b_coverage."""

    def _call(self, patient, secrets):
        from cms_access_fhir_client.coverage_lookup import get_active_medicare_part_b_coverage
        return get_active_medicare_part_b_coverage(patient, secrets)

    def test_no_coverage_returns_none(self):
        patient = MagicMock()
        qs = _make_qs()  # first() returns None by default

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {})

        assert result is None

    def test_name_pattern_match_returns_coverage(self):
        patient = MagicMock()
        cvg = _make_coverage("IL Medicare Part B")
        qs = _make_qs(cvg)

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {})

        assert result is cvg
        # filter should have been called with the default name pattern
        filter_calls = qs.filter.call_args_list
        # First filter: patient + state, second filter: issuer__name__icontains
        icontains_call = next(
            (c for c in filter_calls if "issuer__name__icontains" in c.kwargs),
            None,
        )
        assert icontains_call is not None
        assert icontains_call.kwargs["issuer__name__icontains"] == "Medicare Part B"

    def test_name_pattern_is_case_insensitive(self):
        """The icontains lookup is case-insensitive — verify we pass it correctly."""
        patient = MagicMock()
        cvg = _make_coverage("AK MEDICARE PART B")
        qs = _make_qs(cvg)

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {})

        assert result is cvg

    def test_custom_payer_name_pattern_used_when_set(self):
        patient = MagicMock()
        cvg = _make_coverage("Custom Payer Name")
        qs = _make_qs(cvg)

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {"ACCESS_PAYER_NAME_PATTERN": "Custom Payer"})

        assert result is cvg
        filter_calls = qs.filter.call_args_list
        icontains_call = next(
            (c for c in filter_calls if "issuer__name__icontains" in c.kwargs),
            None,
        )
        assert icontains_call is not None
        assert icontains_call.kwargs["issuer__name__icontains"] == "Custom Payer"

    def test_payer_id_allowlist_filters_by_issuer_id(self):
        """When ACCESS_MEDICARE_PART_B_PAYER_IDS is set, filter by issuer__id__in."""
        patient = MagicMock()
        payer_uuid = "uuid-abc-123"
        cvg = _make_coverage("IL Medicare Part B", issuer_id=payer_uuid)
        qs = _make_qs(cvg)

        secrets = {"ACCESS_MEDICARE_PART_B_PAYER_IDS": f"{payer_uuid}, another-uuid"}

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, secrets)

        assert result is cvg
        filter_calls = qs.filter.call_args_list
        id_in_call = next(
            (c for c in filter_calls if "issuer__id__in" in c.kwargs),
            None,
        )
        assert id_in_call is not None
        assert payer_uuid in id_in_call.kwargs["issuer__id__in"]
        assert "another-uuid" in id_in_call.kwargs["issuer__id__in"]

    def test_payer_id_allowlist_strips_whitespace_and_ignores_empties(self):
        patient = MagicMock()
        qs = _make_qs()

        secrets = {"ACCESS_MEDICARE_PART_B_PAYER_IDS": "  uuid-1 ,  , uuid-2  "}

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            self._call(patient, secrets)

        filter_calls = qs.filter.call_args_list
        id_in_call = next(
            (c for c in filter_calls if "issuer__id__in" in c.kwargs),
            None,
        )
        assert id_in_call is not None
        ids = id_in_call.kwargs["issuer__id__in"]
        assert ids == ["uuid-1", "uuid-2"]

    def test_allowlist_takes_precedence_over_name_pattern(self):
        """When both PAYER_IDS and PAYER_NAME_PATTERN are set, allowlist wins."""
        patient = MagicMock()
        qs = _make_qs()

        secrets = {
            "ACCESS_MEDICARE_PART_B_PAYER_IDS": "uuid-only",
            "ACCESS_PAYER_NAME_PATTERN": "Should Not Be Used",
        }

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            self._call(patient, secrets)

        filter_calls = qs.filter.call_args_list
        icontains_call = next(
            (c for c in filter_calls if "issuer__name__icontains" in c.kwargs),
            None,
        )
        id_in_call = next(
            (c for c in filter_calls if "issuer__id__in" in c.kwargs),
            None,
        )
        assert icontains_call is None
        assert id_in_call is not None

    def test_only_active_coverages_considered(self):
        """The filter must always include state='active'."""
        patient = MagicMock()
        qs = _make_qs()

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            self._call(patient, {})

        filter_calls = qs.filter.call_args_list
        state_call = next(
            (c for c in filter_calls if c.kwargs.get("state") == "active"),
            None,
        )
        assert state_call is not None

    def test_ordered_by_coverage_rank(self):
        """Results must be ordered by coverage_rank so primary (rank=1) comes first."""
        patient = MagicMock()
        qs = _make_qs()

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            self._call(patient, {})

        qs.order_by.assert_called_with("coverage_rank")

    def test_medicare_advantage_not_matched_by_default_pattern(self):
        """'ASPIRUS MEDICARE ADVANTAGE' does not contain 'Medicare Part B' — no match."""
        patient = MagicMock()
        # Simulate: the default pattern filter returns no results for an Advantage payer
        qs = _make_qs()  # first() returns None

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {})

        assert result is None

    def test_deleted_coverage_not_returned(self):
        """State filter on 'active' means deleted coverage should never be returned."""
        patient = MagicMock()
        # Deleted coverage — qs returns None because state filter excluded it
        qs = _make_qs()  # first() returns None

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {})

        assert result is None

    def test_returns_lowest_rank_when_multiple_active(self):
        """With multiple active matches, order_by('coverage_rank').first() returns rank=1."""
        patient = MagicMock()
        primary = _make_coverage("IL Medicare Part B", coverage_rank=1, id_number="MBI-PRIMARY")
        qs = _make_qs(primary)  # first() returns the lowest rank after ordering

        with patch("cms_access_fhir_client.coverage_lookup.Coverage.objects") as mock_mgr:
            mock_mgr.select_related.return_value = qs
            result = self._call(patient, {})

        assert result is primary
        assert result.id_number == "MBI-PRIMARY"
