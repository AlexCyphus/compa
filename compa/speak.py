"""Text-to-speech streamed one sentence at a time, with Kokoro-82M ("kokoro:<voice>") or a built-in macOS voice."""
import asyncio
import io
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

# `say` spends ~0.5-1.3 s starting up for every sentence and `afplay` ~0.2 s before sound plus
# ~0.8 s after it, so one long-lived osascript process keeps an NSSpeechSynthesizer and the audio
# stack warm instead (~45 ms per render, ~35 ms from play to sound). It reads tab-separated commands:
#   render <aiff path> <text>   writes the speech to that file, then answers "done"
#   play <wav path>             starts playing it in the background
#   stop                        stops playing
_ENGINE_SCRIPT = r"""
ObjC.import('AppKit');
ObjC.import('AVFoundation');
function run([voiceName, rate, warmUpPath]) {
  // Matches the identifier's last part ("Montserrat") or the name `say -v '?'` lists ("Montse").
  const listedName = v => ObjC.deepUnwrap($.NSSpeechSynthesizer.attributesForVoice(v)).VoiceName;
  const voice = $.NSSpeechSynthesizer.availableVoices.js.map(v => v.js).find(v => v.endsWith('.' + voiceName)
    || listedName(v) === voiceName || listedName(v).startsWith(voiceName + ' ('));
  if (!voice) throw new Error('Unknown voice: ' + voiceName);
  const synthesizer = $.NSSpeechSynthesizer.alloc.initWithVoice(voice);
  if (rate) synthesizer.rate = Number(rate);
  const output = $.NSFileHandle.fileHandleWithStandardOutput;
  let player = null;
  const render = (path, text) => {
    synthesizer.startSpeakingStringToURL(text, $.NSURL.fileURLWithPath(path));
    while (synthesizer.isSpeaking) $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.005));
  };
  const play = (path, volume = 1) => {
    player = $.AVAudioPlayer.alloc.initWithContentsOfURLError($.NSURL.fileURLWithPath(path), null);
    player.volume = volume;
    player.play;
  };
  const stop = () => player && player.stop;
  const commands = {
    render(path, text) {
      render(path, text);
      output.writeData($('done\n').dataUsingEncoding($.NSUTF8StringEncoding));
    },
    play: path => play(path),
    stop,
  };

  // The first render and the first play each take ~0.2-1.4 s, so get them out of the way silently.
  render(warmUpPath, 'a');
  play(warmUpPath, 0);
  stop();

  const input = $.NSFileHandle.fileHandleWithStandardInput;
  let pending = '';
  for (let data = input.availableData; data.length > 0; data = input.availableData) {
    pending += $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
    let end;
    while ((end = pending.indexOf('\n')) >= 0) {
      const [command, ...args] = pending.slice(0, end).split('\t');
      pending = pending.slice(end + 1);
      commands[command](...args);
    }
  }
}
"""

_UNSPOKEN = re.compile(r"[*#_`~\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D]")

OUTPUT_SAMPLE_RATE = 16000
KOKORO_PREFIX = "kokoro:"
PRERENDER_LIMIT = 4
KOKORO_MODEL = "prince-canuma/Kokoro-82M"
KOKORO_SAMPLE_RATE = 24000
# The first renders compile kernels for new input sizes (~1.3 s, then ~0.5 s), so warm up on two lengths.
KOKORO_WARM_UP = ["Hola.", "Ayer fui al mercado con mi hermana y compramos frutas."]

# Whisper runs on MLX in another thread; one MLX inference from this module at a time keeps the Kokoro
# model and its shared phonemizer state safe (concurrent Whisper + Kokoro was stress-tested without a crash).
_mlx_inference = threading.Lock()


