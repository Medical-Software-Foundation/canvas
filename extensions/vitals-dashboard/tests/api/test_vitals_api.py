"""Tests for vitals_dashboard/api/vitals_api.py."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from vitals_dashboard.api.vitals_api import (
    CUFF_LABEL,
    LABEL_BY_TYPE,
    UNIT_BY_TYPE,
    VitalsAPI,
    _FinishError,
    _fmt_num,
    _loinc,
    _obs_name,
    _parse_datetime,
    _parse_decimal,
    _parse_since,
    _render_summary_html,
    build_vital_observations,
)


# ---------- helpers ----------

class TestParseSince:
    def test_all_returns_none(self):
        assert _parse_since("all") is None
        assert _parse_since("ALL") is None

    def test_known_windows(self):
        before = datetime.now(timezone.utc)
        result = _parse_since("24h")
        after = datetime.now(timezone.utc)
        assert before - timedelta(hours=24, seconds=1) <= result <= after - timedelta(hours=23, minutes=59)

    @pytest.mark.parametrize("key,delta", [
        ("24h", timedelta(hours=24)),
        ("7d", timedelta(days=7)),
        ("30d", timedelta(days=30)),
        ("90d", timedelta(days=90)),
    ])
    def test_each_window(self, key, delta):
        now = datetime.now(timezone.utc)
        result = _parse_since(key)
        assert (now - result) - delta < timedelta(seconds=2)

    def test_unknown_defaults_to_7d(self):
        now = datetime.now(timezone.utc)
        result = _parse_since("bogus")
        assert (now - result) - timedelta(days=7) < timedelta(seconds=2)

    def test_empty_string_defaults_to_7d(self):
        now = datetime.now(timezone.utc)
        result = _parse_since("")
        assert (now - result) - timedelta(days=7) < timedelta(seconds=2)

    def test_none_defaults_to_7d(self):
        now = datetime.now(timezone.utc)
        result = _parse_since(None)
        assert (now - result) - timedelta(days=7) < timedelta(seconds=2)


class TestParseDecimal:
    def test_none_returns_none(self):
        assert _parse_decimal(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_decimal("") is None

    def test_numeric_string(self):
        assert _parse_decimal("12.5") == Decimal("12.5")

    def test_int(self):
        assert _parse_decimal(7) == Decimal("7")

    def test_invalid_returns_none(self):
        assert _parse_decimal("abc") is None


class TestParseDatetime:
    def test_empty_returns_default_or_now(self):
        default = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _parse_datetime(None, default=default) == default
        assert _parse_datetime("", default=default) == default

    def test_no_default_returns_now(self):
        result = _parse_datetime(None)
        assert isinstance(result, datetime)
        assert result.tzinfo is timezone.utc

    def test_iso_with_z(self):
        result = _parse_datetime("2026-04-22T10:30:00Z")
        assert result == datetime(2026, 4, 22, 10, 30, tzinfo=timezone.utc)

    def test_iso_with_offset(self):
        result = _parse_datetime("2026-04-22T10:30:00+00:00")
        assert result == datetime(2026, 4, 22, 10, 30, tzinfo=timezone.utc)

    def test_naive_iso_gets_utc(self):
        result = _parse_datetime("2026-04-22T10:30:00")
        assert result.tzinfo is timezone.utc

    def test_invalid_falls_back_to_default(self):
        default = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _parse_datetime("not a date", default=default) == default


class TestFmtNum:
    def test_none_returns_empty(self):
        assert _fmt_num(None) == ""

    def test_integer(self):
        assert _fmt_num(5) == "5"

    def test_trailing_zeros_stripped(self):
        assert _fmt_num(Decimal("12.50")) == "12.5"
        assert _fmt_num(Decimal("100.00")) == "100"

    def test_no_dot_unchanged(self):
        assert _fmt_num(Decimal("42")) == "42"


class TestLoinc:
    def test_coding_data(self):
        coding = _loinc("8480-6", "Systolic blood pressure")
        assert coding.code == "8480-6"
        assert coding.display == "Systolic blood pressure"
        assert coding.system == "http://loinc.org"


class TestConstants:
    def test_unit_by_type_covers_vital_types(self):
        # Key vitals have units
        assert UNIT_BY_TYPE["bp_systolic"] == "mmHg"
        assert UNIT_BY_TYPE["heart_rate"] == "bpm"
        assert UNIT_BY_TYPE["temperature"] == "F"
        assert UNIT_BY_TYPE["oxygen_saturation"] == "%"
        assert UNIT_BY_TYPE["pain_score"] == ""

    def test_label_by_type_present(self):
        assert LABEL_BY_TYPE["heart_rate"] == "Heart Rate"
        assert LABEL_BY_TYPE["edema"] == "Edema"

    def test_cuff_label_present(self):
        assert CUFF_LABEL["right_arm"] == "Right arm"
        assert CUFF_LABEL["left_wrist"] == "Left wrist"


# ---------- _obs_name ----------

class TestObsName:
    def test_bare(self):
        assert _obs_name("blood_pressure") == "blood_pressure"

    def test_cuff_only(self):
        assert _obs_name("blood_pressure", cuff="right_arm") == "blood_pressure|cuff=right_arm"

    def test_position_only(self):
        assert _obs_name("pulse", position="standing") == "pulse|pos=standing"

    def test_both(self):
        assert _obs_name("blood_pressure", cuff="left_arm", position="standing") \
            == "blood_pressure|cuff=left_arm|pos=standing"


# ---------- build_vital_observations (v0.13 — CCDA-compliant) ----------

class TestBuildVitalObservations:
    def _name_of(self, call):
        return call.kwargs.get("name", "")

    def _coding(self, call):
        codings = call.kwargs.get("codings") or []
        return codings[0].code if codings else None

    def test_empty_measurements_emits_nothing(self, session_dt):
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs:
            mock_obs.return_value.create.return_value = "E"
            effects = build_vital_observations("p-1", None, session_dt, [])
        assert effects == []
        assert mock_obs.call_count == 0

    def test_standard_bp_emits_panel_with_components(self, session_dt, measurement_factory):
        measurements = [
            measurement_factory("bp_systolic", value_numeric=130, cuff_location="right_arm", recorded_at=session_dt),
            measurement_factory("bp_diastolic", value_numeric=85, cuff_location="right_arm", recorded_at=session_dt),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData") as mock_comp:
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        bp_calls = [c for c in mock_obs.call_args_list if self._name_of(c).startswith("blood_pressure")]
        assert len(bp_calls) == 1
        kw = bp_calls[0].kwargs
        assert kw["name"] == "blood_pressure|cuff=right_arm"
        assert kw["value"] == "130/85"
        assert kw["units"] == "mm[Hg]"
        assert kw["codings"][0].code == "85354-9"
        assert len(kw["components"]) == 2

    def test_standard_bp_systolic_only(self, session_dt, measurement_factory):
        measurements = [
            measurement_factory("bp_systolic", value_numeric=140, recorded_at=session_dt),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        bp_calls = [c for c in mock_obs.call_args_list if self._name_of(c) == "blood_pressure"]
        assert len(bp_calls) == 1
        assert bp_calls[0].kwargs["value"] == "140/"

    def test_orthostatic_bp_emits_position_specific_loinc_per_measurement(self, session_dt, measurement_factory):
        measurements = [
            measurement_factory("bp_systolic", value_numeric=120, position="laying", recorded_at=session_dt),
            measurement_factory("bp_diastolic", value_numeric=78, position="laying", recorded_at=session_dt, dbid=2),
            measurement_factory("bp_systolic", value_numeric=125, position="sitting", recorded_at=session_dt, dbid=3),
            measurement_factory("bp_systolic", value_numeric=118, position="standing", recorded_at=session_dt, dbid=4),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        bp_calls = [c for c in mock_obs.call_args_list if self._name_of(c).startswith("blood_pressure")]
        # 4 discrete orthostatic observations, no panel (all positional)
        assert len(bp_calls) == 4
        loincs = sorted(self._coding(c) for c in bp_calls)
        # systolic laying, systolic sitting, systolic standing, diastolic laying
        assert loincs == sorted(["8461-1", "8459-0", "8460-3", "8455-8"])
        # all names carry position suffix
        for c in bp_calls:
            assert "|pos=" in c.kwargs["name"]

    def test_mixed_standard_and_orthostatic_bp(self, session_dt, measurement_factory):
        measurements = [
            measurement_factory("bp_systolic", value_numeric=130, recorded_at=session_dt),  # standard
            measurement_factory("bp_diastolic", value_numeric=85, recorded_at=session_dt, dbid=2),
            measurement_factory("bp_systolic", value_numeric=118, position="standing", recorded_at=session_dt, dbid=3),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        bp_calls = [c for c in mock_obs.call_args_list if self._name_of(c).startswith("blood_pressure")]
        # 1 panel (standard) + 1 discrete (standing systolic)
        assert len(bp_calls) == 2
        panel = [c for c in bp_calls if self._coding(c) == "85354-9"]
        assert len(panel) == 1
        ortho = [c for c in bp_calls if self._coding(c) == "8460-3"]
        assert len(ortho) == 1

    def test_heart_rate_emits_one_per_measurement_with_position_suffix(self, session_dt, measurement_factory):
        measurements = [
            measurement_factory("heart_rate", value_numeric=72, recorded_at=session_dt),
            measurement_factory("heart_rate", value_numeric=88, position="standing", recorded_at=session_dt, dbid=2),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        pulse_calls = [c for c in mock_obs.call_args_list if self._name_of(c).startswith("pulse")]
        assert len(pulse_calls) == 2
        names = sorted(c.kwargs["name"] for c in pulse_calls)
        assert names == ["pulse", "pulse|pos=standing"]
        for c in pulse_calls:
            assert self._coding(c) == "8867-4"
            assert c.kwargs["units"] == "/min"

    def test_weight_current_emits_lbs_no_conversion(self, session_dt, measurement_factory):
        measurements = [measurement_factory("weight_current", value_numeric=180, recorded_at=session_dt)]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        wt_calls = [c for c in mock_obs.call_args_list if self._name_of(c) == "weight"]
        assert len(wt_calls) == 1
        assert wt_calls[0].kwargs["value"] == "180"
        assert wt_calls[0].kwargs["units"] == "[lb_av]"
        assert self._coding(wt_calls[0]) == "29463-7"

    def test_dry_weight_uses_distinct_loinc(self, session_dt, measurement_factory):
        measurements = [measurement_factory("weight_dry", value_numeric=172, recorded_at=session_dt)]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        dry_calls = [c for c in mock_obs.call_args_list if self._name_of(c) == "dry_weight"]
        assert len(dry_calls) == 1
        assert self._coding(dry_calls[0]) == "75292-3"

    def test_simple_vitals_use_correct_loincs_and_ucum(self, session_dt, measurement_factory):
        measurements = [
            measurement_factory("oxygen_saturation", value_numeric=98, recorded_at=session_dt),
            measurement_factory("respiration_rate", value_numeric=16, recorded_at=session_dt, dbid=2),
            measurement_factory("temperature", value_numeric=98.6, recorded_at=session_dt, dbid=3),
            measurement_factory("pain_score", value_numeric=4, recorded_at=session_dt, dbid=4),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        by_name = {self._name_of(c): c for c in mock_obs.call_args_list}
        assert self._coding(by_name["oxygen_saturation"]) == "59408-5"
        assert by_name["oxygen_saturation"].kwargs["units"] == "%"
        assert self._coding(by_name["respiration_rate"]) == "9279-1"
        assert by_name["respiration_rate"].kwargs["units"] == "/min"
        assert self._coding(by_name["body_temperature"]) == "8310-5"
        assert by_name["body_temperature"].kwargs["units"] == "[degF]"
        assert self._coding(by_name["pain_score"]) == "38208-5"

    def test_urine_output_emits_one_per_void(self, session_dt, measurement_factory):
        t1 = session_dt.replace(hour=8)
        t2 = session_dt.replace(hour=12)
        measurements = [
            measurement_factory("urine_output", value_numeric=250, recorded_at=t1),
            measurement_factory("urine_output", value_numeric=300, recorded_at=t2, dbid=2),
        ]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        uo = [c for c in mock_obs.call_args_list if self._name_of(c) == "urine_output"]
        assert len(uo) == 2
        assert all(self._coding(c) == "9187-6" for c in uo)
        assert all(c.kwargs["units"] == "mL" for c in uo)

    def test_edema_emits_text_value_with_loinc(self, session_dt, measurement_factory):
        m = measurement_factory("edema", value_text="2+ pitting, bilateral ankles", recorded_at=session_dt)
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, [m])

        ed = [c for c in mock_obs.call_args_list if self._name_of(c) == "edema"]
        assert len(ed) == 1
        assert ed[0].kwargs["value"] == "2+ pitting, bilateral ankles"
        assert self._coding(ed[0]) == "38378-0"

    def test_edema_empty_text_skipped(self, session_dt, measurement_factory):
        m = measurement_factory("edema", value_text="", recorded_at=session_dt)
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, [m])

        assert not any(self._name_of(c) == "edema" for c in mock_obs.call_args_list)

    def test_value_none_skipped(self, session_dt, measurement_factory):
        measurements = [measurement_factory("oxygen_saturation", value_numeric=None)]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        names = [self._name_of(c) for c in mock_obs.call_args_list]
        assert "oxygen_saturation" not in names

    def test_note_dbid_is_passed_through(self, session_dt, measurement_factory):
        measurements = [measurement_factory("heart_rate", value_numeric=72, recorded_at=session_dt)]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", 99, session_dt, measurements)

        pulse_calls = [c for c in mock_obs.call_args_list if self._name_of(c) == "pulse"]
        assert pulse_calls[0].kwargs["note_id"] == 99

    def test_note_dbid_none_allowed(self, session_dt, measurement_factory):
        measurements = [measurement_factory("heart_rate", value_numeric=72, recorded_at=session_dt)]
        with patch("vitals_dashboard.api.vitals_api.Observation") as mock_obs, \
             patch("vitals_dashboard.api.vitals_api.ObservationComponentData"):
            mock_obs.return_value.create.return_value = "E"
            build_vital_observations("p-1", None, session_dt, measurements)

        pulse_calls = [c for c in mock_obs.call_args_list if self._name_of(c) == "pulse"]
        assert pulse_calls[0].kwargs["note_id"] is None


# ---------- _render_summary_html ----------

class TestRenderSummaryHTML:
    def test_standard_bp_row_included(self, mock_session, measurement_factory):
        measurements = [
            measurement_factory("bp_systolic", value_numeric=130, cuff_location="left_arm"),
            measurement_factory("bp_diastolic", value_numeric=85, cuff_location="left_arm"),
            measurement_factory("heart_rate", value_numeric=72),
        ]
        html = _render_summary_html(mock_session, measurements, "2026-04-22")

        assert "Vitals Session" in html
        assert "2026-04-22" in html
        assert "130/85 mmHg" in html
        assert "HR 72 bpm" in html
        assert "Left arm" in html

    def test_orthostatic_rows_included(self, mock_session, measurement_factory):
        measurements = [
            measurement_factory("bp_systolic", value_numeric=120, position="laying"),
            measurement_factory("bp_diastolic", value_numeric=80, position="laying"),
            measurement_factory("heart_rate", value_numeric=70, position="laying"),
            measurement_factory("bp_systolic", value_numeric=118, position="sitting", dbid=4),
            measurement_factory("bp_systolic", value_numeric=110, position="standing", dbid=5, cuff_location="right_arm"),
        ]
        html = _render_summary_html(mock_session, measurements, "2026-04-22")

        assert "Orthostatic BP" in html
        assert "Laying" in html
        assert "Sitting" in html
        assert "Standing" in html
        assert "Right arm" in html

    def test_weight_section(self, mock_session, measurement_factory):
        measurements = [
            measurement_factory("weight_current", value_numeric=180),
            measurement_factory("weight_dry", value_numeric=175),
        ]
        html = _render_summary_html(mock_session, measurements, "2026-04-22")

        assert "Weight" in html
        assert "Current 180 lbs" in html
        assert "Dry 175 lbs" in html

    def test_urine_output_totals(self, mock_session, measurement_factory):
        t1 = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc)
        measurements = [
            measurement_factory("urine_output", value_numeric=200, value_text="clear", recorded_at=t1, dbid=1),
            measurement_factory("urine_output", value_numeric=150, recorded_at=t2, dbid=2),
        ]
        html = _render_summary_html(mock_session, measurements, "2026-04-22")

        assert "Urine Output" in html
        assert "200 mL" in html
        assert "150 mL" in html
        assert "Total: 350 mL" in html
        assert "(clear)" in html

    def test_other_vitals_section(self, mock_session, measurement_factory):
        measurements = [
            measurement_factory("oxygen_saturation", value_numeric=98),
            measurement_factory("respiration_rate", value_numeric=16, dbid=2),
            measurement_factory("temperature", value_numeric=98.6, dbid=3),
            measurement_factory("pain_score", value_numeric=3, dbid=4),
            measurement_factory("edema", value_text="1+", dbid=5),
        ]
        html = _render_summary_html(mock_session, measurements, "2026-04-22")

        assert "Other Vitals" in html
        assert "O2 Saturation: 98 %" in html
        assert "Respiration Rate: 16" in html
        assert "Temperature: 98.6 F" in html
        assert "Pain Score: 3" in html
        assert "Edema: 1+" in html

    def test_empty_measurements(self, mock_session):
        html = _render_summary_html(mock_session, [], "2026-04-22")
        assert "Vitals Session" in html
        # Shouldn't include any of the vitals sections
        assert "Orthostatic" not in html
        assert "Urine Output" not in html


# ---------- VitalsAPI ----------

def _make_api(request=None):
    api = VitalsAPI.__new__(VitalsAPI)
    api.request = request or MagicMock()
    return api


class TestStaffSessionAuth:
    def test_uses_staff_session_mixin(self):
        from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin
        assert issubclass(VitalsAPI, StaffSessionAuthMixin)


class TestLoggedInStaffId:
    def test_returns_header_id(self):
        api = _make_api(MagicMock())
        api.request.headers = {"canvas-logged-in-user-id": "s-1"}
        assert api._logged_in_staff_id() == "s-1"

    def test_missing_header_empty(self):
        api = _make_api(MagicMock())
        api.request.headers = {}
        assert api._logged_in_staff_id() == ""


class TestCreateSession:
    def _api(self, body, staff_id="s-1"):
        api = _make_api(MagicMock())
        api.request.json.return_value = body
        api.request.headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
        return api

    def test_missing_patient_key(self):
        api = self._api({"measurements": [{}]})
        resp = api.create_session()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST
        assert b"patient_key required" in resp[0].content

    def test_missing_staff_session(self):
        api = self._api({"patient_key": "p-1", "measurements": [{}]}, staff_id=None)
        resp = api.create_session()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST
        assert b"entered_by_staff_key required" in resp[0].content

    def test_measurements_must_be_list(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": "not-a-list",
        })
        resp = api.create_session()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_empty_measurements_rejected(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [],
        })
        resp = api.create_session()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_happy_path_create(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [
                {"vital_type": "heart_rate", "value_numeric": 72},
            ],
        })
        new_session = MagicMock(dbid=50)

        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.create.return_value = new_session
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows

            resp = api.create_session()

        assert resp[0].status_code == HTTPStatus.CREATED
        assert b'"session_id": "50"' in resp[0].content
        assert b'"measurement_count": 1' in resp[0].content
        # Staff attribution comes from session, not body
        assert mock_sess.objects.create.call_args.kwargs["entered_by_staff_key"] == "s-1"
        assert mock_meas.call_args.kwargs["entered_by_staff_key"] == "s-1"

    def test_body_entered_by_is_ignored(self):
        """Body's entered_by_staff_key must not override the authenticated staff id."""
        api = self._api({
            "patient_key": "p-1",
            "entered_by_staff_key": "s-SPOOFED",
            "measurements": [{"vital_type": "heart_rate", "value_numeric": 72}],
        }, staff_id="s-REAL")
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.create.return_value = MagicMock(dbid=50)
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows
            api.create_session()

        assert mock_sess.objects.create.call_args.kwargs["entered_by_staff_key"] == "s-REAL"
        assert mock_meas.call_args.kwargs["entered_by_staff_key"] == "s-REAL"

    def test_update_session_wrong_patient_forbidden(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [{"vital_type": "heart_rate", "value_numeric": 72}],
            "update_session_id": "99",
        })
        existing = MagicMock(dbid=99, patient_key="p-OTHER")
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess:
            mock_sess.objects.filter.return_value.first.return_value = existing
            resp = api.create_session()

        assert resp[0].status_code == HTTPStatus.FORBIDDEN

    def test_update_session_same_patient_resets_measurements(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [{"vital_type": "heart_rate", "value_numeric": 72}],
            "update_session_id": "99",
        })
        existing = MagicMock(dbid=99, patient_key="p-1")
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.filter.return_value.first.return_value = existing
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows

            resp = api.create_session()

        existing.save.assert_called()
        mock_meas.objects.filter.assert_any_call(session_id=str(existing.dbid))

        assert resp[0].status_code == HTTPStatus.CREATED

    def test_unknown_vital_type_skipped(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [
                {"vital_type": "bogus", "value_numeric": 1},
                {"vital_type": "heart_rate", "value_numeric": 72},
            ],
        })
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.create.return_value = MagicMock(dbid=60)
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows

            resp = api.create_session()

        # Only heart_rate constructed (bulk_create receives 1-row list)
        assert len(mock_meas.objects.bulk_create.call_args.args[0]) == 1
        assert resp[0].status_code == HTTPStatus.CREATED

    def test_invalid_position_and_cuff_normalized(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [
                {"vital_type": "bp_systolic", "value_numeric": 130, "position": "upside_down", "cuff_location": "elbow"},
            ],
        })
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.create.return_value = MagicMock(dbid=60)
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows
            api.create_session()

        call_kwargs = mock_meas.call_args.kwargs
        assert call_kwargs["position"] == ""
        assert call_kwargs["cuff_location"] == ""

    def test_measurement_with_no_value_skipped(self):
        api = self._api({
            "patient_key": "p-1",
            "measurements": [
                {"vital_type": "heart_rate"},
                {"vital_type": "heart_rate", "value_numeric": 72},
            ],
        })
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.create.return_value = MagicMock(dbid=61)
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows
            api.create_session()

        assert len(mock_meas.objects.bulk_create.call_args.args[0]) == 1

    def test_finish_true_builds_note_effects(self):
        api = self._api({
            "patient_key": "p-1",
            "session_datetime_display": "2026-04-22",
            "finish": True,
            "measurements": [{"vital_type": "heart_rate", "value_numeric": 72}],
        })
        new_session = MagicMock(dbid=70, patient_key="p-1")
        new_session.session_datetime = datetime(2026, 4, 22, tzinfo=timezone.utc)

        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas, \
             patch.object(api, "_build_finish_effects") as mock_build:
            mock_sess.objects.create.return_value = new_session
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows
            mock_build.return_value = ("note-effect", "command-effect", "new-uuid")

            resp = api.create_session()

        assert resp[0].status_code == HTTPStatus.CREATED
        assert b'"note_created": true' in resp[0].content
        assert b'"note_id": "new-uuid"' in resp[0].content
        assert "note-effect" in resp[1:]
        assert "command-effect" in resp[1:]

    def test_finish_raises_finish_error(self):
        api = self._api({
            "patient_key": "p-1",
            "finish": True,
            "measurements": [{"vital_type": "heart_rate", "value_numeric": 72}],
        })
        new_session = MagicMock(dbid=80)
        new_session.session_datetime = datetime(2026, 4, 22, tzinfo=timezone.utc)

        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas, \
             patch.object(api, "_build_finish_effects", side_effect=_FinishError("boom")):
            mock_sess.objects.create.return_value = new_session
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows

            resp = api.create_session()

        assert resp[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert b'"note_error": "boom"' in resp[0].content

    def test_bulk_create_used_for_measurements(self):
        """Regression guard: measurements are inserted in one bulk_create, not per-row create()."""
        api = self._api({
            "patient_key": "p-1",
            "measurements": [
                {"vital_type": "heart_rate", "value_numeric": 72},
                {"vital_type": "bp_systolic", "value_numeric": 130},
                {"vital_type": "bp_diastolic", "value_numeric": 85},
            ],
        })
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.create.return_value = MagicMock(dbid=55)
            mock_meas.objects.bulk_create.side_effect = lambda rows: rows
            api.create_session()

        # One bulk_create with all three rows; no per-row .create()
        mock_meas.objects.bulk_create.assert_called_once()
        assert len(mock_meas.objects.bulk_create.call_args.args[0]) == 3
        mock_meas.objects.create.assert_not_called()


class TestBuildFinishEffects:
    def test_no_note_type_raises(self):
        api = _make_api()
        session = MagicMock(patient_key="p-1", session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc))

        with patch("vitals_dashboard.api.vitals_api.NoteType") as mock_nt:
            mock_nt.objects.filter.return_value.first.return_value = None
            with pytest.raises(_FinishError, match="No 'Vitals' NoteType"):
                api._build_finish_effects(session, [], "s-1", "2026-04-22")

    def test_no_staff_at_all_raises(self):
        api = _make_api()
        session = MagicMock(patient_key="p-1", session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc))

        with patch("vitals_dashboard.api.vitals_api.NoteType") as mock_nt, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff:
            mock_nt.objects.filter.return_value.first.return_value = MagicMock(id="nt-1")
            mock_staff.objects.filter.return_value.exists.return_value = False
            mock_staff.objects.first.return_value = None
            with pytest.raises(_FinishError, match="No Staff"):
                api._build_finish_effects(session, [], "s-UNKNOWN", "2026-04-22")

    def test_no_practice_location_raises(self):
        api = _make_api()
        session = MagicMock(patient_key="p-1", session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc))

        with patch("vitals_dashboard.api.vitals_api.NoteType") as mock_nt, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff, \
             patch("vitals_dashboard.api.vitals_api.PracticeLocation") as mock_loc:
            mock_nt.objects.filter.return_value.first.return_value = MagicMock(id="nt-1")
            mock_staff.objects.filter.return_value.exists.return_value = True
            mock_loc.objects.first.return_value = None
            with pytest.raises(_FinishError, match="No PracticeLocation"):
                api._build_finish_effects(session, [], "s-1", "2026-04-22")

    def test_happy_path(self):
        api = _make_api()
        session = MagicMock(
            patient_key="p-1",
            session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )

        with patch("vitals_dashboard.api.vitals_api.NoteType") as mock_nt, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff, \
             patch("vitals_dashboard.api.vitals_api.PracticeLocation") as mock_loc, \
             patch("vitals_dashboard.api.vitals_api.NoteEffect") as mock_note_eff, \
             patch("vitals_dashboard.api.vitals_api.VitalsSummaryCommand") as mock_cmd:
            mock_nt.objects.filter.return_value.first.return_value = MagicMock(id="nt-1")
            mock_staff.objects.filter.return_value.exists.return_value = True
            mock_loc.objects.first.return_value = MagicMock(id="loc-1")
            mock_note_eff.return_value.create.return_value = "note-effect"
            mock_cmd.return_value.originate.return_value = "cmd-effect"

            note_eff, cmd_eff, note_uuid = api._build_finish_effects(
                session, [], "s-1", "2026-04-22",
            )

        assert note_eff == "note-effect"
        assert cmd_eff == "cmd-effect"
        assert isinstance(note_uuid, str) and len(note_uuid) > 0

    def test_fallback_staff_used_when_provider_missing(self):
        api = _make_api()
        session = MagicMock(
            patient_key="p-1",
            session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )

        with patch("vitals_dashboard.api.vitals_api.NoteType") as mock_nt, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff, \
             patch("vitals_dashboard.api.vitals_api.PracticeLocation") as mock_loc, \
             patch("vitals_dashboard.api.vitals_api.NoteEffect") as mock_note_eff, \
             patch("vitals_dashboard.api.vitals_api.VitalsSummaryCommand") as mock_cmd:
            mock_nt.objects.filter.return_value.first.return_value = MagicMock(id="nt-1")
            mock_staff.objects.filter.return_value.exists.return_value = False
            mock_staff.objects.first.return_value = MagicMock(id="fallback-s")
            mock_loc.objects.first.return_value = MagicMock(id="loc-1")
            mock_note_eff.return_value.create.return_value = "note-effect"
            mock_cmd.return_value.originate.return_value = "cmd-effect"

            api._build_finish_effects(session, [], "s-unknown", "2026-04-22")

        # NoteEffect constructed with fallback provider id
        kwargs = mock_note_eff.call_args.kwargs
        assert kwargs["provider_id"] == "fallback-s"

    def test_title_uses_session_datetime_when_no_display(self):
        api = _make_api()
        session = MagicMock(
            patient_key="p-1",
            session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )

        with patch("vitals_dashboard.api.vitals_api.NoteType") as mock_nt, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff, \
             patch("vitals_dashboard.api.vitals_api.PracticeLocation") as mock_loc, \
             patch("vitals_dashboard.api.vitals_api.NoteEffect") as mock_note_eff, \
             patch("vitals_dashboard.api.vitals_api.VitalsSummaryCommand") as mock_cmd:
            mock_nt.objects.filter.return_value.first.return_value = MagicMock(id="nt-1")
            mock_staff.objects.filter.return_value.exists.return_value = True
            mock_loc.objects.first.return_value = MagicMock(id="loc-1")
            mock_note_eff.return_value.create.return_value = "note-effect"
            mock_cmd.return_value.originate.return_value = "cmd-effect"

            api._build_finish_effects(session, [], "s-1", "")

        assert mock_note_eff.call_args.kwargs["title"] == "Vitals - 2026-04-22"


