"""Where the learner stands: an approximate CEFR level from past calls, and the mistakes worth a lesson."""
import json
from dataclasses import dataclass
from pathlib import Path

CALLS_FOR_LEVEL = 5
# The report's range score is anchored A2 20, B1 40, B2 60, C1 80, native 100; levels split halfway between.
LEVEL_FLOORS = [(90, "C2"), (70, "C1"), (50, "B2"), (30, "B1"), (10, "A2"), (0, "A1")]


@dataclass(frozen=True)
class Weakness:
    id: str
    pattern: str
    calls: int
    examples: list[str]


def grades(folder: Path, language: str) -> list[dict]:
    path = folder / f"grades-{language}.json"
    return json.loads(path.read_text()) if path.exists() else []


def estimated_level(past_grades: list[dict]) -> str | None:
    """CEFR level from the average range of the last few calls; None before the first call."""
    recent = [grade["range"] for grade in past_grades[-CALLS_FOR_LEVEL:]]
    if not recent:
        return None
    average = sum(recent) / len(recent)
    return next(level for floor, level in LEVEL_FLOORS if average >= floor)


def weaknesses(folder: Path, language: str) -> list[Weakness]:
    """Recurring mistakes, the ones seen in the most calls first."""
    path = folder / f"common-errors-{language}.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    found = [Weakness(pattern_id, entry["pattern"], len(entry["dates"]), entry["examples"][:3])
             for pattern_id, entry in known.items()]
    return sorted(found, key=lambda weakness: -weakness.calls)
