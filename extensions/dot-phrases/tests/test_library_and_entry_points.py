from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from dot_phrases.handlers.admin_app import DotPhrasesAdminApp
from dot_phrases.handlers.panel_button import DotPhrasesButton
from dot_phrases.library import admin_team_name, hidden_ids, is_admin, placeholder_values, usable_phrases


def p(code: str, scope: str, dbid: int) -> Any:
    return SimpleNamespace(code=code, scope=scope, dbid=dbid)


class TestAdmins:
    def test_reads_the_team_name(self) -> None:
        assert admin_team_name({"ADMIN_TEAM": "  Dot Phrase Admins "}) == "Dot Phrase Admins"

    def test_members_of_the_team_are_admins_whatever_the_capitals(self) -> None:
        assert is_admin("abc", {"ADMIN_TEAM": "Dot Phrase Admins"})
        assert is_admin("abc", {"ADMIN_TEAM": "dot phrase admins"})
        assert not is_admin("xyz", {"ADMIN_TEAM": "Dot Phrase Admins"})

    def test_fails_closed_when_empty_missing_or_no_such_team(self) -> None:
        assert not is_admin("abc", {"ADMIN_TEAM": ""})
        assert not is_admin("abc", {})
        assert not is_admin(None, {"ADMIN_TEAM": "Dot Phrase Admins"})
        assert not is_admin("abc", {"ADMIN_TEAM": "Renamed Team"})


def test_personal_phrase_is_used_instead_of_a_practice_phrase_with_the_same_code() -> None:
    rows = [p("fu2w", "practice", 1), p("fu2w", "personal", 2), p("dmed", "practice", 3)]
    with patch("dot_phrases.library.Phrase") as model:
        model.objects.filter.return_value.select_related.return_value.order_by.return_value = rows
        found = usable_phrases(10)
    assert found["fu2w"].dbid == 2
    assert found["dmed"].dbid == 3
    model.objects.filter.return_value.select_related.return_value.order_by.assert_called_once_with("dbid")


def test_a_code_saved_twice_always_uses_the_oldest_row() -> None:
    rows = [p("fu2w", "practice", 4), p("fu2w", "practice", 9)]
    with patch("dot_phrases.library.Phrase") as model:
        model.objects.filter.return_value.select_related.return_value.order_by.return_value = rows
        assert usable_phrases(10)["fu2w"].dbid == 4


def test_placeholder_values_from_the_chart() -> None:
    patient = SimpleNamespace(first_name="Jane", nickname="", last_name="Sample", birth_date=date(1959, 3, 14), preferred_pronouns="she/her")
    note = SimpleNamespace(provider=SimpleNamespace(first_name="Sam", last_name="Lee"))
    with patch("dot_phrases.library.practice_values", return_value={"after_hours_line": "(555) 010-2000"}):
        values = placeholder_values(patient, note, today=date(2026, 10, 13))
    assert values["age"] == "67"
    assert values["dob"] == "03/14/1959"
    assert values["subject_pronoun"] == "she"
    assert values["provider"] == "Sam Lee"
    assert values["after_hours_line"] == "(555) 010-2000"
    assert "preferred_name" not in values  # no nickname, so {preferred_name} stays for the provider


class TestPanelButton:
    def button(self, note_id: Any = 5) -> DotPhrasesButton:
        return DotPhrasesButton(SimpleNamespace(type=0, context={"note_id": note_id}, target=SimpleNamespace(id="patient-1")))

    def test_shown_on_editable_notes_only(self) -> None:
        with patch("dot_phrases.handlers.panel_button.CurrentNoteStateEvent") as states:
            states.objects.filter.return_value.values_list.return_value.first.return_value = "NEW"
            assert self.button().visible() is True
            states.objects.filter.return_value.values_list.return_value.first.return_value = "LKD"
            assert self.button().visible() is False
        assert self.button(note_id=None).visible() is False

    def test_opens_the_chart_panel_for_the_note(self) -> None:
        with patch("dot_phrases.handlers.panel_button.Note") as notes:
            notes.objects.filter.return_value.values_list.return_value.first.return_value = "note-uuid"
            effects = self.button().handle()
        data = json.loads(effects[0].payload)["data"]
        assert data["url"] == "/plugin-io/api/dot_phrases/panel/?note_id=note-uuid"
        assert data["target"] == "right_chart_pane"


