"""AHA PREVENT base-model risk equations.

Line-for-line Python port of the AHAprevent v1.0.0 R package
(GPL-3, https://github.com/AHA-DS-Analytics/PREVENT,
DOI 10.1161/CIRCULATIONAHA.123.067626). Coefficients are unchanged
from the published reference implementation.

Returns six absolute-risk percentages per call:
    10-yr Total CVD, 10-yr ASCVD, 10-yr Heart Failure,
    30-yr Total CVD, 30-yr ASCVD, 30-yr Heart Failure.

Any output is None if the relevant inputs are missing or out of range.
30-yr scores are None when age > 59.
"""

from dataclasses import dataclass
from typing import Any, Optional

# math.exp is unavailable in the Canvas plugin sandbox (the math module is
# not in allowed-module-imports). For PREVENT logor values (roughly -10..+10)
# Python's float ** operator with the constant e gives the same result as
# math.exp to 15+ significant digits.
_E = 2.718281828459045235360287471352662


SEX_FEMALE = 1
SEX_MALE = 0


@dataclass
class PreventInput:
    """All inputs for the PREVENT base and full models.

    Optional fields use ``Optional[T]`` from ``typing`` because the
    Canvas plugin sandbox rejects PEP-604 union annotations
    (``float | None``) on dataclass fields but accepts the
    pre-PEP-604 ``Optional`` spelling. Range validation in
    :func:`compute_prevent_base` handles ``None`` and out-of-range
    cases.

    ``hba1c``, ``uacr``, and ``sdi_decile`` enable the AHA PREVENT
    full/extended model in :mod:`prevent_calculator.services.equations_full`.
    Any of them may be ``None``; if all three are ``None`` the dispatcher
    falls back to the base model.
    """

    sex: int
    age: float
    tc: Optional[float]
    hdl: Optional[float]
    sbp: float
    dm: int
    smoking: int
    bmi: Optional[float]
    egfr: float
    bptreat: int
    statin: Optional[int]
    hba1c: Optional[float] = None
    uacr: Optional[float] = None
    sdi_decile: Optional[int] = None


@dataclass
class PreventResult:
    """All six PREVENT base-model risk percentages (None if not computable)."""

    risk_10yr_cvd: Optional[float]
    risk_10yr_ascvd: Optional[float]
    risk_10yr_hf: Optional[float]
    risk_30yr_cvd: Optional[float]
    risk_30yr_ascvd: Optional[float]
    risk_30yr_hf: Optional[float]


def _mmol(cholesterol_mg_dl: float) -> float:
    return 0.02586 * cholesterol_mg_dl


def _logit_to_pct(logor: float) -> float:
    e = float(_E ** logor)
    return 100.0 * e / (1.0 + e)


