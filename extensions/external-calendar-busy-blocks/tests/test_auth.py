from external_calendar_busy_blocks.auth import canonical_staff_id


def test_canonicalizes_dashed_uuid_to_hex() -> None:
    headers = {"canvas-logged-in-user-id": "00000000-0000-0000-0000-000000000001"}
    assert canonical_staff_id(headers) == "00000000000000000000000000000001"


def test_passes_through_dashless_uuid() -> None:
    headers = {"canvas-logged-in-user-id": "00000000000000000000000000000001"}
    assert canonical_staff_id(headers) == "00000000000000000000000000000001"


def test_returns_none_when_header_absent() -> None:
    assert canonical_staff_id({}) is None


def test_returns_none_when_header_empty() -> None:
    assert canonical_staff_id({"canvas-logged-in-user-id": ""}) is None
