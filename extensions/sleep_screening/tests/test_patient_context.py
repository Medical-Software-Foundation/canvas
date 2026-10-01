from datetime import date
from unittest.mock import MagicMock, patch

from sleep_screening import patient_context


def _patient(birth_date, sex):
    p = MagicMock()
    p.birth_date = birth_date
    p.sex_at_birth = sex
    return p


def test_builds_age_sex_bmi():
    with patch("sleep_screening.patient_context.Patient") as Pt, \
         patch("sleep_screening.patient_context._bmi", return_value=41.2):
        Pt.objects.get.return_value = _patient(date(1960, 1, 1), "M")
        ctx = patient_context.build_context("p1", date(2026, 7, 19))
    assert ctx.age == 66
    assert ctx.sex == "M"
    assert ctx.bmi == 41.2


def test_age_before_birthday_this_year():
    with patch("sleep_screening.patient_context.Patient") as Pt, \
         patch("sleep_screening.patient_context._bmi", return_value=None):
        Pt.objects.get.return_value = _patient(date(1960, 12, 31), "F")
        ctx = patient_context.build_context("p1", date(2026, 7, 19))
    assert ctx.age == 65  # birthday not yet reached in 2026


def test_missing_bmi_is_none():
    with patch("sleep_screening.patient_context.Patient") as Pt, \
         patch("sleep_screening.patient_context._bmi", return_value=None):
        Pt.objects.get.return_value = _patient(date(1990, 6, 1), "Female")
        ctx = patient_context.build_context("p1", date(2026, 7, 19))
    assert ctx.bmi is None
    assert ctx.age == 36
    assert ctx.sex == "F"


def test_patient_not_found_degrades_gracefully():
    with patch("sleep_screening.patient_context.Patient") as Pt:
        Pt.DoesNotExist = Exception
        Pt.objects.get.side_effect = Pt.DoesNotExist
        ctx = patient_context.build_context("missing", date(2026, 7, 19))
    assert ctx.age is None and ctx.sex is None and ctx.bmi is None


def test_bmi_computed_from_height_weight():
    # 200 lb, 70 in -> 703*200/4900 = 28.69...
    with patch("sleep_screening.patient_context._weight_lbs", return_value=200.0), \
         patch("sleep_screening.patient_context._height_inches", return_value=70.0):
        bmi = patient_context._bmi(MagicMock())
    assert round(bmi, 1) == 28.7


def test_bmi_none_when_height_missing():
    with patch("sleep_screening.patient_context._weight_lbs", return_value=200.0), \
         patch("sleep_screening.patient_context._height_inches", return_value=None):
        assert patient_context._bmi(MagicMock()) is None


def test_age_none_when_no_birth_date():
    assert patient_context._age(None, date(2026, 7, 19)) is None


def test_normalize_sex_variants():
    assert patient_context._normalize_sex("male") == "M"
    assert patient_context._normalize_sex("F") == "F"
    assert patient_context._normalize_sex("other") is None
    assert patient_context._normalize_sex(None) is None


def _obs(value, units="lb"):
    o = MagicMock()
    o.value = value
    o.units = units
    return o


def test_weight_lbs_direct():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("180")):
        assert patient_context._weight_lbs(MagicMock()) == 180.0


def test_weight_oz_converts_to_lbs():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("160", "oz")):
        assert patient_context._weight_lbs(MagicMock()) == 10.0


def test_weight_none_when_no_obs():
    with patch("sleep_screening.patient_context._latest_vital", return_value=None):
        assert patient_context._weight_lbs(MagicMock()) is None


def test_weight_none_when_non_numeric():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("heavy")):
        assert patient_context._weight_lbs(MagicMock()) is None


def test_height_inches_direct():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("70")):
        assert patient_context._height_inches(MagicMock()) == 70.0


def test_height_none_when_non_numeric():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("tall")):
        assert patient_context._height_inches(MagicMock()) is None


def test_height_none_when_empty_value():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("")):
        assert patient_context._height_inches(MagicMock()) is None


def test_weight_none_when_empty_value():
    with patch("sleep_screening.patient_context._latest_vital", return_value=_obs("")):
        assert patient_context._weight_lbs(MagicMock()) is None


def test_build_context_full_path_computes_bmi():
    # exercises build_context calling the real _bmi via height/weight readers
    with patch("sleep_screening.patient_context.Patient") as Pt, \
         patch("sleep_screening.patient_context._weight_lbs", return_value=200.0), \
         patch("sleep_screening.patient_context._height_inches", return_value=70.0):
        Pt.objects.get.return_value = _patient(date(1970, 1, 1), "M")
        ctx = patient_context.build_context("p1", date(2026, 7, 19))
    assert ctx.age == 56
    assert ctx.sex == "M"
    assert round(ctx.bmi, 1) == 28.7


def test_latest_vital_queries_observation():
    with patch("sleep_screening.patient_context.Observation") as Obs:
        chain = Obs.objects.filter.return_value.exclude.return_value.order_by.return_value
        chain.last.return_value = "OBS"
        result = patient_context._latest_vital(MagicMock(), "weight")
    assert result == "OBS"
    Obs.objects.filter.assert_called_once()


def test_bmi_zero_height_guarded():
    with patch("sleep_screening.patient_context._weight_lbs", return_value=200.0), \
         patch("sleep_screening.patient_context._height_inches", return_value=0.0):
        assert patient_context._bmi(MagicMock()) is None
