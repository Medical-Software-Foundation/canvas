"""Tests for patient_panel.services.lookups (filter dropdowns)."""

__is_plugin__ = True

import pytest

from canvas_sdk.test_utils.factories import (
    CoverageFactory,
    FacilityFactory,
    PatientFactory,
    StaffFactory,
)

from patient_panel.services.lookups import (
    get_facilities,
    get_staff,
    get_unique_insurances,
)

pytestmark = pytest.mark.django_db


class FakeCache:
    """Minimal dict-backed cache matching the get/set surface the lookups use.

    Kept local so caching tests don't touch the shared plugin cache (which
    would leak global keys like 'facilities' across tests).
    """

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self.store.get(key, default)

    def set(self, key: str, value: object, timeout_seconds: int | None = None) -> None:
        self.store[key] = value


class TestGetStaff:
    def test_returns_staff_with_display_name(self) -> None:
        StaffFactory.create(first_name="Alice", last_name="Adams")
        result = get_staff()
        for entry in result:
            assert "id" in entry
            assert "display_name" in entry


class TestGetUniqueInsurances:
    def test_returns_sorted_distinct(self) -> None:
        from canvas_sdk.v1.data.coverage import CoverageStack

        patient = PatientFactory.create()
        CoverageFactory.create(patient=patient, stack=CoverageStack.IN_USE)
        CoverageFactory.create(patient=patient, stack=CoverageStack.IN_USE)

        result = get_unique_insurances()
        assert result == sorted(result)
        assert len(result) == len(set(result))

    def test_returns_empty_when_no_coverages(self) -> None:
        assert get_unique_insurances() == []


class TestDropdownCaching:
    """The filter-dropdown lookups run on every /table render. They accept an
    optional cache to avoid re-scanning population-sized tables each time.
    Without a cache they behave exactly as before (no behavior change).
    """

    def test_facilities_no_cache_passthrough(self) -> None:
        FacilityFactory.create(name="Clinic A")
        result = get_facilities()  # cache omitted → always live
        assert any(f["name"] == "Clinic A" for f in result)

    def test_facilities_served_from_cache(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        cache = FakeCache()
        FacilityFactory.create(name="Clinic A")
        first = get_facilities(cache)  # populates cache
        # A second facility added after the cache is warm must NOT appear until
        # the cache entry expires.
        FacilityFactory.create(name="Clinic B")
        with CaptureQueriesContext(connection) as ctx:
            second = get_facilities(cache)
        assert second == first
        assert [f["name"] for f in second] == ["Clinic A"]
        assert len(ctx.captured_queries) == 0  # cache hit issues no query

    def test_insurances_served_from_cache(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from canvas_sdk.v1.data.coverage import CoverageStack

        cache = FakeCache()
        patient = PatientFactory.create()
        CoverageFactory.create(patient=patient, stack=CoverageStack.IN_USE)
        first = get_unique_insurances(cache)
        with CaptureQueriesContext(connection) as ctx:
            second = get_unique_insurances(cache)
        assert second == first
        assert len(ctx.captured_queries) == 0
