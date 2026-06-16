"""Lab data access and formatting for the Recent Labs app."""

from canvas_sdk.v1.data.lab import LabValue

# Up to this many most-recent results are shown per test.
RESULTS_PER_TEST = 3

# Inline sparkline dimensions (SVG user units).
SPARKLINE_WIDTH = 64
SPARKLINE_HEIGHT = 18
_SPARKLINE_PAD = 2

# Name used when a lab value has no usable coding name or code.
UNKNOWN_TEST_NAME = "Unknown test"

# abnormal_flag values that mean "not abnormal"
_NORMAL_FLAGS = {"", "N"}

# Tokens that should render as empty (placeholder/blank values seen in lab data).
_EMPTY_TOKENS = {"", "-", "--", "none", "n/a", "na"}


def is_abnormal(flag: str | None) -> bool:
    """Return True when a lab value's abnormal_flag indicates an abnormal result."""
    if not flag:
        return False
    return flag.strip().upper() not in _NORMAL_FLAGS


def abnormal_label(flag: str | None) -> str:
    """Human-readable abnormal label for a flag ('High'/'Low'/'Abnormal'), or '' if normal."""
    if not is_abnormal(flag):
        return ""
    normalized = flag.strip().upper()
    if normalized.startswith("H"):
        return "High"
    if normalized.startswith("L"):
        return "Low"
    return "Abnormal"


def clean_token(raw) -> str:  # type: ignore[no-untyped-def]
    """Normalize a display token, treating placeholders (None, '-', 'N/A', …) as empty."""
    text = ("" if raw is None else str(raw)).strip()
    return "" if text.lower() in _EMPTY_TOKENS else text


def format_lab_date(raw) -> str:  # type: ignore[no-untyped-def]
    """Format a date/datetime as e.g. 'Mar 02, 2023'; pass through anything without strftime."""
    try:
        return raw.strftime("%b %d, %Y")
    except AttributeError:
        return "" if raw is None else str(raw)


def _first_coding(value):  # type: ignore[no-untyped-def]
    """Return a lab value's first coding via the prefetch cache (no extra query)."""
    return next(iter(value.codings.all()), None)


def lab_test_name(value) -> str:  # type: ignore[no-untyped-def]
    """Display name for a lab value's test: coding name, else code, else UNKNOWN_TEST_NAME."""
    coding = _first_coding(value)
    if coding is None:
        return UNKNOWN_TEST_NAME
    return coding.name or coding.code or UNKNOWN_TEST_NAME


def serialize_lab_value(value) -> dict:  # type: ignore[no-untyped-def]
    """Convert a LabValue into a template-friendly dict (display values cleaned)."""
    return {
        "test_name": lab_test_name(value),
        "value": clean_token(value.value),
        "units": clean_token(value.units),
        "abnormal_flag": value.abnormal_flag,
        "is_abnormal": is_abnormal(value.abnormal_flag),
        "abnormal_label": abnormal_label(value.abnormal_flag),
        "reference_range": clean_token(value.reference_range),
        "date": format_lab_date(value.report.original_date),
    }


def numeric_value(raw) -> float | None:  # type: ignore[no-untyped-def]
    """Parse a lab value to a float, or None if it isn't a plain number (e.g. 'POSITIVE')."""
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def sparkline_points(
    results: list,  # type: ignore[no-untyped-def]
    width: int = SPARKLINE_WIDTH,
    height: int = SPARKLINE_HEIGHT,
) -> str | None:
    """Build an SVG polyline `points` string for a test's results, oldest to newest.

    `results` are newest-first (as stored on a group). Returns None when there are
    fewer than two numeric results, so non-numeric tests (e.g. POSITIVE/NEGATIVE)
    get no line.
    """
    nums = [numeric_value(r["value"]) for r in reversed(results)]
    nums = [n for n in nums if n is not None]
    if len(nums) < 2:
        return None

    low, high = min(nums), max(nums)
    span = high - low
    inner = height - 2 * _SPARKLINE_PAD
    last = len(nums) - 1

    coords = []
    for i, value in enumerate(nums):
        x = round(i * width / last, 1)
        if span == 0:
            y = round(height / 2, 1)
        else:
            y = round(_SPARKLINE_PAD + inner * (1 - (value - low) / span), 1)
        coords.append(f"{x},{y}")
    return " ".join(coords)


def _group_key(value) -> str:  # type: ignore[no-untyped-def]
    """Stable grouping key for a lab value: its LOINC code if present, else its test name."""
    coding = _first_coding(value)
    code = coding.code if coding is not None else ""
    return f"code:{code}" if code else f"name:{lab_test_name(value)}"


def get_recent_results_by_test(patient_id: str) -> list:  # type: ignore[no-untyped-def]
    """Group the patient's lab results by test, keeping up to RESULTS_PER_TEST per test.

    Returns a list of ``{"test_name": str, "results": [serialized value, ...]}`` dicts.
    Test groups are ordered by most-recent-result date (the test resulted most recently
    appears first); within each group, results are newest first.

    Note: "top-N per group" is not expressible cheaply in the ORM, so this scans the
    patient's lab values (newest first) and buckets them in Python. The report and codings
    are eagerly loaded (select_related / prefetch_related) so the scan stays ~3 queries
    regardless of how many lab values the patient has.
    """
    values = (
        LabValue.objects.filter(report__patient__id=patient_id, report__junked=False)
        .select_related("report")
        .prefetch_related("codings")
        .order_by("-report__original_date", "-dbid")
    )

    groups: dict = {}
    order: list = []
    for value in values:
        name = lab_test_name(value)
        if name == UNKNOWN_TEST_NAME:
            continue  # omit results we can't identify (no coding name or code)
        key = _group_key(value)
        group = groups.get(key)
        if group is None:
            group = {"test_name": name, "results": []}
            groups[key] = group
            order.append(key)
        if len(group["results"]) < RESULTS_PER_TEST:
            group["results"].append(serialize_lab_value(value))

    result = [groups[key] for key in order]
    for group in result:
        group["sparkline"] = sparkline_points(group["results"])
    return result
