"""Level estimate and recurring mistakes from the learner's past calls."""
import json

from compa.progress import estimated_level, weaknesses


def test_level_comes_from_the_average_range_of_recent_calls():
    past = [{"range": 20}] * 5 + [{"range": 58}, {"range": 62}, {"range": 55}, {"range": 65}, {"range": 60}]

    assert estimated_level(past) == "B2"


def test_no_level_before_three_calls():
    assert estimated_level([{"range": 60}] * 2) is None and estimated_level([{"range": 60}] * 3) == "B2"


def test_mistakes_seen_in_the_most_calls_come_first(tmp_path):
    (tmp_path / "common-errors-es.json").write_text(json.dumps({
        "gender": {"pattern": "Concordancia de género", "dates": ["2026-11-01"], "examples": ["la mano"]},
        "subjunctive": {"pattern": "Subjuntivo", "dates": ["2026-11-01", "2026-11-03", "2026-11-05"],
                        "examples": ["que venga", "que lea", "que llueva", "que sea"]},
    }))

    found = weaknesses(tmp_path, "es")

    assert [(w.id, w.calls) for w in found] == [("subjunctive", 3), ("gender", 1)]
    assert found[0].examples == ["que venga", "que lea", "que llueva"]
