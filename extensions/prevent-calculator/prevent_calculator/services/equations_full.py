"""AHA PREVENT full-model risk equations (UACR / HbA1c / SDI extension).

Coefficients are the sex-stratified full-model betas published with
AHAprevent v1.0.0 (Khan SS et al., *Circulation* 2024,
DOI 10.1161/CIRCULATIONAHA.123.067626). The values below are taken from
the YAML reference republished by the demetra-health/pyAHAPrevent port,
which itself round-trips the official R-package binary `sysdata.rda`.

The "full" coefficient block runs whenever any one of UACR, HbA1c, or
SDI is provided — missing predictors are set to zero and their
``*_missing`` indicator is set to 1, exactly as the upstream R
`select_model()` does when it picks the ``full`` variant.

Encoding (lines up with prevent_equations.R:88-100):

  * ``ln_uacr = ln(uacr)`` if provided else 0; ``uacr_missing`` = 1 if missing
  * ``hba1c_dm  = (hba1c - 5.3) if dm == 1 and hba1c is present else 0``
  * ``hba1c_nodm = (hba1c - 5.3) if dm == 0 and hba1c is present else 0``
  * ``hba1c_missing`` = 1 if hba1c missing
  * SDI deciles 1-3 are the reference category (sdi_term1 = sdi_term2 = 0)
  * SDI deciles 4-6  → sdi_term1 = 1
  * SDI deciles 7-10 → sdi_term2 = 1
  * SDI missing      → sdi_missing = 1

The remaining centring (age, SBP, eGFR, BMI, non-HDL, HDL) and ``_E``
trick mirror :mod:`prevent_calculator.services.equations`.
"""

from typing import Any, Optional

from prevent_calculator.services.equations import (
    PreventInput,
    PreventResult,
    SEX_FEMALE,
    SEX_MALE,
    _E,
    _logit_to_pct,
    _mmol,
)


