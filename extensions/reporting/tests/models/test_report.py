from reporting.models.report import Report


def test_report_is_custom_model():
    from canvas_sdk.v1.data.base import CustomModel
    assert issubclass(Report, CustomModel)


def test_report_instance_holds_definition_and_owner():
    r = Report(name="No-shows", category="Operations", visibility="shared",
               definition={"dataset_key": "appointments"}, owner_id=7, version=1)
    assert r.name == "No-shows"
    assert r.visibility == "shared"
    assert r.definition["dataset_key"] == "appointments"
    assert r.owner_id == 7
