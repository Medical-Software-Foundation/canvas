"""Tests for the HCC002v2 CKD Suspect protocol plugin."""

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import arrow
import pytest

from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.value_set.custom import LabReportCreatinine
from protocols.hcc002v2_ckd_suspect import Hcc002v2


PROTOCOL_MODULE = "protocols.hcc002v2_ckd_suspect"


def _make_protocol(patient_id: str = "patient-123") -> Hcc002v2:
    """Build an Hcc002v2 with a LAB_REPORT_UPDATED event for ``patient_id``."""
    event = MagicMock()
    event.type = EventType.LAB_REPORT_UPDATED
    event.target = MagicMock()
    event.target.id = "lab-report-id"
    protocol = Hcc002v2(event=event)
    protocol._patient_id = patient_id
    protocol.now = arrow.get("2018-12-23T13:24:56+00:00")
    return protocol


def _stub_patient(
    protocol: Hcc002v2,
    *,
    sex_at_birth: str = "M",
    biological_race_codes: list[str] | None = None,
    birth_date: str = "1950-01-01",
    first_name: str = "Jim",
    patient_id: str = "patient-123",
) -> SimpleNamespace:
    """Attach a SimpleNamespace patient stand-in to ``protocol.patient``."""
    patient = SimpleNamespace(
        id=patient_id,
        first_name=first_name,
        sex_at_birth=sex_at_birth,
        biological_race_codes=(
            biological_race_codes if biological_race_codes is not None else ["2054-5"]
        ),
        birth_date=arrow.get(birth_date).date(),
    )

    def age_at(time: arrow.Arrow) -> float:
        birth = arrow.get(patient.birth_date)
        return (time.datetime - birth.datetime).days / 365.25

    patient.age_at = age_at
    # cached_property stores in instance __dict__; writing there pre-seeds the cache.
    protocol.__dict__["patient"] = patient
    return patient


def _lab_value(value: str, units: str = "mg/dL") -> SimpleNamespace:
    """Build a minimal LabValue stand-in."""
    return SimpleNamespace(value=value, units=units)


def test_meta_identifiers_and_types() -> None:
    """Identifier and type Meta values are preserved from the source protocol."""
    assert Hcc002v2.Meta.identifiers == ["HCC002v2"]
    assert Hcc002v2.Meta.types == ["HCC"]


def test_meta_description() -> None:
    """Description Meta value is preserved verbatim from the legacy protocol."""
    assert Hcc002v2.Meta.description == (
        "All patients with evidence of two or more elevated eGFR values "
        "and no active CKD problem on the Conditions List."
    )


def test_meta_information() -> None:
    """Information URL Meta value is preserved verbatim from the legacy protocol."""
    assert Hcc002v2.Meta.information == (
        "https://canvas-medical.help.usepylon.com/articles/6051758367-ckd-suspect"
    )


def test_meta_version() -> None:
    """Version Meta value is preserved verbatim from the legacy protocol."""
    assert Hcc002v2.Meta.version == "2019-02-12v1"


def test_responds_to_event_types() -> None:
    """Protocol responds to lab-report, condition, and patient lifecycle events."""
    assert set(Hcc002v2.RESPONDS_TO) == {
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.PATIENT_UPDATED),
    }


def test_lab_report_creatinine_value_set_loinc() -> None:
    """LabReportCreatinine resolves the serum-creatinine LOINC code."""
    assert LabReportCreatinine.LOINC == {"2160-0"}


def test_in_initial_population_is_true() -> None:
    """All patients are in the initial population."""
    assert _make_protocol().in_initial_population() is True


def test_egfr_baseline_matches_legacy_value() -> None:
    """The MDRD eGFR baseline (AA male, age ~68) matches the legacy reference value."""
    protocol = _make_protocol()
    _stub_patient(protocol)
    assert protocol.egfr(1.37, "mg/dL") == pytest.approx(66.45, abs=0.01)


def test_egfr_unit_conversion_micromol_per_liter() -> None:
    """A creatinine value expressed in µmol/L (creatinine * 88.4) matches the mg/dL eGFR."""
    protocol = _make_protocol()
    _stub_patient(protocol)
    assert protocol.egfr(1.37 * 88.4, "µmol/L") == pytest.approx(66.45, abs=0.01)


def test_egfr_female_multiplier() -> None:
    """Sex-at-birth F multiplies the baseline eGFR by 0.742."""
    protocol = _make_protocol()
    _stub_patient(protocol, sex_at_birth="F")
    assert protocol.egfr(1.37, "mg/dL") == pytest.approx(49.31, abs=0.01)


def test_egfr_non_african_american_drops_race_multiplier() -> None:
    """Dropping the African-American race code removes the 1.210 multiplier."""
    protocol = _make_protocol()
    _stub_patient(protocol, biological_race_codes=["2106-3"])
    assert protocol.egfr(1.37, "mg/dL") == pytest.approx(54.92, abs=0.01)


def test_egfr_age_influence() -> None:
    """An older patient has a lower computed eGFR."""
    protocol = _make_protocol()
    _stub_patient(protocol, birth_date="1941-01-01")
    assert protocol.egfr(1.37, "mg/dL") == pytest.approx(64.80, abs=0.01)


