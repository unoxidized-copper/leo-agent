import json
from datetime import date
from pathlib import Path


class StudentMemory:
    """Long-term memory: who the student is and what they've studied with Leo.

    Stored as a small JSON file keyed by student name, so a returning student
    picks up where they left off (and the Coordinator knows their weak spots).
    """

    def __init__(self, path: Path):
        self.path = path
        self._data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def known_name(self, student: str) -> str:
        """The name as the student first typed it, so "sam" is still greeted as "Sam"."""
        return self._data.get(student.lower(), {}).get("name", student)

    def sessions(self, student: str) -> list[dict]:
        return self._data.get(student.lower(), {}).get("sessions", [])

    def summary(self, student: str) -> str:
        sessions = self.sessions(student)
        if not sessions:
            return "New student, no previous sessions."
        lines = []
        for s in sessions[-5:]:
            weak = ", ".join(s["weak_concepts"]) or "nothing"
            lines.append(f"- {s['date']}: {s['topic']} ({s['level']}), final score {s['score']:.0%}, still weak on: {weak}")
        return "Previous sessions:\n" + "\n".join(lines)

    def record(self, student: str, topic: str, level: str, score: float, weak_concepts: list[str]):
        entry = self._data.setdefault(student.lower(), {"name": student, "sessions": []})
        entry["sessions"].append({
            "date": date.today().isoformat(),
            "topic": topic,
            "level": level,
            "score": round(score, 2),
            "weak_concepts": weak_concepts,
        })
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
