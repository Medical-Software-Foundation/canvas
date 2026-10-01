from typing import Any

import pytest

from failed_fax_dashboard.models import DashboardPreference
from failed_fax_dashboard.services.preferences import (
    clean_views,
    default_tab_view,
    load_views,
    reset_views,
    save_views,
)
from tests.helpers import make_staff

pytestmark = pytest.mark.django_db


def test_nothing_saved_means_the_defaults_for_both_tabs() -> None:
    staff = make_staff()

    assert load_views(staff.id) == {
        "sent": {
            "q": "",
            "people": [],
            "kinds": [],
            "sort": {"key": "when", "dir": -1},
            "collapsed": {"mine": False, "rest": False},
        },
        "received": {
            "q": "",
            "people": [],
            "sort": {"key": "when", "dir": -1},
            "collapsed": {"mine": False, "rest": False},
        },
    }


def test_settings_are_saved_per_staff_member_and_replaced_on_the_next_save() -> None:
    first, second = make_staff("A", "One"), make_staff("B", "Two")
    saved: dict[str, Any] = {
        "sent": {
            "q": "delgado",
            "kinds": ["note"],
            "people": ["__me", "team:abc"],
            "sort": {"key": "patient", "dir": 1},
            "collapsed": {"mine": False, "rest": True},
        },
        "received": {"sort": {"key": "task", "dir": -1}},
    }

    assert save_views(first.id, saved) is True
    assert save_views(first.id, {"sent": {"q": "later"}}) is True

    assert DashboardPreference.objects.count() == 1
    assert load_views(first.id)["sent"]["q"] == "later"
    assert load_views(first.id)["sent"]["sort"] == {"key": "when", "dir": -1}
    assert load_views(second.id)["sent"]["q"] == ""
    assert save_views(second.id, saved) is True
    assert load_views(second.id)["sent"] == {**default_tab_view("sent"), **saved["sent"]}
    assert load_views(second.id)["received"]["sort"] == {"key": "task", "dir": -1}


def test_saving_for_someone_who_is_not_staff_saves_nothing() -> None:
    assert save_views("nobody", {"sent": {"q": "x"}}) is False
    assert DashboardPreference.objects.count() == 0


def test_reset_clears_the_saved_settings() -> None:
    staff = make_staff()
    save_views(staff.id, {"sent": {"q": "x"}})

    reset_views(staff.id)

    assert DashboardPreference.objects.count() == 0
    assert load_views(staff.id)["sent"]["q"] == ""


def test_untrusted_settings_are_cleaned() -> None:
    cleaned = clean_views(
        {
            "sent": {
                "q": 5,
                "kinds": ["note", 7, None],
                "people": "nope",
                "sort": {"key": "task", "dir": 1},
                "collapsed": {"mine": "yes", "rest": True},
                "extra": "dropped",
            },
            "received": {"kinds": ["note"], "sort": {"key": "recipient", "dir": 0}, "collapsed": []},
            "other": {},
        }
    )

    assert cleaned["sent"] == {
        "q": "",
        "kinds": ["note"],
        "people": [],
        "sort": {"key": "when", "dir": -1},
        "collapsed": {"mine": False, "rest": True},
    }
    assert cleaned["received"] == default_tab_view("received")
    assert set(cleaned) == {"sent", "received"}
    assert clean_views("junk") == clean_views({})
    assert clean_views({"sent": "junk"})["sent"] == default_tab_view("sent")


def test_long_search_text_is_cut() -> None:
    assert len(clean_views({"sent": {"q": "x" * 1000}})["sent"]["q"]) == 200
