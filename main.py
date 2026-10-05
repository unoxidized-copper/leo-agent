import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# CrewAI asks about cloud tracing at the end of a run otherwise
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
# provider errors are reported by the Coordinator instead of raw log spam
logging.disable(logging.ERROR)

from leo import ui  # noqa: E402
from leo.crew import TutorCrews  # noqa: E402
from leo.memory import StudentMemory  # noqa: E402
from leo.session import TutorSession  # noqa: E402


def main():
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set - copy .env.example to .env and add your key.")

    timeout = int(os.getenv("LEO_STEP_TIMEOUT", "120"))
    max_rpm = int(os.getenv("LEO_MAX_RPM", "4"))
    try:
        crews = TutorCrews(os.getenv("LEO_MODEL", "gemini/gemini-3.5-flash-lite"), timeout, max_rpm)
        backup_model = os.getenv("LEO_BACKUP_MODEL", "gemini/gemini-3.1-flash-lite")
        backup = TutorCrews(backup_model, timeout, max_rpm) if backup_model else None
    except ImportError as exc:
        # CrewAI raises this for a model name it doesn't recognise
        sys.exit(f"Can't use the configured model - check LEO_MODEL / LEO_BACKUP_MODEL in .env.\n{str(exc).splitlines()[0]}")
    memory = StudentMemory(Path(os.getenv("LEO_MEMORY_FILE", "student_memory.json")))

    try:
        TutorSession(crews, backup, memory).start()
    except (KeyboardInterrupt, EOFError):
        ui.console.print("\n[dim]Session ended. See you next time![/]")


if __name__ == "__main__":
    main()
