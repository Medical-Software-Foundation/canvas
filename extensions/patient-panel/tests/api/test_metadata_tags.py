"""Tests for multi-tag rendering of metadata columns (T4).

A metadata column with `render: "tags"` is rendered as one chip per
pipe-delimited value. Empty values fall back to the empty-cell em-dash.

Uses real Patient + PatientMetadata records (no canvas_sdk mocking) and
exercises the full `get_table` rendering path.
"""

__is_plugin__ = True

import json
from http import HTTPStatus

import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord

from tests._helpers import build_api


pytestmark = pytest.mark.django_db


def _panel_config_with_services(render: str | None = "tags") -> str:
    col: dict = {
        "type": "metadata",
        "key": "services",
        "label": "Services",
        "visible": True,
    }
    if render is not None:
        col["render"] = render
    return json.dumps({"columns": [
        {"type": "built-in", "key": "patient", "visible": True},
        col,
    ]})


def _seed(value: str) -> object:
    p = PatientFactory.create()
    PatientMetadataRecord.objects.create(patient=p, key="services", value=value)
    return p


class TestMetadataTagsRendering:
    def test_pipe_delimited_value_becomes_chips(self) -> None:
        _seed("PCP|Wellness|PRN")
        api = build_api(
            secrets={"PANEL_CONFIG": _panel_config_with_services()},
            query_params={"no_auto_filter": "1"},
        )
        result = api.get_table()
        assert result[0].status_code == HTTPStatus.OK
        body = result[0].content.decode()
        # Each tag rendered inside a chip element.
        for tag in ("PCP", "Wellness", "PRN"):
            assert f">{tag}<" in body, f"tag {tag!r} missing"
        assert body.count('class="metadata-tag"') >= 3

    def test_whitespace_trimmed(self) -> None:
        _seed(" PCP | Wellness ")
        api = build_api(
            secrets={"PANEL_CONFIG": _panel_config_with_services()},
            query_params={"no_auto_filter": "1"},
        )
        body = api.get_table()[0].content.decode()
        assert ">PCP<" in body
        assert ">Wellness<" in body
        # Make sure the leading/trailing space did not produce an empty chip.
        assert "><span class=\"metadata-tag\"></span>" not in body

    def test_empty_value_renders_emdash(self) -> None:
        # No metadata at all → empty cell
        PatientFactory.create()
        api = build_api(
            secrets={"PANEL_CONFIG": _panel_config_with_services()},
            query_params={"no_auto_filter": "1"},
        )
        body = api.get_table()[0].content.decode()
        # Generic empty fallback is the em-dash from .care-team-empty span.
        assert "care-team-empty" in body

    def test_no_render_flag_still_uses_plain_text(self) -> None:
        _seed("PCP|Wellness")
        api = build_api(
            secrets={"PANEL_CONFIG": _panel_config_with_services(render=None)},
            query_params={"no_auto_filter": "1"},
        )
        body = api.get_table()[0].content.decode()
        # No tag class anywhere; raw string rendered.
        assert "metadata-tag" not in body
        assert "PCP|Wellness" in body

    def test_single_value_renders_one_chip(self) -> None:
        _seed("Hospice")
        api = build_api(
            secrets={"PANEL_CONFIG": _panel_config_with_services()},
            query_params={"no_auto_filter": "1"},
        )
        body = api.get_table()[0].content.decode()
        assert body.count('class="metadata-tag"') == 1
        assert ">Hospice<" in body
