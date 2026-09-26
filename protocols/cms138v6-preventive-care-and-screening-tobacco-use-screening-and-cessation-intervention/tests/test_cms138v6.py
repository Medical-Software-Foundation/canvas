"""Tests for the CMS138v6 - Tobacco Screening and Cessation Intervention plugin."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import arrow

from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from protocols.cms138v6_tobacco_screening_and_cessation import (
    ClinicalQualityMeasure138v6,
    HealthAndBehavioralAssessmentInitial,
    HealthAndBehavioralAssessmentReassessment,
    HealthBehavioralAssessmentIndividual,
)
from protocols.helper_population import Population


PROTOCOL_MODULE = "protocols.cms138v6_tobacco_screening_and_cessation"


def _make_protocol(
    *,
    patient_id: str = "patient-id",
    now: arrow.Arrow | None = None,
    event_type: int | None = None,
) -> ClinicalQualityMeasure138v6:
    """Build a CMS138v6 protocol primed with ``patient_id``."""
    event = MagicMock()
    event.type = event_type if event_type is not None else EventType.PATIENT_UPDATED
    event.target = MagicMock()
    event.target.id = patient_id
    event.context = {}
    protocol = ClinicalQualityMeasure138v6(event=event)
    protocol._patient_id = patient_id
    if now is not None:
        protocol.now = now
    return protocol


def _fake_patient(
    *,
    first_name: str = "Jenny",
    birth_date: date | None = None,
    patient_id: str = "patient-id",
    dbid: int = 42,
) -> MagicMock:
    """Build a Patient mock the protocol can call ``age_at`` on."""
    patient = MagicMock()
    patient.id = patient_id
    patient.dbid = dbid
    patient.first_name = first_name
    patient.birth_date = birth_date or date(1980, 1, 1)
    real_birth = arrow.get(patient.birth_date)
    patient.age_at = lambda when, real_birth=real_birth: max(
        0, when.year - real_birth.year - (1 if (when.month, when.day) < (real_birth.month, real_birth.day) else 0)
    )
    return patient


# ---------------------------------------------------------------------------
# Meta and class configuration
# ---------------------------------------------------------------------------


def test_meta_identifiers() -> None:
    """Identifier preserved from the legacy CQM."""
    assert ClinicalQualityMeasure138v6.Meta.identifiers == ["CMS138v6"]


def test_meta_types() -> None:
    """Type preserved from the legacy CQM."""
    assert ClinicalQualityMeasure138v6.Meta.types == ["CQM"]


def test_meta_version() -> None:
    """Version preserved from the legacy CQM."""
    assert ClinicalQualityMeasure138v6.Meta.version == "2022-01-31v1"


def test_meta_description() -> None:
    """Description preserved from the legacy CQM."""
    assert ClinicalQualityMeasure138v6.Meta.description == (
        "Patients aged 18 years and older who have not been screened for "
        "tobacco use OR who have not received tobacco cessation intervention "
        "if identified as a tobacco user."
    )


def test_meta_information() -> None:
    """Information URL preserved from the legacy CQM."""
    assert ClinicalQualityMeasure138v6.Meta.information == (
        "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS138v6.html"
    )


def test_meta_default_permission_flags() -> None:
    """Default permission flags include each recommendable command type."""
    flags = ClinicalQualityMeasure138v6.Meta.default_permission_flags
    assert flags == {
        "protocols:actions:CMS138v6:instruct": True,
        "protocols:actions:CMS138v6:interview": True,
        "protocols:actions:CMS138v6:prescribe": True,
    }


def test_responds_to_expected_events() -> None:
    """Protocol responds to the SDK substitutes for HEALTH_MAINTENANCE."""
    for name in (
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.INTERVIEW_CREATED),
        EventType.Name(EventType.INSTRUCTION_CREATED),
        EventType.Name(EventType.INSTRUCTION_UPDATED),
    ):
        assert name in ClinicalQualityMeasure138v6.RESPONDS_TO


def test_three_populations_initialized() -> None:
    """Each instance owns three Population trackers."""
    protocol = _make_protocol()
    assert set(protocol._populations) == {"population 1", "population 2", "population 3"}
    assert all(isinstance(p, Population) for p in protocol._populations.values())


# ---------------------------------------------------------------------------
# Ported value sets
# ---------------------------------------------------------------------------


def test_health_behavioral_assessment_value_sets_carry_expected_cpt_codes() -> None:
    """Three ported value sets preserve their single CPT code each."""
    assert HealthBehavioralAssessmentIndividual.CPT == {"96152"}
    assert HealthAndBehavioralAssessmentInitial.CPT == {"96150"}
    assert HealthAndBehavioralAssessmentReassessment.CPT == {"96151"}


# ---------------------------------------------------------------------------
# _resolve_patient_id
# ---------------------------------------------------------------------------


def test_resolve_patient_id_uses_event_context_for_unsupported_events() -> None:
    """When patient_id_from_target raises, fall back to event.context['patient_id']."""
    event = MagicMock()
    event.type = EventType.INTERVIEW_CREATED
    event.target = MagicMock()
    event.target.id = "interview-id"
    event.context = {"patient_id": "ctx-patient"}
    protocol = ClinicalQualityMeasure138v6(event=event)

    with patch.object(
        ClinicalQualityMeasure138v6,
        "patient_id_from_target",
        side_effect=ValueError("unsupported"),
    ):
        assert protocol._resolve_patient_id() == "ctx-patient"


# ---------------------------------------------------------------------------
# in_initial_population
# ---------------------------------------------------------------------------


def test_in_initial_population_requires_age_18() -> None:
    """Patient under 18 is excluded even with eligible visits."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    young = _fake_patient(birth_date=date(2010, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=young),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=5),
    ):
        assert protocol.in_initial_population() is False
        assert all(
            not p.in_initial_population for p in protocol._populations.values()
        )


