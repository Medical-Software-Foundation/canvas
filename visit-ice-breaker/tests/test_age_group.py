from datetime import date

from visit_ice_breaker.structures.age_group import AgeGroup


def test_from_birth_date() -> None:
    reference_date: date = date(2025, 6, 15)
    tests = [
        (date(2025, 1, 1), AgeGroup.KIDS),
        (date(2020, 6, 15), AgeGroup.KIDS),
        (date(2013, 6, 16), AgeGroup.KIDS),
        (date(2013, 6, 15), AgeGroup.KIDS),
        (date(2013, 6, 14), AgeGroup.KIDS),
        (date(2012, 6, 16), AgeGroup.KIDS),
        (date(2012, 6, 15), AgeGroup.TEENS),
        (date(2012, 7, 1), AgeGroup.KIDS),
        (date(2008, 6, 16), AgeGroup.TEENS),
        (date(2008, 6, 15), AgeGroup.TEENS),
        (date(2007, 6, 16), AgeGroup.TEENS),
        (date(2007, 6, 15), AgeGroup.ADULTS),
        (date(1990, 1, 1), AgeGroup.ADULTS),
        (date(1961, 6, 16), AgeGroup.ADULTS),
        (date(1961, 6, 15), AgeGroup.ADULTS),
        (date(1960, 6, 16), AgeGroup.ADULTS),
        (date(1960, 6, 15), AgeGroup.SENIORS),
        (date(1940, 1, 1), AgeGroup.SENIORS),
    ]
    for birth_date, expected in tests:
        result: AgeGroup = AgeGroup.from_birth_date(birth_date, today=reference_date)
        assert result == expected, f"birth_date={birth_date} expected={expected} got={result}"
