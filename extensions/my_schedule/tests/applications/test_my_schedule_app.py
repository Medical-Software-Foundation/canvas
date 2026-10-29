"""Tests for my_schedule.applications.my_schedule_app."""

import json

from my_schedule.applications.my_schedule_app import MyScheduleApp


def test_opens_full_page() -> None:
    app = MyScheduleApp.__new__(MyScheduleApp)
    effect = app.on_open()
    data = json.loads(effect.payload)["data"]
    assert data["url"] == "/plugin-io/api/my_schedule/app/"
    assert data["target"] == "page"