class TestReportContext:
    def _api(self, qp=None):
        api = _make_api(MagicMock())
        api.request.query_params = qp or {}
        return api

    def test_requires_patient_key(self):
        resp = self._api({}).get_report_context()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_patient_not_found(self):
        api = self._api({"patient_key": "pk"})
        with patch("vitals_dashboard.api.vitals_api.Patient") as mock_pat:
            mock_pat.objects.filter.return_value.prefetch_related.return_value.first.return_value = None
            resp = api.get_report_context()
        assert resp[0].status_code == HTTPStatus.NOT_FOUND

    def test_happy_path(self):
        api = self._api({"patient_key": "pk"})
        patient = MagicMock()
        patient.id = "pk"
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        patient.mrn = "MRN1"
        patient.birth_date = datetime(1990, 3, 1).date()
        patient.sex_at_birth = "F"
        phone = MagicMock(system="phone", value="555-1111")
        patient.telecom.all.return_value = [phone]
        addr = MagicMock()
        addr.line1 = "1 Test St"
        addr.line2 = ""
        addr.city = "Austin"
        addr.state_code = "TX"
        addr.postal_code = "78701"
        patient.addresses.first.return_value = addr

        location = MagicMock()
        location.full_name = "Clinic"
        location.background_image_url = "logo.png"
        loc_tel = MagicMock(value="555-2222")
        location.telecom.first.return_value = loc_tel
        loc_addr = MagicMock()
        loc_addr.line1 = "2 Clinic Way"
        loc_addr.line2 = "Suite 3"
        loc_addr.city = "Austin"
        loc_addr.state_code = "TX"
        loc_addr.postal_code = "78702"
        location.addresses.first.return_value = loc_addr

        with patch("vitals_dashboard.api.vitals_api.Patient") as mock_pat, \
             patch("vitals_dashboard.api.vitals_api.PracticeLocation") as mock_loc:
            mock_pat.objects.filter.return_value.prefetch_related.return_value.first.return_value = patient
            mock_loc.objects.prefetch_related.return_value.first.return_value = location
            resp = api.get_report_context()

        assert resp[0].status_code == HTTPStatus.OK
        body = resp[0].content
        assert b'"full_name": "Jane Doe"' in body
        assert b'"mrn": "MRN1"' in body
        assert b'"phone": "555-1111"' in body
        assert b'"name": "Clinic"' in body
        assert b'"logo_url": "logo.png"' in body
        assert b"2 Clinic Way Suite 3" in body
        # prefetch_related applied to both lookups
        mock_pat.objects.filter.return_value.prefetch_related.assert_called_with("telecom", "addresses")
        mock_loc.objects.prefetch_related.assert_called_with("telecom", "addresses")


