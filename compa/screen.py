"""Terminal output: the conversation, a live line of what the learner is saying, and feedback under each turn."""
import sys

from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
from rich.text import Text

from compa.brain import Correction, Feedback, Story
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

    def briefing_ready(self, stories: list[Story]) -> None:
        self.console.print(Text(f"   📰 {len(stories)} fresh topics ready", style="dim"))

    def report_card(self, card: ReportCard) -> None:
        self.console.print(Panel(report_card_text(card), title="🤠 Report card", border_style="cyan", padding=(1, 2)))

    def error(self, error: BaseException) -> None:
        self.console.print(Text(f"   ⚠️  {type(error).__name__}: {error}", style="red"))

    def _close_compa_line(self) -> None:
        self._compa_line_open = False
        held, self._held_corrections = self._held_corrections, []
        self._print_corrections(held)


def report_card_text(card: ReportCard) -> Group:
    """The report card as printed after hanging up."""
    scores = card.scores
    change = "" if card.previous_overall is None else f"  ({scores.overall - card.previous_overall:+d} since last call)"
    lines: list = [
        Text.assemble(("Grade ", "bold"), (f"{scores.overall}%", "bold green"), (change, "dim")),
        Text(f"Accuracy {scores.accuracy} · Range {scores.range} · Fluency {scores.fluency}   "
             f"{card.minutes_talking} min talking · {card.words_per_minute} words/min", style="dim"),
    ]
    if card.summary:
        lines += [Text(""), Text(card.summary)]
    if card.patterns:
        lines += [Text(""), Text("Common errors", style="bold yellow")]
        lines += [Text.assemble((f"  • {p.pattern}", "yellow"), (f"  ×{p.times_seen}" if p.times_seen > 1 else "", "bold red"),
                                (f"  {' · '.join(p.examples)}", "dim")) for p in card.patterns]
    if card.english_words:
        lines += [Text(""), Text("Words you said in English", style="bold magenta")]
        lines += [Text(f"  • {w.said} → {w.target}", style="magenta") for w in card.english_words]
    if card.phrases_to_try:
        lines += [Text(""), Text("Try next time", style="bold blue")]
        lines += [Text(f"  • {phrase}", style="blue") for phrase in card.phrases_to_try]
    if card.strengths:
        lines += [Text(""), Text("Went well", style="bold green")]
        lines += [Text(f"  • {strength}", style="green") for strength in card.strengths]
    return Group(*lines)
