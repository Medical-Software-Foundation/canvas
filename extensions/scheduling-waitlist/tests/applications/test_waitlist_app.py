"""The app-drawer entry point."""

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from scheduling_waitlist import CACHE_BUST
from scheduling_waitlist.applications.waitlist_app import WaitlistApp


def _open() -> LaunchModalEffect:
    app = WaitlistApp.__new__(WaitlistApp)
    return app.on_open()


class TestOnOpen:
    def test_launches_the_roster_page_url(self):
        effect = _open()

        assert effect.url.startswith("/plugin-io/api/scheduling_waitlist/app/")

    def test_url_carries_the_current_cache_bust_token(self):
        effect = _open()

        assert effect.url.endswith(f"?v={CACHE_BUST}")

    def test_serves_by_url_rather_than_inline_content(self):
        # Inlining would push the whole stylesheet and script into the effect
        # payload on every open, and cost the page its document origin.
        effect = _open()

        assert effect.content is None

    def test_opens_in_the_default_modal(self):
        effect = _open()

        assert effect.target == LaunchModalEffect.TargetType.DEFAULT_MODAL

    def test_modal_is_titled_for_the_app_drawer(self):
        effect = _open()

        assert effect.title == "Scheduling Waitlist"
