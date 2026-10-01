"""Tests for metadata-column filter chips (T2).

Metadata columns may declare `filterable: true` (with optional
`filter_options: [...]`). The UI emits a `metadata_<key>=v1,v2`
query param; the panel restricts the queryset to patients whose
metadata record matches one of those values.

Real Patient/PatientMetadata records — no canvas_sdk mocking.
"""

__is_plugin__ = True

import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import Patient, PatientMetadata as PatientMetadataRecord

from tests._helpers import build_api


pytestmark = pytest.mark.django_db


def _seed(key: str, value: str | None) -> Patient:
    p = PatientFactory.create()
    if value is not None:
        PatientMetadataRecord.objects.create(patient=p, key=key, value=value)
    return p


class TestMetadataFiltersEndToEnd:
    def test_get_table_reads_metadata_query_param(self) -> None:
        """End-to-end: query param `metadata_risk_score=Low` filters the table.
        Uses PANEL_CONFIG with a filterable risk_score column."""
        import json
        from http import HTTPStatus

        low = _seed("risk_score", "Low")
        _high = _seed("risk_score", "High")

        panel_config = json.dumps(
            {
                "columns": [
                    {"type": "built-in", "key": "patient", "visible": True},
                    {
                        "type": "metadata",
                        "key": "risk_score",
                        "label": "Risk",
                        "visible": True,
                        "filterable": True,
                        "filter_options": ["Low", "Medium", "High"],
                    },
                ]
            }
        )
        api = build_api(
            secrets={"PANEL_CONFIG": panel_config},
            query_params={
                "metadata_risk_score": "Low",
                "no_auto_filter": "1",
            },
        )
        result = api.get_table()
        assert result[0].status_code == HTTPStatus.OK
        body = result[0].content.decode()
        assert str(low.id) in body
        # Heuristic: the high-risk patient row must not appear
        assert str(_high.id) not in body
