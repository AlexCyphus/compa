import dataclasses

from compa.brain import Correction, EnglishWord, Feedback
from compa.call_log import CallLog, TurnRecord
from compa.report import Reporter, Scores, measured_scores
from compa.settings import load_profile


def turn(text: str, seconds: float, errors: int = 0, english: int = 0, upgrades: int = 0) -> TurnRecord:
    corrections = [Correction("x", "y", "", False)] * errors + [Correction("a", "b", "", True)] * upgrades
    return TurnRecord(text, seconds=seconds, feedback=Feedback(corrections, [EnglishWord("w", "p", "")] * english))


def test_clean_fluent_speech_scores_full_accuracy_and_fluency():
    log = CallLog(turns=[turn(" ".join(["palabra"] * 130), seconds=60)])

    assert measured_scores(log, range_score=80) == Scores(accuracy=100, range=80, fluency=100)


def test_errors_lower_accuracy_but_upgrades_do_not():
    log = CallLog(turns=[turn(" ".join(["palabra"] * 100), seconds=60, errors=2, upgrades=3)])

    assert measured_scores(log, 80).accuracy == 88


def test_english_words_and_slow_speech_lower_fluency():
    log = CallLog(turns=[turn(" ".join(["palabra"] * 90), seconds=60, english=2)])

    assert measured_scores(log, 80).fluency == 42


def test_overall_weights_the_three_scores():
    assert Scores(accuracy=100, range=80, fluency=60).overall == 81


async def test_report_card_counts_recurring_patterns_across_calls(tmp_path):
    profile = dataclasses.replace(load_profile("spanish"), sessions_folder=tmp_path)
    history = [("assistant", "¿Qué harías si ganaras la lotería?"),
               ("user", "Si yo ganaría la lotería, compraría una casa. Es importante que mi familia está bien."),
               ("assistant", "¿Y dónde sería la casa?"),
               ("user", "Si tendría que elegir, sería en la costa, porque quiero que mis hijos crecen cerca del mar.")]
    log = CallLog(turns=[
        TurnRecord(history[1][1], seconds=6, feedback=Feedback([
            Correction("Si yo ganaría", "Si yo ganara", "Si + imperfecto de subjuntivo", False),
            Correction("que mi familia está", "que mi familia esté", "Subjuntivo tras 'es importante que'", False)], [])),
        TurnRecord(history[3][1], seconds=7, feedback=Feedback([
            Correction("Si tendría", "Si tuviera", "Si + imperfecto de subjuntivo", False),
            Correction("que mis hijos crecen", "que mis hijos crezcan", "Subjuntivo tras 'querer que'", False)], [])),
    ])
    reporter = Reporter(profile)

    first = await reporter.report(history, log)
    second = await reporter.report(history, log)

    assert first.previous_overall is None and second.previous_overall == first.scores.overall
    assert 0 < first.scores.range <= 100 and first.summary and first.patterns
    assert max(pattern.times_seen for pattern in second.patterns) == 2
    print(first)
