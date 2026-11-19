"""Tests for the chart-side screening record app.

This replaces a chart-summary section that could not be built without taking
over the practice's section list. What matters here is that it finds the right
patient, that it cannot be made to leak one, and that it opens beside the chart
rather than over it.
"""

from typing import Any
from unittest.mock import Mock

from preventive_screenings.applications.record_app import ScreeningRecordApplication


def app(context: Any) -> ScreeningRecordApplication:
    event = Mock()
    event.context = context
    return ScreeningRecordApplication(event=event)


def _url(effect: Any) -> str:
    return str(effect.payload)


def test_the_record_opens_for_the_patient_whose_chart_it_was_opened_from() -> None:
    """The patient arrives on the event's context, not on `target` - the base
    Application matches `target.id` against the app's own identifier, so target
    is the app rather than the chart."""
    effect = app({"patient": {"id": "abc-123"}}).on_open()

    assert "patient=abc-123" in _url(effect)


def test_the_record_opens_beside_the_chart_not_over_it() -> None:
    """A screening record is read *while* looking at the patient. It is also the
    closest thing available to the inline section this replaces."""
    effect = app({"patient": {"id": "abc-123"}}).on_open()

    assert "right_chart_pane" in _url(effect)


def test_opening_outside_a_chart_asks_for_no_patient_rather_than_guessing() -> None:
    """An app opened with no patient in context must not fall back to some other
    patient. The route answers with "nothing to show"."""
    effect = app({}).on_open()

    assert "patient=&" in _url(effect)


def test_a_context_without_an_id_is_treated_the_same_way() -> None:
    effect = app({"patient": {}}).on_open()

    assert "patient=&" in _url(effect)


def test_the_url_is_cache_busted_so_a_redeploy_is_never_served_stale() -> None:
    effect = app({"patient": {"id": "abc-123"}}).on_open()

    assert "&v=" in _url(effect)


def test_the_manifest_registers_it_against_a_patient(manifest: dict[str, Any]) -> None:
    """`patient_specific` is what puts the icon on a chart rather than in the
    global app drawer, where it would have no patient to report on."""
    entry = next(
        a
        for a in manifest["components"]["applications"]
        if a["class"].endswith("record_app:ScreeningRecordApplication")
    )

    assert entry["scope"] == "patient_specific"
    assert entry["icon"]
