"""Claude-backed conversation partner, corrector and news scout, all via the local `claude` CLI (Claude Agent SDK).

Every request runs on a fresh, already-connected client taken from a small pool. We keep the conversation
history ourselves, so a speculative reply can be thrown away just by disconnecting its client.
"""
import asyncio
import json
import random
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

from compa.settings import Profile

HISTORY_TURNS_IN_PROMPT = 30
INTERRUPTED_MARKER = {"es": "interrumpido", "de": "unterbrochen", "fr": "interrompu", "ca": "interromput"}


def _lean_options(model: str, system_prompt: str, **overrides) -> ClaudeAgentOptions:
    """Options that keep the CLI fast: no tools, settings, MCP connectors, skills, plugins or thinking."""
    options = dict(
        model=model,
        system_prompt=system_prompt,
        tools=[],
        setting_sources=[],
        include_partial_messages=True,
        thinking={"type": "disabled"},
        strict_mcp_config=True,
        mcp_servers={},
        skills=[],
        plugins=[],
        extra_args={"disable-slash-commands": None},
        env={"ENABLE_CLAUDEAI_MCP_SERVERS": "false"},
    )
    return ClaudeAgentOptions(**{**options, **overrides})


def _text_delta(message) -> str | None:
    if not isinstance(message, StreamEvent):
        return None
    event = message.event
    if event.get("type") == "content_block_delta" and event["delta"].get("type") == "text_delta":
        return event["delta"]["text"]
    return None


# ---------------------------------------------------------------- client pool


class _ClientPool:
    """Keeps `size` clients connecting or connected; each taken client is replaced right away."""

    def __init__(self, options: ClaudeAgentOptions, size: int = 1):
        self._options = options
        self._size = size
        self._connecting: deque[asyncio.Task] = deque()
        self._disconnecting: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Returns once the pool's clients are connected and ready."""
        while len(self._connecting) < self._size:
            self._refill()
        await asyncio.gather(*(asyncio.shield(connection) for connection in self._connecting))

    async def take(self) -> ClaudeSDKClient:
        if not self._connecting:
            self._refill()
        connection = self._connecting.popleft()
        self._refill()
        try:
            return await asyncio.shield(connection)
        except asyncio.CancelledError:
            self._connecting.appendleft(connection)  # still unused: keep it for the next taker
            raise

    def discard(self, client: ClaudeSDKClient) -> None:
        """Disconnect in the background."""
        task = asyncio.create_task(client.disconnect())
        self._disconnecting.add(task)
        task.add_done_callback(self._disconnecting.discard)

    async def close(self) -> None:
        connections, self._connecting = list(self._connecting), deque()
        for client in await asyncio.gather(*connections, return_exceptions=True):
            if isinstance(client, ClaudeSDKClient):
                self.discard(client)
        await asyncio.gather(*self._disconnecting, return_exceptions=True)

    def _refill(self) -> None:
        self._connecting.append(asyncio.create_task(self._connect()))

    async def _connect(self) -> ClaudeSDKClient:
        client = ClaudeSDKClient(self._options)
        await client.connect()
        return client


# ---------------------------------------------------------------- sentence splitting

_FULL_WIDTH_TERMINATORS = "。！？"  # Japanese and Chinese: no space or capital letter after them
_TERMINATOR_RUN = re.compile(r"[.!?…]+[\"'»”’)\]]*\s+|[。！？]+[」』）”’]*\s*")
_SENTENCE_OPENERS = "¿¡«\"“'(—-"
_ABBREVIATIONS = {
    "sr", "sra", "srta", "dr", "dra", "ud", "uds", "lic", "ing", "prof", "etc", "pág", "aprox",
    "núm", "vs", "av", "mr", "mrs", "ms", "nr", "bzw", "usw", "mme", "mlle",
}