class TestAdminApp:
    def app(self, staff_id: str, team: str = "Dot Phrase Admins") -> DotPhrasesAdminApp:
        event = SimpleNamespace(type=0, context={"user": {"id": staff_id}, "scope": "panel"}, target=SimpleNamespace(id=""))
        return DotPhrasesAdminApp(event, secrets={"ADMIN_TEAM": team})

    def test_only_team_members_see_it(self) -> None:
        assert self.app("abc").visible() is True
        assert self.app("xyz").visible() is False
        assert self.app("abc", team="").visible() is False

    def test_hidden_inside_a_patient_chart(self) -> None:
        app = self.app("abc")
        app.event.context["patient"] = {"id": "patient-uuid"}
        assert app.visible() is False

    def test_opens_the_admin_page(self) -> None:
        effect = self.app("abc").on_open()
        data = json.loads(effect.payload)["data"]  # type: ignore[union-attr]
        assert data["url"] == "/plugin-io/api/dot_phrases/admin/"


def test_hidden_ids_are_per_staff_member_and_empty_without_one() -> None:
    assert hidden_ids(None) == set()
    with patch("dot_phrases.library.PhraseHidden") as model:
        model.objects.filter.return_value.values_list.return_value = [5, 8]
        assert hidden_ids(10) == {5, 8}
    model.objects.filter.assert_called_once_with(staff_id=10)


def test_today_uses_the_providers_time_zone_then_the_patients() -> None:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from dot_phrases.library import local_today

    provider_note = SimpleNamespace(provider=SimpleNamespace(last_known_timezone="Pacific/Kiritimati"))
    assert local_today(None, provider_note) == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    patient = SimpleNamespace(last_known_timezone="Pacific/Pago_Pago")
    assert local_today(patient, SimpleNamespace(provider=None)) == datetime.now(ZoneInfo("Pacific/Pago_Pago")).date()
    assert local_today(SimpleNamespace(last_known_timezone="Not/AZone"), None) == datetime.now(UTC).date()


def test_today_accepts_a_stored_zone_object() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from dot_phrases.library import local_today

    note = SimpleNamespace(provider=SimpleNamespace(last_known_timezone=ZoneInfo("Asia/Tokyo")))
    assert local_today(None, note) == datetime.now(ZoneInfo("Asia/Tokyo")).date()


def test_browser_zone_comes_first_then_the_remembered_one(library_cache_and_calendars: Any) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from dot_phrases.library import local_today, remember_timezone

    provider_note = SimpleNamespace(provider=SimpleNamespace(last_known_timezone="Asia/Tokyo"))
    assert local_today(None, provider_note, zone_name="Pacific/Kiritimati") == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert remember_timezone(10, "Pacific/Pago_Pago") == "Pacific/Pago_Pago"
    assert local_today(None, provider_note, owner_dbid=10) == datetime.now(ZoneInfo("Pacific/Pago_Pago")).date()


def test_a_made_up_browser_zone_is_not_remembered(library_cache_and_calendars: Any) -> None:
    from dot_phrases.library import remember_timezone, remembered_timezone

    assert remember_timezone(10, "Not/AZone") is None
    assert remembered_timezone(10) is None


def test_calendars_decide_when_nobody_has_a_time_zone(library_cache_and_calendars: Any) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from dot_phrases.library import local_today

    library_cache_and_calendars.calendar.objects.values_list.return_value = ["Pacific/Kiritimati", "Pacific/Kiritimati", "UTC", "Asia/Tokyo"]
    assert local_today(None, None) == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
