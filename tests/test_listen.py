import asyncio
import subprocess

import numpy as np
import pytest

from compa.listen import (
    SAMPLE_RATE,
    InjectedSource,
    Listener,
    Partial,
    Paused,
    Resumed,
    SpeechStarted,
    TurnEnded,
    HESITATION_SILENCE,
    TRAILING_OFF_SILENCE,
    decode_audio,
)

PROMPT = "Eh, pues... o sea, este, bueno, es que, eh, no sé."


@pytest.fixture(scope="module")
def speak(tmp_path_factory):
    folder = tmp_path_factory.mktemp("speech")
    spoken = {}

    def speak(text: str, voice: str = "Paulina") -> np.ndarray:
        if (voice, text) not in spoken:
            path = folder / f"{len(spoken)}.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(path), text], check=True)
            spoken[(voice, text)] = decode_audio(path)
        return spoken[(voice, text)]

    return speak


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


async def listen_to(*pieces: np.ndarray) -> list:
    source = InjectedSource(realtime=False)
    source.push(np.concatenate([silence(0.5), *pieces, silence(2.0)]))
    listener = Listener(source, language="es", whisper_prompt=PROMPT)
    events = []

    async def collect():
        async for event in listener.events():
            events.append(event)

    collector = asyncio.create_task(collect())
    # The listener awaits transcriptions before pulling the next chunk, so once the trailing
    # silence is drained every event for the pushed audio has been yielded.
    while not source.idle():
        await asyncio.sleep(0.01)
    collector.cancel()
    return events


def turns(events: list) -> list[TurnEnded]:
    return [event for event in events if isinstance(event, TurnEnded)]


@pytest.mark.asyncio
async def test_single_sentence_ends_one_turn(speak):
    events = await listen_to(speak("Hoy fui al mercado a comprar frutas."))

    assert isinstance(events[0], SpeechStarted)
    [turn] = turns(events)
    assert "mercado" in turn.text.lower()
    assert 1.5 < turn.seconds < 5


@pytest.mark.asyncio
async def test_short_gap_pauses_and_resumes_within_one_turn(speak):
    events = await listen_to(speak("Hoy fui al mercado."), silence(0.6), speak("Compré muchas manzanas."))

    kinds = [type(event) for event in events if not isinstance(event, Partial)]
    assert kinds == [SpeechStarted, Paused, Resumed, Paused, TurnEnded]
    paused = next(event for event in events if isinstance(event, Paused))
    assert "mercado" in paused.text.lower()
    [turn] = turns(events)
    assert "mercado" in turn.text.lower() and "manzanas" in turn.text.lower()


@pytest.mark.asyncio
async def test_long_gap_ends_two_turns(speak):
    events = await listen_to(speak("Hoy fui al mercado."), silence(2.0), speak("Compré muchas manzanas."))

    first, second = turns(events)
    assert "mercado" in first.text.lower()
    assert "manzanas" in second.text.lower()
    assert sum(isinstance(event, SpeechStarted) for event in events) == 2


@pytest.mark.asyncio
async def test_silence_produces_no_events():
    assert await listen_to(silence(3.0)) == []


@pytest.mark.asyncio
async def test_english_word_mid_sentence_stays_english(speak):
    events = await listen_to(
        speak("Fuimos a la playa y vimos un"), silence(0.3), speak("seagull", voice="Samantha"), silence(0.3),
        speak("enorme."),
    )

    [turn] = turns(events)
    assert "seagull" in turn.text.lower()


@pytest.mark.asyncio
async def test_long_utterance_emits_partials(speak):
    events = await listen_to(
        speak("El fin de semana pasado fuimos con mis amigos a una finca cerca de Medellín y nos quedamos tres días.")
    )

    assert any(isinstance(event, Partial) and event.text for event in events)
    assert len(turns(events)) == 1


@pytest.mark.asyncio
async def test_long_pause_after_unfinished_thought_stays_one_turn(speak):
    events = await listen_to(speak("Ayer compré una"), silence(1.6), speak("bicicleta nueva para ir al trabajo."))

    [turn] = turns(events)
    assert "compré" in turn.text.lower() and "bicicleta" in turn.text.lower()


@pytest.mark.asyncio
async def test_same_pause_after_finished_sentence_ends_the_turn(speak):
    events = await listen_to(speak("Ayer compré una bicicleta."), silence(1.6), speak("Es roja."))

    assert len(turns(events)) == 2


def test_pause_after_an_article_or_filler_waits_longest():
    listener = Listener(InjectedSource(realtime=False), language="es")

    assert listener.silence_needed_after("Ayer compré una") == HESITATION_SILENCE
    assert listener.silence_needed_after("Creo que, eh") == HESITATION_SILENCE


def test_pause_after_trailing_off_waits_a_little_longer():
    listener = Listener(InjectedSource(realtime=False), language="es")

    assert listener.silence_needed_after("No sé cómo se dice...") == TRAILING_OFF_SILENCE


def test_pause_after_a_finished_sentence_uses_the_normal_wait():
    listener = Listener(InjectedSource(realtime=False), language="es", end_silence=1.0)

    assert listener.silence_needed_after("Ayer compré una bicicleta.") == 1.0
