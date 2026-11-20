"""Listening: audio sources, Silero VAD turn detection and mlx-whisper transcription."""
import asyncio
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import mlx_whisper
import numpy as np
import onnxruntime

SAMPLE_RATE = 16000
CHUNK = 512  # 32 ms
CHUNK_SECONDS = CHUNK / SAMPLE_RATE

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
VAD_MODEL = Path(__file__).resolve().parent.parent / "models" / "silero_vad.onnx"

START_CHUNKS = 3  # consecutive speech chunks (~100 ms) that open a turn
PRE_ROLL = 0.6  # seconds kept from before speech is detected, so quiet first syllables survive
PAUSE_SILENCE = 0.4
# A pause after an unfinished thought ("compré una…", "pero eh") is the learner searching for a word:
# wait longer before ending the turn.
HESITATION_SILENCE = 2.2  # ended on an article, connector or filler: mid-sentence
TRAILING_OFF_SILENCE = 1.5  # ended with "…": Whisper also writes that at real ends, so wait less
UNFINISHED_ENDINGS = {
    "es": "eh em este pues o sea que de del el la los las un una unos unas y o pero porque como en con para por a al mi tu su muy más es",
    "de": "äh ähm hm also und oder aber weil dass der die das den dem ein eine einen einem mit für von zu in auf ist",
    "fr": "euh ben bah alors et ou mais parce que de du des le la les un une avec pour dans en à au mon ton son très",
    "en": "uh um er like so and or but because that the a an of to in on with for my your his her very is",
    "ca": "eh em doncs o sigui que de del el la els les un una uns unes i o però perquè com en amb per a al meu teu seu molt més és",
}
PARTIAL_EVERY = 1.0
MIN_SPEECH = 0.25
TRAILING_KEEP = 0.2  # silence kept after the last speech chunk when transcribing
SPEECH_THRESHOLD = 0.5
END_HYSTERESIS = 0.15  # inside a turn, speech continues until prob drops below threshold - this

# Learners drop an English word mid-sentence when they don't know the target one.
# Measured on ~10 Spanish `say` sentences with an English word from an English voice:
# forcing language="es" keeps the English word (no prompt: all correct), but the
# profile's filler-only prompt pushed Whisper to "hispanicise" it ("seagull" -> "Sigo").
# Appending a quoted English example word to the prompt fixed every case while keeping
# the filler prompt, so the English word survives as English.
MIXED_LANGUAGE_EXAMPLE = "'stapler'..."

HALLUCINATIONS = [
    "subtítulos realizados por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "gracias por ver el video",
    "gracias por ver",
    "¡suscríbete!",
    "suscríbete al canal",
    "untertitel im auftrag des zdf",
    "untertitel der amara.org-community",
    "sous-titres réalisés par la communauté d'amara.org",
    "sous-titrage st' 501",
    "merci d'avoir regardé",
    "thanks for watching",
    "thank you for watching",
]


@dataclass(frozen=True)
class SpeechStarted:
    pass


@dataclass(frozen=True)
class Partial:
    text: str


@dataclass(frozen=True)
class Paused:
    text: str


@dataclass(frozen=True)
class Resumed:
    pass


@dataclass(frozen=True)
class TurnEnded:
    text: str
    seconds: float


ListenEvent = SpeechStarted | Partial | Paused | Resumed | TurnEnded


class MicSource:
    def __init__(self, device: int | str | None = None):
        self.device = device

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        import sounddevice

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue()

        def on_audio(indata, frames, time_info, status):
            loop.call_soon_threadsafe(queue.put_nowait, indata[:, 0].copy())

        with sounddevice.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=CHUNK, device=self.device, callback=on_audio
        ):
            while True:
                yield await queue.get()


