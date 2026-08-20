"""Page and asset serving for the patient surface."""

import json

from patient_resources.routes.portal_pages import PortalPagesAPI


def _api(make_request, **kwargs):
    api = PortalPagesAPI.__new__(PortalPagesAPI)
    api.secrets = {}
    api.request = make_request(**kwargs)
    return api


def test_portal_page_renders_its_template(make_request):
    responses = _api(make_request).get_portal_page()
    assert "templates/portal.html" in responses[0].body
    assert responses[0].content_type == "text/html"
    assert responses[0].headers["Cache-Control"] == "no-cache"


def test_portal_config_contains_no_patient_identifier(make_request, rendered_context):
    """The page has nothing to send that could name a patient.

    That is what makes a cross-patient read impossible rather than merely
    checked for.
    """
    _api(make_request, query_params={"patient": "somebody-else"}).get_portal_page()
    config = json.loads(rendered_context()["config_json"])
    assert set(config) == {"apiBase", "cacheBust"}
    assert "somebody-else" not in json.dumps(config)


def test_portal_assets_have_their_own_content_types(make_request):
    api = _api(make_request)
    assert api.get_portal_css()[0].content_type == "text/css"
    assert api.get_portal_js()[0].content_type == "application/javascript"


def test_portal_assets_are_separate_files_from_the_staff_ones(make_request):
    """The patient page must not load a bundle that knows how to call staff routes."""
    css = _api(make_request).get_portal_css()[0].body.decode()
    assert "static/css/portal.css" in css