class TestGetDraft:
    def _api(self, qp):
        api = _make_api(MagicMock())
        api.request.query_params = qp
        return api

    def test_requires_patient_key(self):
        resp = self._api({}).get_draft()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_no_draft(self):
        api = self._api({"patient_key": "p-1"})
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess:
            mock_sess.objects.filter.return_value.order_by.return_value.first.return_value = None
            resp = api.get_draft()
        assert resp[0].status_code == HTTPStatus.OK
        assert b'"draft": null' in resp[0].content

    def test_returns_draft_with_measurements(self, measurement_factory):
        api = self._api({"patient_key": "p-1"})
        session = MagicMock(
            dbid=10,
            session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )
        measurements = [
            measurement_factory("heart_rate", value_numeric=72, recorded_at=datetime(2026, 4, 22, tzinfo=timezone.utc)),
        ]
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.filter.return_value.order_by.return_value.first.return_value = session
            mock_meas.objects.filter.return_value.order_by.return_value = measurements
            resp = api.get_draft()

        assert resp[0].status_code == HTTPStatus.OK
        assert b'"session_id": "10"' in resp[0].content


class TestListMeasurements:
    def _api(self, qp):
        api = _make_api(MagicMock())
        api.request.query_params = qp
        return api

    def test_requires_patient_key(self):
        resp = self._api({}).list_measurements()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_rows_include_staff_names(self, measurement_factory):
        api = self._api({"patient_key": "p-1", "since": "7d"})
        m = measurement_factory(
            "heart_rate",
            value_numeric=72,
            recorded_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            dbid=7,
            entered_by_staff_key="s-1",
            session_id="10",
            unit="bpm",
        )
        session = MagicMock(dbid=10, note_id="note-1", provider_of_record_key="s-2")
        staff_a = MagicMock(id="s-1", first_name="Alice", last_name="Smith")
        staff_b = MagicMock(id="s-2", first_name="Bob", last_name="Jones")

        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas, \
             patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff:
            qs = MagicMock()
            qs.order_by.return_value.__getitem__.return_value = [m]
            qs.filter.return_value = qs
            mock_meas.objects.filter.return_value = qs

            mock_sess.objects.filter.return_value = [session]
            mock_staff.objects.filter.return_value = [staff_a, staff_b]

            resp = api.list_measurements()

        assert resp[0].status_code == HTTPStatus.OK
        body = resp[0].content
        assert b'"name": "Alice Smith"' in body
        assert b'"name": "Bob Jones"' in body
        assert b'"note_id": "note-1"' in body

    def test_since_all_skips_filter(self, measurement_factory):
        api = self._api({"patient_key": "p-1", "since": "all"})
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas, \
             patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.Staff") as mock_staff:
            qs = MagicMock()
            qs.order_by.return_value.__getitem__.return_value = []
            mock_meas.objects.filter.return_value = qs
            mock_sess.objects.filter.return_value = []
            mock_staff.objects.filter.return_value = []

            resp = api.list_measurements()

        assert resp[0].status_code == HTTPStatus.OK


