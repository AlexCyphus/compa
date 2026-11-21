"""The call loop: listens, speculates replies during pauses, speaks, handles interruptions, shows feedback."""
import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path

from compa.brain import ClaudeUnavailable, Corrector, Reply, Scout, Talker
from compa.clozemaster import Clozemaster
from compa.call_log import CallLog, TurnRecord
from compa.listen import Listener, Partial, Paused, Resumed, SpeechStarted, TurnEnded
from compa.screen import Screen
from compa.settings import Profile
from compa.speak import Speaker

BRIEFING_WAIT_SECONDS = 1.0
MAX_SENTENCES = 4
RECENT_TURNS_FOR_SAVING = 3
PRERENDER_SENTENCES = 2
SPEECH_THRESHOLD_WHILE_TALKING = 0.7
SPEECH_THRESHOLD = 0.5


@dataclass(frozen=True)
class Brain:
    talker: Talker
    corrector: Corrector
    scout: Scout
    clozemaster: Clozemaster | None = None

    @classmethod
    def for_profile(cls, profile: Profile, cache_dir: Path) -> "Brain":
        clozemaster = Clozemaster(profile) if profile.clozemaster_collection else None
        return cls(Talker(profile), Corrector(profile), Scout(profile, cache_dir), clozemaster)


def same_words(first: str, second: str) -> bool:
    return _words(first) == _words(second)


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class Conversation:
    def __init__(self, listener: Listener, speaker: Speaker, screen: Screen, brain: Brain):
        self.listener = listener
        self.speaker = speaker
        self.screen = screen
        self.talker = brain.talker
        self.corrector = brain.corrector
        self.clozemaster = brain.clozemaster
        self.scout = brain.scout
        self.log = CallLog()
        self.started_at = time.monotonic()
        self._speaking_reply: Reply | None = None
        self._speaking_task: asyncio.Task | None = None
        self._speculative: Reply | None = None
        self._speculative_text = ""
        self._turn_ended_at: float | None = None
        self._pending_turn: TurnRecord | None = None
        self._learner_talking = False
        self._carried_over = ""
        self._reply_to_learner: Reply | None = None
        self._unanswered_learner_text = ""
        self._background: set[asyncio.Task] = set()
        self.unavailable: ClaudeUnavailable | None = None
        self._hung_up = asyncio.Event()
        speaker.on_sentence_started = self._sentence_started

    async def run(self) -> None:
        self.screen.status("Getting ready…")
        await asyncio.gather(self.listener.warm_up(), self.talker.start(), self.corrector.start())
        briefing = self._spawn(self._load_briefing())
        await asyncio.wait([briefing], timeout=BRIEFING_WAIT_SECONDS)  # today's briefing is cached after the first call
        self.screen.status("")
        self._spawn(self.speaker.run())
        self._speak(self.talker.opener())
        listening = asyncio.create_task(self._listen())
        hung_up = asyncio.create_task(self._hung_up.wait())
        done, _ = await asyncio.wait({listening, hung_up}, return_when=asyncio.FIRST_COMPLETED)
        listening.cancel()
        hung_up.cancel()
        if listening in done:
            listening.result()

    async def _listen(self) -> None:
        async for event in self.listener.events():
            match event:
                case SpeechStarted() | Resumed():
                    self._on_speech()
                case Partial(text):
                    self.screen.partial(text)
                case Paused(text):
                    self._speculate(text)
                case TurnEnded(text, seconds):
                    self._on_turn_ended(text, seconds)

    async def close(self) -> None:
        for task in self._background:
            task.cancel()
        await self.speaker.close()
        await asyncio.gather(self.talker.close(), self.corrector.close(), return_exceptions=True)

    def _on_speech(self) -> None:
        self._learner_talking = True
        self._drop_speculation()
        if self._speaking_reply is not None:
            self._interrupt()

    def _interrupt(self) -> None:
        heard = self.speaker.interrupt()
        reply = self._speaking_reply
        self._speaking_reply = None
        if self._speaking_task is not None:
            self._speaking_task.cancel()
        if not heard.strip():
            self._continue_learner_turn(reply)
            return
        reply.commit(spoken_text=heard)
        reply.cancel()
        self.log.interruptions += 1
        self.screen.interrupted()

    def _continue_learner_turn(self, reply: Reply) -> None:
        """The learner carried on before Compa said a word: Compa answers both parts together."""
        reply.cancel()
        if reply is self._reply_to_learner:
            self._carried_over = self._unanswered_learner_text

    def _speculate(self, text: str) -> None:
        if not text or self._speculative is not None:
            return
        self._speculative_text = self._with_carried_over(text)
        self._speculative = self.talker.reply(self._speculative_text)
        self._spawn(self._prerender(self._speculative))

    async def _prerender(self, reply: Reply) -> None:
        """Voice the speculative reply's opening while the learner is still pausing."""
        count = 0
        async for sentence in reply.sentences():
            self.speaker.prerender(sentence)
            count += 1
            if count == PRERENDER_SENTENCES:
                return

    def _drop_speculation(self) -> None:
        if self._speculative is not None:
            self._speculative.cancel()
            self.speaker.drop_prerendered()
        self._speculative = None
        self._speculative_text = ""

    def _on_turn_ended(self, text: str, seconds: float) -> None:
        self._learner_talking = False
        if not text:
            self._drop_speculation()
            return
        previous_line = self._last_assistant_line()
        self.screen.learner(text)
        turn = TurnRecord(learner=text, seconds=seconds)
        self.log.turns.append(turn)
        whole_text = self._with_carried_over(text)
        self._carried_over = ""
        if self._speculative is not None and same_words(self._speculative_text, whole_text):
            reply, turn.speculation_used = self._speculative, True
            self._speculative = None
        else:
            self._drop_speculation()
            reply = self.talker.reply(whole_text)
        self._reply_to_learner, self._unanswered_learner_text = reply, whole_text
        turn.reply = reply
        self._turn_ended_at = time.monotonic()
        self._pending_turn = turn
        self._speak(reply)
        self._spawn(self._show_feedback(turn, previous_line))

    def _with_carried_over(self, text: str) -> str:
        return f"{self._carried_over} {text}" if self._carried_over else text

    def _speak(self, reply: Reply) -> None:
        self._speaking_reply = reply
        self._speaking_task = self._spawn(self._play(reply))

    async def _play(self, reply: Reply) -> None:
        self.listener.set_speech_threshold(SPEECH_THRESHOLD_WHILE_TALKING)
        try:
            said: list[str] = []
            async for sentence in reply.sentences():
                self.speaker.say(sentence)
                said.append(sentence)
                if sentence.rstrip().endswith(("?", "？")) or len(said) == MAX_SENTENCES:
                    reply.stop_at(" ".join(said))  # one question per turn keeps it a conversation
                    break
            self.speaker.end_reply()
            await self.speaker.wait_until_quiet()
            if self._speaking_reply is reply:
                reply.commit()
                self._speaking_reply = None
                self.screen.reply_finished()
        finally:
            self.listener.set_speech_threshold(SPEECH_THRESHOLD)

    def _sentence_started(self, sentence: str) -> None:
        if self._turn_ended_at is not None and self._pending_turn is not None:
            self._pending_turn.reply_after_seconds = time.monotonic() - self._turn_ended_at
            self._turn_ended_at = None
        self.screen.compa(sentence)

    async def _show_feedback(self, turn: TurnRecord, previous_line: str) -> None:
        turn.feedback = await self.corrector.check(turn.learner, previous_line, self._recent_english_words())
        self.screen.feedback(turn.feedback)
        if turn.feedback.words_to_save and self.clozemaster is not None:
            self.screen.saved(await self.clozemaster.save(turn.feedback.words_to_save, previous_line, turn.learner))

    async def _load_briefing(self) -> None:
        stories = await self.scout.briefing()
        self.talker.set_briefing(stories)
        self.screen.briefing_ready(stories)

    def _recent_english_words(self) -> list[str]:
        """So "save that word" can mean a word the learner asked about a turn or two ago."""
        recent = self.log.turns[-RECENT_TURNS_FOR_SAVING:]
        return [f"{word.said} → {word.target}" for turn in recent if turn.feedback for word in turn.feedback.english_words]

    def _last_assistant_line(self) -> str:
        return next((text for role, text in reversed(self.talker.history) if role == "assistant"), "")

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task) -> None:
        self._background.discard(task)
        if task.cancelled() or task.exception() is None:
            return
        if isinstance(task.exception(), ClaudeUnavailable):
            self._hang_up(task.exception())
        else:
            self.screen.error(task.exception())

    def _hang_up(self, reason: ClaudeUnavailable) -> None:
        """Out of Claude usage: stop talking and end the call instead of going silent."""
        if self.unavailable is None:
            self.unavailable = reason
            self.speaker.interrupt()
            self.screen.claude_unavailable(reason)
        self._hung_up.set()
