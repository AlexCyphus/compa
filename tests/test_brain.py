"""Brain tests. The splitter tests are pure; the rest talk to the real `claude` CLI on purpose."""
import json
from datetime import date

import pytest
import pytest_asyncio

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from compa.brain import ClaudeUnavailable, Corrector, Scout, SentenceSplitter, Talker, raise_if_unavailable, split_sentences
from compa.settings import load_profile

SPANISH_HINTS = ("¿", "¡", "qué", "cómo", "parce", "usted", "tú", "vos", "más", "está", "bien", "hola")


@pytest.fixture
def profile():
    return load_profile("spanish")


@pytest_asyncio.fixture
async def talker(profile):
    talker = Talker(profile)
    await talker.start()
    yield talker
    await talker.close()


@pytest_asyncio.fixture
async def corrector(profile):
    corrector = Corrector(profile)
    await corrector.start()
    yield corrector
    await corrector.close()


async def collect(reply) -> list[str]:
    return [sentence async for sentence in reply.sentences()]


# ---------------------------------------------------------------- sentence splitter


def test_splits_questions_statements_and_keeps_decimals():
    assert split_sentences("¿Qué más? Todo bien. Cuesta 3.5 dólares, ¿sí o qué?") == [
        "¿Qué más?", "Todo bien.", "Cuesta 3.5 dólares, ¿sí o qué?",
    ]


def test_keeps_abbreviations_inside_the_sentence():
    assert split_sentences("Hablé con el Sr. Gómez ayer. ¡Qué bacano!") == ["Hablé con el Sr. Gómez ayer.", "¡Qué bacano!"]


def test_keeps_a_mid_sentence_ellipsis_but_splits_before_a_new_sentence():
    assert split_sentences("Pues… no sé. Bueno… Mañana vemos.") == ["Pues… no sé.", "Bueno…", "Mañana vemos."]


def test_splits_on_newlines():
    assert split_sentences("Hola, parce\n¿Cómo vas?") == ["Hola, parce", "¿Cómo vas?"]


def test_splits_japanese_and_chinese_sentences():
    assert split_sentences("今日は暑いですね。映画を見に行きませんか？") == ["今日は暑いですね。", "映画を見に行きませんか？"]
    assert split_sentences("我今天很忙！你呢？") == ["我今天很忙！", "你呢？"]


def test_streamed_chunks_give_the_same_sentences():
    splitter = SentenceSplitter()
    chunks = ["¿Qué ", "más? To", "do bien. Cuesta 3", ".5 dólares, ¿sí o qué?"]
    sentences = [sentence for chunk in chunks for sentence in splitter.feed(chunk)] + splitter.flush()
    assert sentences == ["¿Qué más?", "Todo bien.", "Cuesta 3.5 dólares, ¿sí o qué?"]


# ---------------------------------------------------------------- talker


@pytest.mark.asyncio
async def test_opener_is_spanish_and_starts_fast(talker):
    reply = talker.opener()
    sentences = await collect(reply)
    print(f"\nopener first token: {reply.first_token_seconds:.2f}s :: {reply.full_text}")
    assert sentences
    assert any(hint in reply.full_text.lower() for hint in SPANISH_HINTS)
    assert reply.first_token_seconds < 2.5


@pytest.mark.asyncio
async def test_committed_reply_adds_both_turns(talker):
    reply = talker.reply("Hola, pues aquí en la casa, un poco cansado del trabajo.")
    await collect(reply)
    reply.commit()
    print(f"\nreply first token: {reply.first_token_seconds:.2f}s :: {reply.full_text}")
    assert talker.history == [
        ("user", "Hola, pues aquí en la casa, un poco cansado del trabajo."),
        ("assistant", reply.full_text.strip()),
    ]


@pytest.mark.asyncio
async def test_cancelled_reply_stays_out_of_history(talker):
    reply = talker.reply("Me encanta el café.")
    reply.cancel()
    reply.commit()
    assert talker.history == []


