"""Configuration parsing, and what happens when it is missing or wrong."""

from scheduling_waitlist.constants import DEFAULT_PRIORITY_LABELS
from scheduling_waitlist.services.config import WaitlistConfig


class TestSchedulingTeam:
    def test_unset_leaves_the_team_empty_so_callers_can_refuse(self):
        config = WaitlistConfig.from_secrets({})

        assert config.scheduling_team == ""

    def test_surrounding_whitespace_is_stripped(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_SCHEDULING_TEAM": "  Front Desk  "})

        assert config.scheduling_team == "Front Desk"

    def test_whitespace_only_reads_as_unset(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_SCHEDULING_TEAM": "   "})

        assert config.scheduling_team == ""


class TestAppointmentTypes:
    def test_unset_yields_no_codes(self):
        assert WaitlistConfig.from_secrets({}).appointment_type_codes == ()

    def test_codes_are_split_and_stripped(self):
        config = WaitlistConfig.from_secrets(
            {"WAITLIST_APPOINTMENT_TYPES": "estab, newpt ,  followup"}
        )

        assert config.appointment_type_codes == ("estab", "newpt", "followup")

    def test_empty_segments_are_dropped(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "estab,,  ,newpt"})

        assert config.appointment_type_codes == ("estab", "newpt")


class TestPriorityLabels:
    def test_unset_falls_back_to_the_documented_three_tiers(self):
        assert WaitlistConfig.from_secrets({}).priority_labels == DEFAULT_PRIORITY_LABELS

    def test_blank_value_falls_back_to_the_default(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_PRIORITY_LABELS": "  ,  "})

        assert config.priority_labels == DEFAULT_PRIORITY_LABELS

    def test_configured_labels_are_kept_in_declared_order(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_PRIORITY_LABELS": "Now,Soon,Whenever"})

        assert config.priority_labels == ("Now", "Soon", "Whenever")

    def test_rank_follows_declared_order_with_zero_most_urgent(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_PRIORITY_LABELS": "Now,Soon,Whenever"})

        assert config.priority_rank("Now") == 0
        assert config.priority_rank("Whenever") == 2

    def test_rank_ignores_case_and_padding(self):
        config = WaitlistConfig.from_secrets({})

        assert config.priority_rank("  hIgH ") == 0

    def test_unknown_label_sorts_after_every_configured_one(self):
        # A label orphaned by a configuration change must not outrank a
        # genuinely urgent patient.
        config = WaitlistConfig.from_secrets({})

        assert config.priority_rank("Zebra") == len(DEFAULT_PRIORITY_LABELS)

    def test_unknown_label_is_reported_as_unknown(self):
        config = WaitlistConfig.from_secrets({})

        assert config.is_known_priority("High") is True
        assert config.is_known_priority("Zebra") is False

    def test_default_label_is_the_least_urgent(self):
        assert WaitlistConfig.from_secrets({}).default_priority_label == "Low"


class TestTtlDays:
    def test_unset_is_none_so_nothing_expires(self):
        assert WaitlistConfig.from_secrets({}).ttl_days is None

    def test_valid_value_is_parsed(self):
        assert WaitlistConfig.from_secrets({"WAITLIST_TTL_DAYS": "45"}).ttl_days == 45

    def test_non_numeric_value_expires_nothing(self):
        assert WaitlistConfig.from_secrets({"WAITLIST_TTL_DAYS": "soon"}).ttl_days is None

    def test_zero_expires_nothing(self):
        assert WaitlistConfig.from_secrets({"WAITLIST_TTL_DAYS": "0"}).ttl_days is None

    def test_negative_expires_nothing(self):
        assert WaitlistConfig.from_secrets({"WAITLIST_TTL_DAYS": "-5"}).ttl_days is None


class TestManagerRoles:
    def test_unset_grants_nobody_blanket_management(self):
        assert WaitlistConfig.from_secrets({}).manager_role_codes == ()

    def test_codes_are_upper_cased_for_comparison(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_MANAGER_ROLE_CODES": "admin, front_desk"})

        assert config.manager_role_codes == ("ADMIN", "FRONT_DESK")


class TestTimeWindowEnforcement:
    def test_defaults_to_off_so_a_preference_never_silently_excludes(self):
        assert WaitlistConfig.from_secrets({}).enforce_time_windows is False

    def test_true_turns_it_on(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_ENFORCE_TIME_WINDOWS": "true"})

        assert config.enforce_time_windows is True

    def test_accepts_common_truthy_spellings(self):
        for raw in ("TRUE", "Yes", "1", "on"):
            config = WaitlistConfig.from_secrets({"WAITLIST_ENFORCE_TIME_WINDOWS": raw})
            assert config.enforce_time_windows is True, raw

    def test_anything_unclear_reads_as_off(self):
        for raw in ("maybe", "0", "no", ""):
            config = WaitlistConfig.from_secrets({"WAITLIST_ENFORCE_TIME_WINDOWS": raw})
            assert config.enforce_time_windows is False, raw


class TestNumericDefaults:
    def test_max_matches_defaults_to_ten(self):
        assert WaitlistConfig.from_secrets({}).max_matches_per_task == 10

    def test_max_matches_of_zero_falls_back_rather_than_naming_nobody(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_MAX_MATCHES_PER_TASK": "0"})

        assert config.max_matches_per_task == 10

    def test_max_matches_honours_a_valid_override(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_MAX_MATCHES_PER_TASK": "3"})

        assert config.max_matches_per_task == 3

    def test_lead_times_default_when_unset(self):
        config = WaitlistConfig.from_secrets({})

        assert config.min_lead_time_hours == 2
        assert config.urgent_lead_hours == 48

    def test_zero_minimum_lead_time_is_allowed(self):
        # Zero is meaningful here: announce a slot however close it is.
        config = WaitlistConfig.from_secrets({"WAITLIST_MIN_LEAD_TIME_HOURS": "0"})

        assert config.min_lead_time_hours == 0

    def test_malformed_lead_time_falls_back_to_the_default(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_MIN_LEAD_TIME_HOURS": "two"})

        assert config.min_lead_time_hours == 2


class TestDisplayTimezone:
    def test_defaults_to_utc(self):
        assert WaitlistConfig.from_secrets({}).display_timezone == "UTC"

    def test_configured_zone_is_used(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_DISPLAY_TIMEZONE": "America/Denver"})

        assert config.display_timezone == "America/Denver"

    def test_blank_falls_back_to_utc(self):
        config = WaitlistConfig.from_secrets({"WAITLIST_DISPLAY_TIMEZONE": "   "})

        assert config.display_timezone == "UTC"


class TestNoSecretsAtAll:
    def test_none_is_tolerated(self):
        config = WaitlistConfig.from_secrets(None)

        assert config.scheduling_team == ""
        assert config.priority_labels == DEFAULT_PRIORITY_LABELS
