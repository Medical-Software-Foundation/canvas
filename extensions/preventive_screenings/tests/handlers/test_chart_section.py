"""Tests for the chart-summary section handler.

This is the only handler allowed to compute on chart open, and the only one
whose output is not stored - so the things worth pinning are that it renders
the live answer, that it declines to assert anything it does not know, and that
it never emits the configuration effect that would take over the practice's
chart layout.
"""

from datetime import date
from typing import Any
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Patient

from preventive_screenings.handlers import chart_section as handler_module
from preventive_screenings.handlers.chart_section import PreventiveScreeningChartSection

MODULE = "preventive_screenings.handlers.chart_section"
BORN = date(1970, 5, 2)


def mammogram(**over: Any) -> dict:
    out: dict[str, Any] = {
        "id": "s1",
        "enabled": True,
        "name": "Mammogram",
        "sex": "any",
        "min_age": 40,
        "max_age": 0,
        "grace_days": 90,
        "completions": [
            {"value_set_key": "mammography", "source": "imaging_report", "codes": [],
             "label": "", "interval_quantity": 2, "interval_unit": "years"}
        ],
        "exclusions": [],
        "order_command": "",
        "order_button": "",
        "order_code": "",
        "order_comment": "",
        "guidance": "",
    }
    out.update(over)
    return out


def section(
    target_id: Any, screenings: list[dict], monkeypatch: pytest.MonkeyPatch
) -> PreventiveScreeningChartSection:
    event = Mock()
    event.name = "PATIENT_CHART_SUMMARY__GET_CUSTOM_SECTION"
    event.target.id = target_id
    event.context = {"section": PreventiveScreeningChartSection.SECTION_KEY}
    monkeypatch.setattr(handler_module, "load_config", lambda: {"screenings": screenings})
    return PreventiveScreeningChartSection(event=event)


@pytest.fixture
def woman_of_50() -> Patient:
    return PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)


@pytest.mark.django_db
def test_the_section_renders_the_patients_screening_record(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    effects = section(str(woman_of_50.id), [mammogram()], monkeypatch).compute()

    assert len(effects) == 1
    assert "Mammogram" in effects[0].payload


@pytest.mark.django_db
def test_the_section_never_touches_the_practices_section_list(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The load-bearing assertion.** `PatientChartSummaryConfiguration`
    decides which sections appear rather than adding one, so emitting it would
    mean enumerating every built-in and overriding a layout the practice
    configured - on every instance this ships to."""
    effects = section(str(woman_of_50.id), [mammogram()], monkeypatch).compute()

    assert all("SHOW_PATIENT_CHART_SUMMARY_SECTIONS" not in str(e.type) for e in effects)


@pytest.mark.django_db
def test_no_configured_screenings_renders_nothing(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A practice that tracks nothing should not get an empty box on every
    chart."""
    assert section(str(woman_of_50.id), [], monkeypatch).compute() == []


@pytest.mark.django_db
def test_a_patient_who_cannot_be_assessed_gets_no_section(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deceased patient is not someone to recommend screening to, and an
    unknown birth date makes eligibility unknowable. Either way a section
    reading "no screenings apply" would assert something we do not know, and
    the brief calls a recommendation on the wrong patient the highest-stakes
    failure."""
    deceased = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=True)

    assert section(str(deceased.id), [mammogram()], monkeypatch).compute() == []


@pytest.mark.django_db
def test_an_event_with_no_target_renders_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert section("", [mammogram()], monkeypatch).compute() == []


@pytest.mark.django_db
def test_the_section_is_computed_live_and_stores_nothing(
    woman_of_50: Patient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason this surface has no staleness bug: unlike the cards, nothing
    is written, so there is no key to go stale and nothing to retract."""
    with patch(f"{MODULE}.review_patient", wraps=handler_module.review_patient) as spy:
        section(str(woman_of_50.id), [mammogram()], monkeypatch).compute()

    assert spy.call_count == 1


def test_the_handler_answers_only_to_its_own_section_key() -> None:
    """Canvas fans this event out to every section handler; answering somebody
    else's would put our markup in their box."""
    event = Mock()
    event.context = {"section": "somebody_elses_section"}

    assert PreventiveScreeningChartSection(event=event).accept_event() is False


def test_the_section_key_is_stable() -> None:
    """Part of the plugin's external surface once Canvas knows it, in the same
    way the seed screening ids are. Changing it orphans the section."""
    assert PreventiveScreeningChartSection.SECTION_KEY == "preventive_screenings"


def test_the_manifest_points_at_this_handler(manifest: dict[str, Any]) -> None:
    classes = [handler["class"] for handler in manifest["components"]["handlers"]]

    assert "preventive_screenings.handlers.chart_section:PreventiveScreeningChartSection" in (
        classes
    )
