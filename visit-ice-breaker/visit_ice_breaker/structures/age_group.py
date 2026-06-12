from datetime import date
from enum import Enum


KIDS_MAX_AGE: int = 12
TEENS_MAX_AGE: int = 17
ADULTS_MAX_AGE: int = 64


class AgeGroup(Enum):
    KIDS = "Kids"
    TEENS = "Teens"
    ADULTS = "Adults"
    SENIORS = "Seniors"

    @classmethod
    def from_birth_date(cls, birth_date: date, today: date | None = None) -> "AgeGroup":
        reference_date: date = today if today is not None else date.today()
        age: int = (
            reference_date.year
            - birth_date.year
            - int(
                (reference_date.month, reference_date.day)
                < (birth_date.month, birth_date.day)
            )
        )
        if age <= KIDS_MAX_AGE:
            result: AgeGroup = cls.KIDS
        elif age <= TEENS_MAX_AGE:
            result = cls.TEENS
        elif age <= ADULTS_MAX_AGE:
            result = cls.ADULTS
        else:
            result = cls.SENIORS
        return result
