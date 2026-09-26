from reporting.models.dashboard import Dashboard


def test_dashboard_is_custom_model():
    from canvas_sdk.v1.data.base import CustomModel
    assert issubclass(Dashboard, CustomModel)


def test_dashboard_holds_layout_and_owner():
    d = Dashboard(name="Weekly Ops", visibility="shared",
                  layout={"widgets": [{"report_id": 1, "span": 2}]},
                  default_period={"granularity": "month", "count": 3},
                  owner_id=5, version=1)
    assert d.name == "Weekly Ops"
    assert d.layout["widgets"][0]["report_id"] == 1
    assert d.owner_id == 5
