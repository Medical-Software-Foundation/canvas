from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.ui.pages import ConfigPage


def _page(logged_in_staff: str | None, secrets: dict | None = None) -> ConfigPage:
    headers = {}
    if logged_in_staff:
        headers["canvas-logged-in-user-id"] = logged_in_staff
    request = MagicMock(headers=headers)
    page = ConfigPage.__new__(ConfigPage)
    page.request = request
    page.secrets = secrets or {}
    return page


def test_render_non_admin_has_no_staff_options() -> None:
    with (
        patch("external_calendar_busy_blocks.ui.pages.render_to_string", return_value="<html></html>") as mock_render,
        patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed,
    ):
        MockFeed.objects.filter.return_value.first.return_value = None
        _page("00000000-0000-0000-0000-000000000002", secrets={}).render()
    context = mock_render.call_args.args[1]
    assert context["is_admin"] is False
    assert context["staff_options"] == []


def test_render_admin_lists_active_staff_with_per_row_status() -> None:
    staff_a = MagicMock(id="00000000000000000000000000000010", full_name="Bea Adams")
    staff_b = MagicMock(id="00000000000000000000000000000011", full_name="Cy Brown")
    staff_nameless = MagicMock(id="00000000000000000000000000000012", full_name="")
    # Bea has an active feed; Cy has none.
    feed_a = MagicMock(
        staff_id="00000000000000000000000000000010",
        is_active=True,
        last_sync_at="2026-07-12T10:00:00Z",
        last_error=None,
    )

    def filter_side_effect(*args, **kwargs):
        if "staff_id__in" in kwargs:
            # The single bulk status query. Assert it asked for exactly the
            # active, named staff ids (no per-row query → no N+1).
            assert set(kwargs["staff_id__in"]) == {
                "00000000000000000000000000000010",
                "00000000000000000000000000000011",
            }
            return [feed_a]
        # The admin's own self-service feed lookup.
        self_lookup = MagicMock()
        self_lookup.first.return_value = None
        return self_lookup

    # Bea has 7 imported events; Cy has none. Returned as values_list rows.
    imported_staff_ids = ["00000000000000000000000000000010"] * 7

    with (
        patch("external_calendar_busy_blocks.ui.pages.render_to_string", return_value="<html></html>") as mock_render,
        patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.ui.pages.ImportedEvent") as MockImported,
        patch("external_calendar_busy_blocks.ui.pages.Staff") as MockStaff,
    ):
        MockFeed.objects.filter.side_effect = filter_side_effect
        MockImported.objects.filter.return_value.values_list.return_value = imported_staff_ids
        MockStaff.objects.filter.return_value.order_by.return_value = [staff_a, staff_b, staff_nameless]
        _page(
            "00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        ).render()
    context = mock_render.call_args.args[1]
    assert context["is_admin"] is True
    assert context["staff_options"] == [
        {
            "id": "00000000000000000000000000000010",
            "name": "Bea Adams",
            "connected": True,
            "last_sync_at": "2026-07-12T10:00:00Z",
            "last_error": None,
            "event_count": 7,
        },
        {
            "id": "00000000000000000000000000000011",
            "name": "Cy Brown",
            "connected": False,
            "last_sync_at": None,
            "last_error": None,
            "event_count": 0,
        },
    ]
    assert all(opt["id"] != "00000000000000000000000000000012" for opt in context["staff_options"])
    MockStaff.objects.filter.assert_called_once_with(active=True)
    # Exactly one bulk feed query and one bulk event-count query (no N+1).
    bulk_feed_calls = [c for c in MockFeed.objects.filter.call_args_list if "staff_id__in" in c.kwargs]
    assert len(bulk_feed_calls) == 1
    assert set(MockImported.objects.filter.call_args.kwargs["staff_id__in"]) == {
        "00000000000000000000000000000010",
        "00000000000000000000000000000011",
    }
