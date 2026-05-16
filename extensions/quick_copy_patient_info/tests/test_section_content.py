"""Tests for the QuickCopyPatientInfoSectionContent handler and helpers."""

import base64
import json
from datetime import date
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.effects.base import EffectType

from quick_copy_patient_info.handlers import section_content
from quick_copy_patient_info.handlers.section_config import SECTION_KEY
from quick_copy_patient_info.handlers.section_content import (
    Patient as _RealPatient,
    QuickCopyPatientInfoSectionContent,
    _format_address,
    _format_dob,
    _format_name,
    _format_phone,
)
from tests.conftest import make_address, make_contact_point, make_patient

# Capture the real DoesNotExist class at import time. The TestHandle tests
# patch the `Patient` symbol in the handler module, which turns
# `Patient.DoesNotExist` into a MagicMock attribute - useless as a
# side_effect because it isn't an Exception subclass.
_PATIENT_DOES_NOT_EXIST = _RealPatient.DoesNotExist


# --- handler/config alignment ----------------------------------------------


def test_handler_section_key_matches_config() -> None:
    """If the keys diverge, the GET_CUSTOM_SECTION event will not route
    to this handler."""
    assert QuickCopyPatientInfoSectionContent.SECTION_KEY == SECTION_KEY


# --- _format_name ----------------------------------------------------------


def test_format_name_returns_row_when_first_and_last_present() -> None:
    patient = make_patient(first_name="Jane", last_name="Doe")
    row = _format_name(patient)
    assert row == {"label": "Name", "display": "Jane Doe", "copy": "Jane Doe"}


def test_format_name_returns_first_only_when_last_blank() -> None:
    patient = make_patient(first_name="Cher", last_name="")
    row = _format_name(patient)
    assert row == {"label": "Name", "display": "Cher", "copy": "Cher"}


def test_format_name_returns_last_only_when_first_blank() -> None:
    patient = make_patient(first_name="", last_name="Hendrix")
    row = _format_name(patient)
    assert row == {"label": "Name", "display": "Hendrix", "copy": "Hendrix"}


def test_format_name_returns_none_when_both_blank() -> None:
    patient = make_patient(first_name="", last_name="")
    assert _format_name(patient) is None


def test_format_name_trims_whitespace() -> None:
    patient = make_patient(first_name="  Jane  ", last_name=" Doe ")
    row = _format_name(patient)
    assert row["display"] == "Jane Doe"


# --- _format_dob -----------------------------------------------------------


def test_format_dob_renders_us_format() -> None:
    patient = make_patient(birth_date=date(1985, 3, 14))
    row = _format_dob(patient)
    assert row == {"label": "DOB", "display": "03/14/1985", "copy": "03/14/1985"}


def test_format_dob_pads_single_digit_month_and_day() -> None:
    patient = make_patient(birth_date=date(1972, 1, 9))
    row = _format_dob(patient)
    assert row["display"] == "01/09/1972"


def test_format_dob_returns_none_when_birth_date_missing() -> None:
    patient = make_patient(birth_date=None)
    assert _format_dob(patient) is None


# --- _format_phone ---------------------------------------------------------


def test_format_phone_ten_digit_us_number() -> None:
    patient = make_patient(
        contact_points=[make_contact_point(value="(555) 123-4567")]
    )
    row = _format_phone(patient)
    assert row == {"label": "Phone", "display": "(555) 123-4567", "copy": "5551234567"}


def test_format_phone_strips_leading_country_code_one() -> None:
    patient = make_patient(
        contact_points=[make_contact_point(value="+1 (555) 123-4567")]
    )
    row = _format_phone(patient)
    assert row["display"] == "(555) 123-4567"
    assert row["copy"] == "5551234567"


def test_format_phone_unformatted_input_is_reformatted_for_display() -> None:
    patient = make_patient(contact_points=[make_contact_point(value="5551234567")])
    row = _format_phone(patient)
    assert row["display"] == "(555) 123-4567"
    assert row["copy"] == "5551234567"


