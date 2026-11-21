"""Terminal output: the conversation, a live line of what the learner is saying, and feedback under each turn."""
import sys

from rich.console import Console
from rich.live import Live
from rich.text import Text

from compa.brain import Correction, Feedback, Story
from compa.clozemaster import SaveResult
from compa import cards
from compa.report import ReportCard


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

    def status(self, message: str) -> None:
        self._live.update(Text(message, style="dim"))

    def partial(self, text: str) -> None:
        self._live.update(Text(f"🎙  {text}", style="dim italic"))

    def learner(self, text: str) -> None:
        self._close_compa_line()
        self._live.update(Text(""))
        self.console.print(Text.assemble(("\n🗣  You  ", "bold green"), (text, "green")))

    def compa(self, sentence: str) -> None:
        if not self._compa_line_open:
            self.console.print(Text("\n🤠 Compa", style="bold cyan"))
            self._compa_line_open = True
        self.console.print(Text(f"   {sentence}", style="cyan"))

    def reply_finished(self) -> None:
        self._close_compa_line()

    def interrupted(self) -> None:
        self.console.print(Text("   ✋ (cut off)", style="dim"))
        self._close_compa_line()

    def feedback(self, feedback: Feedback) -> None:
        """English words show straight away so you can use them in your next turn; corrections wait for
        Compa to finish its reply so they don't break it up."""
        for word in feedback.english_words:
            self.console.print(Text.assemble(
                ("   🔤 ", ""), (word.said, "bold magenta"), (" → ", "magenta"), (word.target, "bold magenta"),
                (f"  {word.note}" if word.note else "", "dim magenta")))
        if self._compa_line_open:
            self._held_corrections.extend(feedback.corrections)
        else:
            self._print_corrections(feedback.corrections)

    def _print_corrections(self, corrections: list[Correction]) -> None:
        if not corrections:
            return
        self.console.print(Text("\n   📝 your last turn", style="dim"))
        for correction in corrections:
            icon, style = ("✨", "blue") if correction.upgrade else ("✏️ ", "yellow")
            self.console.print(Text.assemble(
                (f"   {icon} ", ""), (correction.said, f"strike {style}"), (" → ", style),
                (correction.correct, f"bold {style}"), (f"  {correction.why}", f"dim {style}")))

    def saved(self, result: SaveResult) -> None:
        for sentence in result.saved:
            self.console.print(Text(f"   💾 Saved to {result.collection}: {sentence}", style="green"))
        for failure in result.failed:
            self.console.print(Text(f"   💾 Couldn't save to {result.collection}: {failure}", style="red"))

    def briefing_ready(self, stories: list[Story]) -> None:
        self.console.print(Text(f"   📰 {len(stories)} fresh topics ready", style="dim"))

    def report_card(self, card: ReportCard, language_name: str, level: str | None) -> None:
        self.console.print()
        self.console.print(cards.report_card(card, language_name, level))

    def claude_unavailable(self, reason: BaseException) -> None:
        self.console.print(Text(f"\n   ⛔ Claude isn't answering, so the call is over: {reason}", style="bold red"))

    def error(self, error: BaseException) -> None:
        self.console.print(Text(f"   ⚠️  {type(error).__name__}: {error}", style="red"))

    def _close_compa_line(self) -> None:
        self._compa_line_open = False
        held, self._held_corrections = self._held_corrections, []
        self._print_corrections(held)