_FEMALE_COEFFS = {
    "10yr_CVD": {
        "intercept": -3.860385, "age": 0.7716794,
        "nonhdl": 0.0062109, "hdl": -0.1547756,
        "sbp_low": -0.1933123, "sbp_high": 0.3071217,
        "dm": 0.496753, "smoking": 0.466605,
        "egfr_low": 0.4780697, "egfr_high": 0.0529077,
        "bptreat": 0.3034892, "statin": -0.1556524,
        "bptreat_sbp": -0.0667026, "statin_nonhdl": 0.1061825,
        "age_nonhdl": -0.0742271, "age_hdl": 0.0288245,
        "age_sbp": -0.0875188, "age_dm": -0.2267102,
        "age_smoking": -0.0676125, "age_egfr": -0.1493231,
        "sdi_term1": 0.1361989, "sdi_term2": 0.2261596,
        "sdi_missing": 0.1804508,
        "uacr": 0.1645922, "uacr_missing": 0.0198413,
        "hba1c_dm": 0.1298513, "hba1c_nodm": 0.1412555,
        "hba1c_missing": -0.0031658,
    },
    "10yr_ASCVD": {
        "intercept": -4.291503, "age": 0.7023067,
        "nonhdl": 0.0898765, "hdl": -0.1407316,
        "sbp_low": -0.0256648, "sbp_high": 0.314511,
        "dm": 0.4799217, "smoking": 0.4062049,
        "egfr_low": 0.3847744, "egfr_high": 0.0495174,
        "bptreat": 0.2133861, "statin": -0.0678552,
        "bptreat_sbp": -0.0451416, "statin_nonhdl": 0.0788187,
        "age_nonhdl": -0.0535985, "age_hdl": 0.0291762,
        "age_sbp": -0.0961839, "age_dm": -0.2001466,
        "age_smoking": -0.0586472, "age_egfr": -0.1537791,
        "sdi_term1": 0.1413965, "sdi_term2": 0.228136,
        "sdi_missing": 0.1588908,
        "uacr": 0.1371824, "uacr_missing": 0.0061613,
        "hba1c_dm": 0.123192, "hba1c_nodm": 0.1410572,
        "hba1c_missing": 0.005866,
    },
    "10yr_HF": {
        "intercept": -4.896524, "age": 0.884209,
        "sbp_low": -0.421474, "sbp_high": 0.3002919,
        "dm": 0.6170359, "smoking": 0.5380269,
        "bmi_low": -0.0191335, "bmi_high": 0.2764302,
        "egfr_low": 0.5975847, "egfr_high": 0.0654197,
        "bptreat": 0.3313614, "bptreat_sbp": -0.1002304,
        "age_sbp": -0.0845363, "age_dm": -0.2989062,
        "age_smoking": -0.1111354, "age_bmi": 0.0008104,
        "age_egfr": -0.1666635,
        "sdi_term1": 0.1213034, "sdi_term2": 0.2314147,
        "sdi_missing": 0.1819138,
        "uacr": 0.1948135, "uacr_missing": 0.0395368,
        "hba1c_dm": 0.176668, "hba1c_nodm": 0.1614911,
        "hba1c_missing": -0.0010583,
    },
    "30yr_CVD": {
        "intercept": -1.748475, "age": 0.5073749, "age_sq": -0.0981751,
        "nonhdl": 0.0162303, "hdl": -0.1617147,
        "sbp_low": -0.1111241, "sbp_high": 0.282946,
        "dm": 0.4004069, "smoking": 0.2918701,
        "egfr_low": 0.1017102, "egfr_high": 0.0622643,
        "bptreat": 0.2872416, "statin": -0.0768135,
        "bptreat_sbp": -0.0557282, "statin_nonhdl": 0.0917585,
        "age_nonhdl": -0.0679131, "age_hdl": 0.029076,
        "age_sbp": -0.0907755, "age_dm": -0.2702118,
        "age_smoking": -0.1373216, "age_egfr": -0.1255864,
        "sdi_term1": 0.1067741, "sdi_term2": 0.1853138,
        "sdi_missing": 0.1567115,
        "uacr": 0.1028065, "uacr_missing": -0.0006181,
        "hba1c_dm": 0.0925285, "hba1c_nodm": 0.0975598,
        "hba1c_missing": 0.0101713,
    },
    "30yr_ASCVD": {
        "intercept": -2.314066, "age": 0.4386739, "age_sq": -0.0921956,
        "nonhdl": 0.0977728, "hdl": -0.1453525,
        "sbp_low": 0.0590925, "sbp_high": 0.2862862,
        "dm": 0.3669136, "smoking": 0.2354695,
        "egfr_low": 0.0354338, "egfr_high": 0.0573093,
        "bptreat": 0.1840085, "statin": 0.0117504,
        "bptreat_sbp": -0.0331945, "statin_nonhdl": 0.0664311,
        "age_nonhdl": -0.0492826, "age_hdl": 0.0288888,
        "age_sbp": -0.0964709, "age_dm": -0.2279648,
        "age_smoking": -0.120405, "age_egfr": -0.1157635,
        "sdi_term1": 0.1107632, "sdi_term2": 0.1840367,
        "sdi_missing": 0.1308962,
        "uacr": 0.0810739, "uacr_missing": -0.0147785,
        "hba1c_dm": 0.0794709, "hba1c_nodm": 0.1002615,
        "hba1c_missing": 0.017301,
    },
    "30yr_HF": {
        "intercept": -2.642208, "age": 0.5927507, "age_sq": -0.1028754,
        "sbp_low": -0.3593781, "sbp_high": 0.2628556,
        "dm": 0.5113472, "smoking": 0.347344,
        "bmi_low": 0.0564656, "bmi_high": 0.2363857,
        "egfr_low": 0.1971295, "egfr_high": 0.0735227,
        "bptreat": 0.3219386, "bptreat_sbp": -0.0880321,
        "age_sbp": -0.0863132, "age_dm": -0.3425359,
        "age_smoking": -0.181405, "age_bmi": 0.0031285,
        "age_egfr": -0.1356989,
        "sdi_term1": 0.0847634, "sdi_term2": 0.18397,
        "sdi_missing": 0.1485802,
        "uacr": 0.1273306, "uacr_missing": 0.0167008,
        "hba1c_dm": 0.1378342, "hba1c_nodm": 0.1138832,
        "hba1c_missing": 0.0138979,
    },
}


