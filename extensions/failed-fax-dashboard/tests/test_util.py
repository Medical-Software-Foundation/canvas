from datetime import datetime, timezone

from failed_fax_dashboard.services.util import chunked, format_local, full_url, practice_zone, to_e164


def test_numbers_become_e164() -> None:
    assert [to_e164(n) for n in ("(555) 555-0100", "1-555-555-0100", "+15555550100", "", "n/a")] == [
        "+15555550100", "+15555550100", "+15555550100", "", "",
    ]


def test_full_url_needs_an_identifier_and_an_internal_path() -> None:
    assert full_url({"CUSTOMER_IDENTIFIER": "acme"}, "/x?y=1") == "https://acme.canvasmedical.com/x?y=1"
    assert full_url({}, "/x") == "/x"
    assert full_url({"CUSTOMER_IDENTIFIER": "acme"}, "https://other") == "https://other"


def test_local_time_format_uses_the_practice_zone() -> None:
    zone = practice_zone({"INSTALLATION_TIME_ZONE": "America/New_York"})

    assert format_local(datetime(2026, 10, 1, 19, 5, tzinfo=timezone.utc), zone) == "Oct 1, 3:05 PM"
    assert format_local(datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), practice_zone(None)) == "Oct 1, 4:00 AM"
    assert format_local(datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), practice_zone(None)) == "Oct 1, 12:00 AM"


def test_chunked_splits_evenly() -> None:
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
