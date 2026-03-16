"""Tests for the CSV parser and validation logic."""

from __future__ import annotations

import pytest

from patient_csv_loader.apps.csv_parser import (
    ParseResult,
    generate_template_csv,
    parse_csv,
    validate_row,
)


def _make_valid_row(**overrides: str) -> dict[str, str]:
    """Return a minimal valid row dict, with optional overrides."""
    row = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birthdate": "1985-03-15",
        "sex_at_birth": "F",
        "phone": "5551234567",
    }
    row.update(overrides)
    return row


def _make_csv(headers: list[str], rows: list[list[str]]) -> str:
    """Build CSV content from headers and rows."""
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(row))
    return "\n".join(lines)


# ─── Required fields ───


class TestRequiredFields:
    def test_valid_minimal_row(self) -> None:
        errors = validate_row(_make_valid_row())
        assert errors == []

    @pytest.mark.parametrize("field", ["first_name", "last_name", "birthdate", "sex_at_birth", "phone"])
    def test_missing_required_field(self, field: str) -> None:
        row = _make_valid_row(**{field: ""})
        errors = validate_row(row)
        assert any(field in e for e in errors)

    def test_all_required_missing(self) -> None:
        row = {k: "" for k in ("first_name", "last_name", "birthdate", "sex_at_birth", "phone")}
        errors = validate_row(row)
        assert len(errors) >= 5


# ─── Birthdate validation ───


class TestBirthdateValidation:
    def test_valid_birthdate(self) -> None:
        errors = validate_row(_make_valid_row(birthdate="2000-01-01"))
        assert errors == []

    def test_invalid_format(self) -> None:
        errors = validate_row(_make_valid_row(birthdate="03/15/1985"))
        assert any("YYYY-MM-DD" in e for e in errors)

    def test_invalid_date(self) -> None:
        errors = validate_row(_make_valid_row(birthdate="2000-13-01"))
        assert any("YYYY-MM-DD" in e for e in errors)

    def test_future_date(self) -> None:
        errors = validate_row(_make_valid_row(birthdate="2099-01-01"))
        assert any("future" in e for e in errors)


# ─── Sex at birth validation ───


class TestSexAtBirthValidation:
    @pytest.mark.parametrize("val", ["F", "M", "O", "UNK", "f", "m", "unk"])
    def test_valid_values(self, val: str) -> None:
        errors = validate_row(_make_valid_row(sex_at_birth=val))
        assert errors == []

    def test_invalid_value(self) -> None:
        errors = validate_row(_make_valid_row(sex_at_birth="X"))
        assert any("sex_at_birth" in e for e in errors)


# ─── Address validation ───


class TestAddressValidation:
    def test_no_address_fields_is_valid(self) -> None:
        errors = validate_row(_make_valid_row())
        assert errors == []

    def test_complete_address_is_valid(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701",
            address_country="US",
        )
        errors = validate_row(row)
        assert errors == []

    def test_partial_address_missing_required(self) -> None:
        row = _make_valid_row(address_line1="123 Main St")
        errors = validate_row(row)
        assert any("address_city" in e for e in errors)

    def test_invalid_address_use(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701",
            address_country="US",
            address_use="invalid",
        )
        errors = validate_row(row)
        assert any("address_use" in e for e in errors)

    def test_valid_address_use_values(self) -> None:
        for use in ("home", "work", "temp", "old"):
            row = _make_valid_row(
                address_line1="123 Main St",
                address_city="Springfield",
                address_state_code="IL",
                address_postal_code="62701",
                address_country="US",
                address_use=use,
            )
            assert validate_row(row) == []

    def test_invalid_state_code_too_long(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="Illinois",
            address_postal_code="62701",
            address_country="US",
        )
        errors = validate_row(row)
        assert any("2-letter state" in e for e in errors)

    def test_invalid_state_code_has_digits(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="I1",
            address_postal_code="62701",
            address_country="US",
        )
        errors = validate_row(row)
        assert any("2-letter state" in e for e in errors)

    def test_invalid_postal_code_too_long(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701-1234",
            address_country="US",
        )
        errors = validate_row(row)
        assert any("5 digits" in e for e in errors)

    def test_invalid_postal_code_not_digits(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="ABCDE",
            address_country="US",
        )
        errors = validate_row(row)
        assert any("5 digits" in e for e in errors)

    def test_invalid_country_code(self) -> None:
        row = _make_valid_row(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701",
            address_country="USA",
        )
        errors = validate_row(row)
        assert any("2-letter country" in e for e in errors)


# ─── Phone validation ───