_MALE_COEFFS = {
    "10yr_CVD": {
        "intercept": -3.631387, "age": 0.7847578,
        "nonhdl": 0.0534485, "hdl": -0.0911282,
        "sbp_low": -0.4921973, "sbp_high": 0.2972415,
        "dm": 0.4527054, "smoking": 0.3726641,
        "egfr_low": 0.3886854, "egfr_high": 0.0081661,
        "bptreat": 0.2508052, "statin": -0.1538484,
        "bptreat_sbp": -0.0474695, "statin_nonhdl": 0.1415382,
        "age_nonhdl": -0.0436455, "age_hdl": 0.0199549,
        "age_sbp": -0.1022686, "age_dm": -0.1762507,
        "age_smoking": -0.0715873, "age_egfr": -0.1428668,
        "sdi_term1": 0.0802431, "sdi_term2": 0.275073,
        "sdi_missing": 0.144759,
        "uacr": 0.1772853, "uacr_missing": 0.1095674,
        "hba1c_dm": 0.1165698, "hba1c_nodm": 0.1048297,
        "hba1c_missing": -0.0230072,
    },
    "10yr_ASCVD": {
        "intercept": -3.969788, "age": 0.7128741,
        "nonhdl": 0.1465201, "hdl": -0.1125794,
        "sbp_low": -0.3387216, "sbp_high": 0.2980252,
        "dm": 0.399583, "smoking": 0.3379111,
        "egfr_low": 0.2582604, "egfr_high": 0.0147769,
        "bptreat": 0.1686621, "statin": -0.1073619,
        "bptreat_sbp": -0.0381038, "statin_nonhdl": 0.1034169,
        "age_nonhdl": -0.0228755, "age_hdl": 0.0267453,
        "age_sbp": -0.0897449, "age_dm": -0.1497464,
        "age_smoking": -0.077206, "age_egfr": -0.1198368,
        "sdi_term1": 0.0651121, "sdi_term2": 0.2676683,
        "sdi_missing": 0.1388492,
        "uacr": 0.1375837, "uacr_missing": 0.0652944,
        "hba1c_dm": 0.101282, "hba1c_nodm": 0.1092726,
        "hba1c_missing": -0.0112852,
    },
    "10yr_HF": {
        "intercept": -4.663513, "age": 0.9095703,
        "sbp_low": -0.6765184, "sbp_high": 0.3111651,
        "dm": 0.5535052, "smoking": 0.4326811,
        "bmi_low": -0.0854286, "bmi_high": 0.3551736,
        "egfr_low": 0.5102245, "egfr_high": 0.015472,
        "bptreat": 0.2570964, "bptreat_sbp": -0.0591177,
        "age_sbp": -0.1219056, "age_dm": -0.2437577,
        "age_smoking": -0.105363, "age_bmi": 0.0037907,
        "age_egfr": -0.1660207,
        "sdi_term1": 0.1106372, "sdi_term2": 0.3371204,
        "sdi_missing": 0.1694628,
        "uacr": 0.2164607, "uacr_missing": 0.1702805,
        "hba1c_dm": 0.148297, "hba1c_nodm": 0.1234088,
        "hba1c_missing": -0.0234637,
    },
    "30yr_CVD": {
        "intercept": -1.504558, "age": 0.4427595, "age_sq": -0.1064108,
        "nonhdl": 0.0629381, "hdl": -0.1015427,
        "sbp_low": -0.2542326, "sbp_high": 0.2549679,
        "dm": 0.333835, "smoking": 0.1873833,
        "egfr_low": 0.0246102, "egfr_high": 0.0552014,
        "bptreat": 0.1979729, "statin": -0.0407714,
        "bptreat_sbp": -0.0365522, "statin_nonhdl": 0.1232822,
        "age_nonhdl": -0.0441334, "age_hdl": 0.0177865,
        "age_sbp": -0.1046657, "age_dm": -0.2116113,
        "age_smoking": -0.1277905, "age_egfr": -0.0955922,
        "sdi_term1": 0.0256704, "sdi_term2": 0.1887637,
        "sdi_missing": 0.089241,
        "uacr": 0.0894596, "uacr_missing": 0.0710124,
        "hba1c_dm": 0.0676202, "hba1c_nodm": 0.063409,
        "hba1c_missing": 0.0038783,
    },
    "30yr_ASCVD": {
        "intercept": -1.985368, "age": 0.3743566, "age_sq": -0.0995499,
        "nonhdl": 0.1544808, "hdl": -0.1215297,
        "sbp_low": -0.1083968, "sbp_high": 0.2555179,
        "dm": 0.2696998, "smoking": 0.1628432,
        "egfr_low": -0.077507, "egfr_high": 0.0583407,
        "bptreat": 0.1120322, "statin": -0.0025063,
        "bptreat_sbp": -0.0256116, "statin_nonhdl": 0.0886745,
        "age_nonhdl": -0.0254507, "age_hdl": 0.0244639,
        "age_sbp": -0.0869146, "age_dm": -0.165745,
        "age_smoking": -0.1244714, "age_egfr": -0.0624552,
        "sdi_term1": 0.015675, "sdi_term2": 0.1864231,
        "sdi_missing": 0.0845697,
        "uacr": 0.0560171, "uacr_missing": 0.0252244,
        "hba1c_dm": 0.0501422, "hba1c_nodm": 0.0722905,
        "hba1c_missing": 0.0114945,
    },
    "30yr_HF": {
        "intercept": -2.425439, "age": 0.5478829, "age_sq": -0.1111928,
        "sbp_low": -0.4547346, "sbp_high": 0.2527602,
        "dm": 0.4385384, "smoking": 0.2397952,
        "bmi_low": 0.0640931, "bmi_high": 0.2643081,
        "egfr_low": 0.1354588, "egfr_high": 0.0570689,
        "bptreat": 0.220666, "bptreat_sbp": -0.0436769,
        "age_sbp": -0.1168376, "age_dm": -0.2730055,
        "age_smoking": -0.1573691, "age_bmi": -0.0174998,
        "age_egfr": -0.1128676,
        "sdi_term1": 0.057746, "sdi_term2": 0.2446441,
        "sdi_missing": 0.1076782,
        "uacr": 0.1233486, "uacr_missing": 0.1274796,
        "hba1c_dm": 0.0985062, "hba1c_nodm": 0.0804844,
        "hba1c_missing": 0.0022806,
    },
}


