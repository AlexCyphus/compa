"""What the learner has told Compa about their life, kept across calls and languages, so it can follow up like a friend."""
import json
from pathlib import Path

MAX_FACTS = 40


class FriendMemory:
    """about-you.json in the sessions folder: a list of dated facts, e.g. "2026-11-22: Chelsea has an exam on Friday"."""

    def __init__(self, folder: Path):
        self.path = folder / "about-you.json"

    def facts(self) -> list[str]:
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def replace(self, facts: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(facts[-MAX_FACTS:], ensure_ascii=False, indent=2))
