"""Tests for the generic patient-metadata fields handler.

Reads the METADATA_FIELDS JSON secret and emits a
PatientMetadataCreateFormEffect with one FormField per entry.

Per project rule: no canvas_sdk mocking. We construct real handlers, set
real `secrets` dicts on them, and inspect the real effect payloads.
"""

__is_plugin__ = True

import json


from handlers.metadata_fields import PatientMetadataFields


def _make_handler(secrets: dict[str, str] | None = None) -> PatientMetadataFields:
    handler = PatientMetadataFields.__new__(PatientMetadataFields)
    handler.secrets = dict(secrets or {})
    return handler


def _decode_form_fields(effect: object) -> list[dict[str, object]]:
    payload = getattr(effect, "payload", None)
    data: object = json.loads(payload) if isinstance(payload, str) else payload
    # PatientMetadataCreateFormEffect serializes form_fields somewhere in payload;
    # walk it to find the list of field dicts.
    if isinstance(data, dict):
        if "form_fields" in data:
            result: list[dict[str, object]] = list(data["form_fields"])
            return result
        inner_raw = data.get("data")
        inner = inner_raw if isinstance(inner_raw, dict) else None
        if inner:
            for k in ("form_fields", "form"):
                if k in inner:
                    found: list[dict[str, object]] = list(inner[k])
                    return found
    raise AssertionError(f"Could not locate form_fields in payload: {data!r}")


class TestPatientMetadataFields:
    def test_responds_to_correct_event(self) -> None:
        from canvas_sdk.events import EventType

        assert PatientMetadataFields.RESPONDS_TO == EventType.Name(
            EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS
        )

    def test_no_secret_emits_no_effect(self) -> None:
        effects = _make_handler({}).compute()
        assert effects == []

    def test_empty_list_emits_no_effect(self) -> None:
        effects = _make_handler({"METADATA_FIELDS": "[]"}).compute()
        assert effects == []

    def test_invalid_json_emits_no_effect(self) -> None:
        effects = _make_handler({"METADATA_FIELDS": "not-json"}).compute()
        assert effects == []

    def test_single_text_field(self) -> None:
        config = json.dumps(
            [
                {
                    "key": "risk_score",
                    "label": "Risk Score",
                    "type": "TEXT",
                    "required": False,
                    "editable": True,
                }
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        assert len(effects) == 1
        fields = _decode_form_fields(effects[0])
        assert len(fields) == 1
        assert fields[0]["key"] == "risk_score"
        assert fields[0]["label"] == "Risk Score"
        assert str(fields[0]["type"]).upper().endswith("TEXT")
        assert fields[0]["editable"] is True
        assert fields[0]["required"] is False

    def test_select_field_forwards_options(self) -> None:
        config = json.dumps(
            [
                {
                    "key": "risk_score",
                    "label": "Risk Score",
                    "type": "SELECT",
                    "required": False,
                    "editable": True,
                    "options": ["Low", "Medium", "High"],
                }
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        fields = _decode_form_fields(effects[0])
        assert fields[0]["options"] == ["Low", "Medium", "High"]
        assert str(fields[0]["type"]).upper().endswith("SELECT")

    def test_read_only_field_passes_editable_false(self) -> None:
        config = json.dumps(
            [
                {
                    "key": "services",
                    "label": "Services",
                    "type": "TEXT",
                    "required": False,
                    "editable": False,
                }
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        fields = _decode_form_fields(effects[0])
        assert fields[0]["editable"] is False

    def test_date_input_type(self) -> None:
        config = json.dumps(
            [
                {
                    "key": "last_review",
                    "label": "Last Review",
                    "type": "DATE",
                    "required": False,
                    "editable": True,
                }
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        fields = _decode_form_fields(effects[0])
        assert str(fields[0]["type"]).upper().endswith("DATE")

    def test_multiple_fields_preserve_order(self) -> None:
        config = json.dumps(
            [
                {"key": "a", "label": "A", "type": "TEXT"},
                {"key": "b", "label": "B", "type": "TEXT"},
                {"key": "c", "label": "C", "type": "TEXT"},
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        fields = _decode_form_fields(effects[0])
        assert [f["key"] for f in fields] == ["a", "b", "c"]

    def test_missing_key_skips_entry(self) -> None:
        config = json.dumps(
            [
                {"key": "ok", "label": "OK", "type": "TEXT"},
                {"label": "No key", "type": "TEXT"},
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        fields = _decode_form_fields(effects[0])
        assert [f["key"] for f in fields] == ["ok"]

    def test_unknown_input_type_skips_entry(self) -> None:
        config = json.dumps(
            [
                {"key": "ok", "label": "OK", "type": "TEXT"},
                {"key": "bad", "label": "Bad", "type": "BOGUS"},
            ]
        )
        effects = _make_handler({"METADATA_FIELDS": config}).compute()
        fields = _decode_form_fields(effects[0])
        assert [f["key"] for f in fields] == ["ok"]
