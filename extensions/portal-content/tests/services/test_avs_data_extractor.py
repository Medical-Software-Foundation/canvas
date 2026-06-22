"""Tests for AVS data extractor."""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime
from zoneinfo import ZoneInfo

from portal_content.services.avs_data_extractor import AVSDataExtractor, format_icd10_code


# ---------------------------------------------------------------------------
# ICD-10 formatting
# ---------------------------------------------------------------------------


class TestFormatIcd10Code:
    def test_inserts_dot_after_position_3(self):
        assert format_icd10_code("E119") == "E11.9"
        assert format_icd10_code("j441") == "J44.1"

    def test_short_codes_unchanged(self):
        assert format_icd10_code("E11") == "E11"
        assert format_icd10_code("J44") == "J44"

    def test_empty_and_none(self):
        assert format_icd10_code("") == ""
        assert format_icd10_code(None) == ""

    def test_already_formatted(self):
        result = format_icd10_code("E11.9")
        assert "E11" in result


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestAVSDataExtractorInit:
    def test_loads_note_with_select_related(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_objects:
            mock_objects.select_related.return_value.get.return_value = mock_note

            extractor = AVSDataExtractor("note-uuid-123")

            assert call.select_related("patient", "provider") in mock_objects.mock_calls
            assert extractor.note == mock_note
            assert extractor.patient == mock_note.patient


# ---------------------------------------------------------------------------
# Command query helpers
# ---------------------------------------------------------------------------


class TestHelperMethods:
    def test_fetch_latest_command_data(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()
        expected = {"key": "value"}

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            mock_qs = MagicMock()
            mock_qs.order_by.return_value.values_list.return_value.first.return_value = expected
            mock_cmd_obj.filter.return_value = mock_qs

            extractor = AVSDataExtractor("note-uuid-123")
            result = extractor.fetch_latest_command_data_in_note_by_type("reasonForVisit")

            mock_cmd_obj.filter.assert_called_with(
                schema_key="reasonForVisit",
                note=mock_note,
                entered_in_error__isnull=True,
                state="committed",
            )
            assert result == expected

    def test_fetch_all_commands_data(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()
        expected = [{"a": 1}, {"b": 2}]

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            mock_qs = MagicMock()
            mock_qs.order_by.return_value.values_list.return_value.all.return_value = expected
            mock_cmd_obj.filter.return_value = mock_qs

            extractor = AVSDataExtractor("note-uuid-123")
            result = extractor.fetch_all_commands_data_in_note_by_type("prescribe")

            mock_cmd_obj.filter.assert_called_with(
                schema_key="prescribe",
                note=mock_note,
                entered_in_error__isnull=True,
                state="committed",
            )
            assert result == expected


# ---------------------------------------------------------------------------
# Patient info
# ---------------------------------------------------------------------------


class TestPatientInfo:
    def test_patient_name(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock(first_name="John", last_name="Doe")

        with patch("portal_content.services.avs_data_extractor.Note.objects") as m:
            m.select_related.return_value.get.return_value = mock_note
            assert AVSDataExtractor("id")._get_patient_name() == "John Doe"

    def test_patient_dob(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock(birth_date=datetime(1980, 5, 15).date())

        with patch("portal_content.services.avs_data_extractor.Note.objects") as m:
            m.select_related.return_value.get.return_value = mock_note
            assert AVSDataExtractor("id")._get_patient_dob() == "05/15/1980"

    def test_patient_dob_missing(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock(birth_date=None)

        with patch("portal_content.services.avs_data_extractor.Note.objects") as m:
            m.select_related.return_value.get.return_value = mock_note
            assert AVSDataExtractor("id")._get_patient_dob() == ""

    def test_appointment_datetime_from_appointment(self):
        mock_note = MagicMock()
        mock_note.datetime_of_service = None
        mock_note.created = datetime(2025, 1, 15, 12, 0, tzinfo=ZoneInfo("UTC"))
        mock_note.patient = MagicMock(last_known_timezone="America/New_York")

        mock_appt = MagicMock()
        mock_appt.start_time = datetime(2025, 1, 16, 14, 30, tzinfo=ZoneInfo("UTC"))

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Appointment.objects") as mock_appt_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_appt_obj.filter.return_value.order_by.return_value.only.return_value.first.return_value = mock_appt

            result = AVSDataExtractor("id")._get_appointment_datetime()
            assert "January 16, 2025" in result
            assert "9:30 AM" in result

    def test_appointment_datetime_fallback_to_created(self):
        mock_note = MagicMock()
        mock_note.datetime_of_service = None
        mock_note.created = datetime(2025, 1, 15, 20, 0, tzinfo=ZoneInfo("UTC"))
        mock_note.patient = MagicMock(last_known_timezone="America/New_York")

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Appointment.objects") as mock_appt_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_appt_obj.filter.return_value.order_by.return_value.only.return_value.first.return_value = None

            result = AVSDataExtractor("id")._get_appointment_datetime()
            assert "January 15, 2025" in result
            assert "3:00 PM" in result

    def test_provider_name(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()
        mock_note.provider = MagicMock(full_name="Dr. Smith")

        with patch("portal_content.services.avs_data_extractor.Note.objects") as m:
            m.select_related.return_value.get.return_value = mock_note
            assert AVSDataExtractor("id")._get_provider_name() == "Dr. Smith"

    def test_provider_name_missing(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()
        mock_note.provider = None

        with patch("portal_content.services.avs_data_extractor.Note.objects") as m:
            m.select_related.return_value.get.return_value = mock_note
            assert AVSDataExtractor("id")._get_provider_name() == "Provider"


# ---------------------------------------------------------------------------
# Reason for visit
# ---------------------------------------------------------------------------


class TestReasonForVisit:
    def _make_extractor(self, mock_note_obj, mock_cmd_obj, rfv_data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()
        mock_note_obj.select_related.return_value.get.return_value = mock_note

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values_list.return_value.first.return_value = rfv_data
        mock_cmd_obj.filter.return_value = mock_qs
        return AVSDataExtractor("id")

    def test_coding_text(self):
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, {"coding": {"text": "Annual physical"}})
            assert ext._get_reason_for_visit() == "Annual physical"

    def test_comment(self):
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, {"comment": "Follow-up diabetes"})
            assert ext._get_reason_for_visit() == "Follow-up diabetes"

    def test_narrative_json_string(self):
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, {"narrative_json": "Chest pain"})
            assert ext._get_reason_for_visit() == "Chest pain"

    def test_codings_array(self):
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, {"codings": [{"display": "Headache"}]})
            assert ext._get_reason_for_visit() == "Headache"

    def test_default_when_none(self):
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, None)
            assert ext._get_reason_for_visit() == "Follow-up visit"


# ---------------------------------------------------------------------------
# Vitals
# ---------------------------------------------------------------------------


class TestVitals:
    def _make_extractor_with_vitals(self, vitals_data_list):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                if kwargs.get("schema_key") == "vitals":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = vitals_data_list
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_vitals()

    def test_complete_vitals(self):
        vitals = self._make_extractor_with_vitals([{
            "blood_pressure_systole": 120,
            "blood_pressure_diastole": 80,
            "pulse": 72,
            "respiration_rate": 16,
            "body_temperature": 98.6,
            "weight_lbs": 180,
            "weight_oz": 0,
            "height": 70,
            "oxygen_saturation": 98,
        }])

        assert vitals["blood_pressure"]["value"] == "120/80"
        assert vitals["heart_rate"]["value"] == "72"
        assert vitals["respiratory_rate"]["value"] == "16"
        assert vitals["temperature"]["value"] == "98.6"
        assert vitals["weight"]["value"] == "180.0"
        assert vitals["height"]["value"] == "70"
        assert vitals["oxygen_saturation"]["value"] == "98"

    def test_weight_with_ounces(self):
        vitals = self._make_extractor_with_vitals([{"weight_lbs": 180, "weight_oz": 8}])
        assert vitals["weight"]["value"] == "180.5"

    def test_empty_vitals(self):
        vitals = self._make_extractor_with_vitals([])
        assert vitals == {}

    def test_bp_position_enum(self):
        vitals = self._make_extractor_with_vitals([{
            "blood_pressure_systole": 120,
            "blood_pressure_diastole": 80,
            "blood_pressure_position_and_site": "0",
        }])
        assert vitals["blood_pressure"]["position"] == "Sitting, Right Upper Extremity"


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------


class TestDiagnoses:
    def _make_extractor_with_commands(self, diagnose_data=None, assess_data=None):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                sk = kwargs.get("schema_key")
                if sk == "diagnose":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = diagnose_data or []
                elif sk == "assess":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = assess_data or []
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_diagnoses()

    def test_diagnose_with_icd10(self):
        data = [{"diagnose": {"icd10": {"display": "Type 2 diabetes", "code": "E119"}}}]
        result = self._make_extractor_with_commands(diagnose_data=data)
        assert len(result) == 1
        assert "Type 2 diabetes" in result[0]
        assert "E11.9" in result[0]

    def test_diagnose_text_only(self):
        data = [{"diagnose": {"text": "Hypertension"}}]
        result = self._make_extractor_with_commands(diagnose_data=data)
        assert result == ["Diagnosed Hypertension"]

    def test_assess_with_condition(self):
        data = [{"assess": {"icd10": {"display": "Asthma", "code": "J459"}}}]
        result = self._make_extractor_with_commands(assess_data=data)
        assert len(result) == 1
        assert "Assessed Asthma" in result[0]
        assert "J45.9" in result[0]

    def test_assess_without_condition_skipped(self):
        data = [{"assess": {"value": "Narrative only"}}]
        result = self._make_extractor_with_commands(assess_data=data)
        assert result == []


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------


class TestMedications:
    def _make_extractor_with_meds(self, active_meds=None, **command_data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj, \
             patch("portal_content.services.avs_data_extractor.Medication.objects") as mock_med_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            # Mock active medications query
            mock_med_qs = MagicMock()
            mock_med_qs.prefetch_related.return_value = active_meds or []
            mock_med_obj.filter.return_value = mock_med_qs

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                sk = kwargs.get("schema_key")
                mock_qs.order_by.return_value.values_list.return_value.all.return_value = (
                    command_data.get(sk, [])
                )
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_medications()

    def test_prescribe_with_fdb_med_id(self):
        meds = self._make_extractor_with_meds(prescribe=[{
            "prescribe": {
                "fdbMedId": {"display": "Lisinopril 10mg"},
                "sig": "Take 1 daily",
                "quantityToDispense": "30",
                "refills": "3",
            }
        }])
        assert len(meds["start"]) == 1
        assert meds["start"][0]["name"] == "Lisinopril 10mg"
        assert "Take 1 daily" in meds["start"][0]["description"]
        assert "Qty: 30" in meds["start"][0]["description"]
        assert "Refills: 3" in meds["start"][0]["description"]

    def test_categories(self):
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {"fdbMedId": {"display": "New Med"}}}],
            changeMedication=[{"changeMedication": {"fdbMedId": {"display": "Changed Med"}}}],
            stopMedication=[{"stopMedication": {"fdbMedId": {"display": "Stopped Med"}}}],
        )
        assert len(meds["start"]) == 1
        assert len(meds["adjust"]) == 1
        assert len(meds["stop"]) == 1
        assert meds["start"][0]["status"] == "start"
        assert meds["adjust"][0]["status"] == "adjust"
        assert meds["stop"][0]["status"] == "stop"

    def test_medication_text_fallback(self):
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {"text": "Aspirin 81mg"}}]
        )
        assert meds["start"][0]["name"] == "Aspirin 81mg"

    def test_empty_data_skipped(self):
        meds = self._make_extractor_with_meds(prescribe=[{}])
        assert meds["start"] == []