class _MacVoice:
    sample_rate = OUTPUT_SAMPLE_RATE

    def __init__(self, voice: str, rate: int | None):
        self._work_dir = Path(tempfile.mkdtemp(prefix="compa-speak-"))
        self._process = subprocess.Popen(
            ["osascript", "-l", "JavaScript", "-e", _ENGINE_SCRIPT,
             voice, str(rate or ""), str(self._work_dir / "warm-up.aiff")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self._input = threading.Lock()
        self._rendered_count = 0
        self._played_count = 0

    def render(self, text: str) -> np.ndarray:
        """Runs on the renderer thread, one sentence at a time."""
        self._rendered_count += 1
        aiff = self._work_dir / f"{self._rendered_count}.aiff"
        wav = aiff.with_suffix(".wav")
        self._send(f"render\t{aiff}\t{text}")
        self._process.stdout.readline()
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{OUTPUT_SAMPLE_RATE}", "-c", "1", str(aiff), str(wav)], check=True
        )
        aiff.unlink()
        samples = _read_wav(wav)
        wav.unlink()
        return samples

    def play(self, samples: np.ndarray) -> None:
        self._played_count += 1
        wav = self._work_dir / f"play-{self._played_count}.wav"
        _write_wav(wav, samples, self.sample_rate)
        self._send(f"play\t{wav}")
        # The player read the previous one into memory when it started.
        (self._work_dir / f"play-{self._played_count - 1}.wav").unlink(missing_ok=True)

    def stop(self) -> None:
        self._send("stop")

    def close(self) -> None:
        self._process.kill()
        shutil.rmtree(self._work_dir, ignore_errors=True)

    def _send(self, command: str) -> None:
        with self._input:
            self._process.stdin.write(command + "\n")


class _KokoroVoice:
    """Kokoro-82M on MLX, played through a stream that stays open so a sentence starts or stops instantly."""
    sample_rate = KOKORO_SAMPLE_RATE

    def __init__(self, voice: str):
        self._voice = voice
        self._lang_code = voice[0]  # Kokoro voices start with their language: e(s), f(r), i(t), p(t), a/b (en)
        self._model = None
        self._samples = np.zeros(0, dtype=np.float32)
        self._position = 0
        self._playback = threading.Lock()
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", blocksize=240,  # 10 ms
            latency="low", callback=self._fill,
        )
        self._stream.start()
        threading.Thread(target=self._warm_up, daemon=True).start()

    def render(self, text: str) -> np.ndarray:
        with _mlx_inference:
            if self._model is None:
                from mlx_audio.tts.utils import load_model
                self._model = load_model(KOKORO_MODEL)
            results = self._model.generate(
                text=text, voice=self._voice, lang_code=self._lang_code, split_pattern=None, verbose=False
            )
            return np.concatenate([np.array(result.audio, dtype=np.float32) for result in results])

    def play(self, samples: np.ndarray) -> None:
        with self._playback:
            self._samples, self._position = samples, 0

    def stop(self) -> None:
        self.play(np.zeros(0, dtype=np.float32))

    def close(self) -> None:
        self._stream.close()

    def _warm_up(self) -> None:
        # mlx-audio prints setup chatter while it loads; keep it off the call screen.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for text in KOKORO_WARM_UP:
                self.render(text)

    def _fill(self, out: np.ndarray, frames: int, _time, _status) -> None:
        with self._playback:
            chunk = self._samples[self._position:self._position + frames]
            self._position += len(chunk)
        out[:len(chunk), 0] = chunk
        out[len(chunk):] = 0


@dataclass
class _Utterance:
    text: str
    audio: Future  # resolves to the rendered samples at the voice's sample rate
    started_at: float | None = None
    duration: float = 0.0


