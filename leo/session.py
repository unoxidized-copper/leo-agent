import time

from rich.prompt import Confirm

from leo import ui
from leo.crew import TutorCrews
from leo.memory import StudentMemory
from leo.models import Evaluation, LessonPlan, Quiz

QUESTIONS_PER_QUIZ = 3
PASS_MARK = 0.7          # anything below this goes back to the Explainer
MAX_RETEACH_ROUNDS = 2
MAX_CLARIFICATIONS = 3
RETRY_WAIT_SECONDS = 20


class StageFailed(Exception):
    pass


class TutorSession:
    """The Coordinator's side of a session: decides who works next, passes each
    agent's output to the next one, and deals with vague requests and agents
    that stall or return junk."""

    def __init__(self, crews: TutorCrews, backup_crews: TutorCrews | None, memory: StudentMemory, attempts: int = 3):
        self.crews = crews
        self.backup_crews = backup_crews
        self.memory = memory
        self.attempts = attempts

    def start(self):
        ui.console.rule("[bold]Leo - your multi-agent tutor")
        name = self.memory.known_name(ui.ask("Hi! What's your name?"))
        history = self.memory.summary(name)
        if self.memory.sessions(name):
            last = self.memory.sessions(name)[-1]
            ui.say("Coordinator", f"Welcome back, {name}. Last time we did [bold]{last['topic']}[/] ({last['score']:.0%}).")
        else:
            ui.say("Coordinator", f"Nice to meet you, {name}.")

        try:
            plan = self.plan(name, history)
            if plan is None:
                return
            quiz = self.teach(name, plan)
            evaluation = self.quiz_loop(plan, quiz)
        except StageFailed as exc:
            ui.say("Coordinator", f"Sorry, I couldn't get the team to finish this session ({exc}). Please try again in a minute.")
            return

        weak = [g.concept for g in evaluation.weak(PASS_MARK)]
        self.memory.record(name, plan.topic, plan.level, evaluation.score, weak)
        if weak:
            ui.say("Coordinator", f"Good effort, {name}. I've noted what still needs practice ({', '.join(weak)}) and we'll start there next time.")
        else:
            ui.say("Coordinator", f"Well done, {name} - you've got {plan.topic}. I've saved your progress.")

    def plan(self, name: str, history: str) -> LessonPlan | None:
        request = ui.ask("What would you like to learn today?")
        for _ in range(MAX_CLARIFICATIONS):
            plan = self._run("planning", LessonPlan, student_name=name, student_history=history, request=request).pydantic
            if plan.is_clear and plan.topic:
                goals = "\n".join(f"  - {goal}" for goal in plan.learning_goals)
                ui.say("Coordinator", f"Plan: [bold]{plan.topic}[/] at {plan.level} level.\n{goals}")
                return plan
            ui.say("Coordinator", plan.clarifying_question or "Could you be a bit more specific?")
            request = f"{request}\n(The student clarified: {ui.ask('You')})"
        ui.say("Coordinator", "I still couldn't pin down a topic, so let's stop here. Run Leo again whenever you're ready.")
        return None

    def teach(self, name: str, plan: LessonPlan) -> Quiz:
        ui.handoff("Coordinator", "Explainer", "lesson plan")
        result = self._run(
            "lesson",
            Quiz,
            student_name=name,
            topic=plan.topic,
            level=plan.level,
            learning_goals="\n".join(f"- {goal}" for goal in plan.learning_goals),
            brief=plan.brief_for_explainer,
            num_questions=QUESTIONS_PER_QUIZ,
        )
        ui.show_markdown("Explainer", plan.topic, result.tasks_output[0].raw)
        ui.handoff("Explainer", "Quiz Master", "lesson")
        return result.pydantic

    def quiz_loop(self, plan: LessonPlan, quiz: Quiz) -> Evaluation:
        for round_number in range(MAX_RETEACH_ROUNDS + 1):
            answers = self.take_quiz(quiz)
            ui.handoff("Quiz Master", "Evaluator", "questions, answer key and your answers")
            evaluation = self.evaluate(plan, quiz, answers)
            ui.show_results(quiz, answers, evaluation)

            weak = evaluation.weak(PASS_MARK)
            if not weak:
                return evaluation
            if round_number == MAX_RETEACH_ROUNDS:
                ui.say("Coordinator", "We've gone over these a few times now, so let's wrap up and pick them up next session.")
                return evaluation

            concepts = ", ".join(g.concept for g in weak)
            ui.say("Coordinator", f"The Evaluator flagged {len(weak)} weak answer(s): [bold]{concepts}[/].")
            if not Confirm.ask("Send these back to the Explainer for another go?", default=True):
                return evaluation
            ui.handoff("Evaluator", "Explainer", "weak answers + feedback")
            quiz = self.reteach(plan, quiz, answers, evaluation)
        return evaluation

    def take_quiz(self, quiz: Quiz) -> list[str]:
        ui.say("Quiz Master", "Your turn - answer each question (leave blank if you don't know).")
        answers = []
        for number, question in enumerate(quiz.questions, start=1):
            ui.show_question(number, question)
            answers.append(ui.ask_answer(number))
        return answers

    def evaluate(self, plan: LessonPlan, quiz: Quiz, answers: list[str]) -> Evaluation:
        blocks = []
        for question, answer in zip(quiz.questions, answers):
            block = f"Question id {question.id} (concept: {question.concept})\nQuestion: {question.prompt}\n"
            if question.options:
                block += f"Options: {' | '.join(question.options)}\n"
            block += f"Answer key: {question.answer}\nStudent's answer: {answer or '(left blank)'}"
            blocks.append(block)

        def graded_everything(evaluation: Evaluation) -> bool:
            return {g.question_id for g in evaluation.grades} == {q.id for q in quiz.questions}

        result = self._run("evaluation", Evaluation, check=graded_everything, topic=plan.topic, submission="\n\n".join(blocks))
        return result.pydantic

    def reteach(self, plan: LessonPlan, quiz: Quiz, answers: list[str], evaluation: Evaluation) -> Quiz:
        answered = {q.id: (q, a) for q, a in zip(quiz.questions, answers)}
        weak = evaluation.weak(PASS_MARK)
        blocks = []
        for grade in weak:
            question, answer = answered[grade.question_id]
            blocks.append(
                f"Concept: {grade.concept}\n"
                f"Question: {question.prompt}\n"
                f"Correct answer: {question.answer}\n"
                f"Student answered: {answer or '(left blank)'}\n"
                f"Evaluator's feedback: {grade.feedback}"
            )
        result = self._run(
            "reteach",
            Quiz,
            topic=plan.topic,
            level=plan.level,
            weak_points="\n\n".join(blocks),
            num_questions=len(weak),
        )
        ui.show_markdown("Explainer", "let's try that again", result.tasks_output[0].raw)
        ui.handoff("Explainer", "Quiz Master", "re-taught concepts")
        return result.pydantic

    def _run(self, stage: str, expected: type, check=None, **inputs):
        """Kick off one stage's crew and make sure it returned a usable `expected`
        object. If an agent errors out, times out or hands back junk, retry -
        the last attempt goes to the backup model, if one is configured."""
        last_error = None
        for attempt in range(1, self.attempts + 1):
            use_backup = attempt == self.attempts and self.backup_crews is not None
            crews = self.backup_crews if use_backup else self.crews
            try:
                with ui.activity.watching("Working..."):
                    result = getattr(crews, stage)().kickoff(inputs=inputs)
                if not isinstance(result.pydantic, expected):
                    raise ValueError(f"expected a {expected.__name__} but got unstructured output")
                if check and not check(result.pydantic):
                    raise ValueError(f"the {expected.__name__} was incomplete")
                return result
            except Exception as exc:
                last_error = exc
                if attempt < self.attempts:
                    wait = RETRY_WAIT_SECONDS * attempt
                    fallback = " on the backup model" if attempt + 1 == self.attempts and self.backup_crews else ""
                    ui.say("Coordinator", f"[red]The {stage} step stalled[/] ({describe_error(exc)}). Retrying{fallback} in {wait}s...")
                    time.sleep(wait)
        raise StageFailed(f"the {stage} step kept failing: {describe_error(last_error)}")


def describe_error(exc: Exception) -> str:
    text = str(exc)
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "hit the API rate limit"
    if "503" in text or "UNAVAILABLE" in text:
        return "the model is overloaded"
    if "timed out" in text:
        return "took too long"
    return text.split("{")[0].strip()[:100] or type(exc).__name__
