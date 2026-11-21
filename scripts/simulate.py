"""End-to-end test call with a simulated learner (another Claude) speaking through `say`.

Usage: .venv/bin/python scripts/simulate.py [language] [--turns N] [--acoustic]

Default: learner audio is injected straight into the listener, Compa's speech is rendered to files.
--acoustic: learner audio plays out of the MacBook speakers and Compa listens on the MacBook microphone
(the real mic path); Compa talks on the default output device (use headphones so it doesn't hear itself).

Scripted moments: a mid-thought pause and the learner cutting Compa off.
"""
import argparse
import asyncio
import dataclasses
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock  # noqa: E402

from compa.account import use_claude_account  # noqa: E402
from compa.conversation import Brain, Conversation  # noqa: E402
from compa.progress import estimated_level, grades  # noqa: E402
from compa.report import Reporter  # noqa: E402
from compa.session_file import save_call  # noqa: E402
from compa.listen import SAMPLE_RATE, InjectedSource, Listener, MicSource  # noqa: E402
from compa.screen import Screen  # noqa: E402
from compa.settings import load_profile  # noqa: E402
from compa.speak import Speaker  # noqa: E402

LEARNER_VOICES = {"es": "Eddy (Spanish (Mexico))", "de": "Eddy (German (Germany))", "fr": "Eddy (French (France))", "ca": "Montse",
                  "en": "Eddy (English (US))"}
NATIVE_VOICES = {"English": "Samantha", "Spanish": "Paulina"}
PAUSE_TURN, BARGE_IN_TURN = 2, 4
MID_THOUGHT_PAUSE_SECONDS = 0.7
HESITATION_SECONDS = 0.5
WORD_GAP_SECONDS = 0.15

LEARNER_PROMPT = """You role-play a {native} learner of {language} at about {level} level on a voice call with a friend.
Reply to what the friend just said in 1-3 spoken sentences of {language}, engaging with the topic and sometimes
asking something back. Make 1-2 natural learner mistakes per reply (agreement, prepositions, subjunctive, tense).
Every second or third reply, use exactly one {native} word in place of a {language} word you "don't know",
written in square brackets, e.g. "compré un [lawnmower] nuevo". Output only the spoken line."""


class SimulatedLearner:
    def __init__(self, profile, audio_dir: Path):
        self.profile = profile
        self.audio_dir = audio_dir
        self.voice = LEARNER_VOICES[profile.language]
        self._client = ClaudeSDKClient(ClaudeAgentOptions(
            model="claude-haiku-5-5", tools=[], setting_sources=[], strict_mcp_config=True, mcp_servers={},
            skills=[], plugins=[], thinking={"type": "disabled"}, env={"ENABLE_CLAUDEAI_MCP_SERVERS": "false"},
            system_prompt=LEARNER_PROMPT.format(native=profile.native_language, language=profile.language_name,
                                                level=profile.level)))
        self._count = 0

    async def __aenter__(self):
        await self._client.connect()
        return self

    async def __aexit__(self, *_):
        await self._client.disconnect()

    async def answer(self, compa_said: str) -> str:
        heard = compa_said.split(" … [")[0]
        await self._client.query(f"Your friend said (you may have talked over the end): {heard}")
        text = ""
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                text += "".join(block.text for block in message.content if isinstance(block, TextBlock))
        return text.strip()

    def render(self, line: str) -> np.ndarray:
        """Spoken audio of the line: [bracketed] words in a native-language voice, the rest in the learner voice."""
        pieces = [piece for piece in re.split(r"(\[[^\]]+\])", line) if piece.strip()]
        audio = []
        for piece in pieces:
            if piece.startswith("["):
                audio.append(np.zeros(int(HESITATION_SECONDS * SAMPLE_RATE), dtype=np.float32))
            audio.append(_trim_silence(self._say(piece)))
            audio.append(np.zeros(int(WORD_GAP_SECONDS * SAMPLE_RATE), dtype=np.float32))
        return np.concatenate(audio)

    def _say(self, piece: str) -> np.ndarray:
        native = piece.startswith("[")
        self._count += 1
        path = self.audio_dir / f"learner-{self._count}.wav"
        subprocess.run(["say", "-v", NATIVE_VOICES[self.profile.native_language] if native else self.voice, "-o", str(path),
                        "--file-format=WAVE", f"--data-format=LEF32@{SAMPLE_RATE}", piece.strip("[]")], check=True)
        return _read_wav(path)


def _trim_silence(audio: np.ndarray) -> np.ndarray:
    loud = np.flatnonzero(np.abs(audio) > 0.01)
    return audio[loud[0]:loud[-1] + 1] if len(loud) else audio


