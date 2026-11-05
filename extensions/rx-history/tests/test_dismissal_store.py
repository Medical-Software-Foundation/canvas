"""Contract tests for the ORM-backed dismissal store.

These exercise the store's interaction with the DismissedMedication model and
the Patient/Staff proxies using a lightweight in-memory simulation. Full
end-to-end behavior is verified on localhost via the deploy-and-dismiss
manual check.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch


class _FakeRow:
    def __init__(self, patient_id, drug_description, ndc_code, last_fill_date, dismissed_by_id):
        self.patient = MagicMock()
        self.patient.id = patient_id
        self.drug_description = drug_description
        self.ndc_code = ndc_code
        self.last_fill_date = last_fill_date
        self.dismissed_by = MagicMock()
        self.dismissed_by.id = dismissed_by_id
        self.dismissed_at = datetime(2026, 4, 20, 12, 0, 0)


class _FakeQuerySet:
    def __init__(self, rows):
        self._rows = list(rows)

    def exists(self):
        return bool(self._rows)

    def delete(self):
        count = len(self._rows)
        for row in self._rows:
            row._deleted = True
        return count, {}

    def order_by(self, *args, **kwargs):
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeManager:
    """A dict-of-lists simulator keyed by (patient_id, drug_description, ndc_code, last_fill_date)."""

    def __init__(self):
        self._store = {}  # key -> row

    def _key(self, patient_id, drug_description, ndc_code, last_fill_date):
        return (patient_id, drug_description, ndc_code or "", last_fill_date or "")

    def get_or_create(self, **kwargs):
        patient = kwargs["patient"]
        drug_description = kwargs["drug_description"]
        ndc_code = kwargs["ndc_code"]
        last_fill_date = kwargs["last_fill_date"]
        defaults = kwargs.get("defaults", {})
        staff = defaults.get("dismissed_by")
        k = self._key(patient.id, drug_description, ndc_code, last_fill_date)
        if k in self._store:
            return self._store[k], False
        row = _FakeRow(
            patient.id,
            drug_description,
            ndc_code,
            last_fill_date,
            staff.id if staff else None,
        )
        self._store[k] = row
        return row, True

    def filter(self, **kwargs):
        patient_id = kwargs.get("patient__id")
        drug_description = kwargs.get("drug_description")
        ndc_code = kwargs.get("ndc_code")
        last_fill_date = kwargs.get("last_fill_date")
        matching = []
        for (pid, drug, ndc, fill), row in list(self._store.items()):
            if patient_id is not None and pid != patient_id:
                continue
            if drug_description is not None and drug != drug_description:
                continue
            if ndc_code is not None and ndc != (ndc_code or ""):
                continue
            if last_fill_date is not None and fill != (last_fill_date or ""):
                continue
            matching.append(row)

        class _DeletingQS(_FakeQuerySet):
            def __init__(inner, rows, outer):
                super().__init__(rows)
                inner._outer = outer

            def delete(inner):
                count = len(inner._rows)
                for row in inner._rows:
                    k = (
                        row.patient.id,
                        row.drug_description,
                        row.ndc_code,
                        row.last_fill_date,
                    )
                    inner._outer._store.pop(k, None)
                return count, {}

        return _DeletingQS(matching, self)


def _install_fake_manager(patch_ctx):
    """Patch DismissedMedication, PatientProxy, StaffProxy with fakes."""
    manager = _FakeManager()
    mock_dm = patch_ctx.enter_context(
        patch("rx_history.protocols.dismissal_store.DismissedMedication")
    )
    mock_dm.objects = manager

    mock_patient_cls = patch_ctx.enter_context(
        patch("rx_history.protocols.dismissal_store.PatientProxy")
    )
    mock_patient_cls.objects.get = lambda id: _obj_with_id(id)

    mock_staff_cls = patch_ctx.enter_context(
        patch("rx_history.protocols.dismissal_store.StaffProxy")
    )
    mock_staff_cls.objects.get = lambda id: _obj_with_id(id)
    return manager


def _obj_with_id(id_value):
    m = MagicMock()
    m.id = id_value
    return m


class TestDismissAndIsDismissed:
    def test_dismiss_creates_entry(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import (
            dismiss,
            get_dismissals,
        )

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            entries = get_dismissals("p1")
            assert len(entries) == 1
            assert entries[0]["drug_description"] == "Tamiflu 75mg"
            assert entries[0]["ndc_code"] == "12345"
            assert entries[0]["last_fill_date"] == "Jan 10, 2025"
            assert "dismissed_at" in entries[0]

    def test_dismiss_is_idempotent(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import (
            dismiss,
            get_dismissals,
        )

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            assert len(get_dismissals("p1")) == 1

    def test_is_dismissed_true_for_exact_match(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import dismiss, is_dismissed

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            assert is_dismissed("p1", "Tamiflu 75mg", "12345", "Jan 10, 2025") is True

    def test_is_dismissed_false_for_different_fill_date(self):
        """Tamiflu scenario. A new fill with a different date is treated as new."""
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import dismiss, is_dismissed

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            assert is_dismissed("p1", "Tamiflu 75mg", "12345", "Dec 20, 2025") is False

    def test_is_dismissed_false_for_different_drug(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import dismiss, is_dismissed

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            assert is_dismissed("p1", "Metformin 500mg", "67890", "Jan 10, 2025") is False

    def test_is_dismissed_false_when_none_exist(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import is_dismissed

        with ExitStack() as stack:
            _install_fake_manager(stack)
            assert is_dismissed("p1", "Tamiflu 75mg", "12345", "Jan 10, 2025") is False


class TestUndoDismissal:
    def test_undo_removes_entry(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import (
            dismiss,
            get_dismissals,
            undo_dismissal,
        )

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            result = undo_dismissal("p1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            assert result is True
            assert get_dismissals("p1") == []

    def test_undo_returns_false_when_not_found(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import undo_dismissal

        with ExitStack() as stack:
            _install_fake_manager(stack)
            result = undo_dismissal("p1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            assert result is False

    def test_undo_preserves_other_entries(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import (
            dismiss,
            get_dismissals,
            undo_dismissal,
        )

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            dismiss("p1", "s1", "Metformin 500mg", "67890", "Mar 15, 2025")
            undo_dismissal("p1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            entries = get_dismissals("p1")
            assert len(entries) == 1
            assert entries[0]["drug_description"] == "Metformin 500mg"


class TestGetDismissalsIsolation:
    def test_returns_all_entries_for_patient(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import dismiss, get_dismissals

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Drug A", "", "Jan 2025")
            dismiss("p1", "s1", "Drug B", "111", "Feb 2025")
            dismiss("p1", "s1", "Drug C", "222", "Mar 2025")
            assert len(get_dismissals("p1")) == 3

    def test_returns_empty_for_new_patient(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import get_dismissals

        with ExitStack() as stack:
            _install_fake_manager(stack)
            assert get_dismissals("new-patient") == []

    def test_per_patient_isolation(self):
        from contextlib import ExitStack

        from rx_history.protocols.dismissal_store import dismiss, get_dismissals

        with ExitStack() as stack:
            _install_fake_manager(stack)
            dismiss("p1", "s1", "Tamiflu 75mg", "12345", "Jan 10, 2025")
            dismiss("p2", "s1", "Metformin 500mg", "67890", "Mar 15, 2025")
            assert len(get_dismissals("p1")) == 1
            assert len(get_dismissals("p2")) == 1
            assert get_dismissals("p1")[0]["drug_description"] == "Tamiflu 75mg"
            assert get_dismissals("p2")[0]["drug_description"] == "Metformin 500mg"
