"""Plugin-wide constants and Dexcom environment URL routing."""

EGV_RETENTION_DAYS: int = 90
DEFAULT_RANGE_DAYS: int = 14
RANGE_OPTIONS: tuple[int, ...] = (7, 14, 30, 90)
MAGIC_LINK_TTL_SECONDS: int = 15 * 60

# Upper bound on egv points serialized into the /data chart payload. A
# 90-day window holds ~26k 5-minute readings; the trend chart can't resolve
# that many, so longer ranges are stride-downsampled to keep the response
# small. Summary aggregates are still computed from the full reading set.
MAX_CHART_POINTS: int = 600

TIR_LOW_MGDL: int = 70
TIR_HIGH_MGDL: int = 180
HYPER_EVENT_THRESHOLD_MGDL: int = 250
EXCURSION_GAP_MINUTES: int = 15

MMOL_TO_MGDL: float = 18.018

DEXCOM_OAUTH_SCOPE: str = "offline_access"

REQUIRED_SECRETS: tuple[str, ...] = (
    "DEXCOM_CLIENT_ID",
    "DEXCOM_CLIENT_SECRET",
    "DEXCOM_REDIRECT_URI",
    "DEXCOM_ENVIRONMENT",
    "DEXCOM_MAGIC_LINK_SECRET",
)


def dexcom_base_url(environment: str) -> str:
    """Return the Dexcom API base URL for the given environment string."""
    env = (environment or "").strip().lower()
    if env == "production":
        return "https://api.dexcom.com"
    return "https://sandbox-api.dexcom.com"


def parse_range_days(raw: str | None) -> int:
    """Coerce a range query parameter into an allowed day count."""
    if not raw:
        return DEFAULT_RANGE_DAYS
    cleaned = raw.strip().lower().rstrip("d")
    try:
        days = int(cleaned)
    except (TypeError, ValueError):
        return DEFAULT_RANGE_DAYS
    if days not in RANGE_OPTIONS:
        return DEFAULT_RANGE_DAYS
    return days
