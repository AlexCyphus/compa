"""The call loop with fake ears, mouth and brain: speculation, barge-in, carried-over turns, nudges, feedback."""
import asyncio
import io

import pytest
from rich.console import Console

from compa import conversation as conversation_module
from compa.brain import Correction, EnglishWord, Feedback
from compa.conversation import Brain, Conversation
from compa.listen import Paused, SpeechStarted, TurnEnded
from compa.screen import Screen

SENTENCE_SECONDS = 0.2


class FakeListener:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    async def warm_up(self):
        pass

    def set_speech_threshold(self, threshold):
        pass

    async def events(self):
        while True:
            yield await self.queue.get()


class FakeSpeaker:
    """Each sentence 'plays' for SENTENCE_SECONDS; interrupt returns the finished sentences."""

    def __init__(self):
        self.on_sentence_started = None
        self.queue: list[str] = []
        self.spoken: list[str] = []
        self.playing: str | None = None
        self.prerendered: list[str] = []
        self._wake = asyncio.Event()

    def say(self, sentence):
        self.queue.append(sentence)
        self._wake.set()

    def end_reply(self):
        pass

    def prerender(self, sentence):
        self.prerendered.append(sentence)

    def drop_prerendered(self):
        self.prerendered.clear()

    def interrupt(self):
        heard = " ".join(self.spoken)
        self.queue.clear()
        self.playing = None
        self.spoken = []
        return heard

    @property
    def is_speaking(self):
        return bool(self.queue) or self.playing is not None

    async def wait_until_quiet(self):
        while self.is_speaking:
            await asyncio.sleep(0.01)
        self.spoken = []

    async def run(self):
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self.queue:
                self.playing = self.queue.pop(0)
                self.on_sentence_started(self.playing)
                await asyncio.sleep(SENTENCE_SECONDS)
                if self.playing is not None:
                    self.spoken.append(self.playing)
                self.playing = None

    async def close(self):
        pass


class FakeReply:
    def __init__(self, talker, learner_text, lines):
        self.talker = talker
        self.learner_text = learner_text
        self.lines = lines
        self.full_text = " ".join(lines)
        self.cancelled = False
        self.committed: str | None = None

    async def sentences(self):
        for line in self.lines:
            yield line

    def cancel(self):
        self.cancelled = True

    def stop_at(self, text):
        self.full_text = text

    def commit(self, spoken_text=None):
        if self.cancelled or self.committed is not None:
            return
        self.committed = spoken_text if spoken_text is not None else self.full_text
        if self.learner_text:
            self.talker.history.append(("user", self.learner_text))
        self.talker.history.append(("assistant", self.committed))


class FakeTalker:
    def __init__(self):
        self.history = []
        self.replies: list[FakeReply] = []

    async def start(self):
        pass

    async def close(self):
        pass

    def set_briefing(self, stories):
        pass

    def opener(self):
        return self._make(None, ["¡Hola!", "¿Qué más?"])

    def nudge(self):
        return self._make(None, ["¿Y qué opinas del fútbol?"])

    def reply(self, text):
        return self._make(text, [f"Respuesta a {text}", "¿Y tú?"])

    def _make(self, learner_text, lines):
        reply = FakeReply(self, learner_text, lines)
        self.replies.append(reply)
        return reply


class FakeCorrector:
    async def start(self):
        pass

    async def close(self):
        pass

    async def check(self, user_text, context):
        await asyncio.sleep(0.1)
        if "lawnmower" in user_text:
            return Feedback([Correction("que lo corto", "que lo corte", "Subjuntivo", False)],
                            [EnglishWord("lawnmower", "podadora", "")])
        return Feedback([], [])


class FakeScout:
    async def briefing(self):
        return []


@pytest.fixture
async def call():
    listener, speaker, talker = FakeListener(), FakeSpeaker(), FakeTalker()
    output = io.StringIO()
    screen = Screen(Console(file=output, width=200, color_system=None))
    conversation = Conversation(listener, speaker, screen, Brain(talker, FakeCorrector(), FakeScout()))
    task = asyncio.create_task(conversation.run())
    await until(lambda: talker.history)
    yield conversation, listener, talker, output
    task.cancel()
    await conversation.close()


async def until(condition, timeout=5.0):
    async def wait():
        while not condition():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), timeout)


async def say(listener, *events):
    for event in events:
        await listener.queue.put(event)
        await asyncio.sleep(0.02)


async def test_opener_is_spoken_and_committed(call):
    conversation, listener, talker, output = call

    assert talker.history == [("assistant", "¡Hola! ¿Qué más?")]
    assert "¡Hola!" in output.getvalue()


