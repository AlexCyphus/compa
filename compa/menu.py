"""Arrow-key pickers in the screens' style: a bold question, a ❯ pointer on the tan option and a key-hint footer."""
import questionary
from prompt_toolkit.filters import IsDone
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, FormattedTextControl, Window
from questionary import Choice, Style

from compa.theme import ACCENT, FAINT, MUTED, TEXT

STYLE = Style([
    ("qmark", ""),
    ("question", f"fg:{TEXT} bold"),
    ("pointer", f"fg:{ACCENT} bold"),
    ("highlighted", f"fg:{ACCENT} bold"),
    ("text", f"fg:{TEXT}"),
    ("answer", f"fg:{MUTED}"),
    ("instruction", ""),
    ("hint", f"fg:{FAINT}"),
])
HINT = "\n  ↑↓ choose · enter select · esc back"
ESCAPED = -1


def pick(question: str, choices: list[tuple[str, object]]) -> object | None:
    """The value of the chosen option, or None on Esc. Ctrl-C raises KeyboardInterrupt. The picker is erased once
    answered."""
    values = [value for _, value in choices]
    # Choices carry their position: questionary swaps a None value for the option's label.
    prompt = questionary.select(question, [Choice(text, index) for index, (text, _) in enumerate(choices)],
                                qmark=" " if question else "", pointer=" ❯", instruction=" ", style=STYLE,
                                erase_when_done=True)
    prompt.application.layout.container.children.append(_hint_footer())
    prompt.application.key_bindings.add(Keys.Escape, eager=True)(_escape)
    answer = prompt.unsafe_ask()
    return None if answer == ESCAPED else values[answer]


def _hint_footer() -> ConditionalContainer:
    return ConditionalContainer(Window(FormattedTextControl([("class:hint", HINT)]), height=2), filter=~IsDone())


def _escape(event) -> None:
    event.app.exit(result=ESCAPED)