@pytest.mark.asyncio
async def test_interrupted_reply_stores_only_what_was_heard(talker):
    reply = talker.reply("¿Has ido a Medellín?")
    reply.commit(spoken_text="¡Claro, parce! Medellín es")
    assert talker.history == [
        ("user", "¿Has ido a Medellín?"),
        ("assistant", "¡Claro, parce! Medellín es … [interrumpido]"),
    ]


# ---------------------------------------------------------------- corrector


@pytest.mark.asyncio
async def test_corrector_catches_subjunctive_and_english_word(corrector):
    feedback = await corrector.check(
        "Ayer yo fui a la tienda y compré un lawnmower porque el pasto estaba muy alto, y es importante que lo corto hoy",
        context="¿Y qué hiciste ayer?",
    )
    print(f"\n{feedback}")
    assert any("corte" in correction.correct for correction in feedback.corrections)
    assert any(
        word.said == "lawnmower" and any(name in word.target for name in ("podadora", "cortacésped", "cortadora de césped", "cortagrama"))
        for word in feedback.english_words
    )


@pytest.mark.asyncio
async def test_corrector_leaves_a_clean_sentence_alone(corrector):
    feedback = await corrector.check(
        "Ayer fui a cine con mi hermana y la película nos pareció buenísima",
        context="¿Qué más, qué hiciste el fin de semana?",
    )
    print(f"\n{feedback}")
    assert [correction for correction in feedback.corrections if not correction.upgrade] == []
    assert feedback.english_words == []


@pytest.mark.asyncio
async def test_corrector_accepts_a_self_correction_that_ends_up_right(corrector):
    feedback = await corrector.check("Eh, hay algunos, algunas obras en el centro, pero no muchas",
                                     context="¿Y qué hay para ver en tu ciudad?")
    print(f"\n{feedback}")
    assert [correction for correction in feedback.corrections if not correction.upgrade] == []


@pytest.mark.asyncio
async def test_corrector_spots_a_request_to_save_the_word_just_taught(corrector):
    feedback = await corrector.check(
        "Ah, no conocía esa palabra, guárdala en mi Clozemaster porfa",
        context="Se dice podadora, la máquina para cortar el pasto. ¿Tú tienes jardín?",
    )
    print(f"\n{feedback}")
    assert feedback.words_to_save == ["podadora"]


@pytest.mark.asyncio
async def test_corrector_saves_the_word_for_an_english_word_used_a_turn_ago(corrector):
    feedback = await corrector.check("Ah, no conocía esa palabra, guárdala en mi Clozemaster porfa",
                                     context="¿Y te tocó cortar todo el pasto solo?",
                                     recent_english_words=["lawnmower → podadora"])
    assert feedback.words_to_save == ["podadora"]


@pytest.mark.asyncio
async def test_corrector_saves_nothing_when_not_asked(corrector):
    feedback = await corrector.check("Sí, tengo un jardín pequeño atrás de la casa", context="¿Tú tienes jardín?")
    assert feedback.words_to_save == []


# ---------------------------------------------------------------- scout


@pytest.mark.asyncio
async def test_scout_finds_stories_and_caches_them(profile, tmp_path):
    stories = await Scout(profile, tmp_path).briefing()
    for story in stories[:3]:
        print(f"\n{story}")
    assert len(stories) >= 8
    assert all(story.title and story.summary and story.hook for story in stories)
    cache_file = tmp_path / f"{date.today().isoformat()}-es.json"
    assert len(json.loads(cache_file.read_text())) == len(stories)


def test_usage_limit_messages_become_claude_unavailable():
    limit = AssistantMessage(content=[TextBlock("You've hit your limit · resets 5pm")], model="", error="rate_limit")
    failed_result = ResultMessage(subtype="success", duration_ms=0, duration_api_ms=0, is_error=True, num_turns=1,
                                  session_id="", result="Usage limit reached", api_error_status=429)

    for message in (limit, failed_result):
        with pytest.raises(ClaudeUnavailable):
            raise_if_unavailable(message)
    raise_if_unavailable(AssistantMessage(content=[TextBlock("Hola")], model=""))
