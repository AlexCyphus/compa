"""Topic memory: which topic words the learner has used, and which topic the next call focuses on."""
from compa.topics import TOPICS, WORDS_FOR_COVERED, TopicMemory


def test_recording_counts_each_new_word_once(tmp_path):
    memory = TopicMemory(tmp_path, "es")

    memory.record("fishing and hunting", ["anzuelo", "caña de pescar"])
    progress = memory.record("fishing and hunting", ["Anzuelo", "carnada"])

    assert memory.words("fishing and hunting") == ["anzuelo", "caña de pescar", "carnada"]
    assert (progress.words_used, progress.new_words) == (3, 1)


def test_memory_is_kept_between_calls(tmp_path):
    memory = TopicMemory(tmp_path, "es")
    memory.record("fishing and hunting", ["anzuelo"])
    memory.save()

    assert TopicMemory(tmp_path, "es").words("fishing and hunting") == ["anzuelo"]


def test_next_topic_prefers_a_half_started_one(tmp_path):
    memory = TopicMemory(tmp_path, "es")
    memory.topics = {"fishing and hunting": {"words": ["anzuelo"], "calls": ["2026-01-01"]},
                     "pets": {"words": ["perro"], "calls": ["2026-01-02"]},
                     "camping": {"words": ["carpa"], "calls": ["2026-01-03"]},
                     "theatre": {"words": ["telón"], "calls": ["2026-01-04"]}}

    assert memory.next_topic() == "fishing and hunting", "the other three were talked about on the last 3 call days"


def test_next_topic_skips_covered_topics(tmp_path):
    memory = TopicMemory(tmp_path, "es")
    memory.topics = {topic: {"words": [str(n) for n in range(WORDS_FOR_COVERED)], "calls": ["2026-01-01"]}
                     for topic in TOPICS if topic != "pets"}

    assert memory.next_topic() == "pets"
