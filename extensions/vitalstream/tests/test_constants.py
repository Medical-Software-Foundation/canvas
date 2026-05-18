from vitalstream import constants


def test_treatment_intervals_exact_order() -> None:
    assert constants.TREATMENT_INTERVALS == [
        "Pre-administration",
        "40-min post",
        "Pre-discharge",
    ]


def test_loinc_codes_are_nonempty_strings() -> None:
    codes = [
        constants.LOINC_HR,
        constants.LOINC_BP_PANEL,
        constants.LOINC_BP_SYS,
        constants.LOINC_BP_DIA,
        constants.LOINC_SPO2,
        constants.LOINC_RR,
        constants.LOINC_HR_MEAN,
        constants.LOINC_BP_PANEL_MEAN,
        constants.LOINC_BP_SYS_MEAN,
        constants.LOINC_BP_DIA_MEAN,
        constants.LOINC_SPO2_MEAN,
        constants.LOINC_RR_MEAN,
    ]
    for code in codes:
        assert isinstance(code, str) and code


def test_all_vital_codes_covers_discrete_loincs() -> None:
    assert constants.ALL_VITAL_CODES == {
        constants.LOINC_HR,
        constants.LOINC_BP_PANEL,
        constants.LOINC_SPO2,
        constants.LOINC_RR,
    }
