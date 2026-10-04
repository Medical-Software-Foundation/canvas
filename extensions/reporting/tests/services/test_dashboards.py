from unittest.mock import MagicMock, patch

from reporting.services import dashboards as svc


def test_serialize_summary_has_widget_count():
    row = MagicMock(dbid=2, visibility="shared", owner_id=5,
                    layout={"widgets": [{"report_id": 1}, {"report_id": 2}]})
    row.name = "Ops"
    out = svc.serialize_summary(row)
    assert out == {"id": 2, "name": "Ops", "visibility": "shared",
                   "owner_id": 5, "widget_count": 2}


def test_serialize_detail_has_layout_and_period():
    row = MagicMock(dbid=2, visibility="private", owner_id=5,
                    layout={"widgets": []}, default_period={"granularity": "month"})
    row.name = "Ops"
    out = svc.serialize_detail(row)
    assert out["layout"] == {"widgets": []}
    assert out["default_period"] == {"granularity": "month"}


def test_list_visible_owned_or_shared():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.filter.return_value.order_by.return_value = ["a"]
        assert svc.list_visible(staff_dbid=5) == ["a"]
        assert M.objects.filter.called


def test_create_sets_owner_and_version():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.create.return_value = MagicMock(dbid=7)
        out = svc.create(staff_dbid=5, name="Ops", visibility="shared",
                         layout={"widgets": []}, default_period={})
        kwargs = M.objects.create.call_args.kwargs
        assert kwargs["owner_id"] == 5 and kwargs["version"] == 1
        assert out.dbid == 7


def test_update_optimistic_lock():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.filter.return_value.update.return_value = 1
        assert svc.update(dashboard_id=7, staff_dbid=5, expected_version=1,
                          fields={"name": "X"}) is True
        M.objects.filter.assert_called_with(dbid=7, owner_id=5, version=1)


def test_delete_only_owner():
    with patch("reporting.services.dashboards.Dashboard") as M:
        M.objects.filter.return_value.delete.return_value = (1, {})
        assert svc.delete(dashboard_id=7, staff_dbid=5) is True
        M.objects.filter.assert_called_with(dbid=7, owner_id=5)
