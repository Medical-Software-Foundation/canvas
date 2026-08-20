"""Configuration parsing.

Every branch here decides who can edit a library that patients ultimately see,
so the important assertions are about what happens when a value is *wrong*.
"""

import sys

from patient_resources.constants import (
    DEFAULT_ADMIN_ROLE_DOMAINS,
    SECRET_ADMIN_ROLE_DOMAINS,
    SECRET_ADMIN_STAFF_IDS,
)
from patient_resources.services.config import PatientResourcesConfig, parse_csv, parse_upper_csv

log = sys.modules["logger"].log


def test_absent_key_defaults_to_administrative_roles():
    """A fresh install must have a working admin without any configuration.

    Not a fail-open: it still requires a real administrative role.
    """
    config = PatientResourcesConfig.from_secrets({})
    assert config.admin_role_domains == DEFAULT_ADMIN_ROLE_DOMAINS


def test_none_secrets_are_tolerated():
    assert PatientResourcesConfig.from_secrets(None).admin_role_domains == DEFAULT_ADMIN_ROLE_DOMAINS


def test_blank_value_denies_everyone_and_warns():
    """An operator who emptied this meant to switch curation off."""
    config = PatientResourcesConfig.from_secrets({SECRET_ADMIN_ROLE_DOMAINS: "   "})
    assert config.admin_role_domains == ()
    assert log.warning.called


def test_values_are_upper_cased_and_deblanked():
    config = PatientResourcesConfig.from_secrets({SECRET_ADMIN_ROLE_DOMAINS: " adm , hyb ,, "})
    assert config.admin_role_domains == ("ADM", "HYB")


def test_unknown_tokens_are_dropped_with_a_warning():
    config = PatientResourcesConfig.from_secrets({SECRET_ADMIN_ROLE_DOMAINS: "ADM,BOGUS"})
    assert config.admin_role_domains == ("ADM",)
    assert log.warning.called


def test_all_tokens_unknown_denies_everyone_rather_than_reverting():
    """Reverting to the default here would silently undo a deliberate restriction."""
    config = PatientResourcesConfig.from_secrets({SECRET_ADMIN_ROLE_DOMAINS: "BOGUS,NONSENSE"})
    assert config.admin_role_domains == ()
    assert log.error.called


def test_staff_id_allowlist_preserves_case():
    """Keys are opaque; upper-casing them would stop them matching."""
    config = PatientResourcesConfig.from_secrets({SECRET_ADMIN_STAFF_IDS: "aBc123, dEf456"})
    assert config.admin_staff_ids == ("aBc123", "dEf456")


def test_config_is_frozen():
    config = PatientResourcesConfig.from_secrets({})
    try:
        config.admin_staff_ids = ("x",)
    except Exception as exc:  # dataclasses raises FrozenInstanceError
        assert "frozen" in type(exc).__name__.lower() or "frozen" in str(exc).lower()
    else:
        raise AssertionError("config should be immutable")


def test_from_secrets_never_raises_on_odd_values():
    for value in (123, [], {}, object(), True):
        assert PatientResourcesConfig.from_secrets({SECRET_ADMIN_ROLE_DOMAINS: value}) is not None
        assert PatientResourcesConfig.from_secrets({SECRET_ADMIN_STAFF_IDS: value}) is not None


def test_parse_helpers_handle_none():
    assert parse_csv(None) == ()
    assert parse_upper_csv(None) == ()
