from external_calendar_busy_blocks.auth import canonical_staff_id, is_admin


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


def test_is_admin_false_when_secret_unset() -> None:
    assert is_admin("00000000000000000000000000000001", {}) is False


def test_is_admin_false_when_secret_blank() -> None:
    assert is_admin("00000000000000000000000000000001", {"ADMIN_STAFF_IDS": "   "}) is False


def test_is_admin_false_when_staff_id_none() -> None:
    assert is_admin(None, {"ADMIN_STAFF_IDS": "00000000000000000000000000000001"}) is False


def test_is_admin_true_for_member_dashless() -> None:
    secrets = {"ADMIN_STAFF_IDS": "00000000000000000000000000000001,0000000000000000000000000000ffff"}
    assert is_admin("0000000000000000000000000000ffff", secrets) is True


def test_is_admin_matches_regardless_of_dashes_and_case() -> None:
    # Secret entered with dashes and uppercase; caller id is dashless lowercase.
    secrets = {"ADMIN_STAFF_IDS": "00000000-0000-0000-0000-0000000000AB"}
    assert is_admin("000000000000000000000000000000ab", secrets) is True


def test_is_admin_false_for_non_member() -> None:
    secrets = {"ADMIN_STAFF_IDS": "00000000000000000000000000000001"}
    assert is_admin("00000000000000000000000000000002", secrets) is False
