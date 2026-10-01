from sleep_screening.scoring.ess import CODE as ESS_CODE, score as ess_score
from sleep_screening.scoring.isi import CODE as ISI_CODE, score as isi_score
from sleep_screening.scoring.stopbang import CODE as STOPBANG_CODE, score as stopbang_score

SCORERS = {
    STOPBANG_CODE: stopbang_score,
    ESS_CODE: ess_score,
    ISI_CODE: isi_score,
}
QUESTIONNAIRE_CODES = list(SCORERS.keys())


def get_scorer(code: str):
    return SCORERS.get(code)
