from sleep_screening.scoring.base import InstrumentResult, PatientContext, present

CODE = "SLEEP_ISI"
NAME = "Insomnia Severity Index"
ITEMS = ["SLEEP_ISI_Q" + str(i) for i in range(1, 8)]


def score(responses: dict[str, float], context: PatientContext) -> InstrumentResult:
    complete = present(responses, ITEMS)
    total = sum(responses.get(item, 0.0) for item in ITEMS)

    if total >= 22:
        band = "Severe"
    elif total >= 15:
        band = "Moderate"
    elif total >= 8:
        band = "Subthreshold"
    else:
        band = "None"

    abnormal = total >= 15

    narrative = "ISI total " + str(int(total)) + " (" + band + " insomnia)."
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
