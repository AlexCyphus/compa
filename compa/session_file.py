"""Saves each call as a Markdown file: the conversation, then every correction and English word to review."""
from datetime import datetime
from pathlib import Path

from compa.brain import Feedback
from compa.call_log import CallLog
from compa.report import ReportCard


def save_call(folder: Path, language: str, history: list[tuple[str, str]], log: CallLog,
              card: ReportCard | None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = _free_path(folder, f"{datetime.now():%Y-%m-%d %H%M} {language}")
    feedbacks = [turn.feedback for turn in log.turns if turn.feedback is not None]
    path.write_text((_report_card(card) if card else "") + _conversation(history) + _review(feedbacks))
    return path


def _report_card(card: ReportCard) -> str:
    scores = card.scores
    change = "" if card.previous_overall is None else f" ({scores.overall - card.previous_overall:+d} since last call)"
    lines = [f"# Report card: {scores.overall}%{change}", "",
             f"Accuracy {scores.accuracy} · Range {scores.range} · Fluency {scores.fluency} · "
             f"{card.minutes_talking} min talking · {card.words_per_minute} words/min", "", card.summary, ""]
    sections = [("Common errors", [f"{p.pattern} (×{p.times_seen}): {' · '.join(p.examples)}" for p in card.patterns]),
                ("Try next time", card.phrases_to_try), ("Went well", card.strengths)]
    for title, items in sections:
        if items:
            lines += [f"## {title}", ""] + [f"- {item}" for item in items] + [""]
    return "\n".join(lines) + "\n"


def _free_path(folder: Path, stem: str) -> Path:
    path, copy = folder / f"{stem}.md", 2
    while path.exists():
        path, copy = folder / f"{stem}-{copy}.md", copy + 1
    return path


def _conversation(history: list[tuple[str, str]]) -> str:
    lines = [f"**{'You' if role == 'user' else 'Compa'}:** {text}" for role, text in history]
    return "# Conversation\n\n" + "\n\n".join(lines) + "\n"


def _review(feedbacks: list[Feedback]) -> str:
    words = [f"- **{w.said}** → **{w.target}** {w.note}".rstrip() for f in feedbacks for w in f.english_words]
    fixes = [f"- ~~{c.said}~~ → **{c.correct}** · {c.why}" for f in feedbacks for c in f.corrections if not c.upgrade]
    upgrades = [f"- {c.said} → **{c.correct}** · {c.why}" for f in feedbacks for c in f.corrections if c.upgrade]
    sections = [("Words you said in English", words), ("Corrections", fixes), ("More natural", upgrades)]
    return "".join(f"\n## {title}\n\n" + "\n".join(items) + "\n" for title, items in sections if items)
