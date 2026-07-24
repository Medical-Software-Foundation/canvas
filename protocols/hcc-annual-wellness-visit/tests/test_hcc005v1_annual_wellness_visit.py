"""Tests for the HCC005v1 - Annual Wellness Visit protocol plugin."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import arrow
import pytest

from canvas_sdk.events import EventType
from protocols.hcc005v1_annual_wellness_visit import Hcc005v1

PROTOCOL_MODULE = "protocols.hcc005v1_annual_wellness_visit"


def _make_protocol(patient_id: str = "patient-id") -> Hcc005v1:
    """Build an Hcc005v1 with a PATIENT_UPDATED event for ``patient_id``."""
    event = MagicMock()
    event.type = EventType.PATIENT_UPDATED
    event.target = MagicMock()
    event.target.id = patient_id
    protocol = Hcc005v1(event=event)
    protocol._patient_id = patient_id  # short-circuit DB lookup in patient_id_from_target
    return protocol


def _billing_line_item(created_iso: str) -> MagicMock:
    """Build a fake BillingLineItem with a ``created`` datetime attribute."""
    item = MagicMock()
    item.created = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    return item


def _patient(birth_date: date, first_name: str = "Jim") -> MagicMock:
    """Build a fake Patient with the attributes the protocol reads."""
    patient = MagicMock()
    patient.first_name = first_name
    patient.birth_date = birth_date

    def age_at(time: arrow.Arrow) -> float:
        bd = arrow.get(birth_date)
        return (time.date() - bd.date()).days / 365.25

    patient.age_at.side_effect = age_at
    return patient


def test_meta_identifiers() -> None:
    """Identifier and type Meta values are preserved from the source protocol."""
    assert Hcc005v1.Meta.identifiers == ["HCC005v1"]
    assert Hcc005v1.Meta.types == ["HCC"]


def test_meta_description() -> None:
    """Description Meta value is preserved (including the original double-space typo)."""
    assert Hcc005v1.Meta.description == "Patient 65 or older due  for Annual Wellness Visit."


def test_meta_information() -> None:
    """Information URL Meta value is preserved."""
    assert (
        Hcc005v1.Meta.information
        == "https://canvas-medical.help.usepylon.com/articles/3810882246-protocol-annual-wellness-visit-hcc005v1"
    )


def test_meta_version() -> None:
    """Version Meta value is preserved."""
    assert Hcc005v1.Meta.version == "2019-11-04v1"


def test_meta_default_permission_flag() -> None:
    """The instruct permission flag is registered in Meta."""
    assert Hcc005v1.Meta.default_permission_flags == {
        "protocols:actions:HCC005v1:instruct": True
    }


def test_responds_to_billing_and_patient_events() -> None:
    """Protocol responds to billing-line-item, patient, and protocol-override events."""
    expected = {
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_CREATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_DELETED),
    }
    assert expected.issubset(set(Hcc005v1.RESPONDS_TO))


@patch(f"{PROTOCOL_MODULE}.Patient")
def test_in_initial_population_true_for_old_enough_patient(patient_cls: MagicMock) -> None:
    """Patients older than 65 at the timeframe end are in the initial population."""
    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1))
    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    assert protocol.in_initial_population() is True


@patch(f"{PROTOCOL_MODULE}.Patient")
def test_in_initial_population_false_for_young_patient(patient_cls: MagicMock) -> None:
    """Patients not yet 65 at the timeframe end are not in the initial population."""
    patient_cls.objects.get.return_value = _patient(date(1990, 1, 1))
    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    assert protocol.in_initial_population() is False


@patch(f"{PROTOCOL_MODULE}.Patient")
def test_in_denominator_matches_initial_population(patient_cls: MagicMock) -> None:
    """in_denominator delegates to in_initial_population."""
    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1))
    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    assert protocol.in_denominator() is True

    patient_cls.objects.get.return_value = _patient(date(1990, 1, 1))
    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    assert protocol.in_denominator() is False


@pytest.mark.parametrize(
    "cpt, within_window, in_numerator_expected",
    [
        # within the timeframe window (2017-08-23 .. 2018-08-23):
        ("G0437", True, True),  # non-qualifying CPT -> no visit found -> in numerator
        ("G0438", True, False),
        ("G0439", True, False),
        ("G0402", True, False),
        ("99387", True, False),
        ("99397", True, False),
        ("99999", True, True),  # non-qualifying CPT
        # outside the timeframe window (one year earlier): never in numerator? No: outside the
        # timeframe means no qualifying visit was found, so in_numerator is True.
        ("G0438", False, True),
        ("G0439", False, True),
    ],
)
@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_in_numerator_by_cpt(
    patient_cls: MagicMock,
    billing_cls: MagicMock,
    cpt: str,
    within_window: bool,
    in_numerator_expected: bool,
) -> None:
    """A qualifying CPT inside the timeframe satisfies the protocol; everything else is due."""
    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1))

    created_iso = "2018-07-13T21:41:21.407046+00:00" if within_window else "2017-07-13T21:41:21.407046+00:00"
    item = _billing_line_item(created_iso)
    item.cpt = cpt

    # The protocol filters by value-set CPT (G0438/G0439/G0402/99387/99397) at the DB layer
    # via .find(Hcc005v1AnnualWellnessVisit). Simulate that here: only return the item if its
    # CPT is in the qualifying set.
    qualifying = {"G0438", "G0439", "G0402", "99387", "99397"}
    matched = [item] if cpt in qualifying else []
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = matched

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    assert protocol.in_numerator() is in_numerator_expected


@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_in_numerator_true_when_no_billing_items(
    patient_cls: MagicMock, billing_cls: MagicMock
) -> None:
    """A patient with no billing line items is in the numerator (i.e. due)."""
    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1))
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = []

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    assert protocol.in_numerator() is True


@patch(f"{PROTOCOL_MODULE}.ProtocolCard")
@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_compute_satisfied_card_attributes(
    patient_cls: MagicMock,
    billing_cls: MagicMock,
    protocol_card_cls: MagicMock,
) -> None:
    """Satisfied card has status SATISFIED, no recommendations, and expected narrative."""
    from canvas_sdk.effects.protocol_card import ProtocolCard as RealProtocolCard

    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1), first_name="Jim")
    item = _billing_line_item("2018-07-13T21:41:21.407046+00:00")
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = [item]

    card_instance = MagicMock()
    card_instance.recommendations = []
    protocol_card_cls.return_value = card_instance
    protocol_card_cls.Status = RealProtocolCard.Status

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-12-15 13:24:56")
    effects = protocol.compute()

    assert len(effects) == 1
    assert card_instance.status == RealProtocolCard.Status.SATISFIED
    # due_in = (visit_date + 365 days) - now == 2019-07-13 - 2018-12-15 == 210 days
    assert card_instance.due_in == 210
    assert "Jim had a visit" in card_instance.narrative
    assert "7/13/18" in card_instance.narrative
    card_instance.add_recommendation.assert_not_called()


@patch(f"{PROTOCOL_MODULE}.ProtocolCard")
@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_compute_due_when_no_recent_visit(
    patient_cls: MagicMock,
    billing_cls: MagicMock,
    protocol_card_cls: MagicMock,
) -> None:
    """A 65+ patient without a recent AWV gets a due card and a Plan recommendation."""
    from canvas_sdk.effects.protocol_card import ProtocolCard as RealProtocolCard

    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1), first_name="Jim")
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = []

    card_instance = MagicMock()
    card_instance.recommendations = []
    protocol_card_cls.return_value = card_instance
    protocol_card_cls.Status = RealProtocolCard.Status

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    effects = protocol.compute()

    assert len(effects) == 1
    assert card_instance.status == RealProtocolCard.Status.DUE
    assert card_instance.due_in == -1
    assert card_instance.narrative == (
        "Jim is due for a Annual Wellness Visit.\n"
        "There are no Annual Wellness Visits on record."
    )
    card_instance.add_recommendation.assert_called_once_with(
        title="Schedule for Annual Wellness Visit",
        button="Schedule",
        command="instruct",
    )


@patch(f"{PROTOCOL_MODULE}.ProtocolCard")
@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_compute_not_in_denominator_emits_not_applicable_card(
    patient_cls: MagicMock,
    billing_cls: MagicMock,
    protocol_card_cls: MagicMock,
) -> None:
    """A patient under 65 receives a NOT_APPLICABLE card with positive due_in days."""
    from canvas_sdk.effects.protocol_card import ProtocolCard as RealProtocolCard

    patient_cls.objects.get.return_value = _patient(date(1990, 1, 1), first_name="Jim")
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = []

    card_instance = MagicMock()
    card_instance.recommendations = []
    protocol_card_cls.return_value = card_instance
    protocol_card_cls.Status = RealProtocolCard.Status

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-08-23 13:24:56")
    effects = protocol.compute()

    assert len(effects) == 1
    assert card_instance.status == RealProtocolCard.Status.NOT_APPLICABLE
    # due_in is the days until the patient turns 65 from the timeframe end.
    # Patient born 1990-01-01; turns 65 on 2055-01-01. Timeframe end == now == 2018-08-23.
    assert card_instance.due_in > 0


def test_display_date_humanizes_relative_to_now() -> None:
    """display_date uses arrow.humanize against self.now and the M/D/YY date."""
    protocol = _make_protocol()
    protocol.now = arrow.get("2018-12-15 13:24:56")
    rendered = protocol.display_date(arrow.get("2018-07-13T21:41:21.407046Z"))
    assert " on 7/13/18" in rendered


@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_recent_visit_context_with_visit(
    patient_cls: MagicMock, billing_cls: MagicMock
) -> None:
    """recent_visit_context describes the last visit when there is one."""
    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1))
    item = _billing_line_item("2018-07-13T21:41:21.407046+00:00")
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = [item]

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-12-15 13:24:56")
    assert "Last Annual Wellness Visit was" in protocol.recent_visit_context()
    assert "7/13/18" in protocol.recent_visit_context()


@patch(f"{PROTOCOL_MODULE}.BillingLineItem")
@patch(f"{PROTOCOL_MODULE}.Patient")
def test_recent_visit_context_without_visit(
    patient_cls: MagicMock, billing_cls: MagicMock
) -> None:
    """recent_visit_context falls back to the no-visits-on-record narrative."""
    patient_cls.objects.get.return_value = _patient(date(1940, 1, 1))
    billing_cls.objects.filter.return_value.find.return_value.order_by.return_value = []

    protocol = _make_protocol()
    protocol.now = arrow.get("2018-12-15 13:24:56")
    assert protocol.recent_visit_context() == "There are no Annual Wellness Visits on record."