def _female_logors(
    age: float,
    tc: float,
    hdl: float,
    sbp: float,
    dm: int,
    smoking: int,
    bmi: float,
    egfr: float,
    bptreat: int,
    statin: int,
) -> dict[str, float]:
    a = (age - 55) / 10
    a2 = a * a
    # ``nonhdl`` and ``nonhdl_alt`` are algebraically identical because
    # ``_mmol`` is linear (``_mmol(a-b) == _mmol(a) - _mmol(b)``). The dual
    # name is retained on purpose: the upstream AHAprevent R reference
    # uses ``nonhdl`` in the CVD equations and ``nonhdl_alt`` in ASCVD
    # to mirror the published variable names. Do not consolidate — that
    # would make a future side-by-side comparison with the R source
    # harder, even though the floats are bit-identical.
    nonhdl = _mmol(tc - hdl) - 3.5
    nonhdl_alt = _mmol(tc) - _mmol(hdl) - 3.5
    hdl_t = (_mmol(hdl) - 1.3) / 0.3
    sbp_lo = (min(sbp, 110) - 110) / 20
    sbp_hi = (max(sbp, 110) - 130) / 20
    egfr_lo = (min(egfr, 60) - 60) / -15
    egfr_hi = (max(egfr, 60) - 90) / -15
    bmi_lo = (min(bmi, 30) - 25) / 5
    bmi_hi = (max(bmi, 30) - 30) / 5

    logor_10yr_cvd = (
        -3.307728
        + 0.7939329 * a
        + 0.0305239 * nonhdl
        - 0.1606857 * hdl_t
        - 0.2394003 * sbp_lo
        + 0.360078 * sbp_hi
        + 0.8667604 * dm
        + 0.5360739 * smoking
        + 0.6045917 * egfr_lo
        + 0.0433769 * egfr_hi
        + 0.3151672 * bptreat
        - 0.1477655 * statin
        - 0.0663612 * bptreat * sbp_hi
        + 0.1197879 * statin * nonhdl
        - 0.0819715 * a * nonhdl
        + 0.0306769 * a * hdl_t
        - 0.0946348 * a * sbp_hi
        - 0.27057 * a * dm
        - 0.078715 * a * smoking
        - 0.1637806 * a * egfr_lo
    )

    logor_30yr_cvd = (
        -1.318827
        + 0.5503079 * a
        - 0.0928369 * a2
        + 0.0409794 * nonhdl
        + (-0.1663306) * hdl_t
        + (-0.1628654) * sbp_lo
        + 0.3299505 * sbp_hi
        + 0.6793894 * dm
        + 0.3196112 * smoking
        + 0.1857101 * egfr_lo
        + 0.0553528 * egfr_hi
        + 0.2894 * bptreat
        + (-0.075688) * statin
        + (-0.056367) * bptreat * sbp_hi
        + (0.1071019) * statin * nonhdl
        + (-0.0751438) * a * nonhdl
        + (0.0301786) * a * hdl_t
        + (-0.0998776) * a * sbp_hi
        + (-0.3206166) * a * dm
        + (-0.1607862) * a * smoking
        + (-0.1450788) * a * egfr_lo
    )

    logor_10yr_ascvd = (
        -3.819975
        + 0.719883 * a
        + 0.1176967 * nonhdl_alt
        - 0.151185 * hdl_t
        - 0.0835358 * sbp_lo
        + 0.3592852 * sbp_hi
        + 0.8348585 * dm
        + 0.4831078 * smoking
        + 0.4864619 * egfr_lo
        + 0.0397779 * egfr_hi
        + 0.2265309 * bptreat
        - 0.0592374 * statin
        - 0.0395762 * bptreat * sbp_hi
        + 0.0844423 * statin * nonhdl_alt
        - 0.0567839 * a * nonhdl_alt
        + 0.0325692 * a * hdl_t
        - 0.1035985 * a * sbp_hi
        - 0.2417542 * a * dm
        - 0.0791142 * a * smoking
        - 0.1671492 * a * egfr_lo
    )

    logor_30yr_ascvd = (
        -1.974074
        + 0.4669202 * a
        - 0.0893118 * a2
        + 0.1256901 * nonhdl_alt
        - 0.1542255 * hdl_t
        - 0.0018093 * sbp_lo
        + 0.322949 * sbp_hi
        + 0.6296707 * dm
        + 0.268292 * smoking
        + 0.100106 * egfr_lo
        + 0.0499663 * egfr_hi
        + 0.1875292 * bptreat
        + 0.0152476 * statin
        - 0.0276123 * bptreat * sbp_hi
        + 0.0736147 * statin * nonhdl_alt
        - 0.0521962 * a * nonhdl_alt
        + 0.0316918 * a * hdl_t
        - 0.1046101 * a * sbp_hi
        - 0.2727793 * a * dm
        - 0.1530907 * a * smoking
        - 0.1299149 * a * egfr_lo
    )

    logor_10yr_hf = (
        -4.310409
        + 0.8998235 * a
        - 0.4559771 * sbp_lo
        + 0.3576505 * sbp_hi
        + 1.038346 * dm
        + 0.583916 * smoking
        - 0.0072294 * bmi_lo
        + 0.2997706 * bmi_hi
        + 0.7451638 * egfr_lo
        + 0.0557087 * egfr_hi
        + 0.3534442 * bptreat
        - 0.0981511 * bptreat * sbp_hi
        - 0.0946663 * a * sbp_hi
        - 0.3581041 * a * dm
        - 0.1159453 * a * smoking
        - 0.003878 * a * bmi_hi
        - 0.1884289 * a * egfr_lo
    )

    logor_30yr_hf = (
        -2.205379
        + 0.6254374 * a
        - 0.0983038 * a2
        - 0.3919241 * sbp_lo
        + 0.3142295 * sbp_hi
        + 0.8330787 * dm
        + 0.3438651 * smoking
        + 0.0594874 * bmi_lo
        + 0.2525536 * bmi_hi
        + 0.2981642 * egfr_lo
        + 0.0667159 * egfr_hi
        + 0.333921 * bptreat
        - 0.0893177 * bptreat * sbp_hi
        - 0.0974299 * a * sbp_hi
        - 0.404855 * a * dm
        - 0.1982991 * a * smoking
        - 0.0035619 * a * bmi_hi
        - 0.1564215 * a * egfr_lo
    )

    return {
        "logor_10yr_cvd": logor_10yr_cvd,
        "logor_30yr_cvd": logor_30yr_cvd,
        "logor_10yr_ascvd": logor_10yr_ascvd,
        "logor_30yr_ascvd": logor_30yr_ascvd,
        "logor_10yr_hf": logor_10yr_hf,
        "logor_30yr_hf": logor_30yr_hf,
    }


