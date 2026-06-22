"""Targeted tests closing branch gaps in config, demographics, visits, and the router."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from portal_content.content_types import demographics, visits
from portal_content.shared import config
from portal_content.handlers.portal_api import PortalContentAPI


def test_config_all_invalid_components_enables_all():
    # exercises the "unknown component" warning and the no-valid-components fallback
    assert config.get_enabled_components({"ENABLED_COMPONENTS": "bogus, nope"}) == config.DEFAULT_ENABLED


def test_config_visits_ok_when_note_types_present():
    # validate_visits_configuration returns None (no raise) when configured
    assert config.validate_visits_configuration({"NOTE_TYPES": "off"}) is None


def test_pharmacy_name_non_dict_returns_none():
    patient = MagicMock()
    patient.preferred_pharmacy = "not-a-dict"
    assert demographics._pharmacy_name(patient) is None


def test_chief_concern_dict_without_comment_returns_none():
    note = MagicMock()
    with patch("portal_content.content_types.visits.Command") as command:
        command.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = {
            "something_else": "x"
        }
        assert visits._chief_concern(note) is None


def _api(secrets, query=None):
    api = PortalContentAPI.__new__(PortalContentAPI)
    api.secrets = secrets
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": "p1"}
    params = query or {}
    request.query_params.get.side_effect = lambda key, default=None: params.get(key, default)
    api.request = request
    return api


def test_visit_avs_forbidden_when_visits_disabled():
    responses = _api({"ENABLED_COMPONENTS": "labs"}, {"note_id": "n1"}).visit_avs()
    assert responses[0].status_code == HTTPStatus.FORBIDDEN


def test_visit_note_forbidden_when_visits_disabled():
    responses = _api({"ENABLED_COMPONENTS": "labs"}, {"note_id": "n1"}).visit_note()
    assert responses[0].status_code == HTTPStatus.FORBIDDEN


def test_visit_note_invalid_id():
    responses = _api({"ENABLED_COMPONENTS": ""}, {"note_id": ""}).visit_note()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