class SentenceSplitter:
    """Turns streamed text into complete sentences.

    A sentence ends at a newline, or at . ! ? … followed by whitespace and a capital letter, digit or an opening
    mark like ¿ ¡. Waiting for that next character keeps "3.5", "Sr. Pérez" and "Pues... no sé" in one piece.
    """

    def __init__(self):
        self._pending = ""

    def feed(self, text: str) -> list[str]:
        self._pending += text
        *finished_lines, self._pending = self._pending.split("\n")
        sentences = [s for line in finished_lines for s in split_sentences_in_line(line)]
        complete, self._pending = _split_off_complete(self._pending)
        return sentences + complete

    def flush(self) -> list[str]:
        remainder, self._pending = self._pending, ""
        return split_sentences_in_line(remainder)


def split_sentences(text: str) -> list[str]:
    splitter = SentenceSplitter()
    return splitter.feed(text) + splitter.flush()


def split_sentences_in_line(line: str) -> list[str]:
    complete, remainder = _split_off_complete(line)
    return complete + ([remainder.strip()] if remainder.strip() else [])


def _split_off_complete(text: str) -> tuple[list[str], str]:
    sentences, start = [], 0
    for match in _TERMINATOR_RUN.finditer(text):
        if match.end() == len(text) or not _is_sentence_boundary(text, match):
            continue
        sentence = text[start:match.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    return sentences, text[start:]


def _is_sentence_boundary(text: str, match: re.Match) -> bool:
    if match.group()[0] in _FULL_WIDTH_TERMINATORS:
        return True
    next_char = text[match.end()]
    starts_new_sentence = next_char.isupper() or next_char.isdigit() or next_char in _SENTENCE_OPENERS
    return starts_new_sentence and not _ends_with_abbreviation(text, match)


def _ends_with_abbreviation(text: str, match: re.Match) -> bool:
    if not match.group().startswith(".") or match.group().startswith(".."):
        return False
    words_before = text[:match.start()].split()
    word_before = words_before[-1].lstrip(_SENTENCE_OPENERS) if words_before else ""
    is_initial = len(word_before) == 1 and word_before.isupper()
    return word_before.lower() in _ABBREVIATIONS or is_initial


# ---------------------------------------------------------------- talker

SCOUT_TIMEOUT_SECONDS = 180

# Topics to start from when there's no briefing yet, so calls don't all open the same way.
SPARKS = [
    "AI and how it's changing everyday jobs", "a startup or app idea", "remote work and offices",
    "a recent tech gadget", "money habits and saving", "cities and housing prices", "travel plans",
    "a book, series or film", "music you've had on repeat", "food and a recipe", "sport", "fitness and sleep",
    "a surprising science fact", "space exploration", "climate and the weather lately", "learning languages",
    "social media habits", "a childhood memory", "weekend plans", "a weird habit", "pets", "a hot take",
    "what you'd do with a year off", "the future of cars and transport", "a historical what-if",
]



@dataclass(frozen=True)
class Story:
    title: str
    summary: str
    hook: str


class Reply:
    """One generated line, streaming from its own client. Nothing reaches the history until `commit`."""

    def __init__(self, pool: _ClientPool, prompt: str, record: Callable[[str], None], marker: str):
        self.full_text = ""
        self.first_token_seconds: float | None = None
        self._record = record
        self._marker = marker
        self._sentences: list[str] = []
        self._changed = asyncio.Event()
        self._finished = False
        self._failure: BaseException | None = None
        self._settled = False
        self._started_at = time.monotonic()
        self._generation = asyncio.create_task(self._generate(pool, prompt))

    async def sentences(self) -> AsyncIterator[str]:
        """Every sentence so far, then each new one as it completes. Can be iterated more than once."""
        position = 0
        while True:
            changed = self._changed
            while position < len(self._sentences):
                yield self._sentences[position]
                position += 1
            if self._failure:
                raise self._failure
            if self._finished:
                return
            await changed.wait()

    def _notify(self) -> None:
        """Wake every iterator: each waits on the event that was current when it last looked."""
        self._changed.set()
        self._changed = asyncio.Event()

    def cancel(self) -> None:
        self._settled = True
        self._generation.cancel()

    def stop_at(self, text: str) -> None:
        """Stop generating; the reply is just `text` (the sentences already handed out)."""
        self._generation.cancel()
        self.full_text = text

    def commit(self, spoken_text: str | None = None) -> None:
        """Record the exchange. `spoken_text` = the learner cut the reply off and only heard this much."""
        if self._settled:
            return
        self._settled = True
        if spoken_text is None:
            self._record(self.full_text.strip())
            return
        self._generation.cancel()
        self._record(f"{spoken_text.strip()} … [{self._marker}]")

    async def _generate(self, pool: _ClientPool, prompt: str) -> None:
        try:
            client = await pool.take()
            try:
                await self._stream(client, prompt)
            finally:
                pool.discard(client)
        except Exception as error:
            self._failure = error
        finally:
            self._finished = True
            self._notify()

    async def _stream(self, client: ClaudeSDKClient, prompt: str) -> None:
        splitter = SentenceSplitter()
        await client.query(prompt)
        async for message in client.receive_response():
            delta = _text_delta(message)
            if delta:
                self._add_text(delta, splitter)
        self._publish(splitter.flush())

    def _add_text(self, delta: str, splitter: SentenceSplitter) -> None:
        if self.first_token_seconds is None:
            self.first_token_seconds = time.monotonic() - self._started_at
        self.full_text += delta
        self._publish(splitter.feed(delta))

    def _publish(self, sentences: list[str]) -> None:
        if sentences:
            self._sentences.extend(sentences)
            self._notify()


class Talker:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.history: list[tuple[str, str]] = []
        self._briefing: list[Story] = []
        self._pool = _ClientPool(_lean_options(profile.talker_model, _persona(profile)), size=2)

    async def start(self) -> None:
        await self._pool.start()

    async def close(self) -> None:
        await self._pool.close()

    def set_briefing(self, stories: list[Story]) -> None:
        self._briefing = list(stories)

    def reply(self, user_text: str) -> Reply:
        task = f'{self.profile.learner_name} just said: "{user_text}"\nReply now.'
        return self._start_reply(task, user_text)

    def opener(self) -> Reply:
        topic = "one interesting story from the briefing" if self._briefing else f"something about {random.choice(SPARKS)}"
        task = (
            f"The call has just connected. Greet {self.profile.learner_name} warmly, then bring up {topic} "
            "and ask a question about it, all in 2-3 short sentences."
        )
        return self._start_reply(task, None)

    def _start_reply(self, task: str, user_text: str | None) -> Reply:
        prompt = "\n\n".join(part for part in (self._briefing_block(), self._history_block(), task) if part)

        def record(assistant_text: str) -> None:
            if user_text is not None:
                self.history.append(("user", user_text))
            self.history.append(("assistant", assistant_text))

        marker = INTERRUPTED_MARKER.get(self.profile.language, "interrupted")
        return Reply(self._pool, prompt, record, marker)

    def _briefing_block(self) -> str:
        if not self._briefing:
            return ""
        lines = "\n".join(f"- {story.title}: {story.summary} (hook: {story.hook})" for story in self._briefing)
        return f"<briefing>\nThings you could bring up:\n{lines}\n</briefing>"

    def _history_block(self) -> str:
        if not self.history:
            return ""
        speakers = {"user": self.profile.learner_name, "assistant": "You"}
        recent = self.history[-HISTORY_TURNS_IN_PROMPT:]
        lines = "\n".join(f"{speakers[role]}: {text}" for role, text in recent)
        return f"<conversation_so_far>\n{lines}\n</conversation_so_far>"


def _persona(profile: Profile) -> str:
    return f"""You are a friend of {profile.learner_name} on a voice call. You are a native speaker of {profile.variety}: \
curious, opinionated and warm. You speak ONLY {profile.language_name}, the way a relaxed, educated adult from \
there really talks to a friend: natural and understated, not a caricature. Use the everyday vocabulary of \
{profile.variety}, never words typical of other regions. Slang and nicknames ("parce", "mano") are seasoning: \
about one every three or four turns, never in consecutive turns. Don't open with \
exclamations or praise ("¡Qué chévere!", "¡Uy!", "Jaja", "Tienes razón"); just respond to what was said. \
{profile.learner_name} is a {profile.native_language} speaker practising {profile.language_name} at {profile.level} level.

How you talk:
- Your words are spoken aloud by text-to-speech: 1-3 short sentences per turn, under 40 words in total. \
No lists, markdown, emoji, stage directions or text in brackets.
- You are friends: always use the informal "you" with {profile.learner_name} (tú in Spanish, du in German, tu in French and Catalan), never the formal one.
- It is a two-way chat, not an interview: share your own opinions, little anecdotes and surprising facts \
("¿supiste que…?"-style; only facts you are sure are true), then almost always end with one question.
- Follow up on what {profile.learner_name} actually said with specific, curious questions.
- Through your questions, invite {profile.level}-level language: hypotheticals ("what would you do if…"), \
opinions and arguing a side, concessions, wishes and doubts that need the subjunctive.
- When a thread runs dry, switch to something from the briefing or an interesting everyday topic.
- Never correct {profile.learner_name}'s mistakes; corrections are shown separately on screen.
- If {profile.learner_name} uses a {profile.native_language} word, just use the {profile.language_name} word \
naturally in your reply without making a fuss.
- If {profile.learner_name} asks you to save a word to Clozemaster, an app on the call does it: just say \
briefly that it's saved, naming the word, then carry on.
- If {profile.learner_name} speaks {profile.native_language} or asks what a word means, answer briefly in \
{profile.language_name} and carry on the conversation.

Each message gives you the briefing, the conversation so far and what to do next. Reply with only your next spoken line."""


# ---------------------------------------------------------------- corrector


@dataclass(frozen=True)
class Correction:
    said: str
    correct: str
    why: str
    upgrade: bool


@dataclass(frozen=True)
class EnglishWord:
    said: str
    target: str
    note: str


@dataclass(frozen=True)
class Feedback:
    corrections: list[Correction]
    english_words: list[EnglishWord]
    words_to_save: list[str] = field(default_factory=list)


class Corrector:
    def __init__(self, profile: Profile):
        self._pool = _ClientPool(_lean_options(profile.corrector_model, _corrector_instructions(profile)))

    async def start(self) -> None:
        await self._pool.start()

    async def close(self) -> None:
        await self._pool.close()

    async def check(self, user_text: str, context: str, recent_english_words: list[str] = ()) -> Feedback:
        client = await self._pool.take()
        recent = f"\nEnglish words the learner used recently: {', '.join(recent_english_words)}" if recent_english_words else ""
        try:
            await client.query(f'Partner\'s previous line: "{context}"{recent}\nLearner said: "{user_text}"')
            return _parse_feedback(await _final_text(client))
        finally:
            self._pool.discard(client)


async def _final_text(client: ClaudeSDKClient) -> str:
    text = ""
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            text += "".join(block.text for block in message.content if isinstance(block, TextBlock))
    return text


def _corrector_instructions(profile: Profile) -> str:
    return f"""You check what a {profile.level}-level learner of {profile.language_name} said on a voice call. \
Their native language is {profile.native_language}. The text is a speech-recognition transcript.

Flag every real error: grammar, agreement, gender, prepositions, ser/estar-type verb choice, mood (subjunctive), \
tense, calques from {profile.native_language}, wrong word. Add an upgrade (upgrade: true) only rarely, when a clearly \
more natural phrasing exists. Do not flag punctuation, capitalisation, accents, filler words or false starts, and \
never invent errors when the text is fine. Suggest the phrasing used in {profile.variety}; never forms specific to \
another region (for Colombian Spanish: no vosotros, "vale", "coger", "ordenador", "móvil").

Also list every {profile.native_language} word or phrase the learner used in place of a {profile.language_name} \
one, with the {profile.language_name} equivalent used in {profile.variety}. These go only in "english_words", \
never also in "corrections". The sentence around such a word (hesitations, restarting after it, "bueno, …" self-repairs) is not an error. The learner and their partner are friends using the informal "you" (tú / du / tu): never suggest the formal form.

"said" quotes the learner's exact words (just the wrong fragment); "correct" is the fixed fragment; "why" and \
"note" are in {profile.language_name}, at most 8 words.

If the learner asks to save, keep or add a word or phrase (to Clozemaster, their collection, their list…), put \
that {profile.language_name} word or phrase in "words_to_save", in its dictionary form. When they say "that word" \
or similar, work out which one: if they used {profile.native_language} words recently, it is almost always the \
{profile.language_name} word for the latest of those (not the {profile.native_language} one); otherwise it is a word \
from the partner's previous line. The request \
itself is not an error.

Only list a correction when "correct" differs from "said". Answer with JSON only, no prose, exactly this shape (empty lists when there is nothing):
{{"corrections": [{{"said": "...", "correct": "...", "why": "...", "upgrade": false}}],
 "english_words": [{{"said": "...", "target": "...", "note": "..."}}],
 "words_to_save": ["..."]}}"""


def _parse_feedback(text: str) -> Feedback:
    parsed = _parse_json(text, "{")
    if not isinstance(parsed, dict):
        return Feedback(corrections=[], english_words=[])
    corrections = _build_all(Correction, parsed.get("corrections"))
    return Feedback(
        corrections=[correction for correction in corrections if correction.correct != correction.said],
        english_words=_build_all(EnglishWord, parsed.get("english_words")),
        words_to_save=[word for word in parsed.get("words_to_save") or [] if isinstance(word, str) and word.strip()],
    )


def _parse_json(text: str, opening: str):
    """The first JSON value starting with `opening`, ignoring code fences and chatter before or after it; None if unparsable."""
    start = text.find(opening)
    if start == -1:
        return None
    try:
        return json.JSONDecoder().raw_decode(text[start:])[0]
    except json.JSONDecodeError:
        return None


def _build_all(kind: type, items) -> list:
    fields = kind.__dataclass_fields__
    built = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and fields.keys() <= item.keys():
            built.append(kind(**{name: item[name] for name in fields}))
    return built


# ---------------------------------------------------------------- scout


class Scout:
    """Finds today's interesting stories once per day and language, then serves them from cache."""

    def __init__(self, profile: Profile, cache_dir: Path):
        self.profile = profile
        self.cache_dir = cache_dir

    async def briefing(self) -> list[Story]:
        cache_file = self.cache_dir / f"{date.today().isoformat()}-{self.profile.language}.json"
        if cache_file.exists():
            return [Story(**story) for story in json.loads(cache_file.read_text())]
        stories = await self._search()
        if not stories:
            return stories
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps([asdict(story) for story in stories], ensure_ascii=False, indent=2))
        return stories

    async def _search(self) -> list[Story]:
        options = _lean_options(
            self.profile.corrector_model,
            "You research conversation material. You answer with a JSON array only.",
            tools=["WebSearch"],
            allowed_tools=["WebSearch"],
            permission_mode="bypassPermissions",
            include_partial_messages=False,
        )
        try:
            async with asyncio.timeout(SCOUT_TIMEOUT_SECONDS):
                async with ClaudeSDKClient(options) as client:
                    await client.query(_scout_task(self.profile))
                    result = await _result_text(client)
        except TimeoutError:
            return []  # no briefing this call; the next call tries again
        return _build_all(Story, _parse_json(result, "["))


