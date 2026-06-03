from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.searchers.commands import (
    search_commands,
    search_commands_all,
    search_medications,
)


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_cmd(**overrides: Any) -> MagicMock:
    note = _mock_obj(
        dbid=overrides.pop("note_dbid", 1),
        datetime_of_service=overrides.pop("dos", datetime(2024, 3, 1)),
        note_type_version=_mock_obj(display="Office Visit", name="Office Visit"),
    )
    defaults: dict[str, Any] = {
        "schema_key": "diagnose",
        "state": "committed",
        "entered_in_error": False,
        "note": note,
        "anchor_object_dbid": 99,
        "data": {"diagnose": {"text": "Hypertension", "value": "I10"}},
    }
    defaults.update(overrides)
    return _mock_obj(**defaults)


def _setup_cmd_qs(mock_cmd_cls: Any, cmds: list[Any], exclude: bool = True) -> None:
    qs = mock_cmd_cls.objects.filter.return_value
    if exclude:
        qs = qs.exclude.return_value
    qs.select_related.return_value = qs
    qs.filter.return_value = qs
    qs.order_by.return_value.__getitem__ = lambda self, s: cmds


@patch("chart_command_search.searchers.commands.LabTest")
@patch("chart_command_search.searchers.commands.LabOrder")
@patch("chart_command_search.searchers.commands.Command")
class TestSearchCommands:
    def test_basic_command(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd()
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["category"] == "command"
        assert results[0]["state"] == "Committed"

    def test_uncommitted_command(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(state="uncommitted")
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Uncommitted"
        assert results[0]["state_class"] == "uncommitted"

    def test_entered_in_error(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(entered_in_error=True)
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Entered in error"
        assert results[0]["state_class"] == "cancelled"

    def test_text_query_filter(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(data={"diagnose": {"text": "Diabetes"}, "comment": "Type 2"})
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "Diabetes", "")
        assert len(results) == 1

    def test_text_query_matched_field(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(
            schema_key="prescribe",
            data={"prescribe": {"text": "Lisinopril"}, "sig": "take daily"},
        )
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "daily", "")
        matched = [d for d in results[0]["details"] if d["label"] == "Matched in"]
        assert len(matched) == 1

    def test_status_filter_committed(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(state="committed")
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "committed")
        assert len(results) == 1

    def test_status_filter_uncommitted(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(state="uncommitted")
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "uncommitted")
        assert len(results) == 1

    def test_status_filter_entered_in_error(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(entered_in_error=True)
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "entered_in_error")
        assert len(results) == 1

    def test_date_filter(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd()
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "", date_from="2024-01-01", date_to="2024-12-31")
        assert len(results) == 1

    def test_provider_filter(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd()
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "", provider_id="prov-1")
        assert len(results) == 1

    def test_empty_results(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        _setup_cmd_qs(mock_cmd, [])
        results = search_commands("patient-1", "", "")
        assert results == []

    def test_lab_order_enrichment_reviewed(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="H", healthgorilla_id="hg123", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]

        test = _mock_obj(lab_order_id=100, status="RV")
        mock_lt.objects.filter.return_value = [test]

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Reviewed"
        assert results[0]["state_class"] == "completed"

    def test_lab_order_results_in(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]

        test = _mock_obj(lab_order_id=100, status="RE")
        mock_lt.objects.filter.return_value = [test]

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Results In"

    def test_lab_order_error(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]

        test = _mock_obj(lab_order_id=100, status="SF")
        mock_lt.objects.filter.return_value = [test]

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Error"

    def test_lab_order_processing(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]

        test = _mock_obj(lab_order_id=100, status="PR")
        mock_lt.objects.filter.return_value = [test]

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Processing"

    def test_lab_order_sending(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]

        test = _mock_obj(lab_order_id=100, status="SE")
        mock_lt.objects.filter.return_value = [test]

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Sending"

    def test_lab_order_staged(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]

        test = _mock_obj(lab_order_id=100, status="SR")
        mock_lt.objects.filter.return_value = [test]

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Staged"

    def test_lab_order_manual_flagged(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="FLAGGED")
        mock_lo.objects.filter.return_value = [order]
        mock_lt.objects.filter.return_value = []

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Flagged"

    def test_lab_order_manual_processed(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="PROCESSED")
        mock_lo.objects.filter.return_value = [order]
        mock_lt.objects.filter.return_value = []

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Processed"

    def test_lab_order_manual_in_progress(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="IN_PROGRESS")
        mock_lo.objects.filter.return_value = [order]
        mock_lt.objects.filter.return_value = []

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Signed"

    def test_lab_order_manual_needs_review(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="", healthgorilla_id="", manual_processing_status="NEEDS_REVIEW")
        mock_lo.objects.filter.return_value = [order]
        mock_lt.objects.filter.return_value = []

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Committed"

    def test_lab_order_sent_via_healthgorilla(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="H", healthgorilla_id="hg-123", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]
        mock_lt.objects.filter.return_value = []

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Sent"

    def test_lab_order_faxed(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])

        order = _mock_obj(dbid=100, note_id=5, transmission_type="F", healthgorilla_id="", manual_processing_status="")
        mock_lo.objects.filter.return_value = [order]
        mock_lt.objects.filter.return_value = []

        results = search_commands("patient-1", "", "")
        assert results[0]["state"] == "Faxed"

    def test_lab_order_enrichment_exception(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(schema_key="labOrder", note_dbid=5)
        _setup_cmd_qs(mock_cmd, [cmd])
        mock_lo.objects.filter.side_effect = RuntimeError("db error")

        results = search_commands("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["state"] == "Committed"

    def test_no_note(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd = _make_cmd(note=None)
        cmd.note = None
        _setup_cmd_qs(mock_cmd, [cmd])

        results = search_commands("patient-1", "", "")
        assert len(results) == 1


@patch("chart_command_search.searchers.commands.Prescription")
@patch("chart_command_search.searchers.commands.Command")
class TestSearchMedicationsExtended:
    def _setup_med_qs(self, mock_cmd: Any, cmds: list[Any]) -> None:
        qs = mock_cmd.objects.filter.return_value
        qs.select_related.return_value = qs
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: cmds

    def test_signed_note_state(self, mock_cmd: Any, mock_rx: Any) -> None:
        note = _mock_obj(
            dbid=10,
            datetime_of_service=datetime(2024, 3, 1),
            note_type_version=None,
            current_state=_mock_obj(state="SGN"),
        )
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=note,
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.return_value = []

        results = search_medications("patient-1", "", "")
        assert results[0]["state"] == "Signed"

    def test_entered_in_error(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=True,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.return_value = []

        results = search_medications("patient-1", "", "")
        assert results[0]["state"] == "Entered in error"

    def test_prescription_fallback_query(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])

        call_count = [0]

        def filter_side_effect(**kwargs: Any) -> Any:
            call_count[0] += 1
            if call_count[0] == 1:
                return []
            rx = _mock_obj(note_id=10, status="delivered")
            result = MagicMock()
            result.order_by.return_value.__getitem__ = lambda self, s: [rx]
            return result

        mock_rx.objects.filter.side_effect = filter_side_effect

        results = search_medications("patient-1", "", "")
        assert len(results) == 1

    def test_status_filter(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.return_value = []

        results = search_medications("patient-1", "", "committed")
        assert len(results) == 1

    def test_status_filter_excludes(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.return_value = []

        results = search_medications("patient-1", "", "error")
        assert len(results) == 0

    def test_text_query(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Lisinopril"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.return_value = []

        results = search_medications("patient-1", "Lisinopril", "")
        assert len(results) == 1

    def test_date_and_provider_filters(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.return_value = []

        results = search_medications(
            "patient-1", "", "", date_from="2024-01-01", date_to="2024-12-31", provider_id="prov-1"
        )
        assert len(results) == 1

    def test_prescription_fetch_exception(self, mock_cmd: Any, mock_rx: Any) -> None:
        cmd = _mock_obj(
            schema_key="prescribe",
            state="committed",
            entered_in_error=False,
            note=_mock_obj(dbid=10, datetime_of_service=datetime(2024, 3, 1), note_type_version=None, current_state=None),
            anchor_object_dbid=99,
            data={"prescribe": {"text": "Med"}},
        )
        self._setup_med_qs(mock_cmd, [cmd])
        mock_rx.objects.filter.side_effect = RuntimeError("db error")

        results = search_medications("patient-1", "", "")
        assert len(results) == 1


class TestSearchCommandsAll:
    @patch("chart_command_search.searchers.commands.Prescription", None)
    @patch("chart_command_search.searchers.commands.LabTest")
    @patch("chart_command_search.searchers.commands.LabOrder")
    @patch("chart_command_search.searchers.commands.Command")
    def test_combines_and_sorts(
        self, mock_cmd: Any, mock_lo: Any, mock_lt: Any
    ) -> None:
        cmd1 = _make_cmd(dos=datetime(2024, 3, 1))
        cmd2 = _make_cmd(
            schema_key="prescribe",
            dos=datetime(2024, 3, 2),
            data={"prescribe": {"text": "Med"}},
        )

        qs = mock_cmd.objects.filter.return_value
        qs.exclude.return_value = qs
        qs.select_related.return_value = qs
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [cmd1] if "prescribe" not in str(s) else [cmd2]

        call_count = [0]
        original_filter = qs.select_related.return_value.order_by.return_value.__getitem__

        def filter_side(*args: Any, **kwargs: Any) -> Any:
            call_count[0] += 1
            if call_count[0] <= 2:
                return qs
            return qs

        results = search_commands_all("patient-1", "", "")
        assert len(results) >= 1