class InjectedSource:
    def __init__(self, realtime: bool = True):
        self.realtime = realtime
        self._queued: deque[np.ndarray] = deque()
        self._lock = threading.Lock()

    def push(self, audio: np.ndarray) -> None:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        with self._lock:
            self._queued.append(audio)

    def push_file(self, path: str | Path) -> float:
        audio = decode_audio(path)
        self.push(audio)
        return len(audio) / SAMPLE_RATE

    def idle(self) -> bool:
        with self._lock:
            return not self._queued

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        started = time.monotonic()
        emitted = 0
        while True:
            yield self._next_chunk()
            emitted += 1
            if self.realtime:
                # Absolute schedule, so a slow consumer catches up like with a real mic.
                await asyncio.sleep(max(0.0, started + emitted * CHUNK_SECONDS - time.monotonic()))
            else:
                await asyncio.sleep(0)

    def _next_chunk(self) -> np.ndarray:
        chunk = np.zeros(CHUNK, dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < CHUNK and self._queued:
                head = self._queued[0]
                taken = min(CHUNK - filled, len(head))
                chunk[filled:filled + taken] = head[:taken]
                filled += taken
                if taken == len(head):
                    self._queued.popleft()
                else:
                    self._queued[0] = head[taken:]
        return chunk


def decode_audio(path: str | Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


class SileroVad:
    """Silero VAD v5; like the official wrapper, each chunk is prefixed with the last 64 samples of the previous one."""

    CONTEXT = 64

    def __init__(self):
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(str(VAD_MODEL), sess_options=options)
        self._sample_rate = np.array(SAMPLE_RATE, dtype=np.int64)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(self.CONTEXT, dtype=np.float32)

    def speech_probability(self, chunk: np.ndarray) -> float:
        model_input = np.concatenate([self._context, chunk])[None, :]
        probability, self._state = self._session.run(
            None, {"input": model_input, "state": self._state, "sr": self._sample_rate}
        )
        self._context = chunk[-self.CONTEXT:]
        return float(probability[0, 0])


class Listener:
    def __init__(self, source, language: str, whisper_prompt: str | None = None, end_silence: float = 1.0):
        self.source = source
        self.language = language
        self.whisper_prompt = whisper_prompt
        self.end_silence = end_silence
        self._prompt = f"{whisper_prompt or ''} {MIXED_LANGUAGE_EXAMPLE}".strip()
        self._threshold = SPEECH_THRESHOLD
        self._vad = SileroVad()
        self._transcribing = asyncio.Lock()

    def set_speech_threshold(self, threshold: float) -> None:
        self._threshold = threshold

    async def warm_up(self) -> None:
        self._vad.speech_probability(np.zeros(CHUNK, dtype=np.float32))
        await self._transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))

    async def events(self) -> AsyncIterator[ListenEvent]:
        pre_roll: deque[np.ndarray] = deque(maxlen=round(PRE_ROLL / CHUNK_SECONDS) + START_CHUNKS)
        consecutive_speech = 0
        turn: list[np.ndarray] | None = None
        speech_chunks = silence_chunks = chunks_at_last_partial = last_speech_index = 0
        paused = False
        required_silence = self.end_silence
        partial_task: asyncio.Task | None = None

        async for chunk in self.source.chunks():
            probability = self._vad.speech_probability(chunk)

            if partial_task is not None and partial_task.done():
                text = partial_task.result()
                partial_task = None
                if turn is not None and text:
                    yield Partial(text)

            if turn is None:
                pre_roll.append(chunk)
                consecutive_speech = consecutive_speech + 1 if probability >= self._threshold else 0
                if consecutive_speech >= START_CHUNKS:
                    turn = list(pre_roll)
                    pre_roll.clear()
                    speech_chunks = chunks_at_last_partial = START_CHUNKS
                    silence_chunks = 0
                    last_speech_index = len(turn)
                    paused = False
                    yield SpeechStarted()
                continue

            turn.append(chunk)
            if probability >= self._threshold - END_HYSTERESIS:
                silence_chunks = 0
                speech_chunks += 1
                last_speech_index = len(turn)
                if paused:
                    paused = False
                    required_silence = self.end_silence
                    yield Resumed()
                new_speech = (speech_chunks - chunks_at_last_partial) * CHUNK_SECONDS
                if new_speech >= PARTIAL_EVERY and partial_task is None and not self._transcribing.locked():
                    chunks_at_last_partial = speech_chunks
                    partial_task = asyncio.create_task(self._transcribe(np.concatenate(turn)))
                continue

            silence_chunks += 1
            silence = silence_chunks * CHUNK_SECONDS
            if silence >= required_silence:
                if partial_task is not None:
                    text = await partial_task
                    partial_task = None
                    if text:
                        yield Partial(text)
                speech_audio = turn[: last_speech_index + round(TRAILING_KEEP / CHUNK_SECONDS)]
                turn = None
                required_silence = self.end_silence
                consecutive_speech = 0
                if speech_chunks * CHUNK_SECONDS < MIN_SPEECH:
                    continue
                audio = np.concatenate(speech_audio)
                text = await self._transcribe(audio)
                if text:
                    yield TurnEnded(text, len(audio) / SAMPLE_RATE)
            elif silence >= PAUSE_SILENCE and not paused:
                paused = True
                if partial_task is not None:
                    text = await partial_task
                    partial_task = None
                    if text:
                        yield Partial(text)
                so_far = await self._transcribe(np.concatenate(turn))
                required_silence = self.silence_needed_after(so_far)
                yield Paused(so_far)

    def silence_needed_after(self, text: str) -> float:
        """How long a pause after `text` must last before the turn is over."""
        stripped = text.strip()
        words = re.findall(r"\w+", stripped.lower())
        if words and words[-1] in UNFINISHED_ENDINGS.get(self.language, "").split():
            return max(self.end_silence, HESITATION_SILENCE)
        if stripped.endswith(("...", "…", ",")):
            return max(self.end_silence, TRAILING_OFF_SILENCE)
        return self.end_silence

    async def _transcribe(self, audio: np.ndarray) -> str:
        async with self._transcribing:
            result = await asyncio.to_thread(
                mlx_whisper.transcribe,
                audio,
                path_or_hf_repo=WHISPER_MODEL,
                language=self.language,
                initial_prompt=self._prompt,
                condition_on_previous_text=False,
                temperature=0,
                verbose=None,
            )
        return clean_transcript(result["text"], self._prompt)


def clean_transcript(text: str, prompt: str | None) -> str:
    """Drops whole sentences that are known silence hallucinations or an echo of the prompt."""
    text = text.strip()
    if prompt and prompt.strip():
        text = text.replace(prompt.strip(), "")
    echoes = {_normalized(part) for part in [prompt or "", MIXED_LANGUAGE_EXAMPLE]} - {""}
    junk = {_normalized(phrase) for phrase in HALLUCINATIONS} | echoes
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentence for sentence in sentences if _normalized(sentence) and _normalized(sentence) not in junk).strip()


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())