_LN2 = 0.6931471805599453


def _ln(value: float) -> float:
    """Return the natural log of ``value`` using only Python builtins.

    The Canvas plugin sandbox does not expose ``math.log``, so we use
    range reduction by powers of two (ln(x) = ln(m) + k·ln(2) when
    x = m · 2^k, and 0.7 ≤ m ≤ 1.5) and then the rapidly-convergent
    artanh series:

        ln(m) = 2 · sum_{k=0..N} y^(2k+1) / (2k+1),    y = (m-1)/(m+1)

    With 40 series terms over the reduced range, the relative error is
    below 1e-15 for any positive input in the PREVENT UACR range
    [0.1, 25000].
    """
    # Non-finite inputs (inf, -inf, NaN) would either hang the
    # range-reduction loops (``inf / 2 == inf``) or poison the series.
    # The Canvas sandbox blocks ``math.isfinite``, so we use the
    # tautology ``value == value`` (False only for NaN) plus an explicit
    # finite-magnitude bound. Values outside (0, 1e308) — the largest
    # double that ``ln`` can resolve without overflow — fall back to 0.
    if value <= 0 or value != value or value > 1e308:
        return 0.0
    n = 0
    m = float(value)
    while m > 1.5:
        m /= 2.0
        n += 1
    while m < 0.7:
        m *= 2.0
        n -= 1
    y = (m - 1.0) / (m + 1.0)
    y_sq = y * y
    total = 0.0
    term = y
    k = 0
    while k < 40:
        total += term / (2 * k + 1)
        term *= y_sq
        k += 1
    return 2.0 * total + n * _LN2


def _sdi_dummies(sdi_decile: Any) -> tuple[int, int, int]:
    """Return ``(sdi_term1, sdi_term2, sdi_missing)`` for an SDI decile.

    Decile reference categories (per prevent_equations.R:88-100):
      * 1-3  → both zero (reference)
      * 4-6  → sdi_term1
      * 7-10 → sdi_term2
      * None → sdi_missing
    """
    if sdi_decile is None:
        return 0, 0, 1
    try:
        d = int(sdi_decile)
    except (TypeError, ValueError):
        return 0, 0, 1
    if d < 1 or d > 10:
        return 0, 0, 1
    if d <= 3:
        return 0, 0, 0
    if d <= 6:
        return 1, 0, 0
    return 0, 1, 0


