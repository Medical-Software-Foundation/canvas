from sleep_screening.scoring.base import InstrumentResult, PatientContext, present

CODE = "SLEEP_ESS"
NAME = "Epworth Sleepiness Scale"
ITEMS = ["SLEEP_ESS_Q" + str(i) for i in range(1, 9)]
ABNORMAL_MIN = 11  # total > 10 flags excessive daytime sleepiness


def score(responses: dict[str, float], context: PatientContext) -> InstrumentResult:
    complete = present(responses, ITEMS)
    total = sum(responses.get(item, 0.0) for item in ITEMS)

    if total >= ABNORMAL_MIN:
        band = "Excessive daytime sleepiness"
        abnormal = True
    else:
        band = "Normal"
        abnormal = False

    narrative = "Epworth total " + str(int(total)) + " (" + band + ")."
    if not complete:
        narrative = narrative + " One or more items unanswered; result is provisional."

    return InstrumentResult(
        code=CODE,
        name=NAME,
        score=float(total),
        band=band,
        abnormal=abnormal,
        narrative=narrative,
        complete=complete,
    )