def _male_logors(
    age: float,
    tc: float,
    hdl: float,
    sbp: float,
    dm: int,
    smoking: int,
    bmi: float,
    egfr: float,
    bptreat: int,
    statin: int,
) -> dict[str, float]:
    a = (age - 55) / 10
    a2 = a * a
    # ``nonhdl`` and ``nonhdl_alt`` are algebraically identical because
    # ``_mmol`` is linear (``_mmol(a-b) == _mmol(a) - _mmol(b)``). The dual
    # name is retained on purpose: the upstream AHAprevent R reference
    # uses ``nonhdl`` in the CVD equations and ``nonhdl_alt`` in ASCVD
    # to mirror the published variable names. Do not consolidate — that
    # would make a future side-by-side comparison with the R source
    # harder, even though the floats are bit-identical.
    nonhdl = _mmol(tc - hdl) - 3.5
    nonhdl_alt = _mmol(tc) - _mmol(hdl) - 3.5
    hdl_t = (_mmol(hdl) - 1.3) / 0.3
    sbp_lo = (min(sbp, 110) - 110) / 20
    sbp_hi = (max(sbp, 110) - 130) / 20
    egfr_lo = (min(egfr, 60) - 60) / -15
    egfr_hi = (max(egfr, 60) - 90) / -15
    bmi_lo = (min(bmi, 30) - 25) / 5
    bmi_hi = (max(bmi, 30) - 30) / 5

    logor_10yr_cvd = (
        -3.031168
        + 0.7688528 * a
        + 0.0736174 * nonhdl
        - 0.0954431 * hdl_t
        - 0.4347345 * sbp_lo
        + 0.3362658 * sbp_hi
        + 0.7692857 * dm
        + 0.4386871 * smoking
        + 0.5378979 * egfr_lo
        + 0.0164827 * egfr_hi
        + 0.288879 * bptreat
        - 0.1337349 * statin
        - 0.0475924 * bptreat * sbp_hi
        + 0.150273 * statin * nonhdl
        - 0.0517874 * a * nonhdl
        + 0.0191169 * a * hdl_t
        - 0.1049477 * a * sbp_hi
        - 0.2251948 * a * dm
        - 0.0895067 * a * smoking
        - 0.1543702 * a * egfr_lo
    )

    logor_30yr_cvd = (
        -1.148204
        + 0.4627309 * a
        - 0.0984281 * a2
        + 0.0836088 * nonhdl
        + (-0.1029824) * hdl_t
        + (-0.2140352) * sbp_lo
        + 0.2904325 * sbp_hi
        + 0.5331276 * dm
        + 0.2141914 * smoking
        + 0.1155556 * egfr_lo
        + 0.0603775 * egfr_hi
        + 0.232714 * bptreat
        + (-0.0272112) * statin
        + (-0.0384488) * bptreat * sbp_hi
        + (0.134192) * statin * nonhdl
        + (-0.0511759) * a * nonhdl
        + 0.0165865 * a * hdl_t
        + (-0.1101437) * a * sbp_hi
        + (-0.2585943) * a * dm
        + (-0.1566406) * a * smoking
        + (-0.1166776) * a * egfr_lo
    )

    logor_10yr_ascvd = (
        -3.500655
        + 0.7099847 * a
        + 0.1658663 * nonhdl_alt
        - 0.1144285 * hdl_t
        - 0.2837212 * sbp_lo
        + 0.3239977 * sbp_hi
        + 0.7189597 * dm
        + 0.3956973 * smoking
        + 0.3690075 * egfr_lo
        + 0.0203619 * egfr_hi
        + 0.2036522 * bptreat
        - 0.0865581 * statin
        - 0.0322916 * bptreat * sbp_hi
        + 0.114563 * statin * nonhdl_alt
        - 0.0300005 * a * nonhdl_alt
        + 0.0232747 * a * hdl_t
        - 0.0927024 * a * sbp_hi
        - 0.2018525 * a * dm
        - 0.0970527 * a * smoking
        - 0.1217081 * a * egfr_lo
    )

    logor_30yr_ascvd = (
        -1.736444
        + 0.3994099 * a
        - 0.0937484 * a2
        + 0.1744643 * nonhdl_alt
        - 0.120203 * hdl_t
        - 0.0665117 * sbp_lo
        + 0.2753037 * sbp_hi
        + 0.4790257 * dm
        + 0.1782635 * smoking
        - 0.0218789 * egfr_lo
        + 0.0602553 * egfr_hi
        + 0.1421182 * bptreat
        + 0.0135996 * statin
        - 0.0218265 * bptreat * sbp_hi
        + 0.1013148 * statin * nonhdl_alt
        - 0.0312619 * a * nonhdl_alt
        + 0.020673 * a * hdl_t
        - 0.0920935 * a * sbp_hi
        - 0.2159947 * a * dm
        - 0.1548811 * a * smoking
        - 0.0712547 * a * egfr_lo
    )

    logor_10yr_hf = (
        -3.946391
        + 0.8972642 * a
        - 0.6811466 * sbp_lo
        + 0.3634461 * sbp_hi
        + 0.923776 * dm
        + 0.5023736 * smoking
        - 0.0485841 * bmi_lo
        + 0.3726929 * bmi_hi
        + 0.6926917 * egfr_lo
        + 0.0251827 * egfr_hi
        + 0.2980922 * bptreat
        - 0.0497731 * bptreat * sbp_hi
        - 0.1289201 * a * sbp_hi
        - 0.3040924 * a * dm
        - 0.1401688 * a * smoking
        + 0.0068126 * a * bmi_hi
        - 0.1797778 * a * egfr_lo
    )

    logor_30yr_hf = (
        -1.95751
        + 0.5681541 * a
        - 0.1048388 * a2
        - 0.4761564 * sbp_lo
        + 0.30324 * sbp_hi
        + 0.6840338 * dm
        + 0.2656273 * smoking
        + 0.0833107 * bmi_lo
        + 0.26999 * bmi_hi
        + 0.2541805 * egfr_lo
        + 0.0638923 * egfr_hi
        + 0.2583631 * bptreat
        - 0.0391938 * bptreat * sbp_hi
        - 0.1269124 * a * sbp_hi
        - 0.3273572 * a * dm
        - 0.2043019 * a * smoking
        - 0.0182831 * a * bmi_hi
        - 0.1342618 * a * egfr_lo
    )

    return {
        "logor_10yr_cvd": logor_10yr_cvd,
        "logor_30yr_cvd": logor_30yr_cvd,
        "logor_10yr_ascvd": logor_10yr_ascvd,
        "logor_30yr_ascvd": logor_30yr_ascvd,
        "logor_10yr_hf": logor_10yr_hf,
        "logor_30yr_hf": logor_30yr_hf,
    }