class TestPhoneValidation:
    def test_valid_10_digit_phone(self) -> None:
        errors = validate_row(_make_valid_row(phone="5551234567"))
        assert errors == []

    def test_valid_formatted_phone(self) -> None:
        errors = validate_row(_make_valid_row(phone="(555) 123-4567"))
        assert errors == []

    def test_valid_dashed_phone(self) -> None:
        errors = validate_row(_make_valid_row(phone="555-123-4567"))
        assert errors == []

    def test_invalid_7_digit_phone(self) -> None:
        errors = validate_row(_make_valid_row(phone="5551234"))
        assert any("10 digits" in e for e in errors)

    def test_invalid_11_digit_phone(self) -> None:
        errors = validate_row(_make_valid_row(phone="15551234567"))
        assert any("10 digits" in e for e in errors)

    def test_contact_phone_validation(self) -> None:
        row = _make_valid_row(
            contact_1_system="phone",
            contact_1_value="555-123",
        )
        errors = validate_row(row)
        assert any("10 digits" in e for e in errors)

    def test_contact_email_no_phone_validation(self) -> None:
        row = _make_valid_row(
            contact_1_system="email",
            contact_1_value="user@example.com",
        )
        errors = validate_row(row)
        assert errors == []


# ─── Contact point validation ───


class TestContactPointValidation:
    def test_no_contact_fields_is_valid(self) -> None:
        errors = validate_row(_make_valid_row())
        assert errors == []

    def test_valid_contact_point(self) -> None:
        row = _make_valid_row(contact_1_system="email", contact_1_value="test@example.com")
        errors = validate_row(row)
        assert errors == []

    def test_system_without_value(self) -> None:
        row = _make_valid_row(contact_1_system="email")
        errors = validate_row(row)
        assert any("contact_1_value" in e for e in errors)

    def test_value_without_system(self) -> None:
        row = _make_valid_row(contact_1_value="test@example.com")
        errors = validate_row(row)
        assert any("contact_1_system" in e for e in errors)

    def test_invalid_contact_system(self) -> None:
        row = _make_valid_row(contact_1_system="telegram", contact_1_value="@user")
        errors = validate_row(row)
        assert any("contact_1_system" in e for e in errors)

    def test_invalid_contact_use(self) -> None:
        row = _make_valid_row(
            contact_1_system="phone", contact_1_value="5550001234", contact_1_use="invalid"
        )
        errors = validate_row(row)
        assert any("contact_1_use" in e for e in errors)

    def test_invalid_rank_not_integer(self) -> None:
        row = _make_valid_row(
            contact_1_system="phone", contact_1_value="5550001234", contact_1_rank="abc"
        )
        errors = validate_row(row)
        assert any("contact_1_rank" in e for e in errors)

    def test_invalid_rank_negative(self) -> None:
        row = _make_valid_row(
            contact_1_system="phone", contact_1_value="5550001234", contact_1_rank="-1"
        )
        errors = validate_row(row)
        assert any("contact_1_rank" in e for e in errors)

    def test_invalid_has_consent(self) -> None:
        row = _make_valid_row(
            contact_1_system="phone", contact_1_value="5550001234", contact_1_has_consent="yes"
        )
        errors = validate_row(row)
        assert any("contact_1_has_consent" in e for e in errors)

    def test_valid_has_consent_values(self) -> None:
        for val in ("true", "false"):
            row = _make_valid_row(
                contact_1_system="phone", contact_1_value="5550001234", contact_1_has_consent=val
            )
            assert validate_row(row) == []

    def test_slot_2_validation(self) -> None:
        row = _make_valid_row(contact_2_system="fax")
        errors = validate_row(row)
        assert any("contact_2_value" in e for e in errors)


# ─── External identifier validation ───


class TestExternalIdentifierValidation:
    def test_no_external_ids_is_valid(self) -> None:
        errors = validate_row(_make_valid_row())
        assert errors == []

    def test_valid_external_id(self) -> None:
        row = _make_valid_row(
            external_id_1_system="http://old-ehr.com", external_id_1_value="PAT-001"
        )
        errors = validate_row(row)
        assert errors == []

    def test_system_without_value(self) -> None:
        row = _make_valid_row(external_id_1_system="http://old-ehr.com")
        errors = validate_row(row)
        assert any("external_id_1_value" in e for e in errors)

    def test_value_without_system(self) -> None:
        row = _make_valid_row(external_id_1_value="PAT-001")
        errors = validate_row(row)
        assert any("external_id_1_system" in e for e in errors)

    def test_slot_3_validation(self) -> None:
        row = _make_valid_row(external_id_3_system="http://example.com")
        errors = validate_row(row)
        assert any("external_id_3_value" in e for e in errors)


# ─── CSV parsing ───


