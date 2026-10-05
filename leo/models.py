from typing import Literal

from pydantic import BaseModel, Field


class LessonPlan(BaseModel):
    is_clear: bool = Field(description="False if the request is too vague or not something we can teach")
    clarifying_question: str = Field("", description="What to ask the student when is_clear is false")
    topic: str = ""
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    learning_goals: list[str] = Field(default_factory=list)
    brief_for_explainer: str = ""


class Question(BaseModel):
    id: int
    concept: str = Field(description="The specific concept this question checks")
    kind: Literal["multiple_choice", "short_answer"]
    prompt: str
    options: list[str] = Field(default_factory=list, description="Only for multiple_choice, e.g. ['A) ...', 'B) ...']")
    answer: str = Field(description="The expected answer, hidden from the student")


class Quiz(BaseModel):
    questions: list[Question]


class Grade(BaseModel):
    question_id: int
    concept: str
    verdict: Literal["correct", "partial", "incorrect"]
    score: float = Field(ge=0, le=1)
    feedback: str


class Evaluation(BaseModel):
    grades: list[Grade]
    overall_feedback: str

    @property
    def score(self) -> float:
        if not self.grades:
            return 0.0
        return sum(g.score for g in self.grades) / len(self.grades)

    def weak(self, threshold: float) -> list[Grade]:
        return [g for g in self.grades if g.score < threshold]
