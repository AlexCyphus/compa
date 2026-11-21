"""Arrow-key pickers in the screens' style: a pink // label, a ▸ pointer and the highlighted option in cyan."""
import questionary
from prompt_toolkit.keys import Keys
from questionary import Choice, Style

from compa.theme import CYAN, MUTED, PINK, TEXT

STYLE = Style([
    ("qmark", f"fg:{PINK}"),
    ("question", f"fg:{MUTED}"),
    ("pointer", f"fg:{PINK} bold"),
    ("highlighted", f"fg:{CYAN} bold"),
    ("text", f"fg:{TEXT}"),
    ("answer", f"fg:{MUTED}"),
    ("instruction", ""),
])
ESCAPED = -1


def pick(question: str, choices: list[tuple[str, object]]) -> object | None:
    """The value of the chosen option, or None on Esc. Ctrl-C raises KeyboardInterrupt. The picker is erased once
    answered."""
    values = [value for _, value in choices]
    # Choices carry their position: questionary swaps a None value for the option's label.
    prompt = questionary.select(question.upper(), [Choice(text, index) for index, (text, _) in enumerate(choices)],
                                qmark="  //" if question else "", pointer="  ▸", instruction=" ", style=STYLE, erase_when_done=True)
    prompt.application.key_bindings.add(Keys.Escape, eager=True)(_escape)
    answer = prompt.unsafe_ask()
    return None if answer == ESCAPED else values[answer]


def _escape(event) -> None:
    event.app.exit(result=ESCAPED)
