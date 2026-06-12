import random
from typing import NamedTuple

from visit_ice_breaker.structures.age_group import AgeGroup


class Question(NamedTuple):
    category: str
    text: str


class QuestionBank:
    QUESTIONS: dict[AgeGroup, list[Question]] = {
        AgeGroup.KIDS: [
            Question("Fun & Imagination", "If you could be any animal for a day, which one would you pick?"),
            Question("Fun & Imagination", "If you had a superpower, what would it be?"),
            Question("Fun & Imagination", "What is the silliest thing that has ever happened to you?"),
            Question("Fun & Imagination", "If you could build a treehouse anywhere, where would it be?"),
            Question("Food & Cooking", "What is your favorite food in the whole world?"),
            Question("Food & Cooking", "If you could eat only one snack forever, what would it be?"),
            Question("Hobbies & Interests", "What is your favorite game to play?"),
            Question("Hobbies & Interests", "Do you have a pet? If not, what pet would you want?"),
            Question("Entertainment & Media", "What is your favorite cartoon or movie?"),
            Question("Entertainment & Media", "Who is your favorite character from a book or show?"),
            Question("Sports & Outdoors", "What is your favorite thing to do outside?"),
            Question("Sports & Outdoors", "What is the coolest thing you have ever seen in nature?"),
        ],
        AgeGroup.TEENS: [
            Question("Entertainment & Media", "What song have you had on repeat lately?"),
            Question("Entertainment & Media", "Watched any good shows or movies recently?"),
            Question("Entertainment & Media", "What is the last thing that made you laugh really hard?"),
            Question("Hobbies & Interests", "What do you like to do when you have free time?"),
            Question("Hobbies & Interests", "Are you learning anything new right now?"),
            Question("Hobbies & Interests", "If you could start a YouTube channel, what would it be about?"),
            Question("Food & Cooking", "What is your go-to comfort food?"),
            Question("Food & Cooking", "If you could eat dinner anywhere tonight, where would you go?"),
            Question("Sports & Outdoors", "Do you play any sports or follow any teams?"),
            Question("Travel & Adventure", "If you could travel anywhere this summer, where would you go?"),
            Question("Fun & Imagination", "If you could swap lives with anyone for a day, who would it be?"),
            Question("Fun & Imagination", "What is one thing on your bucket list?"),
        ],
        AgeGroup.ADULTS: [
            Question("Travel & Adventure", "What is the best trip you have ever taken?"),
            Question("Travel & Adventure", "Is there a place you have always wanted to visit?"),
            Question("Food & Cooking", "Do you have a favorite recipe you like to make at home?"),
            Question("Food & Cooking", "Tried any new restaurants lately?"),
            Question("Hobbies & Interests", "What do you enjoy doing on weekends?"),
            Question("Hobbies & Interests", "Have you picked up any new hobbies recently?"),
            Question("Entertainment & Media", "Read any good books or watched anything great lately?"),
            Question("Entertainment & Media", "What kind of music do you like to listen to?"),
            Question("Sports & Outdoors", "Do you follow any sports? How is your team doing?"),
            Question("Sports & Outdoors", "Do you enjoy being outdoors? What is your favorite activity?"),
            Question("Food & Cooking", "What is your favorite meal to cook for guests?"),
            Question("Travel & Adventure", "What is the most surprising thing you have seen while traveling?"),
        ],
        AgeGroup.SENIORS: [
            Question("Nostalgia & Memories", "What is your favorite memory from when you were younger?"),
            Question("Nostalgia & Memories", "What is a tradition your family has that you really enjoy?"),
            Question("Nostalgia & Memories", "What is the best piece of advice you have ever received?"),
            Question("Nostalgia & Memories", "What is something that was different when you were growing up?"),
            Question("Food & Cooking", "Do you have a recipe that has been in your family for a long time?"),
            Question("Food & Cooking", "What is your favorite meal to share with family or friends?"),
            Question("Hobbies & Interests", "What do you like to do to relax?"),
            Question("Hobbies & Interests", "Are you working on any projects at home?"),
            Question("Travel & Adventure", "What is the most memorable place you have ever visited?"),
            Question("Entertainment & Media", "Do you enjoy reading or watching anything in particular?"),
            Question("Sports & Outdoors", "Do you enjoy gardening or spending time outdoors?"),
            Question("Sports & Outdoors", "What is your favorite season and why?"),
        ],
    }

    @classmethod
    def get_random_question(cls, age_group: AgeGroup) -> Question:
        questions: list[Question] = cls.QUESTIONS[age_group]
        result: Question = random.choice(questions)
        return result

    @classmethod
    def get_unused_question(
        cls, age_group: AgeGroup, shown_questions: list[str]
    ) -> Question:
        questions: list[Question] = cls.QUESTIONS[age_group]
        available: list[Question] = [
            q for q in questions if q.text not in shown_questions
        ]
        if not available:
            available = questions
        result: Question = random.choice(available)
        return result
