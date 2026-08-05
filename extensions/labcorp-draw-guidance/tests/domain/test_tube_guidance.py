from labcorp_draw_guidance.domain.tube_guidance import (
    ConsolidatedTube,
    ResolvedTest,
    TubeRequirement,
    consolidate,
    resolve_tube_requirement,
)


def test_resolve_tube_requirement_matches_by_name_keyword() -> None:
    """Test that a test name containing a known keyword resolves to guidance."""
    tested = resolve_tube_requirement(order_code=None, order_name="CBC W/DIFF")

    expected = TubeRequirement("Lavender (EDTA)", 1, 3.0)
    assert tested == expected


def test_resolve_tube_requirement_is_case_insensitive() -> None:
    """Test that name keyword matching ignores case."""
    tested = resolve_tube_requirement(order_code=None, order_name="lipid panel")

    expected = TubeRequirement("Gold (SST)", 1, 3.5)
    assert tested == expected


def test_resolve_tube_requirement_matches_more_specific_keyword_first() -> None:
    """Test that HEMOGLOBIN A1C resolves before a generic hemoglobin match would apply."""
    tested = resolve_tube_requirement(order_code=None, order_name="HEMOGLOBIN A1C")

    expected = TubeRequirement("Lavender (EDTA)", 1, 3.0)
    assert tested == expected


def test_resolve_tube_requirement_returns_none_for_unknown_test() -> None:
    """Test that an unrecognized test name returns no guidance."""
    tested = resolve_tube_requirement(order_code=None, order_name="SOME OBSCURE ESOTERIC PANEL")

    assert tested is None


def test_resolve_tube_requirement_returns_none_when_name_missing() -> None:
    """Test that a missing order name with no override returns no guidance."""
    tested = resolve_tube_requirement(order_code=None, order_name=None)

    assert tested is None


def test_resolve_tube_requirement_prefers_order_code_override() -> None:
    """Test that an order-code override table entry takes priority over name matching."""
    from labcorp_draw_guidance.domain import tube_guidance

    override = TubeRequirement("Green (Lithium Heparin)", 2, 5.0)
    tube_guidance.ORDER_CODE_OVERRIDES["001453"] = override

    try:
        tested = resolve_tube_requirement(order_code="001453", order_name="CBC W/DIFF")
    finally:
        del tube_guidance.ORDER_CODE_OVERRIDES["001453"]

    assert tested == override


def test_consolidate_groups_shared_tube_type_and_takes_max_requirement() -> None:
    """Test that tests sharing a tube type consolidate into one entry sized to the max requirement."""
    resolved_tests = [
        ResolvedTest("001", "Comprehensive Metabolic Panel", TubeRequirement("Gold (SST)", 1, 3.5)),
        ResolvedTest("002", "Lipid Panel", TubeRequirement("Gold (SST)", 1, 3.5)),
        ResolvedTest("003", "TSH", TubeRequirement("Gold (SST)", 2, 5.0)),
        ResolvedTest("004", "CBC W/Diff", TubeRequirement("Lavender (EDTA)", 1, 3.0)),
    ]

    tested = consolidate(resolved_tests)

    expected = [
        ConsolidatedTube(
            tube_type="Gold (SST)",
            tube_count=2,
            draw_volume_ml=5.0,
            tests=("Comprehensive Metabolic Panel", "Lipid Panel", "TSH"),
        ),
        ConsolidatedTube(
            tube_type="Lavender (EDTA)",
            tube_count=1,
            draw_volume_ml=3.0,
            tests=("CBC W/Diff",),
        ),
    ]
    assert tested == expected


def test_consolidate_returns_empty_list_for_no_tests() -> None:
    """Test that consolidating an empty list of resolved tests returns an empty list."""
    tested = consolidate([])

    assert tested == []
