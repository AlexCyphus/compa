"""Settings from settings.json at the repo root: shared keys merged with one language profile."""
import json
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Profile:
    learner_name: str
    native_language: str
    sessions_folder: Path
    claude_config_dir: Path
    talker_model: str
    corrector_model: str
    language: str
    language_name: str
    variety: str
    level: str
    voice: str
    news_from: str
    whisper_prompt: str


def profile_names() -> list[str]:
    return list(_read()["languages"])


def load_profile(name: str | None = None) -> Profile:
    """The named profile, else the first one in settings.json."""
    settings = _read()
    profiles = settings.pop("languages")
    chosen = profiles[name or next(iter(profiles))]
    merged = {**settings, **chosen}
    merged["sessions_folder"] = Path(merged["sessions_folder"]).expanduser()
    merged["claude_config_dir"] = Path(merged["claude_config_dir"]).expanduser()
    return Profile(**merged)


def _read() -> dict:
    return json.loads((REPO / "settings.json").read_text())