async def _result_text(client: ClaudeSDKClient) -> str:
    async for message in client.receive_response():
        if isinstance(message, ResultMessage):
            return message.result or ""
    return ""


def _scout_task(profile: Profile) -> str:
    return f"""Today is {date.today().isoformat()}. Use web search to find 12 stories from the last few days that \
would make great conversation with a curious, well-read friend. Mix it up like a real person's news feed: \
world news and geopolitics, tech and AI, business and the economy, science and health, culture, sport and odd or \
surprising stories. At most 3 of the 12 should be local to {profile.news_from}; the rest are global. \
Prefer stories people have opinions about. Skip tragedies and gore.

Answer with only a JSON array of 10-14 objects: {{"title": ..., "summary": ..., "hook": ...}}. \
Write everything in {profile.language_name} as spoken in {profile.variety}. "title": a few words. \
"summary": 1-2 factual sentences with the key specifics. "hook": a casual question or opener a friend would use \
to bring the story up on a call, addressing them with the informal "you" (tú / du / tu), never the formal one."""


async def ask_for_json(model: str, instructions: str, prompt: str):
    """One-off question to Claude whose answer is a JSON object; None if it isn't one."""
    async with ClaudeSDKClient(_lean_options(model, instructions, include_partial_messages=False)) as client:
        await client.query(prompt)
        return _parse_json(await _result_text(client), "{")