def _hba1c_terms(hba1c: Any, dm: int) -> tuple[float, float, int]:
    """Return ``(hba1c_dm, hba1c_nodm, hba1c_missing)``.

    HbA1c is centred at 5.3% and split by diabetes status, matching the
    AHA reference encoding.
    """
    if hba1c is None:
        return 0.0, 0.0, 1
    try:
        h = float(hba1c)
    except (TypeError, ValueError):
        return 0.0, 0.0, 1
    centred = h - 5.3
    if dm == 1:
        return centred, 0.0, 0
    return 0.0, centred, 0


def _uacr_term(uacr: Any) -> tuple[float, int]:
    """Return ``(ln_uacr, uacr_missing)``."""
    if uacr is None:
        return 0.0, 1
    try:
        u = float(uacr)
    except (TypeError, ValueError):
        return 0.0, 1
    if u <= 0:
        return 0.0, 1
    return _ln(u), 0


def _logor_for_block(
    coeffs: dict,
    a: float,
    a2: float,
    nonhdl: float,
    hdl_t: float,
    sbp_lo: float,
    sbp_hi: float,
    dm: int,
    smoking: int,
    bmi_lo: float,
    bmi_hi: float,
    egfr_lo: float,
    egfr_hi: float,
    bptreat: int,
    statin: int,
    sdi_term1: int,
    sdi_term2: int,
    sdi_missing: int,
    ln_uacr: float,
    uacr_missing: int,
    hba1c_dm: float,
    hba1c_nodm: float,
    hba1c_missing: int,
) -> float:
    """Sum the per-block PREVENT enhanced-model linear predictor.

    Each ``coeffs`` dict may omit some keys (e.g. HF blocks omit the
    cholesterol/statin terms; 10-yr blocks omit ``age_sq``). Missing keys
    are treated as zero coefficients.
    """
    def c(key: str) -> float:
        return float(coeffs.get(key, 0.0))

    return (
        c("intercept")
        + c("age") * a
        + c("age_sq") * a2
        + c("nonhdl") * nonhdl
        + c("hdl") * hdl_t
        + c("sbp_low") * sbp_lo
        + c("sbp_high") * sbp_hi
        + c("dm") * dm
        + c("smoking") * smoking
        + c("bmi_low") * bmi_lo
        + c("bmi_high") * bmi_hi
        + c("egfr_low") * egfr_lo
        + c("egfr_high") * egfr_hi
        + c("bptreat") * bptreat
        + c("statin") * statin
        + c("bptreat_sbp") * bptreat * sbp_hi
        + c("statin_nonhdl") * statin * nonhdl
        + c("age_nonhdl") * a * nonhdl
        + c("age_hdl") * a * hdl_t
        + c("age_sbp") * a * sbp_hi
        + c("age_dm") * a * dm
        + c("age_smoking") * a * smoking
        + c("age_bmi") * a * bmi_hi
        + c("age_egfr") * a * egfr_lo
        + c("sdi_term1") * sdi_term1
        + c("sdi_term2") * sdi_term2
        + c("sdi_missing") * sdi_missing
        + c("uacr") * ln_uacr
        + c("uacr_missing") * uacr_missing
        + c("hba1c_dm") * hba1c_dm
        + c("hba1c_nodm") * hba1c_nodm
        + c("hba1c_missing") * hba1c_missing
    )


