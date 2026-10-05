from contextlib import contextmanager

from crewai.events import BaseEventListener, TaskCompletedEvent, TaskStartedEvent
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from leo.models import Evaluation, Question, Quiz

console = Console()

COLOURS = {
    "Coordinator": "magenta",
    "Explainer": "cyan",
    "Quiz Master": "yellow",
    "Evaluator": "green",
}

DOING = {
    "Coordinator": "is reading your request and planning the session",
    "Explainer": "is writing your lesson",
    "Quiz Master": "is writing practice questions",
    "Evaluator": "is grading your answers",
}

VERDICT_STYLE = {"correct": "green", "partial": "yellow", "incorrect": "red"}


def short_role(role: str) -> str:
    # "Coordinator of the Leo tutoring team" -> "Coordinator"
    return next((name for name in COLOURS if role.startswith(name)), role)


def tag(agent: str) -> str:
    return f"[bold {COLOURS[agent]}]{agent}[/]"


def say(agent: str, text: str):
    console.print(f"{tag(agent)}: {text}")


def show_markdown(agent: str, title: str, text: str):
    console.print(Panel(Markdown(text), title=f"{agent} - {title}", border_style=COLOURS[agent], padding=(1, 2)))


def handoff(source: str, target: str, what: str):
    console.print(f"  {tag(source)} [dim]--{what}-->[/] {tag(target)}")


def ask(prompt: str) -> str:
    while True:
        answer = Prompt.ask(f"[bold]{prompt}[/]").strip()
        if answer:
            return answer


def ask_answer(question_number: int) -> str:
    return Prompt.ask(f"[bold]Your answer to Q{question_number}[/]", default="", show_default=False).strip()


def show_question(number: int, question: Question):
    lines = [f"[bold]Q{number}.[/] {question.prompt}", f"[dim](concept: {question.concept})[/]"]
    lines += [f"   {opt}" for opt in question.options]
    console.print(Panel("\n".join(lines), border_style=COLOURS["Quiz Master"]))


def show_results(quiz: Quiz, answers: list[str], evaluation: Evaluation):
    table = Table(title="Evaluator's marking", border_style=COLOURS["Evaluator"], show_lines=True)
    table.add_column("Q")
    table.add_column("Your answer")
    table.add_column("Result")
    table.add_column("Feedback")
    by_id = {g.question_id: g for g in evaluation.grades}
    for number, (question, answer) in enumerate(zip(quiz.questions, answers), start=1):
        grade = by_id.get(question.id)
        if grade is None:
            continue
        style = VERDICT_STYLE[grade.verdict]
        table.add_row(str(number), answer or "[dim](blank)[/]", f"[{style}]{grade.verdict}[/]", grade.feedback)
    console.print(table)
    say("Evaluator", f"{evaluation.overall_feedback} [bold](score: {evaluation.score:.0%})[/]")


class AgentActivity(BaseEventListener):
    """Updates the spinner and prints a line each time a task finishes, as CrewAI
    moves between agents, so you can see who is working at any moment."""

    def __init__(self):
        super().__init__()
        self.status = None

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(TaskStartedEvent)
        def on_task_started(source, event):
            agent = short_role(event.task.agent.role) if event.task and event.task.agent else None
            if self.status and agent in DOING:
                self.status.update(f"{tag(agent)} {DOING[agent]}...")

        @crewai_event_bus.on(TaskCompletedEvent)
        def on_task_completed(source, event):
            agent = short_role(event.output.agent)
            console.print(f"  [dim]done:[/] {tag(agent)} finished '{event.output.name or 'task'}'")

    @contextmanager
    def watching(self, label: str):
        with console.status(label) as status:
            self.status = status
            try:
                yield
            finally:
                self.status = None


activity = AgentActivity()
