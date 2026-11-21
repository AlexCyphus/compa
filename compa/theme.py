"""The look shared by every screen: a synthwave palette on dark, gradient bars and the COMPA wordmark."""
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

PINK = "#ff71ce"
CYAN = "#01cdfe"
PURPLE = "#b967ff"
MINT = "#05ffa1"
TEXT = "#e8e4f4"
MUTED = "#8b85a8"
FAINT = "#4a4560"
TRACK = "#2b2640"
INK = "#1a1626"
GRADIENT = [PINK, PURPLE, CYAN]
SCREEN_WIDTH = 60  # every screen lines up on this width, two characters in from the left edge
INDENT = "  "


def gradient_color(position: float) -> str:
    """The colour at 0..1 along pink → purple → cyan."""
    scaled = min(max(position, 0.0), 1.0) * (len(GRADIENT) - 1)
    index = min(int(scaled), len(GRADIENT) - 2)
    start, end = _rgb(GRADIENT[index]), _rgb(GRADIENT[index + 1])
    mix = scaled - index
    return "#" + "".join(f"{round(a + (b - a) * mix):02x}" for a, b in zip(start, end))


def gradient_text(text: str, style: str = "") -> Text:
    last = max(len(text) - 1, 1)
    return Text.assemble(*((character, f"{style} {gradient_color(index / last)}") for index, character in enumerate(text)))


def bar(percent: int, width: int) -> Text:
    """A bar whose filled part shades pink → purple → cyan along the whole width, so a fuller bar reaches cyan."""
    filled = round(min(max(percent, 0), 100) / 100 * width)
    shaded = Text.assemble(*(("━", gradient_color(index / (width - 1))) for index in range(filled)))
    return shaded.append("━" * (width - filled), style=TRACK)


def label(text: str) -> Text:
    return Text(text.upper(), style=MUTED)


def section(title: str) -> Text:
    return Text.assemble(("// ", PINK), (title.upper(), MUTED))


def header(context: str) -> Table:
    """The top line of every screen: the wordmark on the left, where you are on the right."""
    table = Table.grid()
    table.add_column(width=SCREEN_WIDTH // 2)
    table.add_column(width=SCREEN_WIDTH - SCREEN_WIDTH // 2, justify="right")
    table.add_row(gradient_text("░▒▓  C O M P A  ▓▒░", "bold"),
                  Text(context.upper(), style=MUTED))
    return table


def show_screen(console: Console, context: str) -> None:
    """Clears the terminal and starts a fresh screen with the header, so screens replace each other."""
    console.clear()
    console.file.write("\x1b[3J")  # clear() leaves the old screen in the scrollback; this drops it
    console.file.flush()
    print_header(console, context)


def print_header(console: Console, context: str) -> None:
    console.print(indented(header(context), top=1, bottom=1))


def indented(renderable, top: int = 0, bottom: int = 0) -> Padding:
    return Padding(renderable, (top, 0, bottom, len(INDENT)))


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
