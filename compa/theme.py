"""The look shared by every screen: a calm dark terminal, one warm saddle-tan accent, quiet greys and the 🤠."""
from rich import box
from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ACCENT = "#e0a060"  # saddle tan, the one colour that stands out
TEXT = "#e8e3da"
SOFT = "#bdb6ab"  # your own words, a step quieter than Compa's
MUTED = "#8c857b"
FAINT = "#5f5a52"
TRACK = "#3d3933"
GOOD = "#9cc483"
BAD = "#e07a68"
INK = "#1c1a17"
SCREEN_WIDTH = 64  # every screen lines up on this width, two characters in from the left edge
INDENT = "  "


def bar(percent: int, width: int) -> Text:
    """A thin one-colour bar: ━ for the filled part, ─ for the rest."""
    filled = round(min(max(percent, 0), 100) / 100 * width)
    return Text.assemble(("━" * filled, ACCENT), ("─" * (width - filled), TRACK))


def label(text: str) -> Text:
    return Text(text, style=MUTED)


def section(title: str) -> Text:
    return Text(title, style=f"bold {TEXT}")


def header(context: str, line: str | Text = "", note: str = "") -> Panel:
    """The rounded box at the top of every screen: 🤠 compa and where you are, then a friendly line."""
    top = Table.grid(expand=True)
    top.add_column()
    top.add_column(justify="right")
    top.add_row(Text.assemble("🤠 ", ("compa", f"bold {TEXT}")), Text(context, style=MUTED))
    rows = [top]
    if line:
        rows.append(Text.assemble("   ", line if isinstance(line, Text) else Text(line, style=MUTED)))
    if note:
        rows.append(Text(f"   {note}", style=FAINT))
    return Panel(Group(*rows), box=box.ROUNDED, border_style=ACCENT, width=SCREEN_WIDTH, padding=(0, 1))


def show_screen(console: Console, context: str, line: str | Text = "", note: str = "") -> None:
    """Clears the terminal and starts a fresh screen with the header, so screens replace each other."""
    console.clear()
    console.file.write("\x1b[3J")  # clear() leaves the old screen in the scrollback; this drops it
    console.file.flush()
    print_header(console, context, line, note)


def print_header(console: Console, context: str, line: str | Text = "", note: str = "") -> None:
    console.print(indented(header(context, line, note), top=1, bottom=1))


def indented(renderable, top: int = 0, bottom: int = 0) -> Padding:
    return Padding(renderable, (top, 0, bottom, len(INDENT)))
