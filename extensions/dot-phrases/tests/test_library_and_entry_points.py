from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, patch

import pytest

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
        values = placeholder_values(patient, note, today=date(2026, 10, 13), needed=set())
    assert values["age"] == "67"
    assert values["dob"] == "03/14/1959"
    assert values["subject_pronoun"] == "she"
    assert values["provider"] == "Sam Lee"
    assert values["after_hours_line"] == "(555) 010-2000"
    assert "preferred_name" not in values  # no nickname, so {preferred_name} stays for the provider


def _chart_patient() -> Any:
    return SimpleNamespace(first_name="Jane", nickname="", last_name="Sample", birth_date=date(1959, 3, 14), preferred_pronouns="", mrn="A1B2C3D4E", business_line_id=4)


class TestChartLookups:
    @pytest.fixture
    def models(self) -> Any:
        with (
            patch("dot_phrases.library.practice_values", return_value={}),
            patch("dot_phrases.library.BusinessLine") as business_line,
            patch("dot_phrases.library.PatientFacilityAddress") as facility,
            patch("dot_phrases.library.Appointment") as appointment,
            patch("dot_phrases.library.Coverage") as coverage,
            patch("dot_phrases.library.PatientMetadata") as metadata,
        ):
            yield SimpleNamespace(business_line=business_line, facility=facility, appointment=appointment, coverage=coverage, metadata=metadata)

    def test_only_looks_up_what_the_phrase_uses(self, models: Any) -> None:
        models.facility.objects.filter.return_value.select_related.return_value.order_by.return_value = []
        values = placeholder_values(_chart_patient(), None, today=date(2026, 10, 20), needed={"facility"})
        assert values["mrn"] == "A1B2C3D4E"
        models.facility.objects.filter.assert_called_once_with(patient=ANY, state="active")
        models.business_line.objects.filter.assert_not_called()
        models.appointment.objects.filter.assert_not_called()
        models.coverage.objects.filter.assert_not_called()

    def test_business_line_name(self, models: Any) -> None:
        models.business_line.objects.filter.return_value.values_list.return_value.first.return_value = "Demo Health"
        values = placeholder_values(_chart_patient(), None, today=date(2026, 10, 20), needed={"business_line"})
        assert values["business_line"] == "Demo Health"
        models.business_line.objects.filter.assert_called_once_with(dbid=4)

    def test_every_active_facility_is_listed_with_its_room(self, models: Any) -> None:
        rows = [
            SimpleNamespace(facility=SimpleNamespace(name="Sunrise Assisted Living"), room_number="12"),
            SimpleNamespace(facility=SimpleNamespace(name="Oak Park SNF"), room_number=""),
        ]
        models.facility.objects.filter.return_value.select_related.return_value.order_by.return_value = rows
        values = placeholder_values(_chart_patient(), None, today=date(2026, 10, 20), needed={"facility", "room_number"})
        assert values["facility"] == "Sunrise Assisted Living and Oak Park SNF"
        assert values["room_number"] == "12"

    def test_primary_coverage_in_use_on_the_visit_day(self, models: Any) -> None:
        coverage = SimpleNamespace(issuer=SimpleNamespace(name="Blue Cross Blue Shield"), plan="PPO Gold", id_number="XYZ123", group="G-55012")
        chain = models.coverage.objects.filter.return_value.filter.return_value.select_related.return_value.order_by.return_value
        chain.first.return_value = coverage
        note = SimpleNamespace(provider=None, datetime_of_service=datetime(2026, 10, 15, 16, 0, tzinfo=UTC), location_id=None, dbid=9)
        values = placeholder_values(_chart_patient(), note, today=date(2026, 10, 20), needed={"insurance", "plan", "member_id", "group_number"})
        assert (values["insurance"], values["plan"], values["member_id"], values["group_number"]) == ("Blue Cross Blue Shield", "PPO Gold", "XYZ123", "G-55012")
        assert models.coverage.objects.filter.call_args.kwargs == {"patient": ANY, "coverage_rank": 1, "stack": "IN_USE", "coverage_start_date__lte": date(2026, 10, 15)}

    def test_last_and_next_visit_skip_cancelled_no_shows_and_this_note(self, models: Any) -> None:
        models.appointment.objects.filter.return_value.values_list.return_value = [3]
        visits = models.appointment.objects.filter.return_value.exclude.return_value.exclude.return_value
        found = visits.exclude.return_value.filter.return_value.order_by.return_value.values_list.return_value
        found.first.side_effect = [datetime(2026, 9, 2, 10, 0, tzinfo=UTC), datetime(2099, 11, 5, 21, 30, tzinfo=UTC)]
        note = SimpleNamespace(provider=None, datetime_of_service=datetime(2026, 10, 15, 16, 0, tzinfo=UTC), location_id=None, dbid=9)
        values = placeholder_values(_chart_patient(), note, today=date(2026, 10, 20), needed={"last_visit", "next_visit"})
        assert values["last_visit"] == "09/02/2026 at 10:00 AM"
        assert values["next_visit"] == "11/05/2099 at 9:30 PM"
        models.appointment.objects.filter.return_value.exclude.assert_called_once_with(status__in=["cancelled", "noshowed"])
        models.appointment.objects.filter.return_value.exclude.return_value.exclude.assert_called_once_with(dbid__in=[3])
        visits.exclude.assert_called_once_with(note_id=9)

    def test_practice_location_from_the_note(self, models: Any) -> None:
        note = SimpleNamespace(provider=None, datetime_of_service=None, location_id=2, location=SimpleNamespace(full_name="Demo Clinic"), dbid=9)
        values = placeholder_values(_chart_patient(), note, today=date(2026, 10, 20), needed={"practice_location"})
        assert values["practice_location"] == "Demo Clinic"

    def test_custom_placeholder_reads_patient_metadata(self, models: Any, practice_settings: Any) -> None:
        practice_settings["custom_placeholders"] = {"program": "program_name", "coordinator": "care_coordinator"}
        models.metadata.objects.filter.return_value.values_list.return_value = [("program_name", "Healthy Hearts")]
        values = placeholder_values(_chart_patient(), None, today=date(2026, 10, 20), needed={"program"})
        assert values["program"] == "Healthy Hearts"
        assert models.metadata.objects.filter.call_args.kwargs == {"patient": ANY, "key__in": {"program_name"}}


