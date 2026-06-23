from types import SimpleNamespace

import pytest

from provider_productivity_compensation.applications.productivity_dashboard import (
    ProductivityDashboardApi,
)


@pytest.fixture
def make_api():
    """Factory that builds a ProductivityDashboardApi instance without invoking
    the SimpleAPI __init__, wiring up the `secrets` and `request` it reads from.

    `request.headers` is a plain dict (the handler indexes it directly) and
    `request.query_params` is a plain dict (the handler calls `.get` on it).
    """

    def _make(secrets=None, headers=None, query_params=None):
        api = ProductivityDashboardApi.__new__(ProductivityDashboardApi)
        api.secrets = secrets if secrets is not None else {}
        api.request = SimpleNamespace(
            headers=headers if headers is not None else {},
            query_params=query_params if query_params is not None else {},
        )
        return api

    return _make
