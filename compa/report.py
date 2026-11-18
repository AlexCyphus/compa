"""End-of-call report card: scores, recurring error patterns, English words, phrases to try next time.

Accuracy and fluency are measured from the call; range is judged by Claude against CEFR anchors so the trend means
something. Recurring patterns and past grades live next to the saved calls, one file each per language.
"""
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from compa.brain import EnglishWord, ask_for_json
from compa.call_log import CallLog
from compa.settings import Profile

WEIGHTS = {"accuracy": 0.35, "range": 0.35, "fluency": 0.30}
SLOW_WORDS_PER_MINUTE, FLUENT_WORDS_PER_MINUTE = 50, 130
ENGLISH_WORD_PENALTY, MAX_ENGLISH_PENALTY = 4, 20
ERROR_PENALTY_PER_100_WORDS = 6  # 4 errors per 100 words → 76


@dataclass(frozen=True)
class Scores:
    accuracy: int
    range: int
    fluency: int

    @property
    def overall(self) -> int:
        return round(sum(getattr(self, name) * weight for name, weight in WEIGHTS.items()))


@dataclass(frozen=True)
class Pattern:
    id: str
    pattern: str
    examples: list[str]
    times_seen: int


@dataclass(frozen=True)
class ReportCard:
    scores: Scores
    previous_overall: int | None
    minutes_talking: float
    words_per_minute: int
    patterns: list[Pattern]
    english_words: list[EnglishWord]
    strengths: list[str]
    phrases_to_try: list[str]
    summary: str


def learner_words(log: CallLog) -> int:
    return sum(len(re.findall(r"\w+", turn.learner)) for turn in log.turns)


def measured_scores(log: CallLog, range_score: int) -> Scores:
    words = max(learner_words(log), 1)
    errors = sum(len([c for c in turn.feedback.corrections if not c.upgrade]) for turn in log.turns if turn.feedback)
    english = sum(len(turn.feedback.english_words) for turn in log.turns if turn.feedback)
    accuracy = 100 - ERROR_PENALTY_PER_100_WORDS * errors * 100 / words
    pace = (_words_per_minute(log) - SLOW_WORDS_PER_MINUTE) / (FLUENT_WORDS_PER_MINUTE - SLOW_WORDS_PER_MINUTE) * 100
    fluency = pace - min(english * ENGLISH_WORD_PENALTY, MAX_ENGLISH_PENALTY)
    return Scores(accuracy=_clamp(accuracy), range=_clamp(range_score), fluency=_clamp(fluency))


def _words_per_minute(log: CallLog) -> float:
    seconds = sum(turn.seconds for turn in log.turns)
    return learner_words(log) / seconds * 60 if seconds else 0.0


def _clamp(score: float) -> int:
    return round(min(100, max(0, score)))


class Reporter:
    def __init__(self, profile: Profile):
        self.profile = profile
        folder = profile.sessions_folder
        self.errors_file = folder / f"common-errors-{profile.language}.json"
        self.grades_file = folder / f"grades-{profile.language}.json"

    async def report(self, history: list[tuple[str, str]], log: CallLog) -> ReportCard:
        known = _read(self.errors_file, {})
        judged = await ask_for_json(self.profile.corrector_model, _instructions(self.profile),
                                    _prompt(history, log, known)) or {}
        scores = measured_scores(log, int(judged.get("range", 0)))
        patterns = self._remember_patterns(known, judged.get("patterns", []))
        previous = self._remember_grade(scores)
        return ReportCard(
            scores=scores,
            previous_overall=previous,
            minutes_talking=round(sum(turn.seconds for turn in log.turns) / 60, 1),
            words_per_minute=round(_words_per_minute(log)),
            patterns=patterns,
            english_words=[word for turn in log.turns if turn.feedback for word in turn.feedback.english_words],
            strengths=judged.get("strengths", []),
            phrases_to_try=judged.get("phrases_to_try", []),
            summary=judged.get("summary", ""),
        )

    def _remember_patterns(self, known: dict, found: list[dict]) -> list[Pattern]:
        today = date.today().isoformat()
        patterns = []
        for item in found:
            if not item.get("id") or not item.get("pattern"):
                continue
            entry = known.setdefault(item["id"], {"pattern": item["pattern"], "dates": [], "examples": []})
            entry["dates"].append(today)
            entry["examples"] = (item.get("examples", []) + entry["examples"])[:6]
            patterns.append(Pattern(item["id"], entry["pattern"], item.get("examples", [])[:3], len(entry["dates"])))
        _write(self.errors_file, known)
        return sorted(patterns, key=lambda pattern: -pattern.times_seen)

    def _remember_grade(self, scores: Scores) -> int | None:
        grades = _read(self.grades_file, [])
        previous = grades[-1]["overall"] if grades else None
        grades.append({"date": date.today().isoformat(), "overall": scores.overall, **asdict(scores)})
        _write(self.grades_file, grades)
        return previous


def _instructions(profile: Profile) -> str:
    return f"""You write the end-of-call report for a {profile.native_language} speaker practising \
{profile.language_name} ({profile.variety}) at {profile.level} level on a voice call. Answer with JSON only."""


def _prompt(history: list[tuple[str, str]], log: CallLog, known: dict) -> str:
    conversation = "\n".join(f"{'Learner' if role == 'user' else 'Partner'}: {text}" for role, text in history)
    corrections = [asdict(c) for turn in log.turns if turn.feedback for c in turn.feedback.corrections]
    known_patterns = {pattern_id: entry["pattern"] for pattern_id, entry in known.items()}
    return f"""<conversation>
{conversation}
</conversation>
<corrections_made_during_the_call>
{json.dumps(corrections, ensure_ascii=False)}
</corrections_made_during_the_call>
<patterns_seen_in_earlier_calls>
{json.dumps(known_patterns, ensure_ascii=False)}
</patterns_seen_in_earlier_calls>

Return exactly this JSON shape:
{{"range": <0-100: the range of grammar and vocabulary the learner actually used, CEFR-anchored: A2 20, B1 40, \
B2 60, C1 80, native 100; judge it the same way every call>,
 "patterns": [{{"id": "<stable snake_case id; reuse an id from patterns_seen_in_earlier_calls when it is the \
same kind of mistake>", "pattern": "<short name of the mistake, at most 30 characters>", "examples": ["<corrected \
form>", ...]}}],
 "strengths": ["<something the learner did well>", ...],
 "phrases_to_try": ["<a natural phrase or structure that would have fit what they wanted to say>", ...],
 "summary": "<2 sentences: how the call went and the one thing to focus on next time>"}}
At most 4 patterns (most frequent first, real errors only, not upgrades), 3 strengths and 4 phrases. \
Everything except ids is written in the learner's target language, short and concrete."""


def _read(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2))