def compute_prevent_full(inputs: PreventInput) -> PreventResult:
    """Compute the six PREVENT full-model risks (UACR / HbA1c / SDI extension).

    The full coefficient block is used regardless of how many of the three
    new predictors are present — missing ones are encoded via the
    ``*_missing`` indicators. The cholesterol/BMI gating (CVD/ASCVD need
    valid TC+HDL+statin; HF needs valid BMI) mirrors the base model.
    """
    sex = inputs.sex
    age = inputs.age
    tc = inputs.tc
    hdl = inputs.hdl
    sbp = inputs.sbp
    dm = inputs.dm
    smoking = inputs.smoking
    bmi = inputs.bmi
    egfr = inputs.egfr
    bptreat = inputs.bptreat
    statin = inputs.statin

    if sex not in (SEX_MALE, SEX_FEMALE):
        return PreventResult(None, None, None, None, None, None)

    cvd_ascvd_inputs_ok = (
        tc is not None
        and 130 <= tc <= 320
        and hdl is not None
        and 20 <= hdl <= 100
        and statin in (0, 1)
    )
    hf_inputs_ok = bmi is not None and 18.5 <= bmi < 40

    common_inputs_ok = (
        age is not None
        and 30 <= age <= 79
        and 90 <= sbp <= 200
        and dm in (0, 1)
        and smoking in (0, 1)
        and egfr > 0
        and bptreat in (0, 1)
    )

    if not common_inputs_ok:
        return PreventResult(None, None, None, None, None, None)

    safe_tc = tc if tc is not None else 0.0
    safe_hdl = hdl if hdl is not None else 0.0
    safe_bmi = bmi if bmi is not None else 0.0
    safe_statin = statin if statin in (0, 1) else 0

    a = (age - 55) / 10
    a2 = a * a
    # ``nonhdl`` and ``nonhdl_alt`` are algebraically identical because
    # ``_mmol`` is linear; the dual name is kept on purpose to match the
    # AHAprevent R reference (CVD blocks use ``nonhdl``, ASCVD blocks
    # use ``nonhdl_alt``). See the matching note in
    # ``equations._female_logors``.
    nonhdl = _mmol(safe_tc - safe_hdl) - 3.5
    nonhdl_alt = _mmol(safe_tc) - _mmol(safe_hdl) - 3.5
    hdl_t = (_mmol(safe_hdl) - 1.3) / 0.3
    sbp_lo = (min(sbp, 110) - 110) / 20
    sbp_hi = (max(sbp, 110) - 130) / 20
    egfr_lo = (min(egfr, 60) - 60) / -15
    egfr_hi = (max(egfr, 60) - 90) / -15
    bmi_lo = (min(safe_bmi, 30) - 25) / 5
    bmi_hi = (max(safe_bmi, 30) - 30) / 5

    sdi_term1, sdi_term2, sdi_missing = _sdi_dummies(inputs.sdi_decile)
    ln_uacr, uacr_missing = _uacr_term(inputs.uacr)
    hba1c_dm, hba1c_nodm, hba1c_missing = _hba1c_terms(inputs.hba1c, dm)

    coeffs = _FEMALE_COEFFS if sex == SEX_FEMALE else _MALE_COEFFS

    def run(block: str, *, use_alt_nonhdl: bool = False) -> float:
        return _logor_for_block(
            coeffs[block],
            a, a2,
            nonhdl_alt if use_alt_nonhdl else nonhdl,
            hdl_t,
            sbp_lo, sbp_hi,
            dm, smoking,
            bmi_lo, bmi_hi,
            egfr_lo, egfr_hi,
            bptreat, safe_statin,
            sdi_term1, sdi_term2, sdi_missing,
            ln_uacr, uacr_missing,
            hba1c_dm, hba1c_nodm, hba1c_missing,
        )

    risk_10yr_cvd = _logit_to_pct(run("10yr_CVD")) if cvd_ascvd_inputs_ok else None
    risk_10yr_ascvd = (
        _logit_to_pct(run("10yr_ASCVD", use_alt_nonhdl=True))
        if cvd_ascvd_inputs_ok
        else None
    )
    risk_10yr_hf = _logit_to_pct(run("10yr_HF")) if hf_inputs_ok else None

    if age > 59:
        risk_30yr_cvd = None
        risk_30yr_ascvd = None
        risk_30yr_hf = None
    else:
        risk_30yr_cvd = _logit_to_pct(run("30yr_CVD")) if cvd_ascvd_inputs_ok else None
        risk_30yr_ascvd = (
            _logit_to_pct(run("30yr_ASCVD", use_alt_nonhdl=True))
            if cvd_ascvd_inputs_ok
            else None
        )
        risk_30yr_hf = _logit_to_pct(run("30yr_HF")) if hf_inputs_ok else None

    return PreventResult(
        risk_10yr_cvd=risk_10yr_cvd,
        risk_10yr_ascvd=risk_10yr_ascvd,
        risk_10yr_hf=risk_10yr_hf,
        risk_30yr_cvd=risk_30yr_cvd,
        risk_30yr_ascvd=risk_30yr_ascvd,
        risk_30yr_hf=risk_30yr_hf,
    )


def has_any_enhanced_input(inputs: PreventInput) -> bool:
    """Return True if at least one of UACR / HbA1c / SDI was supplied.

    Triggers the dispatcher to pick the full model over the base model.
    """
    return (
        inputs.uacr is not None
        or inputs.hba1c is not None
        or inputs.sdi_decile is not None
    )


__all__ = ["compute_prevent_full", "has_any_enhanced_input"]
