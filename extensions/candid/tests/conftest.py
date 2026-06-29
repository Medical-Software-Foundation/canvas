import sys
import types
from unittest.mock import MagicMock

import pytest

# The locked canvas_sdk in this plugin's venv doesn't yet expose
# canvas_sdk.effects.http_request; stub it so plugin modules import cleanly.
if "canvas_sdk.effects.http_request" not in sys.modules:
    stub = types.ModuleType("canvas_sdk.effects.http_request")
    stub.HttpRequestEffect = MagicMock()
    sys.modules["canvas_sdk.effects.http_request"] = stub


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    return {
        "CANDID_BASE_URL": "https://api.candid.test",
        "CANDID_CLIENT_ID": "client-id",
        "CANDID_CLIENT_SECRET": "client-secret",
    }


MOCK_SECRETS = {
    "CANDID_BASE_URL": "https://api.candid.test",
    "CANDID_CLIENT_ID": "client-id",
    "CANDID_CLIENT_SECRET": "client-secret",
}
