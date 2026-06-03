import json

from canvas_sdk.events import EventType

from unstructured_med_flag.handlers.medications import (
    Medications,
    partition_medications,
    is_unstructured,
    CODED_GROUP_NAME,
    CODED_GROUP_PRIORITY,
    UNSTRUCTURED_GROUP_NAME,
    UNSTRUCTURED_GROUP_PRIORITY,
)
from tests.conftest import make_med, make_handler, FDB, RXNORM, UNSTRUCTURED


# --- is_unstructured ---------------------------------------------------------

def test_med_with_fdb_coding_is_structured():
    assert is_unstructured(make_med(1, [FDB])) is False


def test_med_with_rxnorm_coding_is_structured():
    assert is_unstructured(make_med(2, [RXNORM])) is False


def test_med_with_empty_codings_is_unstructured():
    assert is_unstructured(make_med(3, [])) is True


def test_med_with_only_unstructured_system_is_unstructured():
    assert is_unstructured(make_med(4, [UNSTRUCTURED])) is True


def test_med_with_missing_codings_key_is_unstructured():
    assert is_unstructured({"id": 5}) is True


def test_med_with_fdb_among_multiple_codings_is_structured():
    assert is_unstructured(make_med(6, [UNSTRUCTURED, FDB])) is False


# --- partition_medications ---------------------------------------------------

def test_partition_splits_coded_and_unstructured_preserving_order():
    coded_med = make_med(1, [FDB])
    free_text = make_med(2, [])
    rxnorm_med = make_med(3, [RXNORM])
    snomed_only = make_med(4, [UNSTRUCTURED])

    coded, unstructured = partition_medications([coded_med, free_text, rxnorm_med, snomed_only])

    assert [m["id"] for m in coded] == [1, 3]
    assert [m["id"] for m in unstructured] == [2, 4]


def test_partition_empty_context():
    assert partition_medications([]) == ([], [])


# --- Medications.compute -----------------------------------------------------

def test_responds_to_patient_chart_medications_event():
    assert Medications.RESPONDS_TO == EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)


def test_compute_returns_empty_when_all_structured():
    handler = make_handler([make_med(1, [FDB]), make_med(2, [RXNORM])])
    assert handler.compute() == []


def test_compute_returns_empty_for_empty_chart():
    handler = make_handler([])
    assert handler.compute() == []


def test_compute_handles_none_context():
    # event.context can be None (patient with no medications); must not raise.
    handler = make_handler(None)
    assert handler.compute() == []


def _groups_by_name(effects):
    """Parse the single PatientChartGroup effect into {group_name: [med ids]}."""
    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    return {g["name"]: [m["id"] for m in g["items"]] for g in payload["data"]["items"]}


def test_compute_mixed_puts_coded_above_unstructured_each_in_its_own_group():
    # Order in context: coded, free-text, coded - to prove partition, not order.
    handler = make_handler([make_med(1, [FDB]), make_med(2, []), make_med(3, [RXNORM])])
    effects = handler.compute()

    payload = json.loads(effects[0].payload)
    groups = payload["data"]["items"]

    # Two groups, coded sorted above unstructured by priority.
    assert len(groups) == 2
    by_priority = sorted(groups, key=lambda g: g["priority"], reverse=True)
    assert by_priority[0]["name"] == CODED_GROUP_NAME
    assert by_priority[0]["priority"] == CODED_GROUP_PRIORITY
    assert by_priority[1]["name"] == UNSTRUCTURED_GROUP_NAME
    assert by_priority[1]["priority"] == UNSTRUCTURED_GROUP_PRIORITY

    by_name = _groups_by_name(effects)
    assert by_name[CODED_GROUP_NAME] == [1, 3]
    assert by_name[UNSTRUCTURED_GROUP_NAME] == [2]


def test_compute_all_unstructured_emits_only_the_unstructured_group():
    handler = make_handler([make_med(1, []), make_med(2, [UNSTRUCTURED])])
    by_name = _groups_by_name(handler.compute())

    assert by_name == {UNSTRUCTURED_GROUP_NAME: [1, 2]}
    assert CODED_GROUP_NAME not in by_name