# ---------------------------------------------------------------------------
# To-Do List
# ---------------------------------------------------------------------------


class TestToDoList:
    def _make_todo(self, **command_data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                sk = kwargs.get("schema_key")
                data = command_data.get(sk)
                if data is not None:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = data
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_todo_list()

    def test_imaging_orders(self):
        todo = self._make_todo(imagingOrder=[{"image": {"text": "Chest X-ray"}}])
        assert todo["imaging_orders"] == ["Chest X-ray"]

    def test_lab_orders(self):
        todo = self._make_todo(labOrder=[{"labOrder": {"text": "CBC"}}])
        assert todo["lab_orders"] == ["CBC"]

    def test_referrals(self):
        todo = self._make_todo(refer=[{"refer_to": {"display": "Cardiology"}}])
        assert todo["referrals"] == ["Cardiology"]

    def test_instructions_with_title_and_narrative(self):
        todo = self._make_todo(instruct=[{
            "instruct": {"text": "Diet"},
            "narrative": "Low sodium diet",
        }])
        assert todo["instructions"] == ["Diet: Low sodium diet"]

    def test_follow_up(self):
        todo = self._make_todo(followUp=[{
            "note_type": {"text": "Office Visit"},
            "requested_date": {"date": "2025-03-15"},
            "coding": {"text": "Diabetes management"},
        }])
        assert len(todo["follow_ups"]) == 1
        assert todo["follow_ups"][0]["type"] == "Office Visit"
        assert "Mar 15, 2025" in todo["follow_ups"][0]["appointment_date"]


# ---------------------------------------------------------------------------
# Immunizations and Procedures
# ---------------------------------------------------------------------------


class TestImmunizations:
    def _make_immunizations(self, data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                if kwargs.get("schema_key") == "immunize":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = data
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_immunizations()

    def test_coding_dict(self):
        result = self._make_immunizations([{"coding": {"display": "Flu vaccine"}}])
        assert result == ["Flu vaccine (administered today)"]

    def test_coding_list(self):
        result = self._make_immunizations([{"coding": [{"display": "COVID-19"}]}])
        assert result == ["COVID-19 (administered today)"]

    def test_fallback_to_manufacturer(self):
        result = self._make_immunizations([{"manufacturer": "Pfizer"}])
        assert result == ["Pfizer (administered today)"]


class TestProcedures:
    def _make_procedures(self, data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                if kwargs.get("schema_key") == "perform":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = data
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_procedures()

    def test_coding_list(self):
        result = self._make_procedures([{"coding": [{"display": "EKG"}]}])
        assert result == ["EKG"]

    def test_perform_cpt_code(self):
        result = self._make_procedures([{"perform": {"cptCode": {"display": "Spirometry"}}}])
        assert result == ["Spirometry"]


# ---------------------------------------------------------------------------
# Upcoming Appointments
# ---------------------------------------------------------------------------


class TestUpcomingAppointments:
    def test_extracts_future_appointments(self):
        mock_note = MagicMock()
        mock_note.patient = MagicMock(last_known_timezone="America/New_York")

        mock_appt = MagicMock()
        mock_appt.start_time = datetime(2025, 2, 1, 15, 0, tzinfo=ZoneInfo("UTC"))
        mock_appt.provider = MagicMock(full_name="Dr. Smith")
        mock_appt.comment = "Follow-up"

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Appointment.objects") as mock_appt_obj, \
             patch("portal_content.services.avs_data_extractor.arrow") as mock_arrow:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_arrow.utcnow.return_value.datetime = datetime(2025, 1, 15, tzinfo=ZoneInfo("UTC"))
            mock_arrow.get.return_value.to.return_value.format.return_value = "February 1, 2025 at 10:00 AM EST"

            mock_qs = MagicMock()
            mock_qs.select_related.return_value.order_by.return_value.__getitem__.return_value = [mock_appt]
            mock_appt_obj.filter.return_value = mock_qs

            result = AVSDataExtractor("id")._extract_upcoming_appointments()
            assert len(result) == 1
            assert result[0]["provider"] == "Dr. Smith"
            assert result[0]["reason_for_visit"] == "Follow-up"


# ---------------------------------------------------------------------------
# Full extraction
# ---------------------------------------------------------------------------


class TestFullExtraction:
    def test_returns_all_expected_keys(self):
        mock_note = MagicMock()
        mock_note.created = datetime(2025, 1, 15, 16, 30, tzinfo=ZoneInfo("UTC"))
        mock_note.datetime_of_service = None
        mock_note.patient = MagicMock(
            first_name="John", last_name="Doe",
            birth_date=datetime(1980, 1, 1).date(),
            last_known_timezone="America/New_York",
        )
        mock_note.provider = MagicMock(full_name="Dr. Smith")

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj, \
             patch("portal_content.services.avs_data_extractor.Appointment.objects") as mock_appt_obj, \
             patch("portal_content.services.avs_data_extractor.Medication.objects") as mock_med_obj, \
             patch("portal_content.services.avs_data_extractor.LabOrder.objects") as mock_lab_obj, \
             patch("portal_content.services.avs_data_extractor.arrow") as mock_arrow:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_arrow.utcnow.return_value.datetime = datetime(2025, 1, 15, tzinfo=ZoneInfo("UTC"))
            mock_arrow.now.return_value.format.return_value = "January 15, 2025 at 11:30 AM EST"
            mock_arrow.get.return_value.to.return_value.format.return_value = "January 15, 2025 at 11:30 AM EST"

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                mock_qs.order_by.return_value.values_list.return_value.first.return_value = None
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            mock_med_qs = MagicMock()
            mock_med_qs.prefetch_related.return_value = []
            mock_med_obj.filter.return_value = mock_med_qs
            mock_lab_obj.filter.return_value.prefetch_related.return_value = []
            mock_appt_obj.filter.return_value.order_by.return_value.only.return_value.first.return_value = None
            mock_appt_obj.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []

            data = AVSDataExtractor("id").extract()

            expected_keys = [
                "patient_name", "patient_dob", "appointment_date_time",
                "appointment_provider", "generated_at", "reason_for_visit",
                "to_do_list", "medications", "vitals",
                "diagnoses", "immunizations", "procedures", "upcoming_appointments",
            ]
            for key in expected_keys:
                assert key in data, f"Missing key: {key}"

            assert data["patient_name"] == "John Doe"
            assert data["appointment_provider"] == "Dr. Smith"


# ---------------------------------------------------------------------------
# Edge-case: Reason for Visit (lines 143-144)
# ---------------------------------------------------------------------------


class TestReasonForVisitEdgeCases:
    """Cover alternative data shapes in _get_reason_for_visit."""

    def _make_extractor(self, mock_note_obj, mock_cmd_obj, rfv_data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()
        mock_note_obj.select_related.return_value.get.return_value = mock_note

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values_list.return_value.first.return_value = rfv_data
        mock_cmd_obj.filter.return_value = mock_qs
        return AVSDataExtractor("id")

    def test_rfv_with_codings_array(self):
        """Line 146-152: codings is a list of dicts with display key."""
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, {"codings": [{"display": "Headache"}]})
            assert ext._get_reason_for_visit() == "Headache"

    def test_rfv_with_narrative_json_dict(self):
        """Lines 143-144: narrative_json is a dict with a value key."""
        with patch("portal_content.services.avs_data_extractor.Note.objects") as n, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as c:
            ext = self._make_extractor(n, c, {"narrative_json": {"value": "Some reason"}})
            assert ext._get_reason_for_visit() == "Some reason"


# ---------------------------------------------------------------------------
# Edge-case: Vitals (lines 219, 238)
# ---------------------------------------------------------------------------


class TestVitalsEdgeCases:
    """Cover temperature site and weight ounces branches in _extract_vitals."""

    def _make_extractor_with_vitals(self, vitals_data_list):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                if kwargs.get("schema_key") == "vitals":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = vitals_data_list
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_vitals()

    def test_vitals_temperature_with_site(self):
        """Line 237-238: body_temperature_site enum is applied."""
        vitals = self._make_extractor_with_vitals([{
            "body_temperature": 98.6,
            "body_temperature_site": "1",
        }])
        assert vitals["temperature"]["value"] == "98.6"
        assert vitals["temperature"]["site"] == "Oral"

    def test_vitals_heart_rate_with_rhythm(self):
        """Line 218-219: pulse_rhythm enum is applied."""
        vitals = self._make_extractor_with_vitals([{
            "pulse": 72,
            "pulse_rhythm": "0",
        }])
        assert vitals["heart_rate"]["value"] == "72"
        assert vitals["heart_rate"]["rhythm"] == "Regular"

    def test_vitals_weight_with_ounces(self):
        """Line 245-246: weight_oz is added to total weight."""
        vitals = self._make_extractor_with_vitals([{
            "weight_lbs": 150,
            "weight_oz": 8,
        }])
        assert vitals["weight"]["value"] == "150.5"

    def test_vitals_weight_as_strings(self):
        """FHIR/Canvas data fields return values as strings, not numbers."""
        vitals = self._make_extractor_with_vitals([{
            "weight_lbs": "180",
            "weight_oz": "8",
        }])
        assert vitals["weight"]["value"] == "180.5"

    def test_vitals_weight_lbs_only_as_string(self):
        """Weight with no ounces, value arrives as string."""
        vitals = self._make_extractor_with_vitals([{
            "weight_lbs": "165",
        }])
        assert vitals["weight"]["value"] == "165.0"

    def test_vitals_weight_unparseable_skipped(self):
        """Non-numeric weight is skipped gracefully."""
        vitals = self._make_extractor_with_vitals([{
            "weight_lbs": "not-a-number",
        }])
        assert "weight" not in vitals


# ---------------------------------------------------------------------------
# Edge-case: Diagnoses (lines 297-300, 321-324, 330)
# ---------------------------------------------------------------------------


class TestDiagnosesEdgeCases:
    """Cover alternative data shapes in _extract_diagnoses and _format_diagnosis_entry."""

    def _make_extractor_with_commands(self, diagnose_data=None, assess_data=None):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                sk = kwargs.get("schema_key")
                if sk == "diagnose":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = diagnose_data or []
                elif sk == "assess":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = assess_data or []
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_diagnoses()

    def test_diagnose_with_coding_array(self):
        """Lines 320-324: coding is a list of dicts, picks first entry's display/code."""
        data = [{"diagnose": {"coding": [{"display": "Migraine", "code": "G43"}]}}]
        result = self._make_extractor_with_commands(diagnose_data=data)
        assert len(result) == 1
        assert "Migraine" in result[0]
        assert "G43" in result[0]

    def test_assess_with_conditions_list(self):
        """Lines 297-298: assess data with conditions as a list, picks first element."""
        data = [{"assess": {
            "conditions": [{"icd10": {"display": "HTN", "code": "I10"}}],
        }}]
        result = self._make_extractor_with_commands(assess_data=data)
        assert len(result) == 1
        assert "Assessed HTN" in result[0]
        assert "I10" in result[0]

    def test_assess_with_scalar_condition_skipped(self):
        """A scalar (non-dict) entry in the conditions list is skipped, not crashed on."""
        data = [{"assess": {
            "conditions": ["hypertension", {"icd10": {"display": "HTN", "code": "I10"}}],
        }}]
        result = self._make_extractor_with_commands(assess_data=data)
        assert len(result) == 1
        assert "Assessed HTN" in result[0]

    def test_assess_with_conditions_dict(self):
        """Lines 299-300: assess data with conditions as a single dict."""
        data = [{"assess": {
            "conditions": {"icd10": {"display": "HTN", "code": "I10"}},
        }}]
        result = self._make_extractor_with_commands(assess_data=data)
        assert len(result) == 1
        assert "Assessed HTN" in result[0]

    def test_diagnose_display_from_text_field(self):
        """Line 327: no icd10 and no coding, falls back to text field."""
        data = [{"diagnose": {"text": "Headache"}}]
        result = self._make_extractor_with_commands(diagnose_data=data)
        assert result == ["Diagnosed Headache"]

    def test_diagnose_no_display_returns_none(self):
        """Line 329-330: when no display can be resolved at all, entry is skipped."""
        data = [{"diagnose": {}}]
        result = self._make_extractor_with_commands(diagnose_data=data)
        assert result == []


# ---------------------------------------------------------------------------
# Edge-case: Medications (lines 352-354, 362-364, 372-374, 390-395,
#                          409-426, 441)
# ---------------------------------------------------------------------------


class TestMedicationsEdgeCases:
    """Cover alternative data shapes and fallbacks in _extract_medications."""

    def _make_extractor_with_meds(self, active_meds=None, **command_data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj, \
             patch("portal_content.services.avs_data_extractor.Medication.objects") as mock_med_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            # Mock active medications query
            mock_med_qs = MagicMock()
            mock_med_qs.prefetch_related.return_value = active_meds or []
            mock_med_obj.filter.return_value = mock_med_qs

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                sk = kwargs.get("schema_key")
                mock_qs.order_by.return_value.values_list.return_value.all.return_value = (
                    command_data.get(sk, [])
                )
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_medications()

    def test_med_name_from_text_field(self):
        """Lines 403-406: fdbMedId missing, falls back to text."""
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {"text": "Aspirin"}}]
        )
        assert meds["start"][0]["name"] == "Aspirin"

    def test_med_name_from_extra_coding(self):
        """Lines 408-415: no fdbMedId, no text, falls back to extra.coding[0].display."""
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {
                "extra": {"coding": [{"display": "Med Name"}]}
            }}]
        )
        assert meds["start"][0]["name"] == "Med Name"

    def test_med_name_from_value_field(self):
        """Lines 417-420: no fdbMedId, no text, no extra, falls back to value."""
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {"value": "Some Med"}}]
        )
        assert meds["start"][0]["name"] == "Some Med"

    def test_med_value_digit_only_skipped(self):
        """Line 419: value is a digit-only string, not used as med name."""
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {"value": "12345", "name": "Fallback Med"}}]
        )
        assert meds["start"][0]["name"] == "Fallback Med"

    def test_adjust_medication_data(self):
        """Lines 389-392: changeMedication with medication dict fallback."""
        meds = self._make_extractor_with_meds(
            changeMedication=[{"medication": {"fdbMedId": {"display": "Adjusted Med"}, "sig": "Take 2 daily"}}]
        )
        assert len(meds["adjust"]) == 1
        assert meds["adjust"][0]["name"] == "Adjusted Med"
        assert meds["adjust"][0]["status"] == "adjust"

    def test_stop_medication_with_rationale(self):
        """Lines 431, 440-441: stopMedication includes rationale in description."""
        meds = self._make_extractor_with_meds(
            stopMedication=[{"stopMedication": {
                "fdbMedId": {"display": "Stopped Med"},
                "rationale": "Side effects",
            }}]
        )
        assert len(meds["stop"]) == 1
        assert meds["stop"][0]["name"] == "Stopped Med"
        assert "Reason: Side effects" in meds["stop"][0]["description"]

    def test_refill_medication(self):
        """Lines 351-354: refill commands go into start list."""
        meds = self._make_extractor_with_meds(
            refill=[{"refill": {"fdbMedId": {"display": "Refilled Med"}}}]
        )
        assert len(meds["start"]) == 1
        assert meds["start"][0]["name"] == "Refilled Med"
        assert meds["start"][0]["status"] == "start"

    def test_adjust_prescription(self):
        """Lines 361-364: adjustPrescription commands go into adjust list."""
        meds = self._make_extractor_with_meds(
            adjustPrescription=[{"adjustPrescription": {"fdbMedId": {"display": "Adjusted Rx"}}}]
        )
        assert len(meds["adjust"]) == 1
        assert meds["adjust"][0]["name"] == "Adjusted Rx"

    def test_active_medications_in_keep_list(self):
        """Keep list pulls from the patient's active medication list."""
        mock_med1 = MagicMock()
        mock_coding1 = MagicMock()
        mock_coding1.display = "Lisinopril 10mg"
        mock_med1.codings.first.return_value = mock_coding1

        mock_med2 = MagicMock()
        mock_coding2 = MagicMock()
        mock_coding2.display = "Metformin 500mg"
        mock_med2.codings.first.return_value = mock_coding2

        meds = self._make_extractor_with_meds(active_meds=[mock_med1, mock_med2])
        assert len(meds["keep"]) == 2
        assert meds["keep"][0]["name"] == "Lisinopril 10mg"
        assert meds["keep"][1]["name"] == "Metformin 500mg"
        assert meds["keep"][0]["status"] == "keep"

    def test_combination_drug_not_excluded_from_keep(self):
        """Prescribing 'Tylenol' must not hide 'Tylenol PM' (a different drug) from Keep
        Taking - token-set matching, not substring."""
        mock_active = MagicMock()
        mock_coding = MagicMock()
        mock_coding.display = "Tylenol PM"
        mock_active.codings.first.return_value = mock_coding

        meds = self._make_extractor_with_meds(
            active_meds=[mock_active],
            prescribe=[{"prescribe": {"fdbMedId": {"display": "Tylenol"}}}],
        )

        keep_names = [m["name"] for m in meds["keep"]]
        assert "Tylenol PM" in keep_names

    def test_empty_active_medications(self):
        """Keep list is empty when patient has no active medications."""
        meds = self._make_extractor_with_meds(active_meds=[])
        assert meds["keep"] == []

    def test_active_medications_exclude_entered_in_error(self):
        """Active-medication query filters out entered_in_error (retracted) records."""
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj, \
             patch("portal_content.services.avs_data_extractor.Medication.objects") as mock_med_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_med_obj.filter.return_value.prefetch_related.return_value = []
            mock_cmd_obj.filter.return_value.order_by.return_value.values_list.return_value.all.return_value = []

            AVSDataExtractor("id")._extract_medications()

            mock_med_obj.filter.assert_called_once_with(
                patient=mock_note.patient,
                status="active",
                entered_in_error__isnull=True,
            )

    def test_med_fallback_to_raw_data(self):
        """Lines 394-395: when schema key field is empty, falls back to raw data dict."""
        meds = self._make_extractor_with_meds(
            prescribe=[{"fdbMedId": {"display": "Raw Data Med"}}]
        )
        assert len(meds["start"]) == 1
        assert meds["start"][0]["name"] == "Raw Data Med"

    def test_med_no_name_found_returns_none(self):
        """Lines 425-426: when no name can be resolved, entry is skipped."""
        meds = self._make_extractor_with_meds(
            prescribe=[{"prescribe": {"value": "99999"}}]
        )
        # value is digit-only so it's skipped; no other name source -> None
        assert meds["start"] == []