@patch(f"{PROTOCOL_MODULE}.LabValue")
def test_high_creatinine_values_skipped_for_infant(lab_value_cls: MagicMock) -> None:
    """Patients with age 0 short-circuit to an empty list (avoids ZeroDivisionError)."""
    protocol = _make_protocol()
    _stub_patient(protocol, birth_date="2018-08-23")
    assert protocol.high_creatinine_values == []
    lab_value_cls.objects.for_patient.assert_not_called()


def _stub_lab_values(lab_value_cls: MagicMock, values: list[SimpleNamespace]) -> MagicMock:
    """Wire LabValue.objects.for_patient().find().within() to return ``values``."""
    chain = lab_value_cls.objects.for_patient.return_value.find.return_value.within
    chain.return_value = values
    return chain


@patch(f"{PROTOCOL_MODULE}.LabValue")
def test_high_creatinine_values_filters_by_egfr_threshold(lab_value_cls: MagicMock) -> None:
    """Only creatinine values whose computed eGFR is below 60 are returned."""
    protocol = _make_protocol()
    _stub_patient(protocol)
    # With an AA male age ~68: eGFR(1.37) ≈ 66.45 (>= 60, excluded);
    # eGFR(1.7) ≈ 52 (< 60, included).
    low = _lab_value("1.7")
    high = _lab_value("1.37")
    _stub_lab_values(lab_value_cls, [high, low])

    assert protocol.high_creatinine_values == [low]


@patch(f"{PROTOCOL_MODULE}.LabValue")
def test_high_creatinine_values_drops_non_positive_values(lab_value_cls: MagicMock) -> None:
    """Non-positive creatinine values are skipped."""
    protocol = _make_protocol()
    _stub_patient(protocol)
    bad = _lab_value("0")
    good = _lab_value("1.7")
    _stub_lab_values(lab_value_cls, [bad, good])

    assert protocol.high_creatinine_values == [good]


def test_in_denominator_requires_two_or_more_high_values() -> None:
    """Two or more low-eGFR lab values place the patient in the denominator."""
    protocol = _make_protocol()
    with patch.object(
        type(protocol),
        "high_creatinine_values",
        new_callable=PropertyMock,
        return_value=[_lab_value("1.7"), _lab_value("1.8")],
    ):
        assert protocol.in_denominator() is True


def test_in_denominator_false_with_single_high_value() -> None:
    """A single low-eGFR lab value is not enough for the denominator."""
    protocol = _make_protocol()
    with patch.object(
        type(protocol),
        "high_creatinine_values",
        new_callable=PropertyMock,
        return_value=[_lab_value("1.7")],
    ):
        assert protocol.in_denominator() is False


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_has_active_kidney_condition_uses_value_set_lookup(condition_cls: MagicMock) -> None:
    """has_active_kidney_condition chains for_patient -> find -> active -> exists."""
    protocol = _make_protocol()
    _stub_patient(protocol)
    qs = (
        condition_cls.objects.for_patient.return_value.find.return_value.active.return_value
    )
    qs.exists.return_value = True

    assert protocol.has_active_kidney_condition is True
    condition_cls.objects.for_patient.assert_called_once_with("patient-123")


def test_in_numerator_mirrors_has_active_kidney_condition() -> None:
    """in_numerator delegates to has_active_kidney_condition."""
    protocol = _make_protocol()
    with patch.object(
        type(protocol),
        "has_active_kidney_condition",
        new_callable=PropertyMock,
        return_value=True,
    ):
        assert protocol.in_numerator() is True
    with patch.object(
        type(protocol),
        "has_active_kidney_condition",
        new_callable=PropertyMock,
        return_value=False,
    ):
        assert protocol.in_numerator() is False


def test_compute_returns_empty_list_when_not_in_denominator() -> None:
    """Patients outside the denominator receive no protocol card."""
    protocol = _make_protocol()
    with patch.object(type(protocol), "in_denominator", return_value=False):
        assert protocol.compute() == []


def test_compute_satisfied_when_active_condition_present() -> None:
    """A patient with an active CKD condition gets a satisfied card."""
    protocol = _make_protocol()
    _stub_patient(protocol)
    with (
        patch.object(type(protocol), "in_denominator", return_value=True),
        patch.object(type(protocol), "in_numerator", return_value=True),
    ):
        effects = protocol.compute()

    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.SATISFIED.value in payload


def test_compute_due_when_no_active_condition() -> None:
    """A patient with no active CKD condition gets a due card and a Diagnose recommendation."""
    protocol = _make_protocol()
    _stub_patient(protocol, first_name="Jim")
    with (
        patch.object(type(protocol), "in_denominator", return_value=True),
        patch.object(type(protocol), "in_numerator", return_value=False),
    ):
        effects = protocol.compute()

    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.DUE.value in payload
    assert (
        "Jim has at least two eGFR measurements < 60 ml/min over the last two years "
        "suggesting renal disease." in payload
    )
    assert "There is no associated condition on the Conditions List." in payload
    assert "Diagnose" in payload
    assert "diagnose" in payload
