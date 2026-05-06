import pytest


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
