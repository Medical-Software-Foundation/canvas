"""Test the admin Application opens the modal at the admin route."""

from gcal_sync.applications.google_calendar_admin import GoogleCalendarAdmin


def test_on_open_returns_modal_effect():
    app = GoogleCalendarAdmin.__new__(GoogleCalendarAdmin)
    effect = app.on_open()
    assert effect is not None
    # The modal points at the admin API route.
    assert "google/admin" in str(getattr(effect, "payload", effect))
