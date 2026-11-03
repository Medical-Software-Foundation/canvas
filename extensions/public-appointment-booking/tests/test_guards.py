import datetime
from datetime import UTC

import pytest

from public_appointment_booking import guards

TODAY = datetime.date(2026, 11, 2)


def _payload(**overrides: object) -> dict:
    base = {
        "first_name": "Ana",
        "last_name": "O'Neil-Smith",
        "birth_date": "1990-04-01",
        "email": "Ana@Example.org",
        "phone": "(555) 123-4567",
        "provider_id": "abc123",
        "start_iso": "2026-11-10T15:00:00+00:00",
        "reason": "Follow-up",
    }
    base.update(overrides)
    return base


# ---- enabled flag ---------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "false", "yes", "1", "on", " TRUEish"])
def test_is_enabled_is_off_unless_exactly_true(value: object) -> None:
    assert guards.is_enabled({guards.ENABLED_SECRET: value}) is False


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_is_enabled_accepts_true_any_case(value: str) -> None:
    assert guards.is_enabled({guards.ENABLED_SECRET: value}) is True


def test_is_enabled_off_when_secret_missing() -> None:
    assert guards.is_enabled({}) is False


# ---- numeric settings -------------------------------------------------------------


def test_lead_time_defaults_and_bounds() -> None:
    assert guards.lead_time_minutes({}) == 120
    assert guards.lead_time_minutes({guards.LEAD_TIME_SECRET: "30"}) == 30
    assert guards.lead_time_minutes({guards.LEAD_TIME_SECRET: "-1"}) == 120
    assert guards.lead_time_minutes({guards.LEAD_TIME_SECRET: "abc"}) == 120


def test_window_days_capped_at_cache_ceiling() -> None:
    assert guards.window_days({}) == 14
    assert guards.window_days({guards.WINDOW_DAYS_SECRET: "7"}) == 7
    assert guards.window_days({guards.WINDOW_DAYS_SECRET: "30"}) == 14
    assert guards.window_days({guards.WINDOW_DAYS_SECRET: "0"}) == 14


# ---- validation -------------------------------------------------------------------


def test_validate_normalizes_good_payload() -> None:
    data = guards.validate_booking(_payload(), today=TODAY)
    assert data["email"] == "ana@example.org"
    assert data["phone"] == "5551234567"
    assert data["birth_date"] == datetime.date(1990, 4, 1)
    assert data["start_time"] == datetime.datetime(2026, 11, 10, 15, tzinfo=UTC)
    assert data["last_name"] == "O'Neil-Smith"


def test_validate_accepts_non_ascii_names() -> None:
    data = guards.validate_booking(
        _payload(first_name="José", last_name="Núñez"), today=TODAY
    )
    assert data["first_name"] == "José"


def test_validate_accepts_missing_reason() -> None:
    payload = _payload()
    del payload["reason"]
    assert guards.validate_booking(payload, today=TODAY)["reason"] == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_name", ""),
        ("first_name", "   "),
        ("first_name", "<script>"),
        ("first_name", "Ana1"),
        ("first_name", "A" * 61),
        ("first_name", 42),
        ("last_name", None),
        ("birth_date", "04/01/1990"),
        ("birth_date", "2027-01-01"),
        ("birth_date", "1890-01-01"),
        ("email", "not-an-email"),
        ("email", "a@b"),
        ("phone", "12345"),
        ("phone", "555-123-45678"),
        ("provider_id", "../etc"),
        ("provider_id", "x" * 65),
        ("start_iso", "tomorrow"),
        ("start_iso", "2026-11-10T15:00:00"),
        ("reason", "x" * 301),
        ("reason", ["list"]),
        ("reason", "bad\x00byte"),
    ],
)
def test_validate_rejects_bad_field(field: str, value: object) -> None:
    with pytest.raises(guards.ValidationError) as exc:
        guards.validate_booking(_payload(**{field: value}), today=TODAY)
    assert exc.value.field == field


