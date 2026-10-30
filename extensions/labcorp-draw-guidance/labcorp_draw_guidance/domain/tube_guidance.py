"""Static Labcorp tube/specimen draw guidance (the "AccuDraw" equivalent).

Canvas's own data models only store collection date/time for a lab order
specimen -- there are no tube, count, or volume fields -- and the Health
Gorilla compendium sync discards the specimen data HG returns. For v1, this
module ships a bundled, maintained table mapping ordered tests to the tube
type/count/volume a phlebotomist needs to pull, so collection staff don't
have to leave Canvas to check Health Gorilla's portal or the paper
requisition.

**Data provenance and an open question left from the plugin spec:** at the
time this was built there was no confirmed source for exact Labcorp order
codes in this instance's `LabPartnerTest` catalog, so codes are NOT used as
the primary lookup key -- fabricating Labcorp-specific order codes would be
worse than not shipping a mapping at all. Instead, matching is done against
`LabPartnerTest.order_name` using case-insensitive keyword matching. The tube
colors/counts/volumes below reflect standard, widely-published phlebotomy
draw conventions (used across most lab vendors, including Labcorp) -- they
are a reasonable v1 seed, but they are NOT pulled from Labcorp's official
compendium and should be reviewed/expanded by clinical ops before relying on
them for high-stakes draws. An optional order-code override table
(`ORDER_CODE_OVERRIDES`) is provided below for practices that want to pin
exact Labcorp order codes once confirmed -- entries there take priority over
name-keyword matches.

Planned v2 (out of scope here): replace this static table with a live call
to Health Gorilla's `CodeSystem/$lookup`, using HG credentials stored as a
plugin secret.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TubeRequirement:
    """The tube guidance for drawing a single test."""

    tube_type: str
    tube_count: int
    draw_volume_ml: float


@dataclass(frozen=True)
class ResolvedTest:
    """A single ordered test matched to its tube guidance."""

    order_code: str
    display_name: str
    tube: TubeRequirement


@dataclass(frozen=True)
class ConsolidatedTube:
    """A single tube requirement consolidated across one or more ordered tests."""

    tube_type: str
    tube_count: int
    draw_volume_ml: float
    tests: tuple[str, ...]


# Keyword -> tube guidance. Matched case-insensitively as a substring against
# `LabPartnerTest.order_name`. Order matters: first match wins, so put more
# specific keywords first (e.g. "HEMOGLOBIN A1C" before a bare "HEMOGLOBIN").
NAME_KEYWORD_GUIDANCE: tuple[tuple[str, TubeRequirement], ...] = (
    ("HEMOGLOBIN A1C", TubeRequirement("Lavender (EDTA)", 1, 3.0)),
    ("CBC", TubeRequirement("Lavender (EDTA)", 1, 3.0)),
    ("COMPLETE BLOOD COUNT", TubeRequirement("Lavender (EDTA)", 1, 3.0)),
    ("ESR", TubeRequirement("Lavender (EDTA)", 1, 2.0)),
    ("SEDIMENTATION RATE", TubeRequirement("Lavender (EDTA)", 1, 2.0)),
    ("PROTHROMBIN", TubeRequirement("Light Blue (Sodium Citrate)", 1, 2.7)),
    ("PT/INR", TubeRequirement("Light Blue (Sodium Citrate)", 1, 2.7)),
    ("PARTIAL THROMBOPLASTIN", TubeRequirement("Light Blue (Sodium Citrate)", 1, 2.7)),
    ("FASTING GLUCOSE", TubeRequirement("Grey (Sodium Fluoride)", 1, 2.0)),
    ("GLUCOSE", TubeRequirement("Grey (Sodium Fluoride)", 1, 2.0)),
    ("COMPREHENSIVE METABOLIC", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("BASIC METABOLIC", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("LIPID PANEL", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("THYROID", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("TSH", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("VITAMIN D", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("FERRITIN", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("IRON", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("PSA", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("HEPATIC FUNCTION", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("LIVER PANEL", TubeRequirement("Gold (SST)", 1, 3.5)),
    ("URINALYSIS", TubeRequirement("Urine cup (not a blood draw)", 1, 0.0)),
)

# Optional, empty by default: practices can pin exact Labcorp order codes
# here once confirmed against this instance's LabPartnerTest catalog. Keys
# are matched case-insensitively against LabPartnerTest.order_code and take
# priority over NAME_KEYWORD_GUIDANCE.
ORDER_CODE_OVERRIDES: dict[str, TubeRequirement] = {}


def resolve_tube_requirement(order_code: str | None, order_name: str | None) -> TubeRequirement | None:
    """Resolve tube guidance for a single test.

    Checks the order-code override table first (exact match, case-insensitive),
    then falls back to keyword matching against the test's display name.
    Returns None if no guidance is known for this test.
    """
    if order_code:
        override = ORDER_CODE_OVERRIDES.get(order_code.strip().upper())
        if override is not None:
            return override

    if not order_name:
        return None

    haystack = order_name.upper()
    for keyword, requirement in NAME_KEYWORD_GUIDANCE:
        if keyword in haystack:
            return requirement

    return None


def consolidate(resolved_tests: list[ResolvedTest]) -> list[ConsolidatedTube]:
    """Consolidate resolved tests into one tube requirement per tube type.

    Where multiple ordered tests share a tube type, a single draw of that
    tube (sized to the largest volume any one of those tests needs, in the
    largest tube count any one of those tests needs) covers all of them --
    this is the core AccuDraw-equivalent logic. Order of first appearance is
    preserved so the UI lists tubes in the same order tests were added.
    """
    by_tube_type: dict[str, list[ResolvedTest]] = {}
    for resolved in resolved_tests:
        by_tube_type.setdefault(resolved.tube.tube_type, []).append(resolved)

    consolidated = []
    for tube_type, tests in by_tube_type.items():
        consolidated.append(
            ConsolidatedTube(
                tube_type=tube_type,
                tube_count=max(t.tube.tube_count for t in tests),
                draw_volume_ml=max(t.tube.draw_volume_ml for t in tests),
                tests=tuple(t.display_name for t in tests),
            )
        )

    return consolidated