async def test_learner_turn_gets_a_spoken_reply(call):
    conversation, listener, talker, output = call

    await say(listener, SpeechStarted(), TurnEnded("Hoy fui al cine.", 2.0))
    await until(lambda: len(talker.history) == 3)

    assert talker.history[1] == ("user", "Hoy fui al cine.")
    assert "Respuesta a Hoy fui al cine." in output.getvalue()


async def test_speculative_reply_from_the_pause_is_used_when_the_turn_ends_the_same(call):
    conversation, listener, talker, output = call

    await say(listener, SpeechStarted(), Paused("Hoy fui al cine."), TurnEnded("Hoy fui al cine", 2.0))
    await until(lambda: len(talker.history) == 3)

    assert len(talker.replies) == 2
    assert conversation.log.turns[0].speculation_used
    assert conversation.speaker.prerendered == ["Respuesta a Hoy fui al cine.", "¿Y tú?"]


async def test_speculative_reply_is_dropped_when_the_learner_says_more(call):
    conversation, listener, talker, output = call

    await say(listener, SpeechStarted(), Paused("Hoy fui"), TurnEnded("Hoy fui al cine con mi hermana.", 3.0))
    await until(lambda: len(talker.history) == 3)

    speculative, final = talker.replies[1], talker.replies[2]
    assert speculative.cancelled
    assert final.learner_text == "Hoy fui al cine con mi hermana."


async def test_speaking_over_compa_cuts_it_off_and_keeps_only_what_was_heard(call):
    conversation, listener, talker, output = call
    await say(listener, SpeechStarted(), TurnEnded("Hoy fui al cine.", 2.0))
    await until(lambda: "¿Y tú?" in output.getvalue())

    await say(listener, SpeechStarted())

    assert talker.history[-1] == ("assistant", "Respuesta a Hoy fui al cine.")
    assert conversation.log.interruptions == 1
    assert "cut off" in output.getvalue()


async def test_carrying_on_before_compa_speaks_answers_both_parts_together(call):
    conversation, listener, talker, output = call

    await say(listener, SpeechStarted(), TurnEnded("Ayer compré una bici.", 2.0), SpeechStarted())
    first = talker.replies[1]
    await say(listener, TurnEnded("Es roja.", 1.0))
    await until(lambda: len(talker.history) == 3)

    assert first.cancelled and first.committed is None
    assert talker.history[1] == ("user", "Ayer compré una bici. Es roja.")
    assert conversation.log.interruptions == 0


async def test_english_word_and_correction_are_shown(call):
    conversation, listener, talker, output = call

    await say(listener, SpeechStarted(), TurnEnded("Compré un lawnmower y es importante que lo corto.", 3.0))
    await until(lambda: "que lo corte" in output.getvalue())

    shown = output.getvalue()
    assert "🔤 lawnmower → podadora" in shown
    assert shown.index("¿Y tú?") < shown.index("que lo corte"), "corrections wait for the reply to finish"


async def test_long_silence_brings_a_new_topic(call, monkeypatch):
    conversation, listener, talker, output = call
    monkeypatch.setattr(conversation_module, "NUDGE_AFTER_SILENCE_SECONDS", 0.5)

    await until(lambda: conversation.log.nudges == 1, timeout=4)
    await until(lambda: len(talker.history) == 2)

    assert talker.history[-1] == ("assistant", "¿Y qué opinas del fútbol?")


async def test_compa_stops_after_its_first_question(call):
    conversation, listener, talker, output = call
    talker.reply = lambda text: talker._make(text, ["Qué bacano.", "¿Y fue chistosa?", "¿O de acción?", "Yo voy poco."])

    await say(listener, SpeechStarted(), TurnEnded("Fui al cine.", 1.0))
    await until(lambda: len(talker.history) == 3)

    assert talker.history[-1] == ("assistant", "Qué bacano. ¿Y fue chistosa?")
    assert "¿O de acción?" not in output.getvalue()


async def test_new_topic_waits_longer_while_there_are_corrections_to_read(call, monkeypatch):
    conversation, listener, talker, output = call
    monkeypatch.setattr(conversation_module, "NUDGE_AFTER_SILENCE_SECONDS", 0.5)
    monkeypatch.setattr(conversation_module, "READING_SECONDS_PER_CORRECTION", 5.0)

    await say(listener, SpeechStarted(), TurnEnded("Compré un lawnmower y es importante que lo corto.", 3.0))
    await until(lambda: "que lo corte" in output.getvalue())
    await asyncio.sleep(3)

    assert conversation.log.nudges == 0
