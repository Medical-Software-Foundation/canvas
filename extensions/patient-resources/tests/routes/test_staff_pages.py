"""Page and asset serving for the staff surfaces."""

import json

from patient_resources import CACHE_BUST
from patient_resources.routes.staff_pages import StaffPagesAPI


def _api(make_request, **kwargs):
    api = StaffPagesAPI.__new__(StaffPagesAPI)
    api.secrets = {}
    api.request = make_request(**kwargs)
    return api


def test_library_page_renders_its_template(make_request):
    responses = _api(make_request).get_library_page()
    assert len(responses) == 1
    assert "templates/library.html" in responses[0].body
    assert responses[0].content_type == "text/html"


def test_pages_are_served_no_cache(make_request):
    """The HTML shell must not be cached; its assets carry the version instead."""
    for responses in (
        _api(make_request).get_library_page(),
        _api(make_request).get_picker_page(),
    ):
        assert responses[0].headers["Cache-Control"] == "no-cache"


def test_library_config_carries_the_api_base_and_no_patient_data(make_request, rendered_context):
    _api(make_request).get_library_page()
    config = json.loads(rendered_context()["config_json"])
    assert config == {"apiBase": "/plugin-io/api/patient_resources", "cacheBust": CACHE_BUST}


def test_picker_config_carries_the_patient_key(make_request, rendered_context):
    _api(make_request, query_params={"patient": "abc123"}).get_picker_page()
    assert json.loads(rendered_context()["config_json"])["patientId"] == "abc123"


def test_picker_trims_the_patient_key(make_request, rendered_context):
    _api(make_request, query_params={"patient": "  abc123  "}).get_picker_page()
    assert json.loads(rendered_context()["config_json"])["patientId"] == "abc123"


def test_picker_without_a_patient_renders_an_empty_key(make_request, rendered_context):
    """The page then reports the patient could not be found, rather than sharing with nobody."""
    _api(make_request).get_picker_page()
    assert json.loads(rendered_context()["config_json"])["patientId"] == ""


def test_a_patient_key_containing_markup_is_escaped(make_request, rendered_context):
    """The whole reason the config goes through safe_json before ``|safe``."""
    _api(
        make_request, query_params={"patient": '</script><img src=x onerror=alert(1)>'}
    ).get_picker_page()
    rendered = rendered_context()["config_json"]
    assert "</script>" not in rendered
    assert "<" not in rendered


def test_this_class_never_looks_the_patient_up(make_request):
    """It declares zero data access, so it must not query anything."""
    from canvas_sdk.v1.data import Patient

    Patient.objects.reset_mock()
    _api(make_request, query_params={"patient": "abc"}).get_picker_page()
    Patient.objects.filter.assert_not_called()


def test_assets_are_served_with_their_own_content_types(make_request):
    api = _api(make_request)
    assert api.get_library_css()[0].content_type == "text/css"
    assert api.get_library_js()[0].content_type == "application/javascript"
    assert api.get_picker_js()[0].content_type == "application/javascript"


def test_assets_are_served_as_bytes(make_request):
    """Response takes bytes; passing str here worked in tests and not on the instance."""
    assert isinstance(_api(make_request).get_library_css()[0].body, bytes)


def test_asset_urls_in_the_page_are_absolute(make_request, rendered_context):
    """A relative href resolves against whether the page URL ended in a slash."""
    _api(make_request).get_library_page()
    assert rendered_context()["asset_base"] == "/plugin-io/api/patient_resources/app"
