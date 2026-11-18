import asyncio
import time
import wave

import mlx_whisper
import pytest
import pytest_asyncio

from compa.listen import WHISPER_MODEL, decode_audio
from compa.speak import Speaker

pytestmark = pytest.mark.asyncio

SENTENCES = [
    "Hola, ¿cómo estás hoy?",
    "Ayer fui al mercado con mi hermana y compramos muchas frutas tropicales deliciosas.",
    "Después cocinamos juntas.",
]


@pytest_asyncio.fixture(params=["Paulina", "kokoro:ef_dora"])
async def speaker(request, tmp_path):
    speaker = Speaker(request.param, output=str(tmp_path))
    playback = asyncio.create_task(speaker.run())
    yield speaker
    await speaker.close()
    await playback


async def wait_for_sentence(started: list[str], sentence: str) -> None:
    while sentence not in started:
        await asyncio.sleep(0.01)


async def test_three_sentences_are_written_in_order_then_quiet(speaker, tmp_path):
    for sentence in SENTENCES:
        speaker.say(sentence)
    speaker.end_reply()
    assert speaker.is_speaking

    await asyncio.wait_for(speaker.wait_until_quiet(), 20)

    assert sorted(path.name for path in tmp_path.glob("*.wav")) == ["001.wav", "002.wav", "003.wav"]
    recordings = [wave.open(str(tmp_path / f"00{index}.wav")) for index in (1, 2, 3)]
    assert {(recording.getframerate(), recording.getnchannels()) for recording in recordings} == {(16000, 1)}
    frame_counts = [recording.getnframes() for recording in recordings]
    assert max(frame_counts) == frame_counts[1]  # the second sentence is by far the longest
    assert not speaker.is_speaking


async def test_sentence_started_callback_runs_in_order(speaker):
    started = []
    speaker.on_sentence_started = started.append
    for sentence in SENTENCES:
        speaker.say(sentence)

    await asyncio.wait_for(speaker.wait_until_quiet(), 20)

    assert started == SENTENCES


async def test_interrupt_during_second_sentence_returns_what_was_heard(speaker, tmp_path):
    started = []
    speaker.on_sentence_started = started.append
    for sentence in SENTENCES:
        speaker.say(sentence)
    await asyncio.wait_for(wait_for_sentence(started, SENTENCES[1]), 10)
    await asyncio.sleep(1.5)

    heard = speaker.interrupt()
    stop_started = time.monotonic()
    await speaker.wait_until_quiet()

    assert time.monotonic() - stop_started < 0.1
    assert not speaker.is_speaking
    assert heard.startswith(SENTENCES[0] + " Ayer fui")
    assert SENTENCES[1] not in heard
    assert "Después" not in heard
    await asyncio.sleep(2)
    assert sorted(path.name for path in tmp_path.glob("*.wav")) == ["001.wav", "002.wav"]
    assert started == SENTENCES[:2]


async def test_interrupt_cuts_simulated_playback_short(speaker):
    started = []
    speaker.on_sentence_started = started.append
    speaker.say(SENTENCES[1])
    await asyncio.wait_for(wait_for_sentence(started, SENTENCES[1]), 10)

    speaker.interrupt()
    speaker.say(SENTENCES[2])
    await asyncio.wait_for(wait_for_sentence(started, SENTENCES[2]), 0.5)


async def test_markdown_and_emoji_are_stripped(speaker):
    started = []
    speaker.on_sentence_started = started.append
    speaker.say("**¡Qué bien!** 😄 ## Me alegro 🇨🇴 mucho_")
    speaker.say("  ")

    await asyncio.wait_for(speaker.wait_until_quiet(), 10)

    assert started == ["¡Qué bien! Me alegro mucho"]


async def test_spoken_text_resets_after_reply_ends(speaker):
    started = []
    speaker.on_sentence_started = started.append
    speaker.say(SENTENCES[0])
    speaker.end_reply()
    await asyncio.wait_for(speaker.wait_until_quiet(), 10)
    speaker.say(SENTENCES[2])
    await asyncio.wait_for(wait_for_sentence(started, SENTENCES[2]), 10)

    heard = speaker.interrupt()

    assert SENTENCES[0] not in heard


@pytest_asyncio.fixture
async def kokoro(tmp_path):
    speaker = Speaker("kokoro:ef_dora", output=str(tmp_path))
    playback = asyncio.create_task(speaker.run())
    speaker.say("Hola.")  # waits for the warm-up
    await asyncio.wait_for(speaker.wait_until_quiet(), 30)
    yield speaker
    await speaker.close()
    await playback


async def test_kokoro_first_sentence_starts_quickly_after_warm_up(kokoro):
    started_at = []
    kokoro.on_sentence_started = lambda _: started_at.append(time.monotonic())

    said_at = time.monotonic()
    kokoro.say("Me encanta la comida colombiana, sobre todo el ajiaco.")
    while not started_at:
        await asyncio.sleep(0.001)

    assert started_at[0] - said_at < 0.6


async def test_kokoro_renders_while_whisper_transcribes(kokoro, tmp_path):
    kokoro.say(SENTENCES[1])
    await asyncio.wait_for(kokoro.wait_until_quiet(), 20)
    recording = decode_audio(tmp_path / "002.wav")

    transcription = asyncio.to_thread(
        mlx_whisper.transcribe, recording, path_or_hf_repo=WHISPER_MODEL, language="es", temperature=0, verbose=None
    )
    for sentence in SENTENCES:
        kokoro.say(sentence)
    result = await transcription
    await asyncio.wait_for(kokoro.wait_until_quiet(), 30)

    assert "mercado" in result["text"]
    assert sorted(path.name for path in tmp_path.glob("*.wav")) == ["001.wav", "002.wav", "003.wav", "004.wav", "005.wav"]


async def test_prerendered_sentence_starts_almost_instantly(kokoro):
    sentence = "Oye, ¿y qué película vieron al final con tu hermana?"
    started_at = []
    kokoro.on_sentence_started = lambda _: started_at.append(time.monotonic())
    kokoro.prerender(sentence)
    await asyncio.sleep(1.5)

    said_at = time.monotonic()
    kokoro.say(sentence)
    while not started_at:
        await asyncio.sleep(0.001)

    assert started_at[0] - said_at < 0.05


async def test_dropped_prerenders_do_not_delay_the_next_sentence(kokoro):
    for number in range(4):
        kokoro.prerender(f"Esta es una frase especulativa bastante larga, la número {number}, que nunca se dice.")
    kokoro.drop_prerendered()
    started_at = []
    kokoro.on_sentence_started = lambda _: started_at.append(time.monotonic())

    said_at = time.monotonic()
    kokoro.say("¿Y tú qué opinas?")
    while not started_at:
        await asyncio.sleep(0.001)

    assert started_at[0] - said_at < 1.0
