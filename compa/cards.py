"""The report card after a call and the progress card: the level first, then a few numbers and words. No paragraphs."""
from rich.console import Group
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from compa.progress import Weakness
from compa.report import ReportCard, Scores
from compa.topics import WORDS_FOR_COVERED, TopicProgress

ACCENT = "#e5a84b"
MUTED = "#6c6c6c"
TRACK = "#3a3a3a"
# Every row lines up on one grid: a label column, a bar column and a value column, WIDTH characters in all.
WIDTH = 60
LABEL_WIDTH = 10
VALUE_WIDTH = 5
GAP = 2
BAR_WIDTH = WIDTH - LABEL_WIDTH - VALUE_WIDTH - 2 * GAP
NAME_WIDTH = 32
MAX_MISTAKES = 3
MAX_WORDS = 3
MAX_TOPICS = 2
TREND_CALLS = 12
SPARK = "▁▂▃▄▅▆▇█"
LEVEL_NAMES = {"A1": "Beginner", "A2": "Elementary", "B1": "Intermediate", "B2": "Upper intermediate",
               "C1": "Advanced", "C2": "Proficient"}


def report_card(card: ReportCard, language_name: str, level: str | None) -> Padding:
    change = None if card.previous_overall is None else card.scores.overall - card.previous_overall
    parts = [_title(language_name, f"{card.minutes_talking:g} min  ·  {card.words_per_minute} wpm"),
             _headline(level, card.scores.overall, change), _score_bars(card.scores)]
    if card.patterns:
        mistakes = [(pattern.pattern, Text(pattern.examples[0] if pattern.examples else "", style=MUTED))
                    for pattern in card.patterns[:MAX_MISTAKES]]
        parts.append(_section("Work on", _pairs(mistakes)))
    if card.english_words:
        words = [(word.said, Text.assemble(("→ ", MUTED), word.target)) for word in card.english_words[:MAX_WORDS]]
        parts.append(_section("Words you reached for", _pairs(words)))
    if card.topics:
        parts.append(_section("Topics", _topic_bars(card.topics[:MAX_TOPICS])))
    return _card(parts)


def progress_card(language_name: str, level: str | None, past_grades: list[dict], mistakes: list[Weakness],
                  topics_covered: int, topics_started: int) -> Padding:
    latest = past_grades[-1]
    change = latest["overall"] - past_grades[-2]["overall"] if len(past_grades) > 1 else None
    calls = len(past_grades)
    parts = [_title(language_name, f"{calls} call{'s' if calls > 1 else ''}"),
             _headline(level, latest["overall"], change),
             _trend([grade["overall"] for grade in past_grades[-TREND_CALLS:]]),
             _score_bars(Scores(latest["accuracy"], latest["range"], latest["fluency"]))]
    if mistakes:
        parts.append(_section("Work on", _pairs([(mistake.pattern, Text("")) for mistake in mistakes[:MAX_MISTAKES]])))
    parts.append(Text(f"{topics_covered} topics covered  ·  {topics_started} started", style=MUTED))
    return _card(parts)


def _card(parts: list) -> Padding:
    spaced = [item for part in parts for item in (part, Text(""))][:-1]
    return Padding(Group(*spaced), (1, 0, 1, 2))


def _title(left: str, right: str) -> Table:
    table = Table.grid()
    table.add_column(width=WIDTH // 2)
    table.add_column(width=WIDTH - WIDTH // 2, justify="right")
    table.add_row(Text(left, style="bold"), Text(right, style=MUTED))
    return table


def _headline(level: str | None, overall: int, change: int | None) -> Table:
    """The level as a badge with its name, the overall grade and its change since last time on the right."""
    table = Table.grid()
    table.add_column(width=WIDTH - 16)
    table.add_column(width=16, justify="right")
    badge = Text.assemble((f" {level} ", f"bold black on {ACCENT}"), (f"  {LEVEL_NAMES[level]}", ACCENT)) if level \
        else Text("")
    grade = Text.assemble(("Grade  ", MUTED), (str(overall), "bold"))
    if change:
        grade.append(f"  {'↑' if change > 0 else '↓'}{abs(change)}", style="green" if change > 0 else "red")
    table.add_row(badge, grade)
    return table


def _trend(overalls: list[int]) -> Table:
    table = _grid(LABEL_WIDTH, BAR_WIDTH)
    table.add_row(Text("Trend", style=MUTED), _sparkline(overalls), Text(""))
    return table


def _score_bars(scores: Scores) -> Table:
    table = _grid(LABEL_WIDTH, BAR_WIDTH)
    for name, value in (("Accuracy", scores.accuracy), ("Range", scores.range), ("Fluency", scores.fluency)):
        table.add_row(Text(name, style=MUTED), _bar(value, BAR_WIDTH), Text(str(value)))
    return table


def _topic_bars(topics: list[TopicProgress]) -> Table:
    bar_width = WIDTH - NAME_WIDTH - VALUE_WIDTH - 2 * GAP
    table = _grid(NAME_WIDTH, bar_width)
    for topic in topics:
        used = min(topic.words_used, WORDS_FOR_COVERED)
        table.add_row(Text(topic.topic[:1].upper() + topic.topic[1:]), _bar(used * 100 // WORDS_FOR_COVERED, bar_width),
                      Text(f"{used}/{WORDS_FOR_COVERED}", style=MUTED))
    return table


def _grid(label_width: int, bar_width: int) -> Table:
    table = Table.grid(padding=(0, 0, 0, GAP))
    table.add_column(width=label_width, no_wrap=True, overflow="ellipsis")
    table.add_column(width=GAP + bar_width)  # a column's width includes its padding
    table.add_column(width=GAP + VALUE_WIDTH, justify="right")
    return table


def _bar(percent: int, width: int) -> Text:
    filled = round(min(percent, 100) / 100 * width)
    return Text.assemble(("━" * filled, ACCENT), ("━" * (width - filled), TRACK))


def _sparkline(overalls: list[int]) -> Text:
    """One spaced block per call, scaled to the calls shown so small changes are visible."""
    low, high = min(overalls), max(overalls)
    steps = [(value - low) * (len(SPARK) - 1) // (high - low) if high > low else len(SPARK) // 2 for value in overalls]
    return Text(" ".join(SPARK[step] for step in steps), style=ACCENT)


def _section(title: str, body: Table) -> Group:
    return Group(Text(title, style=MUTED), body)


def _pairs(rows: list[tuple[str, Text]]) -> Table:
    table = Table.grid(padding=(0, 0, 0, GAP))
    table.add_column(width=NAME_WIDTH, no_wrap=True, overflow="ellipsis")
    table.add_column(width=WIDTH - NAME_WIDTH, no_wrap=True, overflow="ellipsis")
    for left, right in rows:
        table.add_row(Text(left), right)
    return table
