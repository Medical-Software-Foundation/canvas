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


def test_render_admin_lists_active_staff() -> None:
    staff_a = MagicMock(id="00000000000000000000000000000010", full_name="Bea Adams")
    staff_b = MagicMock(id="00000000000000000000000000000011", full_name="Cy Brown")
    with (
        patch("external_calendar_busy_blocks.ui.pages.render_to_string", return_value="<html></html>") as mock_render,
        patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.ui.pages.Staff") as MockStaff,
    ):
        MockFeed.objects.filter.return_value.first.return_value = None
        MockStaff.objects.filter.return_value.order_by.return_value = [staff_a, staff_b]
        _page(
            "00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        ).render()
    context = mock_render.call_args.args[1]
    assert context["is_admin"] is True
    assert context["staff_options"] == [
        {"id": "00000000000000000000000000000010", "name": "Bea Adams"},
        {"id": "00000000000000000000000000000011", "name": "Cy Brown"},
    ]
    MockStaff.objects.filter.assert_called_once_with(active=True)