class TestGetLastFinishedSession:
    def _api(self, qp):
        api = _make_api(MagicMock())
        api.request.query_params = qp
        return api

    def test_requires_patient_key(self):
        resp = self._api({}).get_last_finished_session()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_none_when_no_finished_sessions(self):
        api = self._api({"patient_key": "p-1"})
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess:
            mock_sess.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None
            resp = api.get_last_finished_session()
        assert resp[0].status_code == HTTPStatus.OK
        assert b'"session": null' in resp[0].content

    def test_returns_session_with_measurements(self, measurement_factory):
        api = self._api({"patient_key": "p-1"})
        session = MagicMock(
            dbid=10,
            session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )
        measurements = [
            measurement_factory("heart_rate", value_numeric=72, recorded_at=datetime(2026, 4, 22, tzinfo=timezone.utc)),
        ]
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess, \
             patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_sess.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = session
            mock_meas.objects.filter.return_value.order_by.return_value = measurements
            resp = api.get_last_finished_session()

        assert resp[0].status_code == HTTPStatus.OK
        assert b'"session_id": "10"' in resp[0].content


_SENTINEL = object()


class TestUpdateMeasurement:
    def _api(self, path_params, body, qp=_SENTINEL):
        api = _make_api(MagicMock())
        api.request.path_params = path_params
        api.request.query_params = {"patient_key": "p-OWNER"} if qp is _SENTINEL else qp
        api.request.json.return_value = body
        return api

    def test_invalid_id(self):
        api = self._api({"measurement_id": "abc"}, {})
        resp = api.update_measurement()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_id(self):
        api = self._api({"measurement_id": ""}, {})
        resp = api.update_measurement()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_patient_key(self):
        api = self._api({"measurement_id": "42"}, {}, qp={})
        resp = api.update_measurement()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST
        assert b"patient_key required" in resp[0].content

    def test_not_found(self):
        api = self._api({"measurement_id": "42"}, {})
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_meas.objects.filter.return_value.first.return_value = None
            resp = api.update_measurement()
        assert resp[0].status_code == HTTPStatus.NOT_FOUND

    def test_patient_mismatch_returns_not_found(self):
        """Cross-patient dbid walk returns 404, not details."""
        api = self._api({"measurement_id": "42"}, {}, qp={"patient_key": "p-ATTACKER"})
        measurement = MagicMock(dbid=42, patient_key="p-VICTIM")
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_meas.objects.filter.return_value.first.return_value = measurement
            resp = api.update_measurement()
        assert resp[0].status_code == HTTPStatus.NOT_FOUND
        measurement.save.assert_not_called()

    def test_updates_all_fields(self):
        api = self._api(
            {"measurement_id": "42"},
            {
                "value_numeric": "130",
                "value_text": "updated",
                "recorded_at": "2026-04-22T14:30:00Z",
            },
        )
        measurement = MagicMock(
            dbid=42,
            patient_key="p-OWNER",
            value_numeric=None,
            value_text="",
            recorded_at=None,
        )
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_meas.objects.filter.return_value.first.return_value = measurement
            resp = api.update_measurement()

        assert resp[0].status_code == HTTPStatus.OK
        measurement.save.assert_called()
        assert measurement.value_numeric == Decimal("130")
        assert measurement.value_text == "updated"


