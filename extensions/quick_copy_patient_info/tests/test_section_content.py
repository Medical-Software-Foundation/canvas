"""Tests for the QuickCopyPatientInfoSectionContent handler and helpers."""

import base64
import json
from datetime import date
from unittest.mock import patch

from canvas_sdk.effects.base import EffectType

from quick_copy_patient_info.handlers import section_content
from quick_copy_patient_info.handlers.section_config import SECTION_KEY
from quick_copy_patient_info.handlers.section_content import (
    Patient as _RealPatient,
    QuickCopyPatientInfoSectionContent,
    _format_dob,
    _format_insurance,
    _format_name,
    _format_pharmacy,
)
from tests.conftest import make_coverage, make_patient, make_transactor

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


# --- _format_pharmacy ------------------------------------------------------


def test_format_pharmacy_returns_organization_name() -> None:
    patient = make_patient(
        preferred_pharmacy={
            "organization_name": "CVS Pharmacy #1234",
            "phone": "3175557890",
            "address": "9700 N Michigan Rd, Indianapolis, IN",
        }
    )
    row = _format_pharmacy(patient)
    assert row == {
        "label": "Pharmacy",
        "display": "CVS Pharmacy #1234",
        "copy": "CVS Pharmacy #1234",
    }


def test_format_pharmacy_ignores_other_fields() -> None:
    """Even when phone and address are populated, copy should be name only."""
    patient = make_patient(
        preferred_pharmacy={
            "organization_name": "Walgreens #5678",
            "phone": "3175550000",
        }
    )
    row = _format_pharmacy(patient)
    assert row["copy"] == "Walgreens #5678"
    assert row["display"] == "Walgreens #5678"


def test_format_pharmacy_trims_whitespace() -> None:
    patient = make_patient(
        preferred_pharmacy={"organization_name": "  Express Scripts  "}
    )
    row = _format_pharmacy(patient)
    assert row["display"] == "Express Scripts"


def test_format_pharmacy_returns_none_when_no_pharmacy() -> None:
    patient = make_patient(preferred_pharmacy=None)
    assert _format_pharmacy(patient) is None


def test_format_pharmacy_returns_none_when_empty_dict() -> None:
    """A pharmacy record with no organization_name field is unusable."""
    patient = make_patient(preferred_pharmacy={})
    assert _format_pharmacy(patient) is None


def test_format_pharmacy_returns_none_when_organization_name_blank() -> None:
    patient = make_patient(preferred_pharmacy={"organization_name": "   "})
    assert _format_pharmacy(patient) is None


def test_format_pharmacy_returns_none_when_organization_name_none() -> None:
    patient = make_patient(
        preferred_pharmacy={"organization_name": None, "phone": "3175550000"}
    )
    assert _format_pharmacy(patient) is None


# --- _format_insurance -----------------------------------------------------


def test_format_insurance_returns_payer_name_for_primary_coverage() -> None:
    patient = make_patient(
        coverages=[make_coverage(payer_name="Aetna")],
    )
    row = _format_insurance(patient)
    assert row == {"label": "Insurance", "display": "Aetna", "copy": "Aetna"}


def test_format_insurance_picks_rank_one_when_multiple_coverages() -> None:
    patient = make_patient(
        coverages=[
            make_coverage(payer_name="Medicare", coverage_rank=2),
            make_coverage(payer_name="Aetna", coverage_rank=1),
            make_coverage(payer_name="Cigna", coverage_rank=3),
        ],
    )
    row = _format_insurance(patient)
    assert row["display"] == "Aetna"


def test_format_insurance_skips_non_primary_when_no_primary_exists() -> None:
    """Spec is 'primary only' - if there is no rank=1 coverage, no row."""
    patient = make_patient(
        coverages=[make_coverage(payer_name="Medicare", coverage_rank=2)],
    )
    assert _format_insurance(patient) is None


def test_format_insurance_filters_deleted_state() -> None:
    """A coverage with state=deleted should not surface even at rank=1."""
    patient = make_patient(
        coverages=[
            make_coverage(payer_name="Aetna", state="deleted"),
        ],
    )
    assert _format_insurance(patient) is None


def test_format_insurance_filters_removed_stack() -> None:
    """Coverages removed via the UI keep state=active but get stack=REMOVED.
    Without filtering on stack=IN_USE the section would surface removed
    coverages."""
    patient = make_patient(
        coverages=[
            make_coverage(payer_name="Aetna", stack="REMOVED"),
        ],
    )
    assert _format_insurance(patient) is None


def test_format_insurance_returns_none_when_no_coverages() -> None:
    patient = make_patient(coverages=[])
    assert _format_insurance(patient) is None


def test_format_insurance_returns_none_when_issuer_is_none() -> None:
    """A coverage row with no linked Transactor is meaningless for the
    quick-copy use case."""
    patient = make_patient(
        coverages=[make_coverage(payer_name=None, issuer=None)],
    )
    assert _format_insurance(patient) is None


def test_format_insurance_returns_none_when_payer_name_blank() -> None:
    patient = make_patient(
        coverages=[make_coverage(payer_name="", issuer=make_transactor(name=""))],
    )
    assert _format_insurance(patient) is None


def test_format_insurance_trims_payer_name() -> None:
    patient = make_patient(
        coverages=[
            make_coverage(
                payer_name=None,
                issuer=make_transactor(name="  Blue Cross Blue Shield  "),
            )
        ],
    )
    row = _format_insurance(patient)
    assert row["display"] == "Blue Cross Blue Shield"


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
            preferred_pharmacy={"organization_name": "CVS Pharmacy #1234"},
            coverages=[make_coverage(payer_name="Aetna")],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        labels = [row["label"] for row in ctx["rows"]]
        assert labels == ["Name", "DOB", "Pharmacy", "Insurance"]

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_missing_pharmacy_omits_pharmacy_row(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            preferred_pharmacy=None,
            coverages=[make_coverage(payer_name="Aetna")],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        labels = [row["label"] for row in ctx["rows"]]
        assert "Pharmacy" not in labels
        assert labels == ["Name", "DOB", "Insurance"]

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_missing_insurance_omits_insurance_row(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            preferred_pharmacy={"organization_name": "Walgreens #1"},
            coverages=[],
        )
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args_list[-1].args[1]
        labels = [row["label"] for row in ctx["rows"]]
        assert "Insurance" not in labels

    @patch("quick_copy_patient_info.handlers.section_content.render_to_string")
    @patch("quick_copy_patient_info.handlers.section_content.Patient")
    def test_all_fields_empty_renders_no_rows(
        self, mock_patient_cls, mock_render, mock_event
    ) -> None:
        mock_patient_cls.objects.get.return_value = make_patient(
            first_name="",
            last_name="",
            birth_date=None,
            preferred_pharmacy=None,
            coverages=[],
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
