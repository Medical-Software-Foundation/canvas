"""Tests for chart_event_publisher.ChartEventPublisher."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from provider_clinical_summary_companion.handlers import chart_event_publisher as publisher
from provider_clinical_summary_companion.handlers.chart_event_publisher import (
    ChartEventPublisher,
    EVENT_MAP,
    _patient_id_from_target,
    patient_channel,
)

PATIENT_UUID = "00000000-0000-0000-0000-0000000000aa"
TARGET_UUID = "11111111-1111-1111-1111-111111111111"


def _make(event_type_name: str, target: str | None = TARGET_UUID, context: dict | None = None) -> ChartEventPublisher:
    handler = ChartEventPublisher.__new__(ChartEventPublisher)
    # Use a small stand-in EventType with a .type attribute whose Name() resolves.
    with patch.object(publisher, "EventType") as mock_event_type_cls:
        mock_event_type_cls.Name.return_value = event_type_name
        fake_event = SimpleNamespace(type=event_type_name, target=target, context=context or {})
        handler.event = fake_event
    return handler


class TestPatientChannel:
    def test_channel_name_format(self) -> None:
        assert patient_channel("abc-123") == "patient-abc-123"


class TestRespondsTo:
    def test_covers_every_event_in_the_map(self) -> None:
        # RESPONDS_TO is the result of EventType.Name(...) on each key. We
        # can't introspect the protobuf enum here; just confirm the length
        # matches the EVENT_MAP keys and that the class attribute is a list.
        assert isinstance(ChartEventPublisher.RESPONDS_TO, list)
        assert len(ChartEventPublisher.RESPONDS_TO) == len(EVENT_MAP)


class TestPatientIdFromTarget:
    def test_returns_patient_id_when_record_exists(self) -> None:
        model = MagicMock()
        qs = MagicMock()
        qs.select_related.return_value.first.return_value = SimpleNamespace(
            patient=SimpleNamespace(id="pat-1")
        )
        model.objects.filter.return_value = qs

        assert _patient_id_from_target(model, "target-1") == "pat-1"
        model.objects.filter.assert_called_once_with(id="target-1")

    def test_returns_none_when_target_blank(self) -> None:
        model = MagicMock()
        assert _patient_id_from_target(model, "") is None
        assert model.objects.filter.call_count == 0

    def test_returns_none_when_record_missing(self) -> None:
        model = MagicMock()
        qs = MagicMock()
        qs.select_related.return_value.first.return_value = None
        model.objects.filter.return_value = qs
        assert _patient_id_from_target(model, "unknown") is None

    def test_returns_none_when_record_has_no_patient(self) -> None:
        model = MagicMock()
        qs = MagicMock()
        qs.select_related.return_value.first.return_value = SimpleNamespace(patient=None)
        model.objects.filter.return_value = qs
        assert _patient_id_from_target(model, "orphan") is None


class TestCompute:
    def test_unknown_event_returns_empty(self) -> None:
        handler = _make("NOT_A_REAL_EVENT")
        with patch.object(publisher.EventType, "Name", return_value="NOT_A_REAL_EVENT"):
            assert handler.compute() == []

    def test_condition_created_broadcasts_conditions_and_surgical(self) -> None:
        handler = _make("CONDITION_CREATED")
        with patch.object(publisher.EventType, "Name", return_value="CONDITION_CREATED"), \
             patch.object(publisher, "_patient_id_from_target", return_value=PATIENT_UUID):
            effects = handler.compute()

        assert len(effects) == 2
        payloads = [json.loads(e.payload) for e in effects]
        sections = sorted(p["data"]["message"]["section"] for p in payloads)
        assert sections == ["conditions", "surgicalHistory"]
        for p in payloads:
            assert p["data"]["channel"] == f"patient-{PATIENT_UUID}"

    def test_missing_patient_id_returns_empty(self) -> None:
        handler = _make("MEDICATION_LIST_ITEM_CREATED")
        with patch.object(publisher.EventType, "Name", return_value="MEDICATION_LIST_ITEM_CREATED"), \
             patch.object(publisher, "_patient_id_from_target", return_value=None):
            assert handler.compute() == []

    def test_target_falls_back_to_context(self) -> None:
        handler = _make("INTERVIEW_CREATED", target=None, context={"target": "ctx-target"})
        with patch.object(publisher.EventType, "Name", return_value="INTERVIEW_CREATED"), \
             patch.object(publisher, "_patient_id_from_target", return_value=PATIENT_UUID) as mock_lookup:
            effects = handler.compute()

        assert len(effects) == 1
        assert mock_lookup.call_args[0][1] == "ctx-target"
