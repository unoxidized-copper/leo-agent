from pathlib import Path

import yaml
from crewai import LLM, Agent, Crew, Process, Task

from leo.models import Evaluation, LessonPlan, Quiz

CONFIG_DIR = Path(__file__).parent / "config"


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


AGENTS = _load_yaml("agents.yaml")
TASKS = _load_yaml("tasks.yaml")


class TutorCrews:
    """Builds the small sequential crews Leo runs at each stage of a session.

    Every agent and task takes its prompt from config/*.yaml, so each role's
    prompt template lives in one place and the code only wires them together.
    """

    def __init__(self, model: str, step_timeout: int, max_rpm: int):
        self.llm = LLM(model=model, temperature=0.4)
        self.step_timeout = step_timeout
        self.max_rpm = max_rpm

    def _agent(self, key: str) -> Agent:
        return Agent(
            **AGENTS[key],
            llm=self.llm,
            allow_delegation=False,
            max_execution_time=self.step_timeout,
            max_retry_limit=1,
            verbose=False,
        )

    def _task(self, key: str, agent: Agent, **extra) -> Task:
        return Task(**TASKS[key], name=key.replace("_", " "), agent=agent, **extra)

    def _crew(self, agents: list[Agent], tasks: list[Task]) -> Crew:
        # max_rpm keeps us under the Gemini free tier's per-minute request limit
        return Crew(agents=agents, tasks=tasks, process=Process.sequential, max_rpm=self.max_rpm, verbose=False)

    def planning(self) -> Crew:
        coordinator = self._agent("coordinator")
        plan = self._task("plan_lesson", coordinator, output_pydantic=LessonPlan)
        return self._crew([coordinator], [plan])

    def lesson(self) -> Crew:
        # Explainer -> Quiz Master: the quiz task gets the lesson as context,
        # so the questions are written from what was actually taught.
        explainer, quiz_master = self._agent("explainer"), self._agent("quiz_master")
        explain = self._task("explain_topic", explainer)
        quiz = self._task("create_quiz", quiz_master, context=[explain], output_pydantic=Quiz)
        return self._crew([explainer, quiz_master], [explain, quiz])

    def evaluation(self) -> Crew:
        evaluator = self._agent("evaluator")
        grade = self._task("evaluate_answers", evaluator, output_pydantic=Evaluation)
        return self._crew([evaluator], [grade])

    def reteach(self) -> Crew:
        explainer, quiz_master = self._agent("explainer"), self._agent("quiz_master")
        explain = self._task("reteach_topic", explainer)
        quiz = self._task("create_retry_quiz", quiz_master, context=[explain], output_pydantic=Quiz)
        return self._crew([explainer, quiz_master], [explain, quiz])
