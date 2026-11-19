"""perform_create must return a bare resource id whatever the Location header looks like."""

import pytest

from data_migrations.utils import resource_id_from_location

RID = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "location",
    [
        f"http://fumage-example.canvasmedical.com/Patient/{RID}",
        f"https://fumage-example.canvasmedical.com/Patient/{RID}",
        f"https://fumage-example.canvasmedical.com/Patient/{RID}/_history/1",
        f"https://fumage-example.canvasmedical.com/Patient/{RID}/_history/12",
        f"https://fumage-example.canvasmedical.com/Patient/{RID}/",
        f"http://localhost:8888/Patient/{RID}/_history/1",
        f"https://fumage-example.canvasmedical.com/Patient/{RID}?_format=json",
    ],
)
def test_any_scheme_or_host(location):
    assert resource_id_from_location("Patient", location) == RID


@pytest.mark.parametrize(
    "location",
    [
        "https://fumage-example.canvasmedical.com/Coverage/abc",
        "https://fumage-example.canvasmedical.com/Patient/",
        "",
    ],
)
def test_bad_header_raises(location):
    with pytest.raises(ValueError):
        resource_id_from_location("Patient", location)
