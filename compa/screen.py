"""Terminal output: the conversation, a live line of what the learner is saying, and feedback under each turn."""
import sys
import time

from rich.console import Console, Group
from rich.live import Live
from rich.status import Status
from rich.table import Table
from rich.text import Text

from compa.brain import Correction, Feedback, Story
from compa.clozemaster import SaveResult
from compa import cards
from compa.report import ReportCard
from compa.theme import ACCENT, BAD, FAINT, GOOD, INDENT, MUTED, SOFT, TEXT, indented, show_screen

SPEAKER_WIDTH = 3


class Screen:
    def __init__(self, console: Console | None = None):
        self.console = console or Console(file=sys.stdout, highlight=False)  # fixed, so stdout redirects elsewhere can't swallow it
        self._live_line = _LiveLine()
        self._live = Live(self._live_line, console=self.console, transient=True, refresh_per_second=12)
        self._compa_line_open = False
        self._held_corrections: list[Correction] = []

    def __enter__(self) -> "Screen":
        self._live.start()
        return self

    def __exit__(self, *_) -> None:
        self._live.stop()

    def call_header(self, context: str, focus: Text, account: str) -> None:
        """A clean screen for the call: the header with what the call is about and, quietly, which Claude plan pays."""
        show_screen(self.console, context, focus, f"Claude: {account}")
        self._live_line.call_started_at = time.monotonic()

    def status(self, message: str) -> None:
        self._live_line.show(indented(Text(message, style=MUTED)))

    def partial(self, text: str) -> None:
        self._live_line.show(Group(Text(""), _row(Text("you", style=MUTED), Text(f"{text}…", style=f"italic {MUTED}"))))

    def learner(self, text: str) -> None:
        self._close_compa_line()
        self._live_line.show(Text(""))
        self.console.print()
        self.console.print(_row(Text("you", style=MUTED), Text(text, style=SOFT)))

    def compa(self, sentence: str) -> None:
        speaker = Text("" if self._compa_line_open else "🤠")
        if not self._compa_line_open:
            self.console.print()
            self._compa_line_open = True
        self.console.print(_row(speaker, Text(sentence, style=TEXT)))

    def reply_finished(self) -> None:
        self._close_compa_line()

    def interrupted(self) -> None:
        self.console.print(_row(Text(""), Text("(cut off)", style=FAINT)))
        self._close_compa_line()

    def feedback(self, feedback: Feedback) -> None:
        """English words show straight away so you can use them in your next turn; corrections wait for
        Compa to finish its reply so they don't break it up."""
        for word in feedback.english_words:
            self.console.print(_row(Text(""), _marked(Text("↳", style=MUTED), Text.assemble(
                (word.said, MUTED), (" → ", FAINT), (word.target, f"bold {ACCENT}"),
                (f"  {word.note}" if word.note else "", FAINT)))))
        if self._compa_line_open:
            self._held_corrections.extend(feedback.corrections)
        else:
            self._print_corrections(feedback.corrections)

    def _print_corrections(self, corrections: list[Correction]) -> None:
        if not corrections:
            return
        self.console.print()
        for correction in corrections:
            mark, color = ("✦", ACCENT) if correction.upgrade else ("✗", BAD)
            self.console.print(_row(Text(""), _marked(Text(mark, style=color), Text.assemble(
                (correction.said, f"strike {MUTED}"), (" → ", FAINT), (correction.correct, f"bold {GOOD}"),
                ("\n", ""), (correction.why, FAINT)))))

    def saved(self, result: SaveResult) -> None:
        for sentence in result.saved:
            self.console.print(_row(Text(""), Text(f"✓ Saved to {result.collection}: {sentence}", style=GOOD)))
        for failure in result.failed:
            self.console.print(_row(Text(""), Text(f"✗ Couldn't save to {result.collection}: {failure}", style=BAD)))

    def briefing_ready(self, stories: list[Story]) -> None:
        self.console.print(indented(Text(f"· {len(stories)} fresh topics ready", style=FAINT)))

    def writing_report(self, context: str) -> Status:
        """A clean screen with a spinner while the report card is written."""
        show_screen(self.console, context, "Hang tight, I'm writing your report card.")
        return self.console.status(Text("Writing your report card · ctrl-c to skip", style=MUTED), spinner_style=ACCENT)

    def report_card(self, card: ReportCard, context: str, level: str | None) -> None:
        show_screen(self.console, context, "Good talk! Here's how it went.")
        self.console.print(cards.report_card(card, level))

    def claude_unavailable(self, reason: BaseException) -> None:
        self.console.print()
        self.console.print(indented(Text(f"✗ Claude isn't answering, so the call is over: {reason}", style=f"bold {BAD}")))

    def error(self, error: BaseException) -> None:
        self.console.print(indented(Text(f"! {type(error).__name__}: {error}", style=BAD)))

    def _close_compa_line(self) -> None:
        self._compa_line_open = False
        held, self._held_corrections = self._held_corrections, []
        self._print_corrections(held)


class _LiveLine:
    """The bottom of the call screen, redrawn on every refresh: what's being said right now, then the call timer."""

    def __init__(self):
        self.call_started_at: float | None = None
        self._current = Text("")

    def show(self, renderable) -> None:
        self._current = renderable

    def __rich__(self) -> Group:
        if self.call_started_at is None:
            return Group(self._current)
        minutes, seconds = divmod(int(time.monotonic() - self.call_started_at), 60)
        footer = Text.assemble((f"{minutes:02d}:{seconds:02d}", MUTED), (" · ", FAINT), ("ctrl-c", MUTED),
                               (" to hang up", FAINT))
        return Group(self._current, indented(footer, top=1))


def _marked(mark: Text, body: Text) -> Table:
    """A feedback line under your turn: a one-character mark, the text wrapping beside it rather than under it."""
    table = Table.grid(padding=(0, 0, 0, 0))
    table.add_column(width=2)
    table.add_column()
    table.add_row(mark, body)
    return table


def _row(speaker: Text, body) -> Table:
    """A line of the call: who is speaking in a narrow column, the words wrapping in their own column beside it."""
    table = Table.grid(padding=(0, 0, 0, len(INDENT)), pad_edge=True)
    table.add_column(width=len(INDENT) + SPEAKER_WIDTH)  # a column's width includes its padding
    table.add_column()
    table.add_row(speaker, body)
    return table