def test_enabled_chart_placeholders_default_and_saved(practice_settings: Any) -> None:
    from dot_phrases.library import enabled_chart_placeholders

    default = enabled_chart_placeholders()
    assert default == [
        "first_name", "preferred_name", "last_name", "age", "dob",
        "subject_pronoun", "object_pronoun", "possessive_pronoun", "today", "provider", "practice_location",
    ]
    practice_settings["chart_placeholders"] = ["mrn", "first_name"]
    assert enabled_chart_placeholders() == ["first_name", "mrn"]


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

    def test_shown_before_check_in_for_precharting(self) -> None:
        with patch("dot_phrases.handlers.panel_button.CurrentNoteStateEvent") as states:
            for state, shown in (("SCH", True), ("BKD", True), ("CVD", True), ("RVT", True), ("SGN", False), ("CLD", False), ("NSW", False), ("DLT", False)):
                states.objects.filter.return_value.values_list.return_value.first.return_value = state
                assert self.button().visible() is shown, state

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

    def test_every_staff_member_sees_it(self) -> None:
        assert self.app("abc").visible() is True
        assert self.app("xyz").visible() is True
        assert self.app("abc", team="").visible() is True
        assert self.app("").visible() is False

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


def _label_note(title: str = "") -> Any:
    from datetime import UTC, datetime

    return SimpleNamespace(
        dbid=5,
        title=title,
        note_type_version=SimpleNamespace(name="Home visit"),
        datetime_of_service=datetime(2026, 10, 15, 13, 0, tzinfo=UTC),
        provider=SimpleNamespace(first_name="Canvas", last_name="Support"),
    )


def _rfvs(model: Any, rows: list[Any]) -> None:
    model.objects.committed.return_value.filter.return_value.prefetch_related.return_value.order_by.return_value = rows
    model.string_from_narrative_json.side_effect = lambda doc: (doc or {}).get("text", "")


def _rfv(text: str = "", codes: tuple[str, ...] = ()) -> Any:
    codings = [SimpleNamespace(display=c) for c in codes]
    return SimpleNamespace(narrative_json={"text": text} if text else None, codings=SimpleNamespace(all=lambda: codings))


def test_note_label_falls_back_to_the_note_type_without_a_reason_for_visit() -> None:
    from dot_phrases.library import note_label

    with patch("dot_phrases.library.ReasonForVisit") as model:
        _rfvs(model, [])
        assert note_label(_label_note()) == {"title": "Home visit", "when": "2026-10-15T13:00:00+00:00", "provider": "Canvas Support"}
        assert note_label(_label_note(title="Follow-up call"))["title"] == "Follow-up call"
    model.objects.committed.return_value.filter.assert_called_with(note_id=5)


def test_note_label_uses_the_first_reason_for_visit_like_the_note_heading() -> None:
    from dot_phrases.library import note_label

    with patch("dot_phrases.library.ReasonForVisit") as model:
        _rfvs(model, [_rfv(text="RFV 1"), _rfv(text="RFV 2")])
        assert note_label(_label_note(title="Follow-up call"))["title"] == "RFV 1"


def test_note_label_uses_the_code_name_for_a_coded_reason() -> None:
    from dot_phrases.library import note_label

    with patch("dot_phrases.library.ReasonForVisit") as model:
        _rfvs(model, [_rfv(), _rfv(codes=("Old code", "Annual wellness visit"))])
        assert note_label(_label_note())["title"] == "Annual wellness visit"


def test_note_label_prefers_the_code_name_over_the_comment() -> None:
    from dot_phrases.library import note_label

    with patch("dot_phrases.library.ReasonForVisit") as model:
        _rfvs(model, [_rfv(text="party time", codes=("RFV 1",))])
        assert note_label(_label_note())["title"] == "RFV 1"