class TestDeleteMeasurement:
    def _api(self, path_params, qp=_SENTINEL):
        api = _make_api(MagicMock())
        api.request.path_params = path_params
        api.request.query_params = {"patient_key": "p-OWNER"} if qp is _SENTINEL else qp
        return api

    def test_invalid_id(self):
        resp = self._api({"measurement_id": "abc"}).delete_measurement()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_patient_key(self):
        resp = self._api({"measurement_id": "42"}, qp={}).delete_measurement()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST
        assert b"patient_key required" in resp[0].content

    def test_not_found(self):
        api = self._api({"measurement_id": "42"})
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_meas.objects.filter.return_value.first.return_value = None
            resp = api.delete_measurement()
        assert resp[0].status_code == HTTPStatus.NOT_FOUND

    def test_patient_mismatch_returns_not_found(self):
        api = self._api({"measurement_id": "42"}, qp={"patient_key": "p-ATTACKER"})
        measurement = MagicMock(dbid=42, patient_key="p-VICTIM", is_deleted=False)
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_meas.objects.filter.return_value.first.return_value = measurement
            resp = api.delete_measurement()
        assert resp[0].status_code == HTTPStatus.NOT_FOUND
        assert measurement.is_deleted is False  # Was not modified
        measurement.save.assert_not_called()

    def test_soft_delete(self):
        api = self._api({"measurement_id": "42"})
        measurement = MagicMock(dbid=42, patient_key="p-OWNER", is_deleted=False)
        with patch("vitals_dashboard.api.vitals_api.VitalsMeasurement") as mock_meas:
            mock_meas.objects.filter.return_value.first.return_value = measurement
            resp = api.delete_measurement()

        assert resp[0].status_code == HTTPStatus.OK
        assert measurement.is_deleted is True
        measurement.save.assert_called()


class TestListSessions:
    def _api(self, qp):
        api = _make_api(MagicMock())
        api.request.query_params = qp
        return api

    def test_requires_patient_key(self):
        resp = self._api({}).list_sessions()
        assert resp[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_rows(self):
        api = self._api({"patient_key": "p-1"})
        s = MagicMock(
            dbid=10,
            session_datetime=datetime(2026, 4, 22, tzinfo=timezone.utc),
            note_id="note-1",
            entered_by_staff_key="s-1",
            provider_of_record_key="s-2",
            note_stale=False,
        )
        with patch("vitals_dashboard.api.vitals_api.VitalsSession") as mock_sess:
            qs = MagicMock()
            qs.__getitem__.return_value = [s]
            mock_sess.objects.filter.return_value.order_by.return_value = qs
            resp = api.list_sessions()

        assert resp[0].status_code == HTTPStatus.OK
        assert b'"id": "10"' in resp[0].content
        assert b'"note_id": "note-1"' in resp[0].content


class TestFinishError:
    def test_is_exception(self):
        assert issubclass(_FinishError, Exception)
        with pytest.raises(_FinishError, match="test"):
            raise _FinishError("test")
