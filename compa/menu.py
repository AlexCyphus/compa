"""Arrow-key pickers, styled like the cards: one accent colour, lined up with the cards' left edge."""
import questionary
from prompt_toolkit.keys import Keys
from questionary import Choice, Style

from compa.cards import ACCENT, MUTED

STYLE = Style([
    ("qmark", f"fg:{ACCENT}"),
    ("question", "bold"),
    ("pointer", f"fg:{ACCENT} bold"),
    ("highlighted", f"fg:{ACCENT}"),
    ("answer", f"fg:{MUTED}"),
    ("instruction", ""),
])


def pick(question: str, choices: list[tuple[str, object]]) -> object | None:
    """The value of the chosen option; None on Esc or Ctrl-C."""
    prompt = questionary.select(question, [Choice(label, value) for label, value in choices], qmark="  ◆",
                                pointer=" ›", instruction=" ", style=STYLE)
    prompt.application.key_bindings.add(Keys.Escape, eager=True)(_cancel)
    try:
        return prompt.unsafe_ask()
    except KeyboardInterrupt:
        return None


def _cancel(event) -> None:
    event.app.exit(exception=KeyboardInterrupt, style="class:aborting")
