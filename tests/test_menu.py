import json
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from compa import __main__ as app

DOWN, ENTER, ESCAPE = "\x1b[B", "\r", "\x1b"


@pytest.fixture
def press(monkeypatch):
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


def test_lesson_with_no_weaknesses_goes_back_to_the_menu(tmp_path, press, calls):
    press(DOWN + ENTER, ESCAPE)

    app._menu(learner(tmp_path), None, None)

    assert calls == []


def test_lesson_starts_a_call_on_the_chosen_weakness(tmp_path, press, calls):
    mistakes = {"ser_estar": {"pattern": "Ser y estar", "dates": ["2026-11-20"], "examples": ["estoy cansado"]}}
    press(DOWN + ENTER, ENTER)

    app._menu(learner(tmp_path, mistakes), None, None)

    assert [lesson.pattern for lesson in calls] == ["Ser y estar"]


def test_progress_goes_back_to_the_menu(tmp_path, press, calls, capsys):
    press(DOWN + DOWN + ENTER, ESCAPE)

    app._menu(learner(tmp_path), None, None)

    assert "No Spanish calls yet" in capsys.readouterr().out and calls == []
