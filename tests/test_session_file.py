from compa.brain import Correction, EnglishWord, Feedback
from compa.call_log import CallLog, TurnRecord
from compa.session_file import save_call


def test_call_is_saved_with_conversation_and_review(tmp_path):
    history = [("assistant", "¿Qué más?"), ("user", "Compré un lawnmower.")]
    turn = TurnRecord("Compré un lawnmower.", feedback=Feedback(
        [Correction("que lo corto", "que lo corte", "Subjuntivo", False),
         Correction("muy bueno", "buenísimo", "Más natural", True)],
        [EnglishWord("lawnmower", "podadora", "")]))

    path = save_call(tmp_path, "Spanish", history, CallLog(turns=[turn]), None)

    saved = path.read_text()
    assert "**Compa:** ¿Qué más?" in saved and "**You:** Compré un lawnmower." in saved
    assert "**lawnmower** → **podadora**" in saved
    assert "~~que lo corto~~ → **que lo corte**" in saved
    assert "## More natural" in saved


def test_second_call_in_the_same_minute_gets_its_own_file(tmp_path):
    first = save_call(tmp_path, "Spanish", [("user", "Hola")], CallLog(), None)
    second = save_call(tmp_path, "Spanish", [("user", "Hola")], CallLog(), None)

    assert first != second and second.exists()
