"""Tests for panel_stats_sync event handlers."""

__is_plugin__ = True

from typing import Any

import pytest

from canvas_sdk.test_utils.factories import PatientFactory, TaskFactory

from patient_panel.models import PatientPanelStats
from patient_panel.handlers.panel_stats_sync import (
    PanelStatsOnPatientCreated,
    PanelStatsOnTaskCreated,
    _patient_uuid_from_context,
)


pytestmark = pytest.mark.django_db


class _Ev:
    def __init__(self, context: dict[str, Any] | None = None, target_id: str | None = None) -> None:
        self.context = context or {}
        self.target = type("T", (), {"id": target_id})()


def test_patient_uuid_from_context_prefers_patient_id() -> None:
    assert _patient_uuid_from_context(_Ev(context={"patient_id": "abc"})) == "abc"


def test_patient_uuid_from_context_patient_fallback() -> None:
    assert _patient_uuid_from_context(_Ev(context={"patient": "xyz"})) == "xyz"


def test_handler_recomputes_for_event_patient() -> None:
    p = PatientFactory.create()
    TaskFactory.create(patient=p, status="OPEN")
    handler = PanelStatsOnTaskCreated(event=_Ev(context={"patient_id": str(p.id)}))
    assert handler.compute() == []
    assert PatientPanelStats.objects.get(patient_id=p.dbid).tasks_open_count == 1


def test_handler_noop_when_no_patient() -> None:
    handler = PanelStatsOnTaskCreated(event=_Ev(context={}))
    assert handler.compute() == []
    assert PatientPanelStats.objects.count() == 0


def test_patient_target_handler_uses_target_id_fallback() -> None:
    p = PatientFactory.create()
    handler = PanelStatsOnPatientCreated(event=_Ev(context={}, target_id=str(p.id)))
    assert handler.compute() == []
    assert PatientPanelStats.objects.filter(patient_id=p.dbid).exists()


def test_patient_uuid_from_context_nested_patient_dict() -> None:
    assert _patient_uuid_from_context(_Ev(context={"patient": {"id": "abc"}})) == "abc"


def test_handler_recomputes_for_nested_patient_context() -> None:
    p = PatientFactory.create()
    TaskFactory.create(patient=p, status="OPEN")
    handler = PanelStatsOnTaskCreated(event=_Ev(context={"patient": {"id": str(p.id)}}))
    assert handler.compute() == []
    assert PatientPanelStats.objects.get(patient_id=p.dbid).tasks_open_count == 1


def test_compute_swallows_recompute_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import patient_panel.handlers.panel_stats_sync as mod

    def _boom(_uuid: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "recompute_stats_for_patient_uuid", _boom)
    p = PatientFactory.create()
    handler = PanelStatsOnTaskCreated(event=_Ev(context={"patient_id": str(p.id)}))
    assert handler.compute() == []


def test_debounce_coalesces_repeat_recomputes(monkeypatch: pytest.MonkeyPatch) -> None:
    import patient_panel.handlers.panel_stats_sync as mod

    class _FakeCache:
        def __init__(self) -> None:
            self.store: dict[str, Any] = {}

        def get(self, key: str) -> Any:
            return self.store.get(key)

        def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
            self.store[key] = value

    fake = _FakeCache()
    monkeypatch.setattr(mod, "get_cache", lambda: fake)
    calls: list[str] = []
    monkeypatch.setattr(mod, "recompute_stats_for_patient_uuid", lambda uuid: calls.append(uuid))

    ev = _Ev(context={"patient_id": "same-uuid"})
    PanelStatsOnTaskCreated(event=ev).compute()
    PanelStatsOnTaskCreated(event=ev).compute()

    assert calls == ["same-uuid"]