class TestParseCSV:
    def test_valid_csv(self) -> None:
        csv = _make_csv(
            ["first_name", "last_name", "birthdate", "sex_at_birth", "phone"],
            [["Jane", "Doe", "1985-03-15", "F", "5551234567"]],
        )
        result = parse_csv(csv)
        assert result.total_rows == 1
        assert len(result.valid_rows) == 1
        assert len(result.error_rows) == 0

    def test_multiple_rows_mixed(self) -> None:
        csv = _make_csv(
            ["first_name", "last_name", "birthdate", "sex_at_birth", "phone"],
            [
                ["Jane", "Doe", "1985-03-15", "F", "5551234567"],
                ["", "Smith", "1990-01-01", "M", "5559876543"],  # missing first_name
            ],
        )
        result = parse_csv(csv)
        assert result.total_rows == 2
        assert len(result.valid_rows) == 1
        assert len(result.error_rows) == 1
        assert result.error_rows[0].row_number == 3

    def test_bom_handling(self) -> None:
        csv = "\ufeff" + _make_csv(
            ["first_name", "last_name", "birthdate", "sex_at_birth", "phone"],
            [["Jane", "Doe", "1985-03-15", "F", "5551234567"]],
        )
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1

    def test_header_normalization(self) -> None:
        csv = _make_csv(
            ["First_Name", " Last_Name ", "Birthdate", "Sex_At_Birth", "Phone"],
            [["Jane", "Doe", "1985-03-15", "F", "5551234567"]],
        )
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1

    def test_empty_csv(self) -> None:
        result = parse_csv("")
        assert result.total_rows == 0

    def test_header_only(self) -> None:
        csv = "first_name,last_name,birthdate,sex_at_birth,phone"
        result = parse_csv(csv)
        assert result.total_rows == 0

    def test_extra_columns_ignored(self) -> None:
        csv = _make_csv(
            ["first_name", "last_name", "birthdate", "sex_at_birth", "phone", "extra_col"],
            [["Jane", "Doe", "1985-03-15", "F", "5551234567", "ignored"]],
        )
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1

    def test_row_numbers_are_correct(self) -> None:
        csv = _make_csv(
            ["first_name", "last_name", "birthdate", "sex_at_birth", "phone"],
            [
                ["Jane", "Doe", "1985-03-15", "F", "5551234567"],
                ["John", "Smith", "1990-01-01", "M", "5559876543"],
            ],
        )
        result = parse_csv(csv)
        assert result.valid_rows[0].row_number == 2
        assert result.valid_rows[1].row_number == 3


# ─── Template generation ───


class TestTemplateGeneration:
    def test_template_has_headers(self) -> None:
        csv = generate_template_csv()
        lines = csv.strip().split("\n")
        assert len(lines) >= 2  # header + example row
        headers = lines[0].split(",")
        assert "first_name" in headers
        assert "last_name" in headers
        assert "birthdate" in headers
        assert "sex_at_birth" in headers
        assert "phone" in headers

    def test_template_example_row_is_valid(self) -> None:
        csv = generate_template_csv()
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1
        assert len(result.error_rows) == 0


# ─── Quoted CSV field handling ───


class TestQuotedCSVFields:
    def test_quoted_field_with_comma(self) -> None:
        csv = _make_csv(
            ["first_name", "last_name", "birthdate", "sex_at_birth", "phone"],
            [],
        )
        csv = csv + '\n"Jane,Marie",Doe,1985-03-15,F,5551234567'
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1
        assert result.valid_rows[0].data["first_name"] == "Jane,Marie"

    def test_quoted_field_with_escaped_quote(self) -> None:
        csv = 'first_name,last_name,birthdate,sex_at_birth,phone\n"""Jane""",Doe,1985-03-15,F,5551234567'
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1
        assert result.valid_rows[0].data["first_name"] == '"Jane"'

    def test_carriage_return_in_line(self) -> None:
        csv = "first_name,last_name,birthdate,sex_at_birth,phone\r\nJane,Doe,1985-03-15,F,5551234567"
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1

    def test_quoted_field_containing_newline_characters(self) -> None:
        csv = 'first_name,last_name,birthdate,sex_at_birth,phone\n"Jane",Doe,1985-03-15,F,5551234567'
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1
        assert result.valid_rows[0].data["first_name"] == "Jane"


# ─── SSN validation ───


class TestSSNValidation:
    def test_valid_ssn_with_dashes(self) -> None:
        errors = validate_row(_make_valid_row(social_security_number="123-45-6789"))
        assert errors == []

    def test_valid_ssn_digits_only(self) -> None:
        errors = validate_row(_make_valid_row(social_security_number="123456789"))
        assert errors == []

    def test_invalid_ssn_too_few_digits(self) -> None:
        errors = validate_row(_make_valid_row(social_security_number="1234"))
        assert any("9 digits" in e for e in errors)

    def test_empty_ssn_is_valid(self) -> None:
        errors = validate_row(_make_valid_row(social_security_number=""))
        assert errors == []


# ─── Parse CSV edge cases ───


class TestParseCSVEdgeCases:
    def test_row_with_fewer_fields_than_headers(self) -> None:
        csv = "first_name,last_name,birthdate,sex_at_birth,phone\nJane,Doe"
        result = parse_csv(csv)
        assert result.total_rows == 1
        assert len(result.error_rows) == 1  # missing required fields

    def test_blank_header_column_skipped(self) -> None:
        csv = "first_name,,last_name,birthdate,sex_at_birth,phone\nJane,extra,Doe,1985-03-15,F,5551234567"
        result = parse_csv(csv)
        assert len(result.valid_rows) == 1