# ---------------------------------------------------------------------------
# Edge-case: Todo List (lines 486-505, 517)
# ---------------------------------------------------------------------------


class TestToDoListEdgeCases:
    """Cover alternative data shapes in _extract_todo_list."""

    def _make_todo(self, **command_data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                sk = kwargs.get("schema_key")
                data = command_data.get(sk)
                if data is not None:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = data
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_todo_list()

    def test_referral_with_string_refer_to(self):
        """Lines 486-487: refer_to is a plain string."""
        todo = self._make_todo(refer=[{"refer_to": "Cardiology Dept"}])
        assert todo["referrals"] == ["Cardiology Dept"]

    def test_referral_fallback_to_indications(self):
        """Lines 489-491: refer_to is None, falls back to indications."""
        todo = self._make_todo(refer=[{"refer_to": None, "indications": "Chest pain"}])
        assert todo["referrals"] == ["Chest pain"]

    def test_referral_fallback_to_clinical_question(self):
        """Lines 489-491: refer_to is None and no indications, falls back to clinical_question."""
        todo = self._make_todo(refer=[{"refer_to": None, "clinical_question": "Evaluate murmur"}])
        assert todo["referrals"] == ["Evaluate murmur"]

    def test_referral_fallback_to_default(self):
        """Lines 489-491: refer_to is None with no fallback fields, uses default 'Referral'."""
        todo = self._make_todo(refer=[{"refer_to": None}])
        assert todo["referrals"] == ["Referral"]

    def test_instruction_narrative_only(self):
        """Lines 502-503: instruct data with no title, only narrative."""
        todo = self._make_todo(instruct=[{
            "instruct": {},
            "narrative": "Drink plenty of fluids",
        }])
        assert todo["instructions"] == ["Drink plenty of fluids"]

    def test_instruction_title_only(self):
        """Lines 504-505: instruct data with title but no narrative."""
        todo = self._make_todo(instruct=[{
            "instruct": {"text": "Exercise"},
        }])
        assert todo["instructions"] == ["Exercise"]

    def test_follow_up_without_coding_uses_reason_for_visit(self):
        """followUp with no coding key falls back to reason_for_visit."""
        todo = self._make_todo(followUp=[{
            "note_type": {"text": "Telehealth"},
            "requested_date": {"date": "2025-06-01"},
            "reason_for_visit": "Diabetes check",
        }])
        assert len(todo["follow_ups"]) == 1
        assert todo["follow_ups"][0]["type"] == "Telehealth"
        assert "Diabetes check" in todo["follow_ups"][0]["reason_for_visit"]


# ---------------------------------------------------------------------------
# Edge-case: Immunizations (lines 527-529)
# ---------------------------------------------------------------------------


class TestImmunizationsEdgeCases:
    """Cover coding-as-list branch in _extract_immunizations."""

    def _make_immunizations(self, data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                if kwargs.get("schema_key") == "immunize":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = data
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_immunizations()

    def test_immunization_with_coding_list(self):
        """Lines 563-570: coding is a list of dicts, uses first entry's display."""
        result = self._make_immunizations([{"coding": [{"display": "Hepatitis B"}]}])
        assert result == ["Hepatitis B (administered today)"]

    def test_immunization_coding_list_name_fallback(self):
        """Lines 563-570: coding list entry has name but no display."""
        result = self._make_immunizations([{"coding": [{"name": "Tdap"}]}])
        assert result == ["Tdap (administered today)"]

    def test_immunization_coding_list_code_fallback(self):
        """Lines 563-570: coding list entry has only code."""
        result = self._make_immunizations([{"coding": [{"code": "90715"}]}])
        assert result == ["90715 (administered today)"]


# ---------------------------------------------------------------------------
# Edge-case: Procedures (lines 591, 599, 602)
# ---------------------------------------------------------------------------


class TestProceduresEdgeCases:
    """Cover alternative data shapes in _extract_procedures."""

    def _make_procedures(self, data):
        mock_note = MagicMock()
        mock_note.patient = MagicMock()

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Command.objects") as mock_cmd_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note

            def mock_filter(**kwargs):
                mock_qs = MagicMock()
                if kwargs.get("schema_key") == "perform":
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = data
                else:
                    mock_qs.order_by.return_value.values_list.return_value.all.return_value = []
                return mock_qs

            mock_cmd_obj.filter.side_effect = mock_filter
            return AVSDataExtractor("id")._extract_procedures()

    def test_procedure_from_coding_dict(self):
        """Line 590-591: coding is a dict instead of list."""
        result = self._make_procedures([{"coding": {"display": "Biopsy"}}])
        assert result == ["Biopsy"]

    def test_procedure_from_perform_cpt_code(self):
        """Lines 594-597: no coding, falls back to perform.cptCode.display."""
        result = self._make_procedures([{"perform": {"cptCode": {"display": "Spirometry"}}}])
        assert result == ["Spirometry"]

    def test_procedure_from_perform_text(self):
        """Lines 598-599: no coding, no cptCode display, falls back to perform.text."""
        result = self._make_procedures([{"perform": {"text": "Wound care"}}])
        assert result == ["Wound care"]

    def test_procedure_fallback_to_notes(self):
        """Lines 601-602: no coding, no perform data, falls back to notes field."""
        result = self._make_procedures([{"notes": "Minor procedure performed"}])
        assert result == ["Minor procedure performed"]

    def test_procedure_default_name(self):
        """Line 602: no coding, no perform, no notes - uses default 'Procedure'."""
        result = self._make_procedures([{}])
        assert result == ["Procedure"]


# ---------------------------------------------------------------------------
# Edge-case: Appointment datetime (lines 168, 172)
# ---------------------------------------------------------------------------


class TestAppointmentDatetimeEdgeCases:
    """Cover datetime_of_service and empty-return branches."""

    def test_appointment_datetime_from_datetime_of_service(self):
        """Line 167-168: no appointment found, falls back to datetime_of_service."""
        mock_note = MagicMock()
        mock_note.datetime_of_service = datetime(2025, 3, 10, 18, 0, tzinfo=ZoneInfo("UTC"))
        mock_note.created = datetime(2025, 3, 9, 12, 0, tzinfo=ZoneInfo("UTC"))
        mock_note.patient = MagicMock(last_known_timezone="America/New_York")

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Appointment.objects") as mock_appt_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_appt_obj.filter.return_value.order_by.return_value.only.return_value.first.return_value = None

            result = AVSDataExtractor("id")._get_appointment_datetime()
            assert "March 10, 2025" in result
            assert "2:00 PM" in result

    def test_appointment_datetime_returns_empty_when_no_dates(self):
        """Line 172: no appointment, no datetime_of_service, no created -> empty string."""
        mock_note = MagicMock()
        mock_note.datetime_of_service = None
        mock_note.created = None
        mock_note.patient = MagicMock(last_known_timezone="America/New_York")

        with patch("portal_content.services.avs_data_extractor.Note.objects") as mock_note_obj, \
             patch("portal_content.services.avs_data_extractor.Appointment.objects") as mock_appt_obj:

            mock_note_obj.select_related.return_value.get.return_value = mock_note
            mock_appt_obj.filter.return_value.order_by.return_value.only.return_value.first.return_value = None

            result = AVSDataExtractor("id")._get_appointment_datetime()
            assert result == ""
