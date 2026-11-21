from rich.console import Console

from compa.brain import EnglishWord
from compa.cards import progress_card, report_card
from compa.progress import Weakness
from compa.report import Pattern, ReportCard, Scores


def rendered(renderable) -> str:
    console = Console(width=80, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


def card(patterns: list[Pattern], previous_overall: int | None = None) -> ReportCard:
    return ReportCard(Scores(80, 60, 70), previous_overall, 6.5, 90, patterns, [EnglishWord("wrench", "llave", "")],
                      ["strength"], ["phrase to try"], "A summary paragraph.", [])


def test_report_card_shows_the_level_and_its_name():
    text = rendered(report_card(card([]), "B2"))

    assert "B2" in text and "UPPER INTERMEDIATE" in text


def test_report_card_leaves_out_the_summary_strengths_and_phrases():
    text = rendered(report_card(card([]), "B2"))

    assert "summary" not in text and "strength" not in text and "phrase to try" not in text


def test_report_card_shows_at_most_three_mistakes():
    patterns = [Pattern(f"id{number}", f"Mistake {number}", [], 1) for number in range(5)]

    text = rendered(report_card(card(patterns), "B2"))

    assert "Mistake 2" in text and "Mistake 3" not in text


def test_report_card_shows_the_change_since_last_call():
    assert "▲3" in rendered(report_card(card([], previous_overall=67), "B2"))


def test_progress_card_shows_the_level_and_the_top_weaknesses():
    past = [{"overall": 60, "accuracy": 70, "range": 50, "fluency": 60},
            {"overall": 66, "accuracy": 75, "range": 55, "fluency": 66}]

    text = rendered(progress_card("B2", past, [Weakness("ser_estar", "Ser y estar", 2, [])], 1, 3))

    assert "B2" in text and "▲6" in text and "Ser y estar" in text


def test_report_card_without_a_level_says_when_one_comes():
    text = rendered(report_card(card([]), None))

    assert "LEVEL AFTER 3 CALLS" in text


def test_call_screen_shows_how_long_the_call_has_lasted_and_how_to_hang_up(monkeypatch):
    from rich.console import Console
    from rich.text import Text

    from compa import screen as screen_module
    from compa.screen import Screen

    clock = [100.0]
    monkeypatch.setattr(screen_module.time, "monotonic", lambda: clock[0])
    console = Console(record=True, width=80)
    screen = Screen(console)
    screen.call_header("SPANISH // CALL", Text("topic"), "me · pro")
    clock[0] += 125

    console.print(screen._live_line)

    assert "02:05" in console.export_text() and "CTRL-C to hang up" in console.export_text()
