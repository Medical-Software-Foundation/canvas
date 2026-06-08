"""Tests for the Photon patient pre-sync dispatch handler."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from photon_integration.client.photon_client import PhotonError
from photon_integration.handlers.dispatch import PhotonDispatchHandler

MODULE = "photon_integration.handlers.dispatch"

PRESCRIBER_UUID = "11111111-1111-1111-1111-111111111111"
TEAM_UUID = "22222222-2222-2222-2222-222222222222"

DEFAULT_SECRETS = {
    "PHOTON_CLIENT_ID": "cid",
    "PHOTON_CLIENT_SECRET": "secret",
    "PHOTON_ENV": "sandbox",
}
DEFAULT_FIELDS = {"prescriber": {"id": PRESCRIBER_UUID}}


def _event(fields=None, patient_id="pt-1", command_id="cmd-1"):
    return SimpleNamespace(
        context={
            "patient": {"id": patient_id} if patient_id else {},
            "fields": fields if fields is not None else dict(DEFAULT_FIELDS),
        },
        target=SimpleNamespace(id=command_id),
    )


@contextlib.contextmanager
def _patched(*, selected=True, patient=None, resolve_result=("pat_1", None),
             resolve_error=None):
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}._photon_send_selected", return_value=selected))
        patient_cls = stack.enter_context(patch(f"{MODULE}.Patient"))
        patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        if patient is Exception:
            patient_cls.objects.get.side_effect = patient_cls.DoesNotExist
        else:
            patient_cls.objects.get.return_value = patient or SimpleNamespace(id="pt-1")
        stack.enter_context(patch(f"{MODULE}.build_client", return_value=MagicMock()))
        resolve = stack.enter_context(patch(f"{MODULE}.resolve_photon_patient"))
        if resolve_error is not None:
            resolve.side_effect = resolve_error
        else:
            resolve.return_value = resolve_result
        add_task = stack.enter_context(patch(f"{MODULE}.AddTask"))
        add_task.return_value.apply.return_value = "TASK_EFFECT"
        yield SimpleNamespace(resolve=resolve, add_task=add_task)


class TestGuards:
    def test_not_selected(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(selected=False) as m:
            assert handler.compute() == []
        m.resolve.assert_not_called()

    def test_missing_patient_id(self):
        handler = PhotonDispatchHandler(event=_event(patient_id=None), secrets=DEFAULT_SECRETS)
        with _patched() as m:
            assert handler.compute() == []
        m.resolve.assert_not_called()

    def test_patient_not_found(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=Exception) as m:
            assert handler.compute() == []
        m.resolve.assert_not_called()


class TestSync:
    def test_new_patient_returns_external_id_effect(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(resolve_result=("pat_new", "EXT_EFFECT")):
            assert handler.compute() == ["EXT_EFFECT"]

    def test_already_synced_returns_nothing(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(resolve_result=("pat_existing", None)):
            assert handler.compute() == []

    def test_does_not_attempt_prescription(self):
        # The handler must never try to create a prescription/order (impossible
        # via M2M); it only syncs the patient.
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(resolve_result=("pat_new", "EXT_EFFECT")) as m:
            handler.compute()
        m.resolve.assert_called_once()


class TestFailure:
    def test_sync_error_creates_task(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(resolve_error=PhotonError("no phone")) as m:
            assert handler.compute() == ["TASK_EFFECT"]
        kwargs = m.add_task.call_args.kwargs
        assert kwargs["patient_id"] == "pt-1"
        assert kwargs["assignee_id"] == PRESCRIBER_UUID
        assert "sync failed" in kwargs["title"]
        assert kwargs["labels"] == ["photon"]

    def test_non_uuid_prescriber_unassigned(self):
        fields = {"prescriber": {"id": "usr_01KTFYYT32QNR8ZPCW7QTWBXXD"}}
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(resolve_error=PhotonError("boom")) as m:
            handler.compute()
        assert m.add_task.call_args.kwargs["assignee_id"] is None

    def test_fallback_team_when_no_prescriber(self):
        fields = {"prescriber": None}
        secrets = dict(DEFAULT_SECRETS, PHOTON_FALLBACK_TEAM_ID=TEAM_UUID)
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=secrets)
        with _patched(resolve_error=PhotonError("boom")) as m:
            handler.compute()
        kwargs = m.add_task.call_args.kwargs
        assert kwargs["team_id"] == TEAM_UUID
        assert kwargs["assignee_id"] is None