def test_format_phone_preferred_by_rank() -> None:
    """The lowest rank is the preferred phone."""
    patient = make_patient(
        contact_points=[
            make_contact_point(value="5559999999", rank=3, use="work"),
            make_contact_point(value="5551234567", rank=1, use="mobile"),
            make_contact_point(value="5550000000", rank=2, use="home"),
        ]
    )
    row = _format_phone(patient)
    assert row["copy"] == "5551234567"


def test_format_phone_filters_to_phone_system() -> None:
    """A patient who has only email contact points should not get a phone row."""
    patient = make_patient(
        contact_points=[make_contact_point(value="jane@example.com", system="email")]
    )
    assert _format_phone(patient) is None


def test_format_phone_filters_inactive_contact_points() -> None:
    patient = make_patient(
        contact_points=[
            make_contact_point(value="5551234567", state="inactive"),
        ]
    )
    assert _format_phone(patient) is None


def test_format_phone_returns_none_when_no_phones() -> None:
    patient = make_patient(contact_points=[])
    assert _format_phone(patient) is None


def test_format_phone_non_numeric_value_returns_none() -> None:
    patient = make_patient(contact_points=[make_contact_point(value="no-digits-here")])
    assert _format_phone(patient) is None


def test_format_phone_non_nanp_falls_back_to_raw_value() -> None:
    """A 7-digit phone (no area code) cannot be NANP-formatted, so the
    raw value is shown verbatim but the copy is still digits-only."""
    patient = make_patient(contact_points=[make_contact_point(value="123-4567")])
    row = _format_phone(patient)
    assert row["display"] == "123-4567"
    assert row["copy"] == "1234567"


# --- _format_address -------------------------------------------------------


def test_format_address_full_three_lines() -> None:
    patient = make_patient(
        addresses=[
            make_address(
                line1="123 Main St",
                line2="Apt 4",
                city="Indianapolis",
                state_code="IN",
                postal_code="46077",
            )
        ]
    )
    row = _format_address(patient)
    assert row == {
        "label": "Address",
        "display": "123 Main St\nApt 4\nIndianapolis, IN 46077",
        "copy": "123 Main St\nApt 4\nIndianapolis, IN 46077",
    }


def test_format_address_skips_blank_line_2() -> None:
    patient = make_patient(
        addresses=[
            make_address(
                line1="42 Oak Ridge Ln",
                city="Carmel",
                state_code="IN",
                postal_code="46033",
            )
        ]
    )
    row = _format_address(patient)
    assert row["display"] == "42 Oak Ridge Ln\nCarmel, IN 46033"


def test_format_address_prefers_home_over_other_uses() -> None:
    patient = make_patient(
        addresses=[
            make_address(
                line1="500 Work Pkwy",
                city="Zionsville",
                state_code="IN",
                postal_code="46077",
                use="work",
            ),
            make_address(
                line1="123 Main St",
                city="Indianapolis",
                state_code="IN",
                postal_code="46202",
                use="home",
            ),
        ]
    )
    row = _format_address(patient)
    assert row["display"].startswith("123 Main St")


def test_format_address_falls_back_to_first_active_when_no_home() -> None:
    patient = make_patient(
        addresses=[
            make_address(
                line1="500 Work Pkwy",
                city="Zionsville",
                state_code="IN",
                postal_code="46077",
                use="work",
            ),
        ]
    )
    row = _format_address(patient)
    assert row["display"].startswith("500 Work Pkwy")


def test_format_address_filters_inactive_addresses() -> None:
    patient = make_patient(
        addresses=[
            make_address(
                line1="123 Main St",
                city="Indianapolis",
                state_code="IN",
                postal_code="46077",
                state="inactive",
            )
        ]
    )
    assert _format_address(patient) is None


def test_format_address_returns_none_when_no_addresses() -> None:
    patient = make_patient(addresses=[])
    assert _format_address(patient) is None


def test_format_address_returns_none_when_all_parts_blank() -> None:
    patient = make_patient(addresses=[make_address()])
    assert _format_address(patient) is None


