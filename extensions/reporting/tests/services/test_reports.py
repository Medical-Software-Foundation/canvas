from unittest.mock import MagicMock, patch

from reporting.services import reports as svc


def test_serialize_summary_omits_definition():
    row = MagicMock(dbid=3, category="Operations",
                    visibility="shared", owner_id=5)
    row.name = "X"  # MagicMock(name=...) sets the mock display name, not an attr
    out = svc.serialize_summary(row)
    assert out == {"id": 3, "name": "X", "category": "Operations",
                   "visibility": "shared", "owner_id": 5}
    assert "definition" not in out


def test_serialize_detail_includes_definition():
    row = MagicMock(dbid=3, category="Operations",
                    visibility="private", owner_id=5,
                    definition={"dataset_key": "appointments"})
    row.name = "X"  # MagicMock(name=...) sets the mock display name, not an attr
    out = svc.serialize_detail(row)
    assert out["id"] == 3
    assert out["definition"] == {"dataset_key": "appointments"}


def test_list_visible_returns_owned_and_shared():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.order_by.return_value = ["a", "b"]
        result = svc.list_visible(staff_dbid=5)
        assert M.objects.filter.called
        assert result == ["a", "b"]


def test_create_persists_and_returns_instance():
    with patch("reporting.services.reports.Report") as M:
        M.objects.create.return_value = MagicMock(dbid=9)
        out = svc.create(staff_dbid=5, name="N", category="Operations",
                         visibility="private", definition={"x": 1})
        M.objects.create.assert_called_once()
        kwargs = M.objects.create.call_args.kwargs
        assert kwargs["owner_id"] == 5 and kwargs["version"] == 1
        assert out.dbid == 9


def test_update_uses_version_optimistic_lock():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.update.return_value = 1
        ok = svc.update(report_id=9, staff_dbid=5, expected_version=1,
                        fields={"name": "New"})
        assert ok is True
        M.objects.filter.assert_called_with(dbid=9, owner_id=5, version=1)


def test_update_returns_false_on_version_conflict():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.update.return_value = 0
        ok = svc.update(report_id=9, staff_dbid=5, expected_version=1,
                        fields={"name": "New"})
        assert ok is False


def test_delete_only_owner():
    with patch("reporting.services.reports.Report") as M:
        M.objects.filter.return_value.delete.return_value = (1, {})
        ok = svc.delete(report_id=9, staff_dbid=5)
        assert ok is True
        M.objects.filter.assert_called_with(dbid=9, owner_id=5)
