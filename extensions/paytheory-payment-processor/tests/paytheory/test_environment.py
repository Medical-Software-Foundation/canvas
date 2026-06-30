from paytheory_payment_processor.paytheory.environment import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_PARTNER,
    ENVIRONMENT_DOMAINS,
    get_api_url,
    get_domain,
    get_sdk_url,
    get_tags_static_url,
    get_token_service_url,
)


class TestDefaults:
    def test_default_environment(self):
        assert DEFAULT_ENVIRONMENT == "production"

    def test_default_partner(self):
        assert DEFAULT_PARTNER == "canvas"

    def test_environment_domains(self):
        assert ENVIRONMENT_DOMAINS == {
            "production": "paytheory.com",
            "sandbox": "paytheorystudy.com",
            "lab": "paytheorylab.com",
        }


class TestGetDomain:
    def test_production(self):
        assert get_domain("production") == "paytheory.com"

    def test_sandbox(self):
        assert get_domain("sandbox") == "paytheorystudy.com"

    def test_lab(self):
        assert get_domain("lab") == "paytheorylab.com"

    def test_unknown_falls_back_to_production(self):
        assert get_domain("unknown") == "paytheory.com"


class TestGetSdkUrl:
    def test_production(self):
        assert get_sdk_url("canvas", "production") == "https://canvas.sdk.paytheory.com/index.js"

    def test_sandbox(self):
        assert get_sdk_url("canvas", "sandbox") == "https://canvas.sdk.paytheorystudy.com/index.js"

    def test_lab(self):
        assert get_sdk_url("canvas", "lab") == "https://canvas.sdk.paytheorylab.com/index.js"

    def test_default_partner(self):
        assert get_sdk_url("start", "production") == "https://start.sdk.paytheory.com/index.js"


class TestGetApiUrl:
    def test_production(self):
        assert get_api_url("canvas", "production") == "https://api.canvas.paytheory.com/graphql"

    def test_sandbox(self):
        assert get_api_url("canvas", "sandbox") == "https://api.canvas.paytheorystudy.com/graphql"

    def test_lab(self):
        assert get_api_url("canvas", "lab") == "https://api.canvas.paytheorylab.com/graphql"


class TestGetTokenServiceUrl:
    def test_production(self):
        assert get_token_service_url("canvas", "production") == "https://canvas.paytheory.com/pt-token-service/"

    def test_sandbox(self):
        assert get_token_service_url("canvas", "sandbox") == "https://canvas.paytheorystudy.com/pt-token-service/"


class TestGetTagsStaticUrl:
    def test_production(self):
        assert get_tags_static_url("canvas", "production") == "https://canvas.tags.static.paytheory.com"

    def test_sandbox(self):
        assert get_tags_static_url("canvas", "sandbox") == "https://canvas.tags.static.paytheorystudy.com"