def test_format_address_handles_partial_city_state_zip() -> None:
    """A city-only record should still render a single-line address."""
    patient = make_patient(
        addresses=[
            make_address(line1="123 Main St", city="Indianapolis"),
        ]
    )
    row = _format_address(patient)
    assert row["display"] == "123 Main St\nIndianapolis"


def test_format_address_handles_state_only_without_city() -> None:
    """A rare case: state on file but no city. The state value still
    needs to land on the last line so it can be copied."""
    patient = make_patient(
        addresses=[
            make_address(line1="123 Main St", state_code="IN", postal_code="46077"),
        ]
    )
    row = _format_address(patient)
    assert row["display"] == "123 Main St\nIN 46077"


# --- handler.handle() -------------------------------------------------------


def _make_handler(event_factory, patient_id: str = "patient-1") -> QuickCopyPatientInfoSectionContent:
    return QuickCopyPatientInfoSectionContent(event=event_factory(patient_id=patient_id))


class TestHandle:
    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_all_fields_populated_renders_four_rows(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            first_name="Jane",
            last_name="Doe",
            birth_date=date(1985, 3, 14),
            contact_points=[make_contact_point(value="5551234567")],
            addresses=[
                make_address(
                    line1="123 Main St",
                    city="Indianapolis",
                    state_code="IN",
                    postal_code="46077",
                )
            ],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        labels = [row["label"] for row in ctx["rows"]]
        assert labels == ["Name", "DOB", "Phone", "Address"]

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_missing_phone_omits_phone_row(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            contact_points=[],
            addresses=[
                make_address(line1="1 Main", city="X", state_code="IN", postal_code="46077")
            ],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        labels = [row["label"] for row in ctx["rows"]]
        assert "Phone" not in labels
        assert labels == ["Name", "DOB", "Address"]

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_missing_address_omits_address_row(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            contact_points=[make_contact_point(value="5551234567")],
            addresses=[],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        labels = [row["label"] for row in ctx["rows"]]
        assert "Address" not in labels

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_all_fields_empty_renders_no_rows(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            first_name="",
            last_name="",
            birth_date=None,
            contact_points=[],
            addresses=[],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        assert ctx["rows"] == []

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_patient_not_found_returns_empty_list(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.DoesNotExist = _PATIENT_DOES_NOT_EXIST
        mock_patient_cls.objects.get.side_effect = _PATIENT_DOES_NOT_EXIST

        handler = _make_handler(mock_event)
        effects = handler.handle()
        assert effects == []

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_handler_queries_patient_by_event_target_id(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient()
        mock_render.return_value = ""

        handler = _make_handler(mock_event, patient_id="patient-42")
        handler.handle()

        mock_patient_cls.objects.get.assert_called_once_with(id="patient-42")

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_emits_custom_section_effect_with_html_and_icon(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient()
        mock_render.return_value = "<section>hi</section>"

        handler = _make_handler(mock_event)
        [effect] = handler.handle()

        assert effect.type == EffectType.PATIENT_CHART_SUMMARY__CUSTOM_SECTION
        data = json.loads(effect.payload)["data"]
        assert data["content"] == "<section>hi</section>"
        assert data["url"] is None
        assert data["icon_url"].startswith("data:image/svg+xml;base64,")
        assert data["icon"] is None

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_template_path_is_static_section_html(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient()
        mock_render.return_value = ""

        handler = _make_handler(mock_event)
        handler.handle()

        rendered_templates = [call.args[0] for call in mock_render.call_args_list]
        assert "static/section.html" in rendered_templates
        assert "static/section.css" in rendered_templates
        assert "static/section.js" in rendered_templates


# --- icon ------------------------------------------------------------------


def test_icon_url_decodes_to_valid_svg() -> None:
    """Sanity: the embedded icon round-trips and looks like an SVG."""
    prefix = "data:image/svg+xml;base64,"
    assert section_content._ICON_URL.startswith(prefix)
    decoded = base64.b64decode(section_content._ICON_URL[len(prefix):])
    assert decoded.startswith(b"<svg")
    assert decoded.rstrip().endswith(b"</svg>")