class Speaker:
    def __init__(self, voice: str, rate: int | None = None, output: str | None = None):
        self.on_sentence_started: Callable[[str], None] | None = None
        self._output_dir = Path(output) if output else None
        if self._output_dir:
            self._output_dir.mkdir(parents=True, exist_ok=True)
        if voice.startswith(KOKORO_PREFIX):
            self._voice = _KokoroVoice(voice.removeprefix(KOKORO_PREFIX))
        else:
            self._voice = _MacVoice(voice, rate)
        self._renderer = ThreadPoolExecutor(max_workers=1)
        self._written_count = 0
        self._prerendered: dict[str, Future] = {}
        self._queue: deque[_Utterance | None] = deque()  # None marks the end of a reply
        self._queue_changed = asyncio.Event()
        self._quiet = asyncio.Event()
        self._quiet.set()
        self._stop_playback = asyncio.Event()
        self._playing: _Utterance | None = None
        self._spoken: list[str] = []
        self._closed = False

    def say(self, sentence: str) -> None:
        text = _speakable(sentence)
        if not text:
            return
        audio = self._prerendered.pop(text, None) or self._renderer.submit(self._voice.render, text)
        self._enqueue(_Utterance(text, audio))

    def prerender(self, sentence: str) -> None:
        """Render a sentence that will probably be said soon, so say() can start it at once."""
        text = _speakable(sentence)
        if text and text not in self._prerendered:
            if len(self._prerendered) >= PRERENDER_LIMIT:
                self._prerendered.pop(next(iter(self._prerendered))).cancel()
            self._prerendered[text] = self._renderer.submit(self._voice.render, text)

    def drop_prerendered(self) -> None:
        """The speculative reply was abandoned: don't spend render time on its sentences."""
        for audio in self._prerendered.values():
            audio.cancel()
        self._prerendered.clear()

    def end_reply(self) -> None:
        self._enqueue(None)

    def interrupt(self) -> str:
        heard = self._heard_so_far()
        for utterance in filter(None, self._queue):
            utterance.audio.cancel()
        self._queue.clear()
        self._spoken.clear()
        self._playing = None
        self._stop_audio()
        self._update_quiet()
        return heard

    @property
    def is_speaking(self) -> bool:
        return self._playing is not None or any(self._queue)

    async def wait_until_quiet(self) -> None:
        await self._quiet.wait()

    async def run(self) -> None:
        while True:
            await self._queue_changed.wait()
            self._queue_changed.clear()
            while self._queue and not self._closed:
                utterance = self._queue.popleft()
                if utterance:
                    await self._play(utterance)
                else:
                    self._spoken.clear()
                self._update_quiet()
            if self._closed:
                return

    async def close(self) -> None:
        self.interrupt()
        self._closed = True
        self._queue_changed.set()
        self._voice.close()
        self._renderer.shutdown(wait=False, cancel_futures=True)

    def _enqueue(self, item: _Utterance | None) -> None:
        self._queue.append(item)
        self._queue_changed.set()
        self._update_quiet()

    def _update_quiet(self) -> None:
        if self.is_speaking:
            self._quiet.clear()
        else:
            self._quiet.set()

    async def _play(self, utterance: _Utterance) -> None:
        self._playing = utterance
        samples = await asyncio.wrap_future(utterance.audio)
        if self._playing is not utterance:  # interrupted while rendering
            return
        utterance.duration = len(samples) / self._voice.sample_rate
        self._stop_playback.clear()
        if self._output_dir:
            self._written_count += 1
            _write_wav(self._output_dir / f"{self._written_count:03d}.wav", samples, self._voice.sample_rate)
        else:
            self._voice.play(samples)
        utterance.started_at = time.monotonic()
        if self.on_sentence_started:
            self.on_sentence_started(utterance.text)
        with suppress(TimeoutError):  # playing or simulated, the audio lasts its duration
            await asyncio.wait_for(self._stop_playback.wait(), utterance.duration)
        if self._playing is utterance:
            self._spoken.append(utterance.text)
            self._playing = None

    def _stop_audio(self) -> None:
        self._stop_playback.set()
        if not self._output_dir:
            self._voice.stop()

    def _heard_so_far(self) -> str:
        heard = list(self._spoken)
        current = self._playing
        if current and current.started_at is not None:
            fraction = (time.monotonic() - current.started_at) / current.duration
            heard.append(_first_words(current.text, min(fraction, 1.0)))
        return " ".join(part for part in heard if part)


def _speakable(sentence: str) -> str:
    return " ".join(_UNSPOKEN.sub(" ", sentence).split())


def _first_words(text: str, fraction: float) -> str:
    words = text.split()
    return " ".join(words[: int(len(words) * fraction)])


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as recording:
        return np.frombuffer(recording.readframes(recording.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Writes 16 kHz mono 16-bit, resampling linearly if needed."""
    if sample_rate != OUTPUT_SAMPLE_RATE:
        times = np.arange(round(len(samples) * OUTPUT_SAMPLE_RATE / sample_rate)) / OUTPUT_SAMPLE_RATE
        samples = np.interp(times, np.arange(len(samples)) / sample_rate, samples)
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(OUTPUT_SAMPLE_RATE)
        recording.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