def _read_wav(path: Path) -> np.ndarray:
    decoded = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                              str(SAMPLE_RATE), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(decoded, dtype=np.float32)


class Mouth:
    """Where the learner's audio goes: injected into the listener, or out of the laptop speakers."""

    def __init__(self, injected: InjectedSource | None, speaker_device: str | None):
        self.injected = injected
        self.speaker_device = speaker_device

    async def speak(self, audio: np.ndarray) -> None:
        if self.injected is not None:
            self.injected.push(audio)
            await asyncio.sleep(len(audio) / SAMPLE_RATE)
        else:
            sd.play(audio, SAMPLE_RATE, device=self.speaker_device)
            await asyncio.sleep(len(audio) / SAMPLE_RATE + 0.1)


async def wait_for(condition, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("waited too long")
        await asyncio.sleep(0.05)


async def drive(conversation: Conversation, learner: SimulatedLearner, mouth: Mouth, turns: int) -> None:
    compa_idle = lambda: conversation._speaking_reply is None and not conversation.speaker.is_speaking  # noqa: E731
    compa_talking = lambda: conversation.speaker.is_speaking  # noqa: E731
    await wait_for(compa_talking, timeout=90)
    for turn in range(1, turns + 1):
        if turn == BARGE_IN_TURN:
            await wait_for(compa_talking)
            await asyncio.sleep(1.5)
        else:
            await wait_for(compa_idle)
            await asyncio.sleep(0.4)
        line = await learner.answer(conversation._last_assistant_line())
        audio = learner.render(line)
        if turn == PAUSE_TURN:
            middle = len(audio) // 2
            await mouth.speak(audio[:middle])
            await mouth.speak(np.zeros(int(MID_THOUGHT_PAUSE_SECONDS * SAMPLE_RATE), dtype=np.float32))
            await mouth.speak(audio[middle:])
        else:
            await mouth.speak(audio)
        await wait_for(lambda: len(conversation.log.turns) >= turn, timeout=30)
    await wait_for(compa_idle)
    await asyncio.sleep(6)


def report(conversation: Conversation) -> None:
    log = conversation.log
    print("\n=== REPORT ===")
    for number, turn in enumerate(log.turns, 1):
        latency = f"{turn.reply_after_seconds:.2f}s" if turn.reply_after_seconds is not None else "—"
        found = turn.feedback
        reply = turn.reply
        timing = (f"first token {reply.first_token_seconds:.2f}s after request, request "
                  f"{reply._started_at - turn.ended_at:+.2f}s vs turn end") if reply and reply.first_token_seconds else ""
        print(f"{number}. {timing} reply after {latency} speculation={'hit' if turn.speculation_used else 'miss'} "
              f"corrections={len(found.corrections) if found else '?'} "
              f"english={[w.said + '→' + w.target for w in found.english_words] if found else '?'}")
    print(f"interruptions={log.interruptions}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("language", nargs="?")
    parser.add_argument("--turns", type=int, default=7)
    parser.add_argument("--acoustic", action="store_true")
    arguments = parser.parse_args()
    profile = load_profile(arguments.language)
    print("Claude account:", use_claude_account(profile))
    work =Path(tempfile.mkdtemp(prefix="compa-sim-"))
    injected = None if arguments.acoustic else InjectedSource(realtime=True)
    source = MicSource("MacBook Pro Microphone") if arguments.acoustic else injected
    speaker = Speaker(profile.voice) if arguments.acoustic else Speaker(profile.voice, output=str(work / "compa"))
    mouth = Mouth(injected, "MacBook Pro Speakers" if arguments.acoustic else None)
    with Screen() as screen:
        conversation = Conversation(Listener(source, profile.language, profile.whisper_prompt), speaker, screen,
                                    Brain.for_profile(profile, Path("~/.cache/compa").expanduser()))
        async with SimulatedLearner(profile, work) as learner:
            call = asyncio.create_task(conversation.run())
            try:
                await drive(conversation, learner, mouth, arguments.turns)
            finally:
                call.cancel()
                await conversation.close()
    for role, text in conversation.talker.history:
        print(f"{role:>9}: {text}")
    report(conversation)
    test_profile = dataclasses.replace(profile, sessions_folder=work / "sessions")
    card = await Reporter(test_profile).report(conversation.talker.history, conversation.log)
    Screen().report_card(card, profile.language_name,
                         estimated_level(grades(test_profile.sessions_folder, test_profile.language)))
    print("saved:", save_call(test_profile.sessions_folder, profile.language_name, conversation.talker.history,
                              conversation.log, card))
    print(f"audio in {work}")


if __name__ == "__main__":
    asyncio.run(main())
