from vitalstream.util import session_key


def test_session_key_prefixes_with_session_id_literal() -> None:
    assert session_key("abc-123") == "session_id:abc-123"


def test_session_key_with_empty_string() -> None:
    assert session_key("") == "session_id:"
