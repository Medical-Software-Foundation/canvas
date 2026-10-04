"""The template-to-JavaScript config handshake."""

import json

from patient_resources.services.html import safe_json


def test_output_is_still_parseable_json():
    assert json.loads(safe_json({"apiBase": "/plugin-io/api/patient_resources"})) == {
        "apiBase": "/plugin-io/api/patient_resources"
    }


def test_script_closing_tag_cannot_terminate_the_element():
    """The reason this helper exists.

    json.dumps leaves `<` alone, so a stored value containing `</script>` would
    close the tag early and everything after it would be parsed as markup.
    """
    rendered = safe_json({"title": "</script><img src=x onerror=alert(1)>"})
    assert "</script>" not in rendered
    assert "<" not in rendered
    assert ">" not in rendered


def test_ampersand_is_escaped():
    assert "&" not in safe_json({"url": "https://example.org/?a=1&b=2"})


def test_escaped_output_round_trips_to_the_original_value():
    original = {"title": "<b>a & b</b>"}
    assert json.loads(safe_json(original)) == original
