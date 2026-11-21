import io
import json
import sys
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from compa import __main__ as app

UP, DOWN, ENTER, ESCAPE, CTRL_C = "\x1b[A", "\x1b[B", "\r", "\x1b", "\x03"
MISTAKES = {"ser_estar": {"pattern": "Ser y estar", "dates": ["2026-11-20"], "examples": ["estoy cansado"]}}


@pytest.fixture
def screen(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(app, "CONSOLE", Console(file=output, width=80, color_system=None))
    return output


@pytest.fixture
def press(monkeypatch, screen):
    """Queues the keys to press at each picker in turn; a picker reads all waiting input, so they can't go in at once."""
    queued = []
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        def pick_with_keys(question, choices):
            pipe.send_text(queued.pop(0))
            return real_pick(question, choices)

        real_pick = app.pick
        monkeypatch.setattr(app, "pick", pick_with_keys)
        yield lambda *keys_per_picker: queued.extend(keys_per_picker)


@pytest.fixture
def calls(monkeypatch):
    started = []
    monkeypatch.setattr(app, "_start_call", lambda profile, topics, arguments, lesson=None: started.append(lesson))
    return started


def learner(folder, mistakes=None):
    if mistakes:
        (folder / "common-errors-es.json").write_text(json.dumps(mistakes))
    return SimpleNamespace(sessions_folder=folder, language="es", language_name="Spanish")


def test_escape_quits_the_menu_without_starting_a_call(tmp_path, press, calls):
    press(ESCAPE)

    app._menu(learner(tmp_path), None, None)

    assert calls == []


def test_start_a_call_starts_one_without_a_lesson(tmp_path, press, calls):
    press(ENTER)

    app._menu(learner(tmp_path), None, None)

    assert calls == [None]


def test_lesson_with_no_weaknesses_goes_back_to_the_menu(tmp_path, press, calls, screen):
    press(DOWN + ENTER, ENTER, ESCAPE)

    app._menu(learner(tmp_path), None, None)

    assert "No weaknesses yet" in screen.getvalue() and calls == []


def test_lesson_starts_a_call_on_the_chosen_weakness(tmp_path, press, calls):
    press(DOWN + ENTER, ENTER)

    app._menu(learner(tmp_path, MISTAKES), None, None)

    assert [lesson.pattern for lesson in calls] == ["Ser y estar"]


def test_back_in_the_weakness_picker_goes_back_to_the_menu(tmp_path, press, calls):
    press(DOWN + ENTER, DOWN + ENTER, ESCAPE)

    app._menu(learner(tmp_path, MISTAKES), None, None)

    assert calls == []


def test_progress_goes_back_to_the_menu(tmp_path, press, calls, screen):
    press(DOWN + DOWN + ENTER, ENTER, ESCAPE)

    app._menu(learner(tmp_path), None, None)

    assert "No Spanish calls yet" in screen.getvalue() and calls == []


def test_done_after_the_report_card_starts_no_lesson(tmp_path, press):
    press(UP + ENTER)

    assert app._pick_next_lesson(learner(tmp_path, MISTAKES)) is None


def test_ctrl_c_at_the_language_picker_quits_quietly(press, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["compa"])
    press(CTRL_C)

    app.main()

    assert "Traceback" not in capsys.readouterr().err


def test_add_language_saves_the_chosen_language_and_level(press, monkeypatch):
    added = []
    italian = SimpleNamespace(key="italian", name="Italian", flag="🇮🇹")
    monkeypatch.setattr(app, "addable_languages", lambda: [italian])
    monkeypatch.setattr(app, "add_language", lambda key, level: added.append((key, level)))
    press(UP + ENTER, ENTER, DOWN + DOWN + ENTER)

    assert app._ask_language() == "italian" and added == [("italian", "B1")]


def test_back_from_add_language_returns_to_the_language_picker(press, monkeypatch):
    monkeypatch.setattr(app, "add_language", lambda key, level: pytest.fail("nothing should be added"))
    press(UP + ENTER, UP + ENTER, ESCAPE)

    assert app._ask_language() is None
