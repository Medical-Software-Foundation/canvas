from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.apps.busy_blocks_app import BusyBlocksApplication


def test_on_open_launches_modal_to_config_page() -> None:
    event = MagicMock()
    event.target.id = "external_calendar_busy_blocks.apps.busy_blocks_app:BusyBlocksApplication"
    app = BusyBlocksApplication(event=event)
    effect = app.on_open()
    # The effect's serialized form should reference our plugin's config URL
    assert "external_calendar_busy_blocks" in str(effect) or "external_calendar_busy_blocks" in effect.payload.decode()


def test_config_page_renders_disconnected_state() -> None:
    from external_calendar_busy_blocks.ui.pages import ConfigPage

    request = MagicMock(headers={"canvas-logged-in-user-id": "staff-abc"})
    page = ConfigPage.__new__(ConfigPage)
    page.request = request
    page.secrets = {}

    with patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = None
        responses = page.render()
    html = responses[0].content.decode()
    assert "Paste" in html or "ical" in html.lower()


def test_config_page_renders_connected_state() -> None:
    from datetime import datetime, timezone
    from external_calendar_busy_blocks.ui.pages import ConfigPage

    request = MagicMock(headers={"canvas-logged-in-user-id": "staff-abc"})
    page = ConfigPage.__new__(ConfigPage)
    page.request = request
    page.secrets = {}

    feed = MagicMock(
        last_sync_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        last_error=None,
        is_active=True,
    )
    with patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = feed
        responses = page.render()
    html = responses[0].content.decode()
    assert "Disconnect" in html