def test_in_initial_population_true_with_preventive_visit() -> None:
    """Adult with a preventive visit is in the initial population."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
    ):
        assert protocol.in_initial_population() is True
        assert all(p.in_initial_population for p in protocol._populations.values())


def test_in_initial_population_true_with_two_other_visits() -> None:
    """Adult with at least two other eligible visits is in the initial population."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=False),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=2),
    ):
        assert protocol.in_initial_population() is True


def test_in_initial_population_false_with_one_other_visit() -> None:
    """A single non-preventive visit is not enough."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=False),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=1),
    ):
        assert protocol.in_initial_population() is False


# ---------------------------------------------------------------------------
# Denominator and numerator
# ---------------------------------------------------------------------------


def test_in_denominator_population_2_drops_when_not_tobacco_user() -> None:
    """Population 2 leaves the denominator when no positive screening exists."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=None
        ),
    ):
        assert protocol.in_denominator() is True
        assert protocol._populations["population 1"].in_denominator is True
        assert protocol._populations["population 2"].in_denominator is False
        assert protocol._populations["population 3"].in_denominator is True


def test_in_numerator_population_1_false_without_any_screening() -> None:
    """Population 1 fails numerator when there is no screening of either kind."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=None),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=False
        ),
    ):
        protocol.in_denominator()
        protocol.in_numerator()
        assert protocol._populations["population 1"].in_numerator is False
        assert protocol._populations["population 3"].in_numerator is False


def test_in_numerator_population_3_true_for_non_user() -> None:
    """A patient screened as a non-user satisfies Population 3."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get("2019-02-05")
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=None),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=screen_date
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=False
        ),
    ):
        protocol.in_denominator()
        protocol.in_numerator()
        assert protocol._populations["population 1"].in_numerator is True
        assert protocol._populations["population 3"].in_numerator is True


def test_in_numerator_population_2_true_when_intervention_present() -> None:
    """A tobacco user with an intervention satisfies Population 2."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get("2019-02-05")
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=True
        ),
    ):
        protocol.in_denominator()
        protocol.in_numerator()
        assert protocol._populations["population 2"].in_numerator is True
        assert protocol._populations["population 3"].in_numerator is True


def test_in_numerator_population_2_false_when_user_without_intervention() -> None:
    """A tobacco user without an intervention fails Population 2 and 3."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get("2019-02-05")
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=False
        ),
    ):
        protocol.in_denominator()
        protocol.in_numerator()
        assert protocol._populations["population 2"].in_numerator is False
        assert protocol._populations["population 3"].in_numerator is False


# ---------------------------------------------------------------------------
# tobacco_cessation_intervention_counseling
# ---------------------------------------------------------------------------


def test_counseling_returns_none_when_no_positive_screening() -> None:
    """Without a tobacco-user screening there is no counseling lookup."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    with patch.object(
        ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=None
    ):
        assert protocol.tobacco_cessation_intervention_counseling is None


def test_counseling_returns_instruction_datetime_when_found() -> None:
    """A matching Instruction returns its note datetime_of_service as an arrow."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get(datetime(2019, 2, 5, tzinfo=timezone.utc))
    counseling_at = datetime(2019, 2, 10, tzinfo=timezone.utc)
    instruction = MagicMock()
    instruction.note.datetime_of_service = counseling_at
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch(f"{PROTOCOL_MODULE}.Instruction") as instruction_cls,
    ):
        instruction_cls.objects.for_patient.return_value.committed.return_value.find.return_value.filter.return_value.order_by.return_value.first.return_value = instruction
        assert protocol.tobacco_cessation_intervention_counseling == arrow.get(counseling_at)


