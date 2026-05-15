from visit_ice_breaker.models import ShownQuestion
from visit_ice_breaker.question_bank import Question, QuestionBank
from visit_ice_breaker.structures.age_group import AgeGroup


class QuestionTracker:
    @classmethod
    def get_or_select_question(
        cls, note_id: str, patient_id: str, age_group: AgeGroup
    ) -> Question:
        existing: ShownQuestion | None = ShownQuestion.objects.filter(
            note_id=note_id
        ).first()

        if existing is not None:
            result: Question = Question(
                category=existing.category, text=existing.question_text
            )
            return result

        shown_texts: list[str] = cls._get_shown_questions(patient_id)
        question: Question = QuestionBank.get_unused_question(age_group, shown_texts)

        ShownQuestion.objects.create(
            note_id=note_id,
            patient_id=patient_id,
            question_text=question.text,
            category=question.category,
        )

        result = question
        return result

    @classmethod
    def _get_shown_questions(cls, patient_id: str) -> list[str]:
        result: list[str] = list(
            ShownQuestion.objects.filter(patient_id=patient_id).values_list(
                "question_text", flat=True
            )
        )
        return result
