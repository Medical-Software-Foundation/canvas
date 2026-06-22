"""Fixtures for AVS service tests.

The AVS extractor now queries ``LabOrder`` directly (the previous broad
try/except was removed per the no-silent-failure rule). These tests exercise
the command-data path, so by default we stub ``LabOrder`` to return nothing,
which triggers the labOrder command-data fallback in ``_extract_todo_list``.
"""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _stub_lab_order():
    with patch("portal_content.services.avs_data_extractor.LabOrder") as lab_order:
        lab_order.objects.filter.return_value.prefetch_related.return_value = []
        yield lab_order
