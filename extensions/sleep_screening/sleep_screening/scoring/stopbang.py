from sleep_screening.scoring.base import InstrumentResult, PatientContext, present

CODE = "SLEEP_STOPBANG"
NAME = "STOP-BANG"

STOP_ITEMS = [
    "SLEEP_STOPBANG_S1",
    "SLEEP_STOPBANG_S2",
    "SLEEP_STOPBANG_S3",
    "SLEEP_STOPBANG_S4",
]
NECK_ITEM = "SLEEP_STOPBANG_NECK"
ITEMS = STOP_ITEMS + [NECK_ITEM]

BMI_THRESHOLD = 35.0
AGE_THRESHOLD = 50
HIGH_MIN = 5
INTERMEDIATE_MIN = 3


def score(responses: dict[str, float], context: PatientContext) -> InstrumentResult:
    complete = present(responses, ITEMS)
    stop_count = sum(1 for item in STOP_ITEMS if responses.get(item) == 1)
    neck_over_40 = responses.get(NECK_ITEM) == 1

    bmi_known = context.bmi is not None
    bmi_over_35 = context.bmi is not None and context.bmi > BMI_THRESHOLD
    age_over_50 = context.age is not None and context.age > AGE_THRESHOLD
    is_male = context.is_male

    bang_points = sum(
        [bool(bmi_over_35), bool(age_over_50), bool(neck_over_40), bool(is_male)]
    )
    total = stop_count + bang_points

    high_risk_override = stop_count >= 2 and (is_male or bmi_over_35 or neck_over_40)

    if total >= HIGH_MIN or high_risk_override:
        band = "High"
        high_risk = True
    elif total >= INTERMEDIATE_MIN:
        band = "Intermediate"
        high_risk = False
    else:
        band = "Low"
        high_risk = False

    narrative = "STOP-BANG total " + str(total) + " (" + band + " OSA risk)."
    if not bmi_known:
        narrative = narrative + " BMI unavailable; that point omitted."
    if high_risk_override and total < HIGH_MIN:
        narrative = narrative + " High-risk override applied."
    if not complete:
        narrative = narrative + " One or more items unanswered; result is provisional."

    return InstrumentResult(
        code=CODE,
        name=NAME,
        score=float(total),
        band=band,
        abnormal=band != "Low",
        narrative=narrative,
        complete=complete,
        high_risk=high_risk,
        subscores={
            "stop_count": float(stop_count),
            "bang_points": float(bang_points),
        },
    )