def compute_prevent_base(inputs: PreventInput) -> PreventResult:
    """Compute the six PREVENT base-model risks. Returns None for any score
    whose required inputs are missing or out of range."""

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

    if sex == SEX_FEMALE:
        logors = _female_logors(
            age, safe_tc, safe_hdl, sbp, dm, smoking, safe_bmi, egfr, bptreat, safe_statin
        )
    else:
        logors = _male_logors(
            age, safe_tc, safe_hdl, sbp, dm, smoking, safe_bmi, egfr, bptreat, safe_statin
        )

    risk_10yr_cvd = _logit_to_pct(logors["logor_10yr_cvd"]) if cvd_ascvd_inputs_ok else None
    risk_10yr_ascvd = _logit_to_pct(logors["logor_10yr_ascvd"]) if cvd_ascvd_inputs_ok else None
    risk_10yr_hf = _logit_to_pct(logors["logor_10yr_hf"]) if hf_inputs_ok else None

    if age > 59:
        risk_30yr_cvd = None
        risk_30yr_ascvd = None
        risk_30yr_hf = None
    else:
        risk_30yr_cvd = (
            _logit_to_pct(logors["logor_30yr_cvd"]) if cvd_ascvd_inputs_ok else None
        )
        risk_30yr_ascvd = (
            _logit_to_pct(logors["logor_30yr_ascvd"]) if cvd_ascvd_inputs_ok else None
        )
        risk_30yr_hf = _logit_to_pct(logors["logor_30yr_hf"]) if hf_inputs_ok else None

    return PreventResult(
        risk_10yr_cvd=risk_10yr_cvd,
        risk_10yr_ascvd=risk_10yr_ascvd,
        risk_10yr_hf=risk_10yr_hf,
        risk_30yr_cvd=risk_30yr_cvd,
        risk_30yr_ascvd=risk_30yr_ascvd,
        risk_30yr_hf=risk_30yr_hf,
    )


def compute_prevent(inputs: PreventInput) -> PreventResult:
    """Dispatch to the base or full PREVENT model.

    The full model (UACR / HbA1c / SDI extension) is picked whenever the
    caller supplied at least one of those three predictors; otherwise the
    base model is used. This matches the upstream AHAprevent
    ``select_model()`` behaviour.
    """
    # Local import to keep equations_full's coefficient block out of the
    # base-model import path for plugins that only want the smaller core.
    from prevent_calculator.services.equations_full import (
        compute_prevent_full,
        has_any_enhanced_input,
    )

    if has_any_enhanced_input(inputs):
        return compute_prevent_full(inputs)
    return compute_prevent_base(inputs)
