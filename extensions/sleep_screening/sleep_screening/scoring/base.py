# NOTE: intentionally NOT using `from __future__ import annotations`. The plugin
# sandbox executes each module without registering it in sys.modules; dataclass
# processing of *string* annotations crashes on that path. Keep annotations as
# real objects.
from dataclasses import dataclass, field
from typing import TYPE_CHECKING


@dataclass(frozen=True)
class PatientContext:
    age: int | None = None
    sex: str | None = None  # normalized to "M" / "F" when known
    bmi: float | None = None

    @property
    def is_male(self) -> bool:
        return (self.sex or "").upper().startswith("M")


@dataclass
class InstrumentResult:
    code: str
    name: str
    score: float | None
    band: str | None
    abnormal: bool
    narrative: str
    complete: bool
    high_risk: bool = False
    subscores: dict[str, float] = field(default_factory=dict)


if TYPE_CHECKING:
    from typing import Protocol

    class Scorer(Protocol):
        code: str
        name: str

        def score(
            self, responses: dict[str, float], context: PatientContext
        ) -> InstrumentResult: ...


def present(responses: dict[str, float], codes: list[str]) -> bool:
    return all(code in responses for code in codes)