def test_counseling_returns_none_when_no_instruction_in_window() -> None:
    """An empty queryset yields None even after a positive screening."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get(datetime(2019, 2, 5, tzinfo=timezone.utc))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch(f"{PROTOCOL_MODULE}.Instruction") as instruction_cls,
    ):
        instruction_cls.objects.for_patient.return_value.committed.return_value.find.return_value.filter.return_value.order_by.return_value.first.return_value = None
        assert protocol.tobacco_cessation_intervention_counseling is None


# ---------------------------------------------------------------------------
# compute()
# ---------------------------------------------------------------------------


def test_compute_under_18_returns_not_applicable_card() -> None:
    """Patients under 18 receive a single not_applicable card."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    young = _fake_patient(birth_date=date(2010, 4, 1))
    with patch.object(ClinicalQualityMeasure138v6, "patient", new=young):
        effects = protocol.compute()
    assert len(effects) == 1
    assert ProtocolCard.Status.NOT_APPLICABLE.value in effects[0].payload


def test_compute_not_in_denominator_returns_no_effects() -> None:
    """No visits => no protocol card emitted."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=False),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
    ):
        effects = protocol.compute()
    assert effects == []


def test_compute_emits_due_card_for_unscreened_adult_with_visit() -> None:
    """Adult with eligible visit but no screening gets a 'due' interview recommendation."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=None),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_counseling",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_medication",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=False
        ),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.DUE.value in payload
    assert "screened for tobacco use" in payload
    assert "interview" in payload


def test_compute_emits_due_card_for_tobacco_user_without_intervention() -> None:
    """Tobacco user without intervention => due card with instruct and prescribe."""
    protocol = _make_protocol(now=arrow.get("2019-04-01"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get("2019-02-05")
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_counseling",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_medication",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=False
        ),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.DUE.value in payload
    assert "current tobacco user" in payload
    assert "instruct" in payload
    assert "prescribe" in payload


def test_compute_emits_satisfied_card_for_non_user() -> None:
    """A patient screened as a non-user yields a satisfied card."""
    protocol = _make_protocol(now=arrow.get("2019-03-17"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    non_user_at = arrow.get(datetime(2019, 2, 5, tzinfo=timezone.utc))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=None),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_use_screening_non_user",
            new=non_user_at,
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_counseling",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_medication",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=False
        ),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.SATISFIED.value in payload
    assert "is not a smoker" in payload


def test_compute_emits_satisfied_card_for_counseling() -> None:
    """A tobacco user with cessation counseling yields a satisfied card."""
    protocol = _make_protocol(now=arrow.get("2019-03-17"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get(datetime(2019, 2, 5, tzinfo=timezone.utc))
    counseling_at = arrow.get(datetime(2019, 2, 6, tzinfo=timezone.utc))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_counseling",
            new=counseling_at,
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_medication",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=True
        ),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.SATISFIED.value in payload
    assert "smoking cessation counseling" in payload


def test_compute_emits_satisfied_card_for_medication() -> None:
    """A tobacco user with cessation medication yields a satisfied card."""
    protocol = _make_protocol(now=arrow.get("2019-03-30"))
    adult = _fake_patient(birth_date=date(1980, 1, 1))
    screen_date = arrow.get(datetime(2019, 2, 5, tzinfo=timezone.utc))
    med_at = arrow.get(datetime(2019, 3, 27, tzinfo=timezone.utc))
    with (
        patch.object(ClinicalQualityMeasure138v6, "patient", new=adult),
        patch.object(ClinicalQualityMeasure138v6, "has_preventive_visit", return_value=True),
        patch.object(ClinicalQualityMeasure138v6, "count_eligible_visits", return_value=0),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_user", new=screen_date
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_use_screening_non_user", new=None
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_counseling",
            new=None,
        ),
        patch.object(
            ClinicalQualityMeasure138v6,
            "tobacco_cessation_intervention_medication",
            new=med_at,
        ),
        patch.object(
            ClinicalQualityMeasure138v6, "tobacco_cessation_intervention", new=True
        ),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.SATISFIED.value in payload
    assert "cessation medication" in payload
