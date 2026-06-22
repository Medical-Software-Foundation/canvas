from enum import Enum


class RecurrenceEnum(Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    EVERY_2_WEEKS = "every 2 weeks"
    EVERY_3_WEEKS = "every 3 weeks"
    MONTHLY = "monthly"


FIELD_FACILITY_KEY = "facility"
FIELD_RECURRENCE_KEY = "recurrence"

# Target horizon: always maintain 3 months (90 days) of scheduled events
TARGET_HORIZON_DAYS = 90

# Default timezone for preserving wall-clock time across DST changes
# Used as fallback if location-specific timezone is not configured
DEFAULT_TIMEZONE = "America/New_York"

# Initial batch count for recurring events when first created
# Creates approximately 2 months of events initially
INITIAL_BATCH_COUNT = {
    "daily": 60,            # 60 days = ~2 months
    "weekly": 8,            # 8 weeks = ~2 months
    "every 2 weeks": 4,    # 8 weeks = ~2 months
    "every 3 weeks": 3,    # 9 weeks = ~2 months
    "monthly": 2,           # 2 months
}
