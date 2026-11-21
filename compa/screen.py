"""Terminal output: the conversation, a live line of what the learner is saying, and feedback under each turn."""
import sys

from rich.console import Console
from rich.live import Live
from rich.status import Status
from rich.table import Table
from rich.text import Text

from compa.brain import Correction, Feedback, Story
from compa.clozemaster import SaveResult
from compa import cards
from compa.report import ReportCard
from compa.theme import CYAN, FAINT, INDENT, MINT, MUTED, PINK, PURPLE, TEXT, indented, section, show_screen

SPEAKER_WIDTH = 5


class Screen:
    def __init__(self, console: Console | None = None):
        self.console = console or Console(file=sys.stdout, highlight=False)  # fixed, so stdout redirects elsewhere can't swallow it
        self._live = Live(Text(""), console=self.console, transient=True, refresh_per_second=12)
        self._compa_line_open = False
        self._held_corrections: list[Correction] = []

    def __enter__(self) -> "Screen":
        self._live.start()
        return self

    def __exit__(self, *_) -> None:
        self._live.stop()

    def call_header(self, context: str, focus: Text, account: str) -> None:
        """A clean screen for the call: the header, what the call is about and, quietly, which Claude plan pays."""
        show_screen(self.console, context)
        self.console.print(indented(focus))
        self.console.print(indented(Text.assemble(("CLAUDE  ", FAINT), (account, FAINT))))

    def status(self, message: str) -> None:
        self._live.update(indented(Text(message, style=MUTED)))

    def partial(self, text: str) -> None:
        self._live.update(_row(Text("●", style=PINK), Text(text, style=f"italic {MUTED}")))

    def learner(self, text: str) -> None:
        self._close_compa_line()
        self._live.update(Text(""))
        self.console.print()
        self.console.print(_row(Text("YOU", style=f"bold {PINK}"), Text(text, style=TEXT)))

    def compa(self, sentence: str) -> None:
        speaker = Text("" if self._compa_line_open else "COMPA", style=f"bold {CYAN}")
        if not self._compa_line_open:
            self.console.print()
            self._compa_line_open = True
        self.console.print(_row(speaker, Text(sentence, style=TEXT)))

    def reply_finished(self) -> None:
        self._close_compa_line()

    def interrupted(self) -> None:
        self.console.print(_row(Text(""), Text("(cut off)", style=MUTED)))
        self._close_compa_line()

    def feedback(self, feedback: Feedback) -> None:
        """English words show straight away so you can use them in your next turn; corrections wait for
        Compa to finish its reply so they don't break it up."""
        for word in feedback.english_words:
            self.console.print(_row(Text("EN", style=PURPLE), Text.assemble(
                (word.said, MUTED), (" → ", PURPLE), (word.target, f"bold {CYAN}"),
                (f"  {word.note}" if word.note else "", MUTED))))
        if self._compa_line_open:
            self._held_corrections.extend(feedback.corrections)
        else:
            self._print_corrections(feedback.corrections)

    def _print_corrections(self, corrections: list[Correction]) -> None:
        if not corrections:
            return
        self.console.print()
        self.console.print(_row(Text(""), section("Your last turn")))
        for correction in corrections:
            mark, color = ("✦", PURPLE) if correction.upgrade else ("✗", PINK)
            self.console.print(_row(Text(""), Text.assemble(
                (f"{mark} ", color), (correction.said, f"strike {MUTED}"), (" → ", color),
                (correction.correct, f"bold {MINT if not correction.upgrade else CYAN}"), (f"  {correction.why}", MUTED))))

    def saved(self, result: SaveResult) -> None:
        for sentence in result.saved:
            self.console.print(_row(Text(""), Text(f"✓ Saved to {result.collection}: {sentence}", style=MINT)))
        for failure in result.failed:
            self.console.print(_row(Text(""), Text(f"✕ Couldn't save to {result.collection}: {failure}", style=PINK)))

    def briefing_ready(self, stories: list[Story]) -> None:
        self.console.print(indented(Text(f"▸ {len(stories)} fresh topics ready", style=FAINT)))

    def writing_report(self, context: str) -> Status:
        """A clean screen with a spinner while the report card is written."""
        show_screen(self.console, context)
        return self.console.status(Text("Writing your report card  //  Ctrl-C to skip", style=MUTED), spinner_style=PINK)

    def report_card(self, card: ReportCard, context: str, level: str | None) -> None:
        show_screen(self.console, context)
        self.console.print(cards.report_card(card, level))

    def claude_unavailable(self, reason: BaseException) -> None:
        self.console.print()
        self.console.print(indented(Text(f"✕ Claude isn't answering, so the call is over: {reason}", style=f"bold {PINK}")))

    def error(self, error: BaseException) -> None:
        self.console.print(indented(Text(f"! {type(error).__name__}: {error}", style=PINK)))

    def _close_compa_line(self) -> None:
        self._compa_line_open = False
        held, self._held_corrections = self._held_corrections, []
        self._print_corrections(held)


def _row(speaker: Text, body: Text) -> Table:
    """A line of the call: who is speaking in a narrow column, the words wrapping in their own column beside it."""
    table = Table.grid(padding=(0, 0, 0, len(INDENT)), pad_edge=True)
    table.add_column(width=len(INDENT) + SPEAKER_WIDTH)  # a column's width includes its padding
    table.add_column()
    table.add_row(speaker, body)
    return table
