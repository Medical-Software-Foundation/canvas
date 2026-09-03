"""Signal gathering against the test DB. Each test seeds only what it asserts.

Factory reality (confirmed against canvas-plugins canvas_sdk/test_utils/factories):
  - PatientFactory, LabReportFactory, LabValueFactory, LabValueCodingFactory exist.
  - There is NO ConditionFactory (the SDK's LabOrderReasonConditionFactory even
    comments "would need a ConditionFactory"), so active conditions are created
    directly via Condition.objects.create(...) + ConditionCoding.objects.create(...).

Code-system strings are the production ValueSet CODE_SYSTEM_MAPPING URLs:
  ICD-10 conditions are stored with system "ICD-10" (NOT the FHIR sid URL);
  LOINC labs with "http://loinc.org". Seeds use those real strings so the tests
  exercise the same filter signals.py runs in production.

Factory imports are inside each test (matching the sibling): a top-level import
of canvas_sdk factories breaks Django app-loading at collection time.
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from note_protocol_automation.lib.signals import gather_signals

_ICD10_SYSTEM = "ICD-10"
_LOINC_SYSTEM = "http://loinc.org"


@pytest.fixture
def patient() -> Any:
    """A persisted patient with a known birth_date and sex_at_birth."""
    from canvas_sdk.test_utils.factories import PatientFactory

    return PatientFactory.create(birth_date="1958-03-14", sex_at_birth="F")


@pytest.mark.integtest
@pytest.mark.django_db
def test_demographics(patient: Any) -> None:
    """Age is whole years from birth_date; sex is sex_at_birth."""
    s = gather_signals(
        patient.id,
        need_conditions=False,
        need_demographics=True,
        need_loincs=frozenset(),
        need_care_team=False,
    )
    assert s.sex == "F"
    assert s.age is not None and s.age >= 60


@pytest.mark.integtest
@pytest.mark.django_db
def test_active_conditions_icd10(patient: Any) -> None:
    """Active (committed) conditions contribute their ICD-10 codes."""
    from canvas_sdk.test_utils.factories import CanvasUserFactory
    from canvas_sdk.v1.data.condition import Condition, ConditionCoding

    committer = CanvasUserFactory.create()
    # Direct create: no ConditionFactory exists. .active() = .committed() (needs a
    # committer, no entered_in_error) AND clinical_status="active"; the base manager
    # also filters deleted=False. All NOT-NULL fields without defaults are supplied.
    today = timezone.now().date()
    condition = Condition.objects.create(
        patient=patient,
        clinical_status="active",
        committer=committer,
        entered_in_error=None,
        deleted=False,
        onset_date=today,
        resolution_date=today,
        notes="",
        surgical=False,
    )
    ConditionCoding.objects.create(
        condition=condition, code="I10", system=_ICD10_SYSTEM, display="Essential hypertension"
    )

    s = gather_signals(
        patient.id,
        need_conditions=True,
        need_demographics=False,
        need_loincs=frozenset(),
        need_care_team=False,
    )
    assert "I10" in s.icd10_codes


@pytest.mark.integtest
@pytest.mark.django_db
def test_latest_lab_within_window(patient: Any) -> None:
    """Only the requested LOINC's latest committed value is returned, with days_old."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        LabReportFactory,
        LabValueCodingFactory,
        LabValueFactory,
    )

    # The report must be COMMITTED and non-junked or signals.py's lifecycle gate
    # excludes it. LabReportFactory leaves committer=None and entered_in_error=None
    # (junked=False is its default), so a value gates only once a committer is set.
    committer = CanvasUserFactory.create()
    report = LabReportFactory.create(
        patient=patient,
        original_date=timezone.now() - timedelta(days=30),
        committer=committer,
        entered_in_error=None,
        junked=False,
    )
    value = LabValueFactory.create(report=report, value="40.0", observation_status="final")
    LabValueCodingFactory.create(value=value, code="33914-3", system=_LOINC_SYSTEM)

    s = gather_signals(
        patient.id,
        need_conditions=False,
        need_demographics=False,
        need_loincs=frozenset({"33914-3"}),
        need_care_team=False,
    )
    assert "33914-3" in s.lab_values
    assert s.lab_values["33914-3"].value == 40.0
    assert s.lab_values["33914-3"].days_old <= 31


@pytest.mark.integtest
@pytest.mark.django_db
def test_junked_or_uncommitted_report_does_not_gate(patient: Any) -> None:
    """The lifecycle gate bites: junked, uncommitted, and entered-in-error reports
    are ALL excluded, even though each carries a final, in-window, correctly-coded
    LOINC value identical to the positive case.

    Three bad reports on three LOINCs isolate each of the gate's three clauses, so
    removing any single clause from signals.py makes this test fail:
      - junked (committer set, no entered_in_error)  -> only junked=False excludes
      - uncommitted (committer=None)                 -> only committer clause excludes
      - entered_in_error set (committer set, non-junked) -> only that clause excludes
    """
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        LabReportFactory,
        LabValueCodingFactory,
        LabValueFactory,
    )

    committer = CanvasUserFactory.create()
    erroring_user = CanvasUserFactory.create()
    recent = timezone.now() - timedelta(days=10)

    # Bad report #1: committed, non-error, but JUNKED -> isolates the junked clause.
    junked_report = LabReportFactory.create(
        patient=patient,
        original_date=recent,
        committer=committer,
        entered_in_error=None,
        junked=True,
    )
    junked_value = LabValueFactory.create(
        report=junked_report, value="40.0", observation_status="final"
    )
    LabValueCodingFactory.create(value=junked_value, code="33914-3", system=_LOINC_SYSTEM)

    # Bad report #2: non-junked, non-error, but UNCOMMITTED -> isolates committer.
    uncommitted_report = LabReportFactory.create(
        patient=patient,
        original_date=recent,
        committer=None,
        entered_in_error=None,
        junked=False,
    )
    uncommitted_value = LabValueFactory.create(
        report=uncommitted_report, value="41.0", observation_status="final"
    )
    LabValueCodingFactory.create(value=uncommitted_value, code="4548-4", system=_LOINC_SYSTEM)

    # Bad report #3: committed, non-junked, but ENTERED IN ERROR -> isolates that clause.
    errored_report = LabReportFactory.create(
        patient=patient,
        original_date=recent,
        committer=committer,
        entered_in_error=erroring_user,
        junked=False,
    )
    errored_value = LabValueFactory.create(
        report=errored_report, value="42.0", observation_status="final"
    )
    LabValueCodingFactory.create(value=errored_value, code="2160-0", system=_LOINC_SYSTEM)

    s = gather_signals(
        patient.id,
        need_conditions=False,
        need_demographics=False,
        need_loincs=frozenset({"33914-3", "4548-4", "2160-0"}),
        need_care_team=False,
    )
    assert "33914-3" not in s.lab_values  # junked report excluded
    assert "4548-4" not in s.lab_values  # uncommitted report excluded
    assert "2160-0" not in s.lab_values  # entered-in-error report excluded
    assert s.lab_values == {}


@pytest.mark.integtest
@pytest.mark.django_db
def test_lazy_skips_unrequested(patient: Any) -> None:
    """Unrequested signal types come back empty (no wasted queries)."""
    s = gather_signals(
        patient.id,
        need_conditions=False,
        need_demographics=False,
        need_loincs=frozenset(),
        need_care_team=False,
    )
    assert s.icd10_codes == frozenset()
    assert s.lab_values == {}
    assert s.age is None