def test_validate_rejects_non_object_body() -> None:
    with pytest.raises(guards.ValidationError) as exc:
        guards.validate_booking(["a"], today=TODAY)
    assert exc.value.field == "body"


def test_normalize_phone_accepts_leading_country_code() -> None:
    assert guards.normalize_phone("+1 555 123 4567") == "5551234567"
    assert guards.normalize_phone("555.123.4567") == "5551234567"
    assert guards.normalize_phone("abc") is None


# ---- origin / CSRF ------------------------------------------------------------------


def test_hostname_from_url_strips_scheme_port_path_userinfo() -> None:
    assert (
        guards.hostname_from_url("https://user@Clinic.Example.com:8443/a/b")
        == "clinic.example.com"
    )
    assert guards.hostname_from_url("http://[::1]:8000/") == "::1"


def test_allowed_hosts_includes_instance_forwarded_host_and_extras() -> None:
    hosts = guards.allowed_hosts(
        {guards.ALLOWED_HOSTS_SECRET: "book.example.org, https://www.example.org/"},
        {"CUSTOMER_IDENTIFIER": "demo"},
        {"X-Forwarded-Host": "demo.canvasmedical.com"},
    )
    assert hosts == {"demo.canvasmedical.com", "book.example.org", "www.example.org"}


def test_origin_allowed_for_same_host() -> None:
    hosts = {"demo.canvasmedical.com"}
    assert guards.origin_allowed({"Origin": "https://demo.canvasmedical.com"}, hosts)


def test_origin_rejected_for_other_host() -> None:
    hosts = {"demo.canvasmedical.com"}
    assert not guards.origin_allowed({"Origin": "https://evil.example"}, hosts)


def test_origin_rejected_for_lookalike_suffix_host() -> None:
    hosts = {"demo.canvasmedical.com"}
    assert not guards.origin_allowed(
        {"Origin": "https://demo.canvasmedical.com.evil.example"}, hosts
    )


def test_referer_used_when_origin_missing() -> None:
    hosts = {"demo.canvasmedical.com"}
    assert not guards.origin_allowed({"Referer": "https://evil.example/page"}, hosts)
    assert guards.origin_allowed({"Referer": "https://demo.canvasmedical.com/x"}, hosts)


def test_null_origin_rejected() -> None:
    assert not guards.origin_allowed({"Origin": "null"}, {"demo.canvasmedical.com"})


def test_origin_present_but_no_known_hosts_fails_closed() -> None:
    assert not guards.origin_allowed(
        {"Origin": "https://demo.canvasmedical.com"}, set()
    )


def test_no_origin_header_is_allowed_for_non_browser_clients() -> None:
    assert guards.origin_allowed({}, set())


def test_is_json_request() -> None:
    assert guards.is_json_request({"Content-Type": "application/json; charset=utf-8"})
    assert not guards.is_json_request(
        {"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert not guards.is_json_request({"Content-Type": "text/plain"})
    assert not guards.is_json_request({})


# ---- rate limiting ---------------------------------------------------------------------


def test_client_key_uses_last_forwarded_hop() -> None:
    assert guards.client_key({"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}) == "10.0.0.1"
    # A caller-chosen first hop can't pick a new bucket.
    assert guards.client_key({"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}) == "10.0.0.1"
    assert guards.client_key({"X-Real-Ip": "198.51.100.7"}) == "198.51.100.7"
    assert guards.client_key({}) == "unknown"


def test_rate_limit_allows_up_to_limit_then_blocks(cache) -> None:
    limit = (3, 60)
    results = [guards.hit_rate_limit(cache, "k", limit) for _ in range(5)]
    assert results == [False, False, False, True, True]
    assert cache.timeouts["rl:k"] == 60


def test_rate_limit_keys_are_independent(cache) -> None:
    limit = (1, 60)
    assert guards.hit_rate_limit(cache, "a", limit) is False
    assert guards.hit_rate_limit(cache, "a", limit) is True
    assert guards.hit_rate_limit(cache, "b", limit) is False
