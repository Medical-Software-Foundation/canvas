from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from failed_fax_dashboard.services.failures import collect_sent, cutoff_for
from tests.helpers import make_event

pytestmark = pytest.mark.django_db

# Large text columns the dashboard never reads.
UNUSED = ('."body"', '."body_content"', '."content"')


@pytest.mark.parametrize("type_key", ["note", "referral", "imaging_order", "lab_order", "letter"])
def test_dashboard_rows_do_not_load_note_bodies_or_letter_text(type_key: str) -> None:
    make_event(type_key)

    with CaptureQueriesContext(connection) as queries:
        rows: list[Any] = collect_sent(cutoff_for(None))

    assert len(rows) == 1
    loaded = " ".join(query["sql"] for query in queries.captured_queries)
    assert [column for column in UNUSED if column in loaded] == []


def test_show_dismissed_builds_the_lists_once() -> None:
    from failed_fax_dashboard.models import FaxDismissal
    from failed_fax_dashboard.services.dashboard import dashboard_page
    from tests.helpers import make_staff

    staff = make_staff()
    for type_key in ("note", "referral", "lab_order", "letter"):
        make_event(type_key)
    dismissed = make_event("note", number="+15555550199")
    FaxDismissal.objects.create(
        source_type="note", source_id=str(dismissed.id), dismissed_by=staff.id, dismissed_at=dismissed.created
    )

    def count(**params: str) -> int:
        with CaptureQueriesContext(connection) as queries:
            dashboard_page("sent", params, staff.id)
        return len(queries)

    # Show dismissed adds only its own lookups (recent dismissals, who dismissed them),
    # not a second build of every list.
    assert count(dismissed="1") - count() <= 2
